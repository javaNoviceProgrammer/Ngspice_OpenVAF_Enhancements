use basedb::diagnostics::{Diagnostic, Label, LabelStyle, Report};
use basedb::lints::builtin::{
    const_simparam, rng_in_loop, trivial_probe, unknown_analysis_name, unknown_limit_function,
    variant_const_simparam,
};
use basedb::lints::{self, Lint, LintSrc};
use basedb::{AstIdMap, BaseDB, FileId};
pub use body::BodyValidationDiagnostic;
use hir_def::body::BodySourceMap;
use hir_def::{
    DisciplineAttr, ExprId, ItemLoc, ItemTree, ItemTreeNode, Lookup, NatureAttr, NodeId,
    NodeTypeDecl, StmtId,
};
use syntax::name::Name;
use syntax::sourcemap::{FileSpan, SourceMap};
use syntax::{Parse, SourceFile, TextRange};
pub use types::TypeValidationDiagnostic;

use crate::db::HirTyDB;
use crate::inference::BranchWrite;
use crate::validation::body::{BodyCtx, IllegalCtxAccess, IllegalCtxAccessKind};
use crate::validation::types::DuplicateItem;

mod body;
mod types;

#[derive(PartialEq, Eq, Clone, Debug)]
struct IncompatibleBranchDiagnostic {
    branch_span: FileSpan,
    branch_name: String,
    node1: NodeId,
    node2: NodeId,
}

impl IncompatibleBranchDiagnostic {
    fn into_report(
        self,
        db: &dyn HirTyDB,
        parse: &Parse<SourceFile>,
        map: &AstIdMap,
        sm: &SourceMap,
    ) -> Report {
        let Self { branch_span, branch_name, node1, node2 } = self;

        let node1_ = node1.lookup(db.upcast());
        let node1_range = map.get_syntax(node1_.discipline_ast_id(db.upcast()).unwrap()).range();
        let node1_span = parse.to_file_span(node1_range, sm);
        let node1 = db.node_data(node1);

        let node2_ = node2.lookup(db.upcast());
        let node2_range = map.get_syntax(node2_.discipline_ast_id(db.upcast()).unwrap()).range();
        let node2_span = parse.to_file_span(node2_range, sm);
        let node2 = db.node_data(node2);

        let msg = format!(
            "nodes '{}' and '{}' of branch '{}' have incompatible disciplines!",
            node1.name, node2.name, branch_name
        );

        Report::error()
                    .with_labels(vec![Label {
                        style: LabelStyle::Primary,
                        file_id: branch_span.file,
                        range: branch_span.range.into(),
                        message: format!("'{}' has mismatched disciplines", branch_name),
                    }])
                    .with_labels(vec![Label {
                        style: LabelStyle::Secondary,
                        file_id: node1_span.file,
                        range: node1_span.range.into(),
                        message: format!("help: '{}' declared with discipline '{}'", node1.name, node1.discipline.as_ref().unwrap()),
                    }])
                    .with_labels(vec![Label {
                        style: LabelStyle::Secondary,
                        file_id: node2_span.file,
                        range: node2_span.range.into(),
                        message: format!("help: '{}' declared with discipline '{}'", node2.name, node2.discipline.as_ref().unwrap()),
                    }])
                    .with_message(msg)
                    .with_notes(vec![
                        format!("help: disciplines are compatible if their potential and flow natures have the same 'units' attribute"),
                    ])
    }
}

pub struct BodyValidationDiagnosticWrapped<'a> {
    pub body_sm: &'a BodySourceMap,
    pub diag: &'a BodyValidationDiagnostic,
    pub parse: &'a Parse<SourceFile>,
    pub db: &'a dyn HirTyDB,
    pub sm: &'a SourceMap,
    pub map: &'a AstIdMap,
}

impl BodyValidationDiagnosticWrapped<'_> {
    fn expr_src(&self, expr: ExprId) -> FileSpan {
        // Enhancement-220: a synthesized expression has no source-map-back entry;
        // fall back to an empty range rather than panic while reporting an error.
        let range =
            self.body_sm.expr_map_back[expr].as_ref().map_or_else(TextRange::default, |it| it.range());
        self.parse.to_file_span(range, self.sm)
    }

    /// Enhancement-390: the source span of a STATEMENT, for diagnostics that
    /// point at a statement rather than an expression.
    fn stmt_src(&self, stmt: StmtId) -> FileSpan {
        let range = self.body_sm.stmt_map_back[stmt]
            .as_ref()
            .map_or_else(TextRange::default, |it| it.range());
        self.parse.to_file_span(range, self.sm)
    }

    fn lookup<I, T>(&self, id: I) -> (Name, FileSpan)
    where
        I: Lookup<Data = ItemLoc<T>>,
        T: ItemTreeNode,
    {
        let loc = id.lookup(self.db.upcast());
        let src = loc.ast_ptr(self.db.upcast()).range();
        (loc.name(self.db.upcast()), self.parse.to_file_span(src, self.sm))
    }
}

