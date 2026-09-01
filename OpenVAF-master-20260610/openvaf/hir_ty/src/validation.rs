use basedb::diagnostics::{Diagnostic, Label, LabelStyle, Report};
use basedb::lints::builtin::{
    const_simparam, rng_in_loop, runtime_format_string, trivial_probe, unknown_analysis_name,
    unknown_limit_function, unknown_simparam,
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
use crate::validation::body::{
    BodyCtx, IllegalCtxAccess, IllegalCtxAccessKind, SIMPARAM_NAMES, SIMPARAM_STR_NAMES,
};
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
                        "help: LRM 3.11.1: disciplines of one domain are compatible when \
                         every nature binding PRESENT ON BOTH sides is compatible (same \
                         base nature or same 'units'); a binding absent on one side is \
                         no conflict, and a natureless discipline is compatible with its \
                         whole domain"
                            .to_owned(),
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
            BodyValidationDiagnostic::UnknownSimparam { stmt, .. } => {
                let src = self.body_sm.lint_src(stmt, unknown_simparam);
                Some((unknown_simparam, src))
            }
            BodyValidationDiagnostic::RuntimeFormatString { stmt, .. } => {
                let src = self.body_sm.lint_src(stmt, runtime_format_string);
                Some((runtime_format_string, src))
            }
            _ => None,
        }
    }

    fn build_report(&self, root_file: basedb::FileId, db: &dyn basedb::BaseDB) -> Report {
        let _ = (root_file, db);
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
            BodyValidationDiagnostic::IllegalEventControl { stmt, ctx } => {
                let FileSpan { range, file } = self.stmt_src(stmt);
                Report::error()
                    .with_message(format!("event control statements are not allowed in {ctx}"))
                    .with_labels(vec![Label {
                        style: LabelStyle::Primary,
                        file_id: file,
                        range: range.into(),
                        message: "this event control cannot be used here".to_owned(),
                    }])
                    .with_notes(vec![
                        "help: the statement it guards would never run; move the event \
                         control into the analog block, where events are evaluated"
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
            // Enhancement-414: as TableFileUnusable, for a noise data file.
            BodyValidationDiagnostic::NoiseTableFileUnusable { expr, ref path, log } => {
                let FileSpan { range, file } = self.expr_src(expr);
                // Enhancement-506: the file form validated STRUCTURE and not VALUES.
                // When the structure is fine and only a value is out of domain, say
                // which value -- the inline form has named it since Enhancement-396.
                let bad = noise_table_file_bad_value(root_file, db, path, log);
                let (label, extra) = match bad {
                    Some((v, what)) if log => (
                        format!("holds a {what} of {v}; noise_table_log needs every entry > 0"),
                        "log-log interpolation takes log10 of BOTH columns, so a zero entry \
                         is as unrepresentable as a negative one and made the whole output \
                         spectrum NaN -- at every frequency, with nothing reported"
                            .to_owned(),
                    ),
                    Some((v, what)) => (
                        format!("holds a {what} of {v}; every entry must be >= 0"),
                        "a negative entry reached the runtime and produced exactly the \
                         spectrum of its positive twin, so the sign was discarded in \
                         silence -- the same defect Enhancement-396 fixed for an inline \
                         table, which this form did not share"
                            .to_owned(),
                    ),
                    None => (
                        "missing, unreadable, or contains no usable table data".to_owned(),
                        "an unusable file used to yield an EMPTY noise table, and an empty \
                         table contributes NO NOISE -- the output spectrum came out identical \
                         to a model with no noise source at all, with nothing reported"
                            .to_owned(),
                    ),
                };
                Report::error()
                    .with_message(format!("cannot use '{path}' as noise_table data"))
                    .with_labels(vec![Label {
                        style: LabelStyle::Primary,
                        file_id: file,
                        range: range.into(),
                        message: label,
                    }])
                    .with_notes(vec![
                        "the path is resolved relative to the directory of the file being \
                         compiled"
                            .to_owned(),
                        extra,
                    ])
            }
            // Enhancement-390: only reached when the file is genuinely unusable --
            // `to_report` filters out the readable, parseable ones.
            BodyValidationDiagnostic::TableFileUnusable { expr, ref path, .. } => {
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
            BodyValidationDiagnostic::IllegalIndirectContribute { stmt, ctx } => {
                let FileSpan { range, file } = self.parse.to_file_span(
                    self.body_sm.stmt_map_back[stmt]
                        .as_ref()
                        .map_or_else(TextRange::default, |it| it.range()),
                    self.sm,
                );

                Report::error()
                    .with_message(format!(
                        "indirect branch contributions are not allowed in {}",
                        ctx
                    ))
                    .with_labels(vec![Label {
                        style: LabelStyle::Secondary,
                        file_id: file,
                        range: range.into(),
                        message: "not allowed here".to_owned(),
                    }])
                    .with_notes(vec![
                        "help: LRM 5.6.7 forbids indirect branch contributions in conditional \
                         or looping statements unless the controlling expression is a constant \
                         expression, and 5.6.5 forbids contributions inside event controls; a \
                         guarded-off indirect assignment leaves its constraint equation as \
                         0 = 0 -- a singular matrix"
                            .to_owned(),
                    ])
            }
            BodyValidationDiagnostic::MixedIndirectContribute { direct, indirect } => {
                let FileSpan { range, file } = self.parse.to_file_span(
                    self.body_sm.stmt_map_back[direct]
                        .as_ref()
                        .map_or_else(TextRange::default, |it| it.range()),
                    self.sm,
                );
                let ind_span = self.parse.to_file_span(
                    self.body_sm.stmt_map_back[indirect]
                        .as_ref()
                        .map_or_else(TextRange::default, |it| it.range()),
                    self.sm,
                );

                Report::error()
                    .with_message(
                        "direct contribution to a branch that is the target of an indirect \
                         branch assignment"
                            .to_owned(),
                    )
                    .with_labels(vec![
                        Label {
                            style: LabelStyle::Primary,
                            file_id: file,
                            range: range.into(),
                            message: "this `<+` contribution targets the branch".to_owned(),
                        },
                        Label {
                            style: LabelStyle::Secondary,
                            file_id: ind_span.file,
                            range: ind_span.range.into(),
                            message: "the branch is indirectly assigned here".to_owned(),
                        },
                    ])
                    .with_notes(vec![
                        "help: LRM 5.6.7.2 -- once a value is indirectly assigned to a branch \
                         it cannot be contributed to with `<+`; the constraint equation pins \
                         the branch value and the direct contribution would be silently \
                         absorbed by the implicit unknown"
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
            BodyValidationDiagnostic::SelfReferentialParam { def, expr } => {
                let FileSpan { range, file } = self.expr_src(expr);
                let (def_name, _) = self.lookup(def);
                Report::error()
                    .with_message(format!(
                        "definition of '{def_name}' references itself"
                    ))
                    .with_labels(vec![Label {
                        style: LabelStyle::Primary,
                        file_id: file,
                        range: range.into(),
                        message: format!("'{def_name}' has no value here -- it is the \
                                          declaration being defined"),
                    }])
                    .with_notes(vec![
                        "the initializer used to be folded twice, so a self-reference \
                         produced an arbitrary value (`p = p + 1` gave 2) with nothing \
                         reported"
                            .to_owned(),
                    ])
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
                    IllegalCtxAccessKind::SmallSignalSourceInLoop { name } => res
                        .with_message(format!(
                            "'{}' creates a small-signal source, which is not allowed in \
                             loops",
                            name
                        ))
                        .with_notes(vec![
                            "the source was silently DROPPED: the device registered no \
                             source at all and contributed exactly nothing"
                                .to_owned(),
                            "help: analog operators (ddt, idt, laplace_*, ...) have always \
                             been rejected here for the same reason (LRM 4.5.1); noise and \
                             ac_stim sources reached the same code path and were discarded \
                             instead of reported"
                                .to_owned(),
                            "help: hoist it out of the loop, or unroll with `generate` -- a \
                             genvar loop creates one source per iteration, which is what a \
                             per-finger or per-segment model wants"
                                .to_owned(),
                        ]),
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
                        "help: the value of parameters like \"gmin\" or \"sourceScaleFactor\" may vary between iterations"
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
            BodyValidationDiagnostic::RealtimeInAnalog { expr, .. } => {
                let FileSpan { range, file } = self.expr_src(expr);
                Report::warning()
                    .with_message(
                        "$realtime in the analog context is deprecated by VAMS-2023",
                    )
                    .with_labels(vec![Label {
                        style: LabelStyle::Primary,
                        file_id: file,
                        range: range.into(),
                        message: "behaves as $abstime here".to_owned(),
                    }])
                    .with_notes(vec![
                        "help: Table 9-7 removes $realtime from the analog context; this \
                         compiler keeps it as an alias of $abstime -- absolute SECONDS, \
                         ignoring any `timescale (VAMS 2.0-2.4 scaled it to `timescale \
                         units instead). Use $abstime"
                            .to_owned(),
                    ])
            }
            BodyValidationDiagnostic::NestedEventControl { stmt } => {
                let FileSpan { range, file } = self.stmt_src(stmt);
                Report::error()
                    .with_message("nested event control statements are not allowed")
                    .with_labels(vec![Label {
                        style: LabelStyle::Primary,
                        file_id: file,
                        range: range.into(),
                        message: "this @(...) is inside another @(...)".to_owned(),
                    }])
                    .with_notes(vec![
                        "help: LRM 5.10 forbids nesting; the nested form would gate the \
                         body on BOTH events firing in one evaluation -- for step events \
                         that is never. Use one @(...) with an `or` list instead"
                            .to_owned(),
                    ])
            }
            BodyValidationDiagnostic::EventInConditional { stmt, form, in_loop } => {
                let FileSpan { range, file } = self.stmt_src(stmt);
                let place = if in_loop { "a repeat/while/for loop" } else { "a conditional" };
                Report::error()
                    .with_message(format!("{form} is not allowed inside {place}"))
                    .with_labels(vec![Label {
                        style: LabelStyle::Primary,
                        file_id: file,
                        range: range.into(),
                        message: format!("{form} under a runtime condition"),
                    }])
                    .with_notes(vec![format!(
                        "help: LRM 5.10.3.1: cross/above shall not be used inside an \
                         if/case unless the condition is a genvar expression, and not in \
                         repeat/while loops -- the event's internal state only advances \
                         when this branch executes, so detection would compare against a \
                         stale value. Move the {form} to the top level and test the \
                         condition inside its body"
                    )])
            }
            BodyValidationDiagnostic::InvalidEventExpr { stmt, ref name } => {
                let FileSpan { range, file } = self.stmt_src(stmt);
                let (msg, help) = match name.as_deref() {
                    Some("absdelta") => (
                        "@(absdelta) is not part of the analog subset".to_owned(),
                        "help: LRM 5.10.3.4 allows absdelta only in digital initial/always \
                         blocks, which Verilog-A does not have (Annex C.7)"
                            .to_owned(),
                    ),
                    Some(name) => (
                        format!("`{name}` is not a valid analog event"),
                        "help: LRM 5.10: the analog event expressions are initial_step, \
                         final_step, cross(...), above(...) and timer(...); named events \
                         (5.10.4) are not part of the Verilog-A analog subset. Before this \
                         check, an unrecognized event was silently DROPPED and the guarded \
                         statement ran on every evaluation"
                            .to_owned(),
                    ),
                    None => (
                        "not a valid analog event expression".to_owned(),
                        "help: LRM 5.10: expected initial_step, final_step, cross(...), \
                         above(...) or timer(...)"
                            .to_owned(),
                    ),
                };
                Report::error()
                    .with_message(msg)
                    .with_labels(vec![Label {
                        style: LabelStyle::Primary,
                        file_id: file,
                        range: range.into(),
                        message: "unrecognized event expression".to_owned(),
                    }])
                    .with_notes(vec![help])
            }
            BodyValidationDiagnostic::SimprobeNoDefault { expr, .. } => {
                let FileSpan { range, file } = self.expr_src(expr);
                Report::warning()
                    .with_message(
                        "$simprobe without a default expression is FATAL at run time"
                            .to_owned(),
                    )
                    .with_labels(vec![Label {
                        style: LabelStyle::Primary,
                        file_id: file,
                        range: range.into(),
                        message: "no default to fall back on".to_owned(),
                    }])
                    .with_notes(vec![
                        "help: this simulator resolves no $simprobe probes, and LRM 9.16 \
                         says 'if either the inst_name or param_name cannot be resolved, \
                         and the optional expression is not supplied, then an error shall \
                         be generated'; supply a third argument to fall back on it instead"
                            .to_owned(),
                    ])
            }
            BodyValidationDiagnostic::AliasOutsideInitial { expr, port, .. } => {
                let FileSpan { range, file } = self.expr_src(expr);
                let name =
                    if port { "$analog_port_alias" } else { "$analog_node_alias" };
                Report::error()
                    .with_message(format!(
                        "{name} is only allowed inside an analog initial block"
                    ))
                    .with_labels(vec![Label {
                        style: LabelStyle::Primary,
                        file_id: file,
                        range: range.into(),
                        message: "not an analog initial block".to_owned(),
                    }])
                    .with_notes(vec![
                        "help: LRM 9.20 -- aliases are established before the analog \
                         block runs; 'it shall be an error for these functions to be \
                         used in any other context'"
                            .to_owned(),
                    ])
            }
            BodyValidationDiagnostic::TypeStringOutsideParamset { expr, .. } => {
                let FileSpan { range, file } = self.expr_src(expr);
                Report::warning()
                    .with_message(
                        "the type_string argument is only meaningful inside a paramset"
                            .to_owned(),
                    )
                    .with_labels(vec![Label {
                        style: LabelStyle::Primary,
                        file_id: file,
                        range: range.into(),
                        message: "has no effect here".to_owned(),
                    }])
                    .with_notes(vec![
                        "help: LRM 9.13.1/9.13.2 -- \"global\"/\"instance\" 'shall only \
                         be used in calls to these functions from within a paramset'; \
                         outside one the draw is unaffected"
                            .to_owned(),
                    ])
            }
            BodyValidationDiagnostic::DynamicFilterCoeff { expr, form, .. } => {
                let FileSpan { range, file } = self.expr_src(expr);
                Report::warning()
                    .with_message(format!(
                        "{form}: a coefficient depends on the solution and will TRACK"
                    ))
                    .with_labels(vec![Label {
                        style: LabelStyle::Primary,
                        file_id: file,
                        range: range.into(),
                        message: "solution-dependent filter coefficient".to_owned(),
                    }])
                    .with_notes(vec![
                        "help: LRM 4.5.14 / Table 4-20 class the zero/pole/coefficient \
                         vectors as constant expressions: a dynamic value would take its \
                         value at the start of the analysis and further changes 'shall be \
                         ignored'. This implementation re-evaluates the vectors every \
                         iteration, so the filter becomes time-varying instead"
                            .to_owned(),
                    ])
            }
            BodyValidationDiagnostic::EventTolIgnored { expr, form, what, .. } => {
                let FileSpan { range, file } = self.expr_src(expr);
                Report::warning()
                    .with_message(format!(
                        "{form}: the {what} tolerance is accepted but not honored"
                    ))
                    .with_labels(vec![Label {
                        style: LabelStyle::Primary,
                        file_id: file,
                        range: range.into(),
                        message: "this tolerance has no effect".to_owned(),
                    }])
                    .with_notes(vec![
                        "help: event detection is evaluation-granular and does not bound \
                         the timestep, so the event fires at the first solver evaluation \
                         past the crossing regardless of the requested tolerance; write \
                         0.0 (LRM: 'the simulator shall apply a suitable value') to \
                         accept that without this warning"
                            .to_owned(),
                    ])
            }
            BodyValidationDiagnostic::JumpOutsideLoop { stmt, is_break } => {
                let kw = if is_break { "break" } else { "continue" };
                let FileSpan { range, file } = self.stmt_src(stmt);
                Report::error()
                    .with_message(format!("`{kw}` outside a loop"))
                    .with_labels(vec![Label {
                        style: LabelStyle::Primary,
                        file_id: file,
                        range: range.into(),
                        message: "no enclosing runtime loop".to_owned(),
                    }])
                    .with_notes(vec![format!(
                        "help: LRM 5.11: `{kw}` acts on the innermost enclosing loop; \
                         a genvar analog for-loop does not count (5.9.3 excludes jump \
                         statements there)"
                    )])
            }
            BodyValidationDiagnostic::ReturnOutsideFunction { stmt } => {
                let FileSpan { range, file } = self.stmt_src(stmt);
                Report::error()
                    .with_message("`return` outside an analog function")
                    .with_labels(vec![Label {
                        style: LabelStyle::Primary,
                        file_id: file,
                        range: range.into(),
                        message: "not inside an analog function body".to_owned(),
                    }])
                    .with_notes(vec![
                        "help: LRM 5.11: `return` exits an analog user-defined function; \
                         in a module's analog block use `disable <block>` to leave a \
                         named block early"
                            .to_owned(),
                    ])
            }
            BodyValidationDiagnostic::SameNodeBranchAccess { access, node, is_pot } => {
                let name = &self.db.node_data(node).name;
                let acc = if is_pot { "potential" } else { "flow" };
                let FileSpan { range, file } = self.expr_src(access);
                Report::error()
                    .with_message(format!(
                        "both arguments of the {acc} access name the same net '{name}'"
                    ))
                    .with_labels(vec![Label {
                        style: LabelStyle::Primary,
                        file_id: file,
                        range: range.into(),
                        message: format!("({name}, {name}) does not define a branch"),
                    }])
                    .with_notes(vec![
                        "help: LRM 4.4 (Table 4-16): the two nets of a branch access must \
                         be distinct -- V(n,n) and I(n,n) are errors"
                            .to_owned(),
                    ])
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
                        // Enhancement-420: `ac_stim` reaches this diagnostic too, and
                        // its consequence is a different one -- the source is still
                        // built, it just never becomes active.
                        if &**builtin == "ac_stim" {
                            "as written this stimulus is permanently inactive -- the \
                             simulator gates the source on this name, so it sources \
                             nothing in any analysis"
                                .to_owned()
                        } else {
                            "as written this is dead code -- the branch is never taken \
                             and the event never fires"
                                .to_owned()
                        },
                    ])
            }
            BodyValidationDiagnostic::RuntimeFormatString { ref builtin, expr, .. } => {
                let FileSpan { range, file } = self.expr_src(expr);
                Report::warning()
                    .with_message(format!(
                        "{builtin}: this format string is not a literal, so it is printed \
                         rather than interpreted"
                    ))
                    .with_labels(vec![Label {
                        style: LabelStyle::Primary,
                        file_id: file,
                        range: range.into(),
                        message: "printed as a value; the arguments after it are appended"
                            .to_owned(),
                    }])
                    .with_notes(vec![
                        "a format is read when the model is COMPILED, to fix each \
                         conversion's argument type; a string only known at run time \
                         cannot be read then, so `%g` and friends reach the output \
                         verbatim"
                            .to_owned(),
                        "help: write the format as a literal, or build the whole message \
                         with $sformat and print that"
                            .to_owned(),
                    ])
            }
            BodyValidationDiagnostic::UnknownSimparam {
                ref name,
                ref builtin,
                has_default_form,
                expr,
                ..
            } => {
                let FileSpan { range, file } = self.expr_src(expr);
                /* Enhancement-476: built from the same arrays the check uses.
                 * This note used to be a second, hand-written copy of the list,
                 * and it drifted: `temp` was served by ngspice (Enhancement-434)
                 * yet appeared in neither, so the warning fired on a name that
                 * works and then told the author it was fatal. */
                let served = if has_default_form {
                    SIMPARAM_NAMES.join(", ")
                } else {
                    SIMPARAM_STR_NAMES.join(", ")
                };
                let mut notes = vec![
                    format!("the simulator serves these names: {served}"),
                    "an unresolvable name is FATAL at run time -- the model aborts the \
                     analysis, it does not merely read zero"
                        .to_owned(),
                ];
                if has_default_form {
                    notes.push(
                        format!("help: `$simparam(\"{name}\", <default>)` returns the \
                                 default instead of aborting, which is how a model stays \
                                 portable across simulators"),
                    );
                }
                Report::warning()
                    .with_message(format!(
                        "{builtin} names the simulator parameter \"{name}\", which this \
                         simulator does not provide"
                    ))
                    .with_labels(vec![Label {
                        style: LabelStyle::Primary,
                        file_id: file,
                        range: range.into(),
                        message: "unknown simulator parameter".to_owned(),
                    }])
                    .with_notes(notes)
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
                         and limvds/vdslim (0)"
                            .to_owned(),
                        "a name or argument count ngspice cannot resolve falls back to NO \
                         limiting at load time, with a warning (LRM 9.17.3: an unknown \
                         function behaves as if no string had been supplied)"
                            .to_owned(),
                    ])
            }

            BodyValidationDiagnostic::InvalidBuiltinArg {
                ref builtin, ref what, ref why, expr, warn,
            } => {
                let FileSpan { range, file } = self.expr_src(expr);
                if warn { Report::warning() } else { Report::error() }
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

                // Enhancement-406: this used to read "Current probe always returns zero",
                // with a note that "branches are open circuted by default: I(x) <+ 0".
                // Both described the behaviour Enhancement-36 replaced. A branch nothing
                // contributes to is no longer an open circuit that reads zero: probing its
                // flow synthesises the LRM's 0 V source, so it is an ideal AMMETER -- a
                // SHORT across its nodes -- and the probe reads whatever current then
                // flows. Measured: 1.0e-3 A through such a branch while the message
                // claimed zero. It reads zero only when the short carries no current,
                // which is the isolated case and no longer the general one.
                let mut res = Report::error()
                    .with_message(format!(
                        "branch {branch_name} has no contributions, so probing its flow \
                         shorts it"
                    ))
                    .with_labels(vec![Label {
                        style: LabelStyle::Primary,
                        file_id: file,
                        range: range.into(),
                        message: "this probe makes the branch an ideal ammeter".to_owned(),
                    }]);

                res = res.with_notes(vec![
                    format!("help: there are no contributions to branch {branch_name}"),
                    "info: probing the flow of a branch nothing contributes to synthesises \
                     an ideal ammeter -- a 0 V source (LRM 5.4.2) -- so the branch is a \
                     SHORT across its nodes, and the probe reads the current that then \
                     flows through it; it reads zero only when no current can flow"
                        .to_owned(),
                    format!(
                        "help: to model an open circuit instead, contribute nothing and do \
                         not probe; to model a device, contribute to it -- e.g. \
                         I({branch_probe}) <+ ..."
                    ),
                ]);

                res
            }
        }
    }

    fn to_report(&self, root_file: FileId, db: &dyn BaseDB) -> Option<Report> {
        // Enhancement-390: a `$table_model` data file is reported only when it
        // cannot actually be used. The check lives here because this is the first
        // point with both the root file (to resolve a relative path) and the VFS.
        if let BodyValidationDiagnostic::TableFileUnusable { ref path, ndim, .. } = *self.diag {
            if table_file_is_usable(root_file, db, path, ndim, true) {
                return None;
            }
        }
        // Enhancement-414: a noise data file is judged by the same rule -- readable, and
        // holding at least one finite pair.
        // Enhancement-425: a noise data file is ALWAYS the one-dimensional
        // two-column form -- `read_noise_table_file` reads the first two tokens of
        // each line -- so it is checked with ndim = 1 unconditionally.
        // Enhancement-506: and by the same VALUE rule the inline form has applied
        // since Enhancement-396 -- structure alone let a negative frequency or
        // power through, and a zero through to `noise_table_log`.
        if let BodyValidationDiagnostic::NoiseTableFileUnusable { ref path, log, .. } = *self.diag {
            if table_file_is_usable(root_file, db, path, 1, false)
                && noise_table_file_bad_value(root_file, db, path, log).is_none()
            {
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
            TypeValidationDiagnostic::UnresolvedNatureRef {
                ref owner,
                what,
                ref referenced,
                ref err,
                src,
            } => {
                let span = self.parse.to_file_span(self.map.get_syntax(src).range(), self.sm);
                let (kind, of) = if what == "potential" || what == "flow" {
                    ("discipline", "attribute")
                } else {
                    ("nature", "attribute")
                };
                Report::error()
                    .with_message(format!(
                        "{kind} '{owner}' names '{referenced}' as its {what}, which is not \
                         a nature"
                    ))
                    .with_labels(vec![Label {
                        style: LabelStyle::Primary,
                        file_id: span.file,
                        range: span.range.into(),
                        message: format!("unresolved {what} {of}"),
                    }])
                    .with_notes(vec![
                        err.message(),
                        match what {
                            "parent nature" => {
                                "this used to abort the compiler with a crash report \
                                 during code generation, whether or not the nature was \
                                 ever used"
                                    .to_owned()
                            }
                            "potential" | "flow" => format!(
                                "the discipline has no {what} nature; every access \
                                 through it was previously reported against the model \
                                 body instead of here"
                            ),
                            _ => format!(
                                "the {what} was silently discarded, so the nature behaved \
                                 as though it had none"
                            ),
                        },
                    ])
            }
            TypeValidationDiagnostic::NatureCycle { ref name, ref chain, src } => {
                let span = self.parse.to_file_span(self.map.get_syntax(src).range(), self.sm);
                let chain =
                    chain.iter().map(|it| it.to_string()).collect::<Vec<_>>().join(" -> ");
                Report::error()
                    .with_message(format!(
                        "nature '{name}' inherits from itself: its parent chain closes on \
                         itself"
                    ))
                    .with_labels(vec![Label {
                        style: LabelStyle::Primary,
                        file_id: span.file,
                        range: span.range.into(),
                        message: "cyclic parent nature".to_owned(),
                    }])
                    .with_notes(vec![
                        format!("info: cycle: {chain}"),
                        "the cycle was silently broken, leaving the nature as its own base \
                         nature -- it inherited no units, which changes which disciplines \
                         it is compatible with"
                            .to_owned(),
                    ])
            }
            TypeValidationDiagnostic::NonConstantAbstol { ref name, src } => {
                let span = self.parse.to_file_span(self.map.get_syntax(src).range(), self.sm);
                Report::error()
                    .with_message(format!(
                        "nature '{name}' declares an abstol that is not a real constant"
                    ))
                    .with_labels(vec![Label {
                        style: LabelStyle::Primary,
                        file_id: span.file,
                        range: span.range.into(),
                        message: "abstol must be a real constant".to_owned(),
                    }])
                    .with_notes(vec![
                        "the value was discarded, so the nature ended up with no abstol at \
                         all -- which is not what the declaration says"
                            .to_owned(),
                    ])
            }
            TypeValidationDiagnostic::BadAbstol { ref name, ref value, src } => {
                let span = self.parse.to_file_span(self.map.get_syntax(src).range(), self.sm);
                Report::error()
                    .with_message(format!(
                        "nature '{name}' declares abstol = {value}, which is not a usable \
                         absolute tolerance"
                    ))
                    .with_labels(vec![Label {
                        style: LabelStyle::Primary,
                        file_id: span.file,
                        range: span.range.into(),
                        message: "abstol must be finite and greater than zero".to_owned(),
                    }])
                    .with_notes(vec![
                        "abstol is the size below which the solver stops distinguishing two \
                         values; zero, negative, infinite and NaN all reach the simulator \
                         unchallenged"
                            .to_owned(),
                    ])
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
            TypeValidationDiagnostic::DerivedNatureUnits { nature, attr } => {
                let nature_ = &self.item_tree[nature.lookup(self.db.upcast()).id];
                let id = u32::from(nature_.attrs.start()) + u32::from(attr);
                let id = NatureAttr::lookup(self.item_tree, id.into()).ast_id();
                let range = self.map.get(id).range();
                let FileSpan { file, range } = self.parse.to_file_span(range, self.sm);
                let name = self.db.nature_data(nature).name.clone();
                let inherited = self
                    .db
                    .nature_info(nature)
                    .units
                    .clone()
                    .unwrap_or_default();
                Report::warning()
                    .with_labels(vec![Label {
                        style: LabelStyle::Primary,
                        file_id: file,
                        range: range.into(),
                        message: "this units value is ignored".to_owned(),
                    }])
                    .with_message(format!(
                        "derived nature '{name}' declares units; the inherited value \
                         \"{inherited}\" is used instead"
                    ))
                    .with_notes(vec![
                        "help: LRM 3.6.1.2: it is illegal for a derived nature to define or \
                         change the units -- it always inherits its parent nature's units"
                            .to_owned(),
                    ])
            }
            TypeValidationDiagnostic::UnrelatedIdtDdtOverride {
                nature,
                what,
                own,
                parent_link,
                src,
            } => {
                let range = self.map.get_syntax(src).range();
                let FileSpan { file, range } = self.parse.to_file_span(range, self.sm);
                let name = self.db.nature_data(nature).name.clone();
                let own_name = self.db.nature_data(own).name.clone();
                let link_name = self.db.nature_data(parent_link).name.clone();
                Report::warning()
                    .with_labels(vec![Label {
                        style: LabelStyle::Primary,
                        file_id: file,
                        range: range.into(),
                        message: format!("{what} override is '{own_name}'"),
                    }])
                    .with_message(format!(
                        "derived nature '{name}' overrides {what} with '{own_name}', which is \
                         unrelated to the parent's '{link_name}'"
                    ))
                    .with_notes(vec![format!(
                        "help: LRM 3.6.1.2: a {what} override in a derived nature shall be \
                         related (share the same base nature) to the nature the parent uses; \
                         only idt/ddt tolerance selection is affected"
                    )])
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
            TypeValidationDiagnostic::DegenerateBranch { branch, node, src } => {
                let src = self.parse.to_file_span(self.map.get_syntax(src).range(), self.sm);
                let bname = self.db.branch_data(branch).name.clone();
                let nname = self.db.node_data(node).name.clone();
                Report::warning()
                    .with_message(format!(
                        "branch '{bname}' names the same node '{nname}' twice"
                    ))
                    .with_labels(vec![Label {
                        style: LabelStyle::Primary,
                        file_id: src.file,
                        range: src.range.into(),
                        message: "both endpoints are the same node".to_owned(),
                    }])
                    .with_notes(vec![
                        format!(
                            "the potential across it is identically zero, and every flow \
                             contributed to it is DISCARDED -- `I({bname}) <+ ..` adds \
                             nothing to the system"
                        ),
                        "if a second terminal was meant, name it here".to_owned(),
                    ])
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
            // Enhancement-414
            TypeValidationDiagnostic::DegenerateBranch { src, .. } => {
                Some((lints::builtin::degenerate_branch, LintSrc::item(src)))
            }
            _ => None,
        }
    }
}

/// Enhancement-390: can this `$table_model` / `noise_table` data file actually be
/// used, given the dimensionality of the call that names it?
///
/// Enhancement-425 gave this the CALL'S `ndim` and split it into the two grammars
/// the readers actually implement, because a single "count the numbers" rule could
/// not express either of them.
///
/// Formerly the only shape check was global token-count PARITY (`nums.len() % 2 ==
/// 0`) over the whole file, with non-numeric tokens silently discarded. Detection
/// was therefore luck: a corrupt row that dropped TWO tokens (`N/A N/A`) kept the
/// count even and sailed through, while one that dropped ONE was caught. Measured
/// on a table `(0,0) (1,100) (2,20)` queried at x=0.5: 50 with the row intact, 5
/// with it corrupted -- a tenfold wrong answer, silently.
///
/// The N-dimensional case was strictly worse. Corrupting one token in
/// examples/mdtable_examples/mos_iv.tbl leaves 50 numbers -- even, so parity
/// accepted it -- `read_table_grid_nd` then returns `None` and `lower_table_model`
/// does `return F_ZERO`, so the whole table contributes EXACTLY ZERO. Measured:
/// drain current -3.2e-04 to 0.0, with a clean compile.
///
/// WHY `ndim` HAD TO COME FROM THE CALL. The two forms cannot be told apart by
/// looking at the file: `2 3 / 4 5 / 6 7` is a perfectly good 1-D table whose
/// leading numbers also read as a 2-dimensional header. Guessing from the content
/// -- which is what the old `let d = nums[0]` branch did -- false-positives on real
/// 1-D data.
/// `multi_col` distinguishes the two 1-D consumers (kernel audit): a
/// `$table_model` file may carry N+M columns per LRM 9.21.1 (the dependent
/// selector picks one), while a noise data file is ALWAYS the two-column
/// `(frequency, power)` form -- `read_noise_table_file` reads exactly two
/// tokens per line, and this check must keep agreeing with that reader.
fn table_file_is_usable(
    root_file: FileId,
    db: &dyn BaseDB,
    path: &str,
    ndim: usize,
    multi_col: bool,
) -> bool {
    let Some(dir) = db.file_path(root_file).parent() else { return true };
    let Some(full) = dir.join(path) else { return true };
    let Some(abs) = full.as_path() else { return true };
    let Ok(content) = std::fs::read_to_string(abs) else { return false };
    // Whole-line comments only, exactly as all three readers in `hir_lower` do it.
    // Inline comments are deliberately NOT stripped here: no reader strips them
    // either, so stripping them would make this check disagree with the code that
    // consumes the file -- and the invariant that the validator and the readers
    // apply the same rule is what Enhancement-396 relied on.
    let lines = || {
        content
            .lines()
            .map(str::trim)
            .filter(|l| {
                !(l.is_empty()
                    || l.starts_with('#')
                    || l.starts_with("//")
                    || l.starts_with('*'))
            })
    };

    // Parse every non-comment line into finite numeric rows; any unusable
    // token fails the file, exactly as before.
    let mut rows: Vec<Vec<f64>> = Vec::new();
    for line in lines() {
        let mut row = Vec::new();
        for tok in line.split_ascii_whitespace() {
            // Enhancement-396: `f64::from_str` accepts "nan", "inf", "-infinity",
            // and returns an INFINITY rather than an error for an overflowing
            // exponent like 1e400 -- exactly how a measured data file spells a
            // missing value. The readers in hir_lower apply the same rule.
            let Ok(v) = tok.parse::<f64>() else { return false };
            if !v.is_finite() {
                return false;
            }
            row.push(v);
        }
        if !row.is_empty() {
            rows.push(row);
        }
    }
    if rows.is_empty() {
        return false;
    }

    // The LRM 9.21.1 isoline judgement: one sample per line and a CONSTANT
    // N+M column count. Ragged isolines are LEGAL ("the number and spacing
    // of samples may be different on each isoline" -- the LRM's own sample
    // file is ragged), so no grid-completeness demand: the reader
    // interpolates the isoline tree directly.
    let isoline_ok = |rows: &[Vec<f64>], ndim: usize, multi_col: bool| -> bool {
        let width = rows[0].len();
        if width <= ndim || rows.iter().any(|r| r.len() != width) {
            return false;
        }
        if !multi_col && width != ndim + 1 {
            return false;
        }
        true
    };

    if ndim <= 1 {
        // The one-dimensional form is line-structured. A noise file must be
        // exactly the two-column pair form; a `$table_model` file may carry
        // extra dependent columns (LRM 9.21.1; the `;N` selector picks one).
        return isoline_ok(&rows, 1, multi_col);
    }

    // The self-describing N-dimensional grid: free-form whitespace across
    // lines (grid4.tbl puts its 36-value tensor on one line), the header
    // accounting for the token count EXACTLY.
    let nums: Vec<f64> = rows.iter().flatten().copied().collect();
    let grid_ok = (|| {
        if nums.len() < 1 + ndim {
            return false;
        }
        // The file's own leading `ndim` must agree with the call's.
        if nums[0].fract() != 0.0 || nums[0] != ndim as f64 {
            return false;
        }
        let sizes: Vec<usize> = nums[1..1 + ndim]
            .iter()
            .map(|v| if v.fract() == 0.0 && *v >= 1.0 { *v as usize } else { 0 })
            .collect();
        if sizes.iter().any(|&s| s == 0) {
            return false;
        }
        let axes: usize = sizes.iter().sum();
        let vals: usize = sizes.iter().product();
        nums.len() == 1 + ndim + axes + vals
    })();
    // Kernel audit: the LRM 9.21.1 N+M-column format is the normative one
    // and is accepted alongside the project's self-describing grid, exactly
    // as `lower_table_model` now tries both.
    grid_ok || isoline_ok(&rows, ndim, true)
}

/// Enhancement-506: the first out-of-domain entry of a noise data file, if any.
///
/// `table_file_is_usable` judges a noise file's STRUCTURE -- readable, one
/// `(frequency, power)` pair per line, every token finite. Its VALUES were judged
/// nowhere, so a file was accepted that the identical table written inline is
/// refused for: a frequency of -1 produced output bit-identical to +1 (the sign
/// quietly discarded), and a zero handed to `noise_table_log` made the entire
/// spectrum NaN.
///
/// The rule is the inline rule, so that which of the two forms the author chose
/// cannot change whether the table is legal: entries must be non-negative, and
/// strictly positive for the log variant, whose log-log interpolation cannot
/// represent a zero. Reading is deliberately the same whole-line-comment grammar
/// the readers in `hir_lower` use -- the invariant that the validator and the
/// readers agree is what Enhancement-396 relied on.
fn noise_table_file_bad_value(
    root_file: FileId,
    db: &dyn BaseDB,
    path: &str,
    log: bool,
) -> Option<(f64, &'static str)> {
    let dir = db.file_path(root_file).parent()?;
    let full = dir.join(path)?;
    let abs = full.as_path()?;
    let content = std::fs::read_to_string(abs).ok()?;
    for line in content.lines().map(str::trim).filter(|l| {
        !(l.is_empty() || l.starts_with('#') || l.starts_with("//") || l.starts_with('*'))
    }) {
        let mut it = line.split_ascii_whitespace();
        let (Some(a), Some(b)) = (it.next(), it.next()) else { continue };
        let (Ok(f), Ok(p)) = (a.parse::<f64>(), b.parse::<f64>()) else { continue };
        for (v, what) in [(f, "frequency"), (p, "noise power")] {
            let ok = if log { v > 0.0 } else { v >= 0.0 };
            if !ok {
                return Some((v, what));
            }
        }
    }
    None
}