impl Diagnostic for BodyValidationDiagnosticWrapped<'_> {
    fn lint(&self, root_file: FileId, db: &dyn BaseDB) -> Option<(Lint, LintSrc)> {
        match *self.diag {
            BodyValidationDiagnostic::ConstSimparam { known: false, stmt, .. } => {
                let src1 = self.body_sm.lint_src(stmt, const_simparam);
                let (lvl1, _) = src1.lvl(const_simparam, root_file, db);
                let src2 = self.body_sm.lint_src(stmt, variant_const_simparam);
                let (lvl2, _) = src2.lvl(variant_const_simparam, root_file, db);

                let res = if lvl2 > lvl1 {
                    (variant_const_simparam, src2)
                } else {
                    (const_simparam, src1)
                };
                Some(res)
            }

            BodyValidationDiagnostic::ConstSimparam { known: true, stmt, .. } => {
                let src = self.body_sm.lint_src(stmt, const_simparam);
                Some((const_simparam, src))
            }
            BodyValidationDiagnostic::TrivialBranchAccess { stmt, .. } => {
                let src = self.body_sm.lint_src(stmt, trivial_probe);
                Some((trivial_probe, src))
            }
            BodyValidationDiagnostic::RngInLoop { stmt, .. } => {
                let src = self.body_sm.lint_src(stmt, rng_in_loop);
                Some((rng_in_loop, src))
            }
            BodyValidationDiagnostic::UnknownLimitFunction { stmt, .. } => {
                let src = self.body_sm.lint_src(stmt, unknown_limit_function);
                Some((unknown_limit_function, src))
            }
            BodyValidationDiagnostic::UnknownAnalysisName { stmt, .. } => {
                let src = self.body_sm.lint_src(stmt, unknown_analysis_name);
                Some((unknown_analysis_name, src))
            }
            _ => None,
        }
    }

    fn build_report(&self, _root_file: basedb::FileId, _db: &dyn basedb::BaseDB) -> Report {
        match *self.diag {
            BodyValidationDiagnostic::ExpectedPort { expr, node } => {
                let FileSpan { range, file } = self.expr_src(expr);
                let node = node.lookup(self.db.upcast());
                let module = node.module.lookup(self.db.upcast());
                let tree = module.item_tree(self.db.upcast());
                let node = &tree[module.id].nodes[node.id];
                let name = &node.name;

                let mut labels = vec![Label {
                    style: LabelStyle::Primary,
                    file_id: file,
                    range: range.into(),
                    message: "expected port".to_owned(),
                }];

                // Enhancement-230: a node that appears in the module port list but
                // has no direction declared carries BOTH a Net decl (its `electrical`
                // net type) and a Port decl (its header port-list entry). This
                // "expected a port" diagnostic labels the net declarations; skip any
                // Port decl instead of `unreachable!()` (which panicked the compiler
                // on `x = I(<p>)` where `p` is such a directionless header port).
                labels.extend(node.decls.iter().filter_map(|decl| {
                    let net = match decl {
                        NodeTypeDecl::Net(net) => *net,
                        NodeTypeDecl::Port(_) => return None,
                    };

                    let range = self.map.get(tree[net].ast_id).range();
                    let FileSpan { range, file } = self.parse.to_file_span(range, self.sm);
                    Some(Label {
                        style: LabelStyle::Secondary,
                        file_id: file,
                        range: range.into(),
                        message: format!("info: '{}' was declared here", name),
                    })
                }));

                Report::error()
                    .with_message(format!(
                        "expected a port reference but no direction was declared for net '{}'",
                        name
                    ))
                    .with_labels(labels)
                    .with_notes(vec![
                        "help: prefix one of the declarations with inout, input or output"
                            .to_owned(),
                    ])
            }
            BodyValidationDiagnostic::StrayPartSelect { expr } => {
                let FileSpan { range, file } = self.expr_src(expr);
                Report::error()
                    .with_message("part-select in an expression")
                    .with_labels(vec![Label {
                        style: LabelStyle::Primary,
                        file_id: file,
                        range: range.into(),
                        message: "part-selects cannot be used here".to_owned(),
                    }])
                    .with_notes(vec![
                        "help: `v[msb:lsb]` is supported in instance port connections \
                         (e.g. `adc2 hi (out[3:2], in);`); in behavioral code \
                         access the bits individually"
                            .to_owned(),
                    ])
            }
            BodyValidationDiagnostic::StrayDontCareLiteral { expr } => {
                let FileSpan { range, file } = self.expr_src(expr);
                Report::error()
                    .with_message("don't-care digits are only allowed in casex/casez items")
                    .with_labels(vec![Label {
                        style: LabelStyle::Primary,
                        file_id: file,
                        range: range.into(),
                        message: "literal with x/z/? digits".to_owned(),
                    }])
                    .with_notes(vec![
                        "help: `x`/`z`/`?` digits form comparison masks and are meaningful \
                         only as items of a `casex`/`casez` statement"
                            .to_owned(),
                    ])
            }
            BodyValidationDiagnostic::XDigitInCaseZ { expr } => {
                let FileSpan { range, file } = self.expr_src(expr);
                Report::error()
                    .with_message("'x' digits are not don't-cares in casez")
                    .with_labels(vec![Label {
                        style: LabelStyle::Primary,
                        file_id: file,
                        range: range.into(),
                        message: "casez item with an 'x' digit".to_owned(),
                    }])
                    .with_notes(vec![
                        "help: `casez` treats only `z`/`?` digits as don't-cares; use `casex` \
                         to treat `x` digits as don't-cares as well"
                            .to_owned(),
                    ])
            }
            BodyValidationDiagnostic::NonIntegerCaseXZ { kind, discr } => {
                let FileSpan { range, file } = self.expr_src(discr);
                let kw = if kind == hir_def::CaseKind::CaseX { "casex" } else { "casez" };
                Report::error()
                    .with_message(format!("{} requires an integer discriminant", kw))
                    .with_labels(vec![Label {
                        style: LabelStyle::Primary,
                        file_id: file,
                        range: range.into(),
                        message: "expected an integer expression".to_owned(),
                    }])
                    .with_notes(vec![
                        "help: don't-care masks compare bit-wise, which is only defined for \
                         `integer` values"
                            .to_owned(),
                    ])
            }
            // Enhancement-392
            BodyValidationDiagnostic::TableTooLargeToSort { expr, len, max } => {
                let FileSpan { range, file } = self.expr_src(expr);
                Report::error()
                    .with_message(format!(
                        "$table_model runtime data has {len} points; at most {max} are sorted"
                    ))
                    .with_labels(vec![Label {
                        style: LabelStyle::Primary,
                        file_id: file,
                        range: range.into(),
                        message: "too many points to normalise in the emitted code".to_owned(),
                    }])
                    .with_notes(vec![
                        format!(
                            "the compile-time forms sort and de-duplicate at any size, so a \
                             larger runtime table would silently disagree with the same data \
                             written inline; supply at most {max} points, or a data file"
                        ),
                        "a runtime table must in any case be ascending in x (LRM); the sorting \
                         is a convenience, not a requirement of the language"
                            .to_owned(),
                    ])
            }
            // Enhancement-390: only reached when the file is genuinely unusable --
            // `to_report` filters out the readable, parseable ones.
            BodyValidationDiagnostic::TableFileUnusable { expr, ref path } => {
                let FileSpan { range, file } = self.expr_src(expr);
                Report::error()
                    .with_message(format!("cannot use '{path}' as $table_model data"))
                    .with_labels(vec![Label {
                        style: LabelStyle::Primary,
                        file_id: file,
                        range: range.into(),
                        message: "missing, unreadable, or contains no usable table data"
                            .to_owned(),
                    }])
                    .with_notes(vec![
                        "a value that is not finite -- 'nan', 'inf', or an overflowing \
                         exponent such as 1e400 -- makes the whole file unusable, because it \
                         would poison every interpolation drawn from it"
                            .to_owned(),
                        "the path is resolved relative to the directory of the file being \
                         compiled"
                            .to_owned(),
                        "an unusable data file used to yield an EMPTY table, so the device \
                         silently contributed zero with nothing reported"
                            .to_owned(),
                    ])
            }
            // Enhancement-395: an unimplemented or malformed control code.
            BodyValidationDiagnostic::TableControlUnsupported { expr, ref code, ref why } => {
                let FileSpan { range, file } = self.expr_src(expr);
                Report::error()
                    .with_message(format!("unsupported $table_model control string \"{code}\""))
                    .with_labels(vec![Label {
                        style: LabelStyle::Primary,
                        file_id: file,
                        range: range.into(),
                        message: why.to_string(),
                    }])
                    .with_notes(vec![
                        "supported: interpolation '1' (linear) or '3' (cubic spline), and \
                         extrapolation 'C' (constant) or 'L' (linear) applied to both ends"
                            .to_owned(),
                        "an unrecognised code used to fall through to linear interpolation \
                         with clamped ends, with nothing reported"
                            .to_owned(),
                    ])
            }
            // Enhancement-390
            BodyValidationDiagnostic::UnresolvedDisable { stmt, ref name } => {
                let FileSpan { range, file } = self.stmt_src(stmt);
                Report::error()
                    .with_message(format!("no enclosing block named '{name}' to disable"))
                    .with_labels(vec![Label {
                        style: LabelStyle::Primary,
                        file_id: file,
                        range: range.into(),
                        message: "no block with this name encloses the statement".to_owned(),
                    }])
                    .with_notes(vec![
                        "`disable` leaves the nearest enclosing block with the given name, \
                         so the name must match a `begin : <name>` that contains it"
                            .to_owned(),
                        "this used to be silently ignored, which turned a typo'd label into \
                         a changed result: the statement did nothing and execution simply \
                         carried on"
                            .to_owned(),
                    ])
            }
            // Enhancement-375
            BodyValidationDiagnostic::NonTerminatingLoop { cond, always } => {
                let FileSpan { range, file } = self.expr_src(cond);
                let (msg, label) = if always {
                    ("loop condition is always true", "this is never false")
                } else {
                    (
                        "loop condition can never change",
                        "nothing in the loop writes what this reads",
                    )
                };
                Report::error()
                    .with_message(msg.to_owned())
                    .with_labels(vec![Label {
                        style: LabelStyle::Primary,
                        file_id: file,
                        range: range.into(),
                        message: label.to_owned(),
                    }])
                    .with_notes(vec![
                        "a module body must complete one evaluation; a loop that cannot \
                         exit would hang the simulator on the first evaluation with no \
                         further diagnostic"
                            .to_owned(),
                        "help: write what the condition reads inside the loop body, or in \
                         the `for` increment"
                            .to_owned(),
                        "note: `disable <block>` is not accepted as the only way out of \
                         such a loop; it works for a loop that can also finish normally"
                            .to_owned(),
                    ])
            }
            BodyValidationDiagnostic::PotentialOfPortFlow { expr, branch } => {
                let FileSpan { range, file } = self.expr_src(expr);

                let mut labels = vec![Label {
                    style: LabelStyle::Primary,
                    file_id: file,
                    range: range.into(),
                    message: "invalid potential access".to_owned(),
                }];

                if let Some(branch) = branch {
                    let (name, FileSpan { range, file }) = self.lookup(branch);

                    labels.push(Label {
                        style: LabelStyle::Secondary,
                        file_id: file,
                        range: range.into(),
                        message: format!("info: '{}' was declared here", name),
                    });
                }

                Report::error()
                    .with_message("access of port-branch potential")
                    .with_labels(labels)
                    .with_notes(vec![
                        "help: only the flow of port branches like <foo> can be accessed"
                            .to_owned(),
                    ])
            }
            BodyValidationDiagnostic::ContributeToPortFlow { expr, branch } => {
                let FileSpan { range, file } = self.expr_src(expr);
                let (name, FileSpan { range: decl_range, file: decl_file }) =
                    self.lookup(branch);

                Report::error()
                    .with_message("contribution to a port branch")
                    .with_labels(vec![
                        Label {
                            style: LabelStyle::Primary,
                            file_id: file,
                            range: range.into(),
                            message: "cannot contribute to a port branch".to_owned(),
                        },
                        Label {
                            style: LabelStyle::Secondary,
                            file_id: decl_file,
                            range: decl_range.into(),
                            message: format!("info: '{}' was declared here", name),
                        },
                    ])
                    .with_notes(vec![
                        "help: a port branch carries the flow already defined by the \
                         connected network; it can only be probed, e.g. I(branch_name)"
                            .to_owned(),
                    ])
            }
            BodyValidationDiagnostic::ContributeToGround { expr } => {
                let FileSpan { range, file } = self.expr_src(expr);
                Report::error()
                    .with_message("contribution to a ground node")
                    .with_labels(vec![Label {
                        style: LabelStyle::Primary,
                        file_id: file,
                        range: range.into(),
                        message: "this branch is entirely 'ground'".to_owned(),
                    }])
                    .with_notes(vec![
                        "help: the potential of 'ground' is fixed at 0, so there is no \
                         unknown to contribute to; contribute to a real node instead"
                            .to_owned(),
                    ])
            }
            BodyValidationDiagnostic::IllegalContribute { stmt, ctx } => {
                // Enhancement-220: fall back to an empty range for a synthesized
                // statement rather than panic while reporting an error.
                let FileSpan { range, file } = self.parse.to_file_span(
                    self.body_sm.stmt_map_back[stmt]
                        .as_ref()
                        .map_or_else(TextRange::default, |it| it.range()),
                    self.sm,
                );

                Report::error()
                    .with_message(format!("branch contributions are not allowed in {}", ctx))
                    .with_labels(vec![Label {
                        style: LabelStyle::Secondary,
                        file_id: file,
                        range: range.into(),
                        message: "not allowed here".to_owned(),
                    }])
                    .with_notes(vec![
                        "help: branch contributions are only allowed in module-level analog blocks"
                            .to_owned(),
                    ])
            }
            BodyValidationDiagnostic::WriteToInputArg { expr, arg } => {
                let FileSpan { range, file } = self.expr_src(expr);
                let arg_name = arg.name(self.db.upcast());
                let arg_src = arg.ast_ptr(self.db.upcast()).range();
                let arg_src = self.parse.to_file_span(arg_src, self.sm);

                Report::error()
                    .with_message(format!("write to input function argument '{}'", arg_name))
                    .with_labels(vec![Label {
                        style: LabelStyle::Secondary,
                        file_id: arg_src.file,
                        range: arg_src.range.into(),
                        message: format!("help: '{}' is defined here", arg_name),
                    }])
                    .with_labels(vec![Label {
                        style: LabelStyle::Primary,
                        file_id: file,
                        range: range.into(),
                        message: "write to input argument".to_owned(),
                    }])
                    .with_notes(vec![format!("help: change direction of '{}' to inout", arg_name)])
            }
            BodyValidationDiagnostic::IllegalParamAccess { def, expr, param } => {
                let FileSpan { range, file } = self.expr_src(expr);
                let (def_name, def_src) = self.lookup(def);
                let (ref_name, ref_src) = self.lookup(param);

                Report::error()
                    .with_message(format!(
                        "definition of '{}' references parameter '{}' defined afterwards",
                        def_name, ref_name
                    ))
                    .with_labels(vec![Label {
                        style: LabelStyle::Secondary,
                        file_id: def_src.file,
                        range: def_src.range.into(),
                        message: format!("help: '{}' is defined here", def_name),
                    }])
                    .with_labels(vec![Label {
                        style: LabelStyle::Primary,
                        file_id: file,
                        range: range.into(),
                        message: "illegal reference".to_owned(),
                    }])
                    .with_labels(vec![Label {
                        style: LabelStyle::Secondary,
                        file_id: ref_src.file,
                        range: ref_src.range.into(),
                        message: format!(".. to parameter '{}' defined here", ref_name),
                    }])
                    .with_notes(vec![
                            "help: parameters may only refer to parameters (textually) defined before them"
                            .to_owned(),
                    ])
            }
            BodyValidationDiagnostic::IllegalCtxAccess(IllegalCtxAccess {
                ref kind,
                ctx,
                expr,
            }) => {
                let FileSpan { range, file } = self.expr_src(expr);

                let mut res = Report::error().with_labels(vec![Label {
                    style: LabelStyle::Primary,
                    file_id: file,
                    range: range.into(),
                    message: "not allowed here".to_owned(),
                }]);

                match kind {
                    IllegalCtxAccessKind::NatureAccess => res
                        .with_message(format!("nature access is not allowed in {}", ctx))
                        .with_notes(vec![
                            "help: nature access is only allowed in module-level analog blocks"
                                .to_owned(),
                        ]),
                    IllegalCtxAccessKind::AnalogOperator {
                        name,
                        is_standard: _, // TODO add a note?
                        non_const_dominator,
                    } => {
                        let notes = if ctx == BodyCtx::Conditional {
                            vec![
                                "help: analog operators are only allowed in non-conditional behaviour".to_owned(),
                                "help: only constant and analysis functions are allowed in conditions".to_owned()
                            ]
                        } else if ctx == BodyCtx::Loop {
                            vec![
                                "help: analog operators are not allowed inside looping statements (LRM 4.5.1)".to_owned(),
                                "help: hoist the operator out of the loop, or unroll the loop with `generate`".to_owned(),
                            ]
                        } else {
                            vec!["help: analog operators are only allowed in the main-analog block"
                                .to_owned()]
                        };

                        res.labels.extend(non_const_dominator.iter().map(|expr| {
                            let FileSpan { range, file } = self.expr_src(*expr);
                            Label {
                                style: LabelStyle::Secondary,
                                file_id: file,
                                range: range.into(),
                                message: "help: this condition is not a constant".to_owned(),
                            }
                        }));

                        res.with_message(format!(
                            "analog operator '{}' is not allowed in {}",
                            name, ctx
                        ))
                        .with_notes(notes)
                    }
                    IllegalCtxAccessKind::AnalysisFun { name } => res.with_message(format!(
                        "analysis function '{}' is not allowed in constants",
                        name
                    )),
                    IllegalCtxAccessKind::Var(var) => {
                        let name = var.lookup(self.db.upcast()).name(self.db.upcast());
                        let def = var.lookup(self.db.upcast()).ast_ptr(self.db.upcast()).range();
                        let FileSpan { range, file } = self.parse.to_file_span(def, self.sm);
                        res.labels.push(Label {
                            style: LabelStyle::Secondary,
                            file_id: file,
                            range: range.into(),
                            message: format!("help: '{}' was declared here", name),
                        });
                        res.with_message(
                            "constant expressions must not contain variable references".to_owned(),
                        )
                    }
                }
            }
            BodyValidationDiagnostic::ConstSimparam { known, expr, .. } => {
                let FileSpan { range, file } = self.expr_src(expr);

                let mut res = Report::warning()
                    .with_message(
                        "call to $simparam in a constant is evaluated before the simulation"
                            .to_owned(),
                    )
                    .with_labels(vec![Label {
                        style: LabelStyle::Primary,
                        file_id: file,
                        range: range.into(),
                        message: "call to $simparam in a constant".to_owned(),
                    }]);

                if !known {
                    res = res.with_notes(vec![
                        "help: the value of paramaeters like \"gmin\' or \"sourceScaleFactor\" may vary between iterations"
                            .to_owned(),
                    ])
                }

                res
            }
            BodyValidationDiagnostic::UnsupportedFunction { expr, func } => {
                let FileSpan { range, file } = self.expr_src(expr);

                let mut res = Report::error()
                    .with_message(format!(
                        "function '{func:?}' is currently not supported by OpenVAF"
                    ))
                    .with_labels(vec![Label {
                        style: LabelStyle::Primary,
                        file_id: file,
                        range: range.into(),
                        message: "unsupported function".to_owned(),
                    }]);

                res = res.with_notes(vec![
                        "This function is part of the Verilog-A standard but currently not implemented by OpenVAF\nIf this function is important to your application, create an issue:\nhttps://github.com/pascalkuthe/openvaf/issues/new".to_owned(),
                    ]);

                res
            }
            BodyValidationDiagnostic::IncompatibleNatureAccess {
                ref candidates,
                access_nature,
                access_expr,
                ref branch,
            } => {
                let FileSpan { range, file } = self.expr_src(access_expr);
                let access_nature = access_nature.map(|nature| self.db.nature_data(nature));

                let message = if let Some(access_nature) = access_nature {
                    format!("'{}' is not a valid nature for this branch", access_nature.name)
                } else {
                    "illegal access".to_owned()
                };

                let labels = vec![Label {
                    style: LabelStyle::Primary,
                    file_id: file,
                    range: range.into(),
                    message,
                }];

                let help_msg = match candidates {
                    [None, None] => {
                        "help: this branch has a natureless discipline and can't be accessed"
                            .to_owned()
                    }
                    [None, Some((flow, flow_access))] => {
                        format!("help: use '{}' to access '{}' (flow)", flow_access, flow)
                    }
                    [Some((pot, pot_access)), None] => {
                        format!("help: use '{}' to access '{}' (potential)", pot_access, pot)
                    }
                    [Some((pot, pot_access)), Some((flow, flow_access))] => {
                        format!(
                            "help: use '{}' or '{}' to access '{}' (potential) or '{}' (flow)",
                            pot_access, flow_access, pot, flow
                        )
                    }
                };

                let msg = format!("illegal access of branch '{branch}'");

                Report::error().with_labels(labels).with_message(msg).with_notes(vec![help_msg])
            }
            BodyValidationDiagnostic::IllegalNatureAccess { is_pot, access_expr } => {
                let name = if is_pot { "potential" } else { "flow" };
                let src = self.expr_src(access_expr);
                Report::error()
                    .with_labels(vec![Label {
                        style: LabelStyle::Primary,
                        file_id: src.file,
                        range: src.range.into(),
                        message: format!("access of branch without {name}"),
                    }])
                    .with_message(format!("'{name}' access of branch without {name}"))
                    .with_notes(vec![format!("help: this branches nodes have a discipline without the '{name}' attribute")])
            }
            BodyValidationDiagnostic::IncompatibleImplicitBranch { access, node1, node2 } => {
                let node1_ = self.db.node_data(node1);
                let node2_ = self.db.node_data(node2);
                IncompatibleBranchDiagnostic {
                    branch_span: self.expr_src(access),
                    branch_name: format!("({},{})", node1_.name, node2_.name),
                    node1,
                    node2,
                }
                .into_report(self.db, self.parse, self.map, self.sm)
            }
            BodyValidationDiagnostic::RecursiveFunctionCall { expr, ref cycle } => {
                let FileSpan { range, file } = self.expr_src(expr);
                let name = &cycle[0];
                let chain =
                    cycle.iter().map(|n| n.to_string()).collect::<Vec<_>>().join(" -> ");
                Report::error()
                    .with_message(format!(
                        "analog function '{name}' cannot call itself: recursion is not allowed"
                    ))
                    .with_labels(vec![Label {
                        style: LabelStyle::Primary,
                        file_id: file,
                        range: range.into(),
                        message: "this call is mutually recursive".to_owned(),
                    }])
                    .with_notes(vec![
                        format!("info: call cycle: {chain}"),
                        "help: Verilog-A analog functions must not be recursive (LRM 4.7); rewrite the computation as a loop".to_owned(),
                    ])
            }
            BodyValidationDiagnostic::UnknownAnalysisName {
                ref name,
                ref builtin,
                expr,
                stmt,
            } => {
                let FileSpan { range, file } = match expr {
                    Some(expr) => self.expr_src(expr),
                    None => self.stmt_src(stmt),
                };
                Report::warning()
                    .with_message(format!(
                        "{builtin} names the analysis \"{name}\", which no analysis \
                         can ever match"
                    ))
                    .with_labels(vec![Label {
                        style: LabelStyle::Primary,
                        file_id: file,
                        range: range.into(),
                        message: "not an analysis name".to_owned(),
                    }])
                    .with_notes(vec![
                        "the simulator matches these names: ac, dc, ic, nodeset, noise, \
                         static, tran"
                            .to_owned(),
                        "as written this is dead code -- the branch is never taken and \
                         the event never fires"
                            .to_owned(),
                    ])
            }
            BodyValidationDiagnostic::UnknownLimitFunction { ref name, nargs, expr, .. } => {
                let FileSpan { range, file } = self.expr_src(expr);
                Report::error()
                    .with_message(format!(
                        "$limit names the limiting function \"{name}\", which this \
                         simulator does not provide with {nargs} extra argument(s)"
                    ))
                    .with_labels(vec![Label {
                        style: LabelStyle::Primary,
                        file_id: file,
                        range: range.into(),
                        message: "unresolvable limiting function".to_owned(),
                    }])
                    .with_notes(vec![
                        "ngspice provides pnjlim (2 extra args), fetlim (1), limitlog (1) \
                         and limvds (0)"
                            .to_owned(),
                        "a name or argument count it cannot resolve makes the .osdi file \
                         refuse to load; it used to crash the simulator outright"
                            .to_owned(),
                    ])
            }

            BodyValidationDiagnostic::InvalidBuiltinArg {
                ref builtin, ref what, ref why, expr,
            } => {
                let FileSpan { range, file } = self.expr_src(expr);
                Report::error()
                    .with_message(format!("{builtin}: {what} {why}"))
                    .with_labels(vec![Label {
                        style: LabelStyle::Primary,
                        file_id: file,
                        range: range.into(),
                        message: format!("invalid {what} for {builtin}"),
                    }])
                    .with_notes(vec![
                        "checked only when the argument is written out as a constant; a \
                         value computed at run time is the model's own responsibility"
                            .to_owned(),
                    ])
            }

            BodyValidationDiagnostic::RngInLoop { ref name, expr, .. } => {
                let FileSpan { range, file } = self.expr_src(expr);
                Report::error()
                    .with_message(format!(
                        "`{name}` inside a loop draws the same number every iteration"
                    ))
                    .with_labels(vec![Label {
                        style: LabelStyle::Primary,
                        file_id: file,
                        range: range.into(),
                        message: "constant within the loop".to_owned(),
                    }])
                    .with_notes(vec![
                        "the statistical builtins are pure functions of (seed, salt), and \
                         `salt` is fixed per call site, so one call site in a loop yields \
                         one value"
                            .to_owned(),
                        "this is deliberate: a seed that advances in place, as the LRM \
                         nominally prescribes, would change on every model evaluation and \
                         break DC/transient convergence"
                            .to_owned(),
                        "help: to vary a draw per iteration, use a separate call site per \
                         sample (e.g. unroll with a genvar), or move the draw out of the loop"
                            .to_owned(),
                    ])
            }

            BodyValidationDiagnostic::TrivialBranchAccess { branch, expr, .. } => {
                let FileSpan { range, file } = self.expr_src(expr);
                let db = self.db.upcast();
                let branch_name = match branch {
                    BranchWrite::Named(branch) => {
                        let branch = branch.lookup(db).name(db);
                        branch.to_string()
                    }
                    BranchWrite::Unnamed { hi, lo: Some(lo) } => {
                        format!("({}, {})", db.node_data(hi).name, db.node_data(lo).name)
                    }
                    BranchWrite::Unnamed { hi, lo: None } => {
                        format!("({})", db.node_data(hi).name)
                    }
                };
                let branch_probe = match branch {
                    BranchWrite::Named(_) => &branch_name,
                    BranchWrite::Unnamed { .. } => &branch_name[1..branch_name.len() - 1],
                };

                let mut res = Report::error()
                    .with_message("Current probe always returns zero".to_owned())
                    .with_labels(vec![Label {
                        style: LabelStyle::Primary,
                        file_id: file,
                        range: range.into(),
                        message: "always returns zero".to_owned(),
                    }]);

                res = res.with_notes(vec![
                    format!("help: there are no contributions to branch {branch_name}",),
                    format!("info: branches are open circuted by default: I({branch_probe}) <+ 0"),
                ]);

                res
            }
        }
    }

    fn to_report(&self, root_file: FileId, db: &dyn BaseDB) -> Option<Report> {
        // Enhancement-390: a `$table_model` data file is reported only when it
        // cannot actually be used. The check lives here because this is the first
        // point with both the root file (to resolve a relative path) and the VFS.
        if let BodyValidationDiagnostic::TableFileUnusable { ref path, .. } = *self.diag {
            if table_file_is_usable(root_file, db, path) {
                return None;
            }
        }
        if let Some((lint, lint_src)) = self.lint(root_file, db) {
            let (lvl, is_default) = match lint_src.overwrite {
                Some(lvl) => (lvl, false),
                None => db.lint_lvl(lint, root_file, lint_src.ast),
            };
            let basedb::lints::LintData { name, documentation_id, .. } = db.lint_data(lint);

            let seververity = match lvl {
                basedb::lints::LintLevel::Deny => basedb::diagnostics::Severity::Error,
                basedb::lints::LintLevel::Warn => basedb::diagnostics::Severity::Warning,
                basedb::lints::LintLevel::Allow => return None,
            };

            let mut report = self.build_report(root_file, db);

            if is_default {
                let hint = format!("{} is set to {} by default", name, lvl);
                report.notes.push(hint)
            }

            report.severity = seververity;
            Some(report.with_code(format!("L{:03}", documentation_id)))
        } else {
            Some(self.build_report(root_file, db))
        }
    }
}

pub struct TypeValidationDiagnosticWrapped<'a> {
    pub diag: &'a TypeValidationDiagnostic,
    pub parse: &'a Parse<SourceFile>,
    pub db: &'a dyn HirTyDB,
    pub sm: &'a SourceMap,
    pub map: &'a AstIdMap,
    pub item_tree: &'a ItemTree,
}

impl TypeValidationDiagnosticWrapped<'_> {
    fn build_duplicate_item<Def, Item: Copy>(
        &self,
        info: &DuplicateItem<Item, Def>,
        mut to_loc: impl FnMut(Item) -> TextRange,
    ) -> Vec<Label> {
        let first = self.parse.to_file_span(to_loc(info.first), self.sm);

        let mut labels = vec![Label {
            style: LabelStyle::Secondary,
            file_id: first.file,
            range: first.range.into(),
            message: "first declared here".to_owned(),
        }];
        let subsequent = info.subsequent.iter().map(|item| {
            let loc = self.parse.to_file_span(to_loc(*item), self.sm);
            Label {
                style: LabelStyle::Primary,
                file_id: loc.file,
                range: loc.range.into(),
                message: "redeclared here".to_owned(),
            }
        });

        labels.extend(subsequent);

        labels
    }
}
impl Diagnostic for TypeValidationDiagnosticWrapped<'_> {
    fn build_report(&self, _root_file: basedb::FileId, _db: &dyn basedb::BaseDB) -> Report {
        match *self.diag {
            TypeValidationDiagnostic::PathError { ref err, src } => {
                let src = self.parse.to_file_span(src.range(), self.sm);

                Report::error()
                    .with_labels(vec![Label {
                        style: LabelStyle::Primary,
                        file_id: src.file,
                        range: src.range.into(),
                        message: err.message(),
                    }])
                    .with_message(err.to_string())
            }
            TypeValidationDiagnostic::DuplicateDisciplineAttr(ref info) => {
                let discipline = &self.item_tree[info.src.lookup(self.db.upcast()).id];
                let labels = self.build_duplicate_item(info, |attr| {
                    let id = u32::from(discipline.extra_attrs.start()) + u32::from(attr);
                    let id = DisciplineAttr::lookup(self.item_tree, id.into()).ast_id();
                    self.map.get(id).range()
                });

                let name = self.db.discipline_data(info.src).attrs[info.first].name.clone();

                Report::error().with_labels(labels).with_message(format!(
                    "discipline attribute '{}' was defined multiple times",
                    name
                ))
            }
            TypeValidationDiagnostic::DuplicateNatureAttr(ref info) => {
                let nature = &self.item_tree[info.src.lookup(self.db.upcast()).id];
                let labels = self.build_duplicate_item(info, |attr| {
                    let id = u32::from(nature.attrs.start()) + u32::from(attr);
                    let id = NatureAttr::lookup(self.item_tree, id.into()).ast_id();
                    self.map.get(id).range()
                });

                let name = self.db.nature_data(info.src).attrs[info.first].name.clone();

                Report::error()
                    .with_labels(labels)
                    .with_message(format!("nature attribute '{}' was defined multiple times", name))
            }
            TypeValidationDiagnostic::MultipleDirections(ref info) => {
                let labels = self.build_duplicate_item(info, |id| self.map.get(id).range());
                let name = self.db.node_data(info.src).name.clone();

                Report::error()
                    .with_labels(labels)
                    .with_message(format!("multiple direction declarations for port '{}'", name))
            }
            TypeValidationDiagnostic::MultipleDisciplines(ref info) => {
                let labels = self.build_duplicate_item(info, |id| self.map.get_syntax(id).range());
                let name = self.db.node_data(info.src).name.clone();

                Report::error()
                    .with_labels(labels)
                    .with_message(format!("multiple discipline declarations for net '{}'", name))
            }
            TypeValidationDiagnostic::MultipleGnds(ref info) => {
                let labels = self.build_duplicate_item(info, |id| self.map.get_syntax(id).range());
                let name = self.db.node_data(info.src).name.clone();

                Report::error()
                    .with_labels(labels)
                    .with_message(format!("multiple 'ground' declarations for net '{}'", name))
            }
            TypeValidationDiagnostic::PortWithoutDirection { decl, ref name } => {
                let src = self.parse.to_file_span(self.map.get_syntax(decl).range(), self.sm);

                Report::error()
                    .with_labels(vec![Label {
                        style: LabelStyle::Primary,
                        file_id: src.file,
                        range: src.range.into(),
                        message: format!("'{}' is declared here without direction", name),
                    }])
                    .with_message(format!("no direction declared for port '{}'", name))
                    .with_notes(vec![
                        "if port_without_direction is set to warn/allow the direciton will be set to 'inout'.".to_owned(), 
                        "note: port directions are always required by the language standard.".to_owned()])
            }
            TypeValidationDiagnostic::ExpectedPort { node, src } => {
                let src = self.parse.to_file_span(self.map.get_syntax(src).range(), self.sm);
                let decl = node.lookup(self.db.upcast()).ast_id(self.db.upcast());
                let decl = self.parse.to_file_span(self.map.get_syntax(decl).range(), self.sm);
                let node = self.db.node_data(node);
                let name = &node.name;

                Report::error()
                    .with_labels(vec![
                        Label {
                            style: LabelStyle::Primary,
                            file_id: src.file,
                            range: src.range.into(),
                            message: format!("'{}' is not a port", name),
                        },
                        Label {
                            style: LabelStyle::Secondary,
                            file_id: decl.file,
                            range: decl.range.into(),
                            message: format!("info: '{}' was declared here", name),
                        },
                    ])
                    .with_notes(vec![
                        "help: prefix one of the declarations with inout, input or output"
                            .to_owned(),
                    ])
                    .with_message(format!(
                        "expected a port reference but no direction was declared for net '{}",
                        name
                    ))
            }
            TypeValidationDiagnostic::NodeWithoutDiscipline { decl, ref name } => {
                let src = self.parse.to_file_span(self.map.get_syntax(decl).range(), self.sm);

                Report::error()
                    .with_labels(vec![Label {
                        style: LabelStyle::Primary,
                        file_id: src.file,
                        range: src.range.into(),
                        message: format!("'{name}' is missing a discipline"),
                    }])
                    .with_message(format!("no discipline for net '{name}'"))
                    .with_notes(vec![
                        format!("info: disciplineless nets are digital and therefore not supported in Verilog-A"),
                        format!("help: add a discipline with 'electrical {name}'"),
                    ])
            }
            TypeValidationDiagnostic::IncompatibleBranch { branch, node1, node2 } => {
                let branch = branch.lookup(self.db.upcast());
                let branch_range = branch.ast_ptr(self.db.upcast()).range();
                let branch_name = branch.name(self.db.upcast()).to_string();
                IncompatibleBranchDiagnostic {
                    branch_span: self.parse.to_file_span(branch_range, self.sm),
                    branch_name,
                    node1,
                    node2,
                }
                .into_report(self.db, self.parse, self.map, self.sm)
            }
        }
    }

    fn lint(&self, _root_file: FileId, _db: &dyn BaseDB) -> Option<(Lint, LintSrc)> {
        match *self.diag {
            TypeValidationDiagnostic::PortWithoutDirection { decl, .. } => {
                Some((lints::builtin::port_without_direction, LintSrc::item(decl)))
            }
            _ => None,
        }
    }
}

/// Enhancement-390: can this `$table_model` data file actually be read and does it
/// contain at least one usable number?
///
/// Deliberately permissive -- it answers "is this file usable at all", not "is the
/// grid well formed". The lowering code owns the format; this only distinguishes a
/// real data file from a mistyped name, an empty file, or prose. Anything it lets
/// through behaves exactly as before.
fn table_file_is_usable(root_file: FileId, db: &dyn BaseDB, path: &str) -> bool {
    let Some(dir) = db.file_path(root_file).parent() else { return true };
    let Some(full) = dir.join(path) else { return true };
    let Some(abs) = full.as_path() else { return true };
    let Ok(content) = std::fs::read_to_string(abs) else { return false };
    // Comment lines are skipped by the readers, so skip them here too.
    let nums: Vec<f64> = content
        .lines()
        .map(str::trim)
        .filter(|l| !(l.is_empty() || l.starts_with('#') || l.starts_with("//") || l.starts_with('*')))
        .flat_map(|l| l.split_ascii_whitespace())
        .filter_map(|tok| tok.parse::<f64>().ok())
        .collect();
    if nums.len() < 2 {
        return false;
    }
    // Enhancement-396: `f64::from_str` accepts "nan", "inf", "-infinity", and it
    // returns an INFINITY rather than an error for an overflowing exponent like
    // 1e400. A non-numeric token such as "abc" was already rejected, so a file
    // holding a missing-data marker -- which is exactly how measured data files
    // spell one -- slipped through and poisoned the ENTIRE table: every query,
    // including points that should interpolate between valid rows, returned NaN
    // with no diagnostic. The readers in hir_lower apply the same rule.
    if nums.iter().any(|v| !v.is_finite()) {
        return false;
    }
    // The N-dimensional form is `ndim / sizes[ndim] / axes... / values`; the
    // one-dimensional form is a flat list of (x, y) PAIRS. Accept a file that fits
    // either shape exactly, which is what distinguishes a real table from a stray
    // column of numbers -- the case that used to interpolate an empty table and
    // contribute zero.
    let d = nums[0];
    if d.fract() == 0.0 && (1.0..=8.0).contains(&d) && nums.len() > 1 + d as usize {
        let ndim = d as usize;
        let sizes: Vec<usize> = nums[1..1 + ndim]
            .iter()
            .map(|v| if v.fract() == 0.0 && *v >= 1.0 { *v as usize } else { 0 })
            .collect();
        if sizes.iter().all(|&s| s > 0) {
            let axes: usize = sizes.iter().sum();
            let vals: usize = sizes.iter().product();
            if nums.len() == 1 + ndim + axes + vals {
                return true;
            }
        }
    }
    nums.len() % 2 == 0
}
