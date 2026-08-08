use ordered_float::OrderedFloat;
use std::mem;
use std::sync::Arc;

use arena::IdxRange;
use basedb::{AstId, AstIdMap, ErasedAstId, FileId};
use syntax::ast::{self, BinaryOp, ParamRef, PathSegmentKind, UnaryOp};
use syntax::name::{kw, AsIdent, AsName, Name};
use syntax::ast::ConstraintKind;
use syntax::{match_ast, AstNode, ConstExprValue, WalkEvent};
use typed_index_collections::TiVec;

use super::{
    Block, Branch, BranchKind, BusDecl, Discipline, DisciplineAttr, DisciplineAttrKind, Domain,
    Function, FunctionArg, FunctionItem, Instantiation, ItemTree, ItemTreeDiagnostic, ItemTreeId,
    Module, ModuleItem, Nature, NatureAttr, NatureRef, NatureRefKind, Net, Node, Param, Port,
    RootItem, Var,
};
// use tracing::trace;
use crate::db::HirDefDB;
use crate::item_tree::AliasParam;
use crate::types::AsType;
use crate::{LocalFunctionArgId, LocalNodeId, Path, Type};
use rustc_hash::FxHashMap;

/// Tries to constant-fold a `[msb:lsb]` width clause into two integers.
/// Only literal integers (optionally unary-negated) are supported, matching
/// `ast::Expr::as_constexprval`. Returns `None` if either bound is missing or
/// not a constant integer.
/// Enhancement-148: cap on how many scalar elements an array / bus / instance-array
/// declaration may expand to. Each element becomes its own scalar net/var/instance, so
/// an unbounded range (`real x[0:100000000]`) would exhaust memory; past this it is
/// reported and degraded to a single scalar. Real declared arrays are far smaller.
const MAX_ARRAY_ELEMS: i64 = 1 << 20; // ~1.05M

/// Number of scalar elements a set of `[msb:lsb]` dimensions expands to, or `None` if
/// that exceeds `MAX_ARRAY_ELEMS` (or overflows).
fn array_elem_count(dims: &[(i32, i32)]) -> Option<i64> {
    let n = dims.iter().try_fold(1i64, |acc, (msb, lsb)| {
        acc.checked_mul((*msb as i64 - *lsb as i64).abs() + 1)
    })?;
    (n <= MAX_ARRAY_ELEMS).then_some(n)
}

/// Enhancement-405: folds an integer CONSTANT EXPRESSION appearing in a `[msb:lsb]` bound.
///
/// `as_constexprval` sees only a literal with an optional unary sign, so `[0:3-1]` was
/// rejected as "not a constant expression", and so was `` [0:`N-1] `` -- the ordinary way to
/// size an array from a `define`. Even `[(0):(2)]` was rejected, while a *named* parameter
/// bound `[0:P]` worked, because named bounds are resolved on a different path (E-92). The
/// LRM asks for a constant expression here, not a literal.
///
/// This is deliberately a small SYNTACTIC folder and not `const_int_expr`: it runs in the
/// item tree, BEFORE name resolution, so it cannot and must not try to resolve names -- a
/// name still folds to `None` and takes the existing path. Division and remainder by zero
/// fold to `None` rather than panicking, and every step is checked so an overflowing bound is
/// reported as non-constant instead of wrapping.
fn fold_const_int(expr: &ast::Expr) -> Option<i32> {
    match expr {
        ast::Expr::ParenExpr(e) => fold_const_int(&e.expr()?),
        ast::Expr::PrefixExpr(e) => {
            let val = fold_const_int(&e.expr()?)?;
            match e.op_kind()? {
                UnaryOp::Neg => val.checked_neg(),
                UnaryOp::Identity => Some(val),
                _ => None,
            }
        }
        ast::Expr::BinExpr(e) => {
            let lhs = fold_const_int(&e.lhs()?)?;
            let rhs = fold_const_int(&e.rhs()?)?;
            match e.op_details()?.1 {
                BinaryOp::Addition => lhs.checked_add(rhs),
                BinaryOp::Subtraction => lhs.checked_sub(rhs),
                BinaryOp::Multiplication => lhs.checked_mul(rhs),
                BinaryOp::Division => lhs.checked_div(rhs),
                BinaryOp::Remainder => lhs.checked_rem(rhs),
                BinaryOp::LeftShift => u32::try_from(rhs).ok().and_then(|s| lhs.checked_shl(s)),
                BinaryOp::RightShift => u32::try_from(rhs).ok().and_then(|s| lhs.checked_shr(s)),
                _ => None,
            }
        }
        _ => match expr.as_constexprval()? {
            ConstExprValue::Int(v) => Some(v),
            _ => None,
        },
    }
}

fn fold_width_range(range: &ast::Range) -> Option<(i32, i32)> {
    Some((fold_const_int(&range.start()?)?, fold_const_int(&range.end()?)?))
}

/// Folds every `[msb:lsb]` width clause of an array declaration into a per-dimension
/// `(msb, lsb)` list (outermost dimension first). `None` if any bound isn't a constant integer.
/// Counts the leaf elements of a (possibly nested) `'{...}` array literal; any
/// non-aggregate expression counts as one leaf. Used to check an array
/// variable/parameter initializer against the declared element count
/// (Enhancement-43) before the per-element bodies index into it.
fn count_literal_leaves(expr: &ast::Expr) -> u32 {
    match expr {
        ast::Expr::ArrayExpr(arr) => arr.exprs().map(|e| count_literal_leaves(&e)).sum(),
        _ => 1,
    }
}

fn fold_width_ranges<'a>(widths: impl Iterator<Item = ast::Range>) -> Option<Vec<(i32, i32)>> {
    widths.map(|r| fold_width_range(&r)).collect()
}

/// Parses a synthesized bus-bit name like `"bus[3]"` back into `("bus", 3)`.
/// Used only for diagnosing out-of-range branch-endpoint bit-selects after the
/// fact (the index was already validated to be a constant integer at the
/// point the name was synthesized).
fn parse_synthesized_bit_name(name: &Name) -> Option<(Name, i32)> {
    let s: &str = name;
    let open = s.rfind('[')?;
    if !s.ends_with(']') {
        return None;
    }
    let idx_str = &s[open + 1..s.len() - 1];
    let idx: i32 = idx_str.parse().ok()?;
    Some((Name::resolve(&s[..open]), idx))
}

fn is_input(direction: &Option<ast::Direction>) -> bool {
    direction.as_ref().map_or(false, |it| it.input_token().is_some() || it.inout_token().is_some())
}

fn is_output(direction: &Option<ast::Direction>) -> bool {
    direction.as_ref().map_or(false, |it| it.output_token().is_some() || it.inout_token().is_some())
}

pub(super) struct Ctx {
    tree: ItemTree,
    source_ast_id_map: Arc<AstIdMap>,
}

impl Ctx {
    pub(super) fn new(db: &dyn HirDefDB, file: FileId) -> Self {
        Self { tree: ItemTree::default(), source_ast_id_map: db.ast_id_map(file) }
    }

    pub(super) fn lower_root_items(mut self, file: &ast::SourceFile) -> ItemTree {
        self.tree.top_level = file.items().filter_map(|it| self.lower_root_item(it)).collect();
        self.tree
    }

    fn lower_root_item(&mut self, item: ast::Item) -> Option<RootItem> {
        let item = match item {
            ast::Item::DisciplineDecl(discipline) => self.lower_discipline(discipline)?.into(),
            ast::Item::NatureDecl(nature) => self.lower_nature(nature)?.into(),
            ast::Item::ModuleDecl(module) => self.lower_module(module)?.into(),
            ast::Item::ParamsetDecl(paramset) => self.lower_paramset(paramset)?.into(),
        };
        Some(item)
    }

    /// Lowers a Verilog-AMS `paramset` (Enhancement-21) into a synthetic "twin" module.
    ///
    /// A `paramset <name> <target>;` defines an instantiable model `<name>` that behaves exactly
    /// like `<target>` (same terminals, same analog behaviour) but with the listed target
    /// parameters bound to the paramset's `.<param> = <expr>;` expressions. The twin module reuses
    /// the target's ports/body/branches/functions verbatim by *sharing the target's `ast_id`*,
    /// under the paramset's name; the paramset's own parameters are added as the twin's (card)
    /// parameters, and each bound target parameter is replaced by a fresh `localparam` whose value
    /// is the override expression (so it is no longer settable from the model card). Everything
    /// downstream (name resolution, body lowering, OSDI descriptor emission) then treats the twin
    /// as an ordinary module.
    fn lower_paramset(&mut self, decl: ast::ParamsetDecl) -> Option<ItemTreeId<Module>> {
        let name = decl.name()?.as_name();
        let ast_id = self.source_ast_id_map.ast_id(&decl);
        let target_name = decl.target()?.as_name();
        // Enhancement-398: the syntax root, so a target parameter's declaration
        // (and therefore its constraints) can be reached while binding.
        let root = decl.syntax().ancestors().last()?;

        // The target module must already be lowered (declared earlier in the file).
        let target_id = self
            .tree
            .data
            .modules
            .iter_enumerated()
            .find(|(_, m)| m.name == target_name)
            .map(|(id, _)| id);
        let Some(target_id) = target_id else {
            self.tree.diagnostics.push(ItemTreeDiagnostic::UnknownParamsetTarget {
                ast_id: ast_id.into(),
                target: target_name,
            });
            return None;
        };

        // Collect the override map: target-parameter name -> `.<param> = <expr>;` node.
        // A `.$mfactor = <expr>;` (hierarchical system parameter, Enhancement-44) is kept
        // separately: it binds no target parameter, but becomes a hidden localparam whose
        // value composes with the instance-level system parameter in `sim_back`.
        let mut overrides: Vec<(Name, AstId<ast::ParamsetOverride>, ast::ParamsetOverride)> =
            Vec::new();
        let mut hsp_overrides: Vec<(crate::builtin::ParamSysFun, AstId<ast::ParamsetOverride>)> =
            Vec::new();
        for ov in decl.overrides() {
            let Some(name_ref) = ov.name() else { continue };
            let ov_id = self.source_ast_id_map.ast_id(&ov);
            if let Some(tok) = name_ref.sysfun_token() {
                match crate::builtin::ParamSysFun::from_sysfun_text(tok.text()) {
                    Some(sys) => hsp_overrides.push((sys, ov_id)),
                    None => self.tree.diagnostics.push(
                        ItemTreeDiagnostic::InvalidParamsetSysParam {
                            ast_id: ov_id.into(),
                            name: tok.text().to_owned(),
                        },
                    ),
                }
                continue;
            }
            // Enhancement-398: the binder below takes the FIRST match, so a
            // repeated assignment silently discarded the later one.
            let nm = name_ref.as_name();
            if overrides.iter().any(|(n, _, _)| *n == nm) {
                self.tree.diagnostics.push(ItemTreeDiagnostic::ParamsetDuplicateOverride {
                    ast_id: ov_id.into(),
                    name: nm.clone(),
                });
            }
            overrides.push((nm, ov_id, ov.clone()));
        }

        // Lower the paramset's own parameters (the twin's card parameters) first, so their item-
        // tree ids precede the target's items -- a bound target parameter (now a localparam) may
        // reference them in its override expression.
        let mut items: Vec<ModuleItem> = Vec::new();
        let mut param_arrays: Vec<BusDecl> = Vec::new();
        for pd in decl.param_decls() {
            self.lower_param(pd, &mut items, Some(&mut param_arrays));
        }

        // Each hierarchical system parameter override becomes a hidden real localparam named
        // `$paramset$<name>` (Enhancement-44). The `$`-spelling can collide with no user
        // identifier, deliberately differs from the OSDI built-in instance parameter
        // `$mfactor` (so ngspice's `m=` alias keeps pointing at the instance value), and is
        // recognised by name in `sim_back`, which composes it with the instance-level value
        // (multiplicatively for $mfactor/$hflip/$vflip, additively for positions/$angle).
        // Its value is the override expression, lowered through the ordinary E-21
        // localparam-with-override machinery, so it may reference the card parameters above.
        // The `ast_id` is a placeholder (there is no `ast::Param` node behind it); the
        // override-expression branch of `param_body_with_sourcemap` never dereferences it.
        for &(sys, ov) in &hsp_overrides {
            let param = Param {
                name: Name::resolve(&format!("$paramset${sys:?}")),
                ty: Some(Type::Real),
                is_local: true,
                ast_id: AstId::<ast::Param>::from_erased(ov.erased()),
                array_index: None,
                override_expr: Some(ov),
            };
            let id = self.tree.data.parameters.push_and_get_key(param);
            items.push(ModuleItem::Parameter(id));
        }

        // Append the target's items, rebinding any overridden parameter to a fresh localparam.
        let target = self.tree.data.modules[target_id].clone();
        let mut bound_names: Vec<Name> = Vec::new();
        for &item in &target.items {
            match item {
                ModuleItem::Parameter(pid) => {
                    let param_name = self.tree.data.parameters[pid].name.clone();
                    if let Some((_, ov, ov_node)) =
                        overrides.iter().find(|(n, _, _)| *n == param_name).cloned()
                    {
                        bound_names.push(param_name.clone());
                        // Enhancement-398: the bound parameter becomes a localparam and
                        // `param_body_with_sourcemap` discards its constraints, so nothing
                        // downstream ever range-checks it -- a paramset was the ONE way to
                        // put a value the declaration forbids into a model. Check it here,
                        // where both the override and the target's constraints are still
                        // syntax.
                        if let Some(pa) = self
                            .source_ast_id_map
                            .get(self.tree.data.parameters[pid].ast_id)
                            .to_node(&root)
                            .into()
                        {
                            let pa: ast::Param = pa;
                            self.check_paramset_range(&param_name, &pa, &ov_node, ov);
                        }
                        let mut bound = self.tree.data.parameters[pid].clone();
                        bound.is_local = true;
                        bound.override_expr = Some(ov);
                        let new_id = self.tree.data.parameters.push_and_get_key(bound);
                        items.push(ModuleItem::Parameter(new_id));
                    } else {
                        items.push(ModuleItem::Parameter(pid));
                    }
                }
                other => items.push(other),
            }
        }

        // Enhancement-398: an override that matched no target parameter was simply
        // never applied -- silently. Report it, as the netlist path does.
        for (n, ov, _) in &overrides {
            if !bound_names.contains(n) {
                self.tree.diagnostics.push(ItemTreeDiagnostic::ParamsetUnknownParam {
                    ast_id: (*ov).into(),
                    name: n.clone(),
                    target: target_name.clone(),
                });
            }
        }

        param_arrays.extend(target.param_arrays.iter().cloned());

        let twin = Module {
            name,
            nodes: target.nodes.clone(),
            num_ports: target.num_ports,
            items,
            // Share the target's declaration AST: the twin's ports and analog body are the
            // target's, resolved through the twin's own scope.
            ast_id: target.ast_id,
            buses: target.buses.clone(),
            var_arrays: target.var_arrays.clone(),
            param_arrays,
            genvars: target.genvars.clone(),
        };
        Some(self.tree.data.modules.push_and_get_key(twin))
    }

    /// Enhancement-398: check a `paramset` override against the range the TARGET
    /// parameter declares.
    ///
    /// This is the one supply path that was unchecked. A model card, an instance
    /// line, `alter`, `altermod`, a `.param` and a subcircuit parameter all reach
    /// ngspice's runtime validation and abort with "Parameter k is out of
    /// bounds!"; a paramset instead binds the value to a localparam, and
    /// `param_body_with_sourcemap` returns `bounds: Vec::new()` for it -- so the
    /// constraint was discarded and `insert_param_init` had nothing to emit.
    ///
    /// Both the override and the constraints are still syntax at this point, so
    /// the check folds them directly. Only literal values are folded, which is
    /// deliberately narrow: an override built from the paramset's own (netlist-
    /// settable) parameters is not knowable here, and pretending otherwise would
    /// reject legitimate paramsets.
    ///
    /// This does NOT conflict with Enhancement-56, which refuses to range-check a
    /// parameter's DEFAULT: a paramset override is a supplied value, not a
    /// default, and is exactly what a range is meant to bind.
    /// Enhancement-399: a declared range that no value can satisfy.
    ///
    /// `from [3:1]` (inverted) and `from (1:1)` (open and degenerate) were both
    /// accepted. The consequence is not cosmetic: the DEFAULT bypasses range
    /// checking by design (Enhancement-56), so the parameter still reads its
    /// default, but EVERY value supplied from a netlist is rejected at run time.
    /// The parameter is silently unsettable, and the declaration -- which is
    /// where the mistake is -- said nothing.
    ///
    /// Only literal bounds are folded, deliberately: a bound built from another
    /// parameter is not knowable here, and `inf` does not fold, so `from (0:inf)`
    /// is untouched.
    fn check_param_range_satisfiable(
        &mut self,
        name: &Name,
        param_ast: &ast::Param,
        ast_id: ErasedAstId,
    ) {
        for c in param_ast.constraints() {
            if c.kind() != Some(ConstraintKind::From) {
                continue;
            }
            let Some(ast::ConstraintValue::Range(r)) = c.val() else { continue };
            let (Some(lo), Some(hi)) =
                (r.start().and_then(|e| Self::const_num(&e)), r.end().and_then(|e| Self::const_num(&e)))
            else {
                continue;
            };
            let why = if lo > hi {
                Some(format!("its lower bound {lo} is above its upper bound {hi}"))
            } else if lo == hi && !(r.start_inclusive() && r.end_inclusive()) {
                Some(format!(
                    "both bounds are {lo} and at least one of them is exclusive"
                ))
            } else {
                None
            };
            if let Some(why) = why {
                self.tree.diagnostics.push(ItemTreeDiagnostic::ParamRangeEmpty {
                    ast_id,
                    name: name.clone(),
                    constraint: Self::range_text(&r).into_boxed_str(),
                    why: why.into_boxed_str(),
                });
                return;
            }
        }
        self.check_param_excludes(name, param_ast, ast_id);
    }

    /// Enhancement-421: the same two questions as `check_param_range_satisfiable`,
    /// asked of `exclude` instead of `from`.
    ///
    /// Enhancement-399 rejected a `from` range no value can satisfy. It did not
    /// look at `exclude`, and the identical bounds spelled there fail in two
    /// ways that were both silent:
    ///
    ///   * `exclude [3:1]` -- an INVERTED interval excludes NOTHING. The author
    ///     wrote "keep 1 through 3 out" with the bounds the wrong way round and
    ///     every value in that band is accepted, with nothing said. The exact
    ///     same bounds as `from [3:1]` are a compile error.
    ///   * `from [0:10] exclude [0:10]` -- the exclusions between them cover the
    ///     whole range, so the parameter is UNSETTABLE. That is precisely the
    ///     end state Enhancement-399 reports for an empty `from`: the default
    ///     still reads (Enhancement-56 exempts it), and every netlist-supplied
    ///     value aborts the analysis with "Parameter x is out of bounds!".
    ///     Reached by the plausible route too -- an exclude WIDER than the range
    ///     it guards, or two excludes that happen to tile it.
    ///
    /// Literal bounds only, like every neighbouring check: one unfoldable bound
    /// anywhere in the exclusion set and the cover question is unanswerable, so
    /// nothing is said. `inf` does not fold either, so `from [0:inf)` is left
    /// alone exactly as Enhancement-399 leaves it.
    fn check_param_excludes(
        &mut self,
        name: &Name,
        param_ast: &ast::Param,
        ast_id: ErasedAstId,
    ) {
        // --- an exclusion that excludes nothing -----------------------------
        for c in param_ast.constraints() {
            if c.kind() != Some(ConstraintKind::Exclude) {
                continue;
            }
            let Some(ast::ConstraintValue::Range(r)) = c.val() else { continue };
            let (Some(lo), Some(hi)) = (
                r.start().and_then(|e| Self::const_num(&e)),
                r.end().and_then(|e| Self::const_num(&e)),
            ) else {
                continue;
            };
            let why = if lo > hi {
                Some(format!("its lower bound {lo} is above its upper bound {hi}"))
            } else if lo == hi && !(r.start_inclusive() && r.end_inclusive()) {
                Some(format!("both bounds are {lo} and at least one of them is exclusive"))
            } else {
                None
            };
            if let Some(why) = why {
                self.tree.diagnostics.push(ItemTreeDiagnostic::ParamExcludeEmpty {
                    ast_id,
                    name: name.clone(),
                    constraint: format!("exclude {}", Self::range_text(&r)).into_boxed_str(),
                    why: why.into_boxed_str(),
                });
                return;
            }
        }

        // --- do the exclusions cover the whole range? -----------------------
        // Exactly ONE `from` is handled. Several `from` clauses are a UNION, and
        // answering the cover question over a union is not what the mistake this
        // catches looks like; an unbounded (absent) `from` can never be covered.
        let mut from = None;
        for c in param_ast.constraints() {
            if c.kind() != Some(ConstraintKind::From) {
                continue;
            }
            if from.is_some() {
                return;
            }
            let Some(ast::ConstraintValue::Range(r)) = c.val() else { return };
            let (Some(lo), Some(hi)) = (
                r.start().and_then(|e| Self::const_num(&e)),
                r.end().and_then(|e| Self::const_num(&e)),
            ) else {
                return;
            };
            from = Some((
                Ival {
                    lo: Bound { v: lo, closed: r.start_inclusive() },
                    hi: Bound { v: hi, closed: r.end_inclusive() },
                },
                Self::range_text(&r),
            ));
        }
        let Some((from, from_text)) = from else { return };

        let mut excl: Vec<Ival> = Vec::new();
        let mut excl_text: Vec<String> = Vec::new();
        for c in param_ast.constraints() {
            if c.kind() != Some(ConstraintKind::Exclude) {
                continue;
            }
            match c.val() {
                Some(ast::ConstraintValue::Range(r)) => {
                    let (Some(lo), Some(hi)) = (
                        r.start().and_then(|e| Self::const_num(&e)),
                        r.end().and_then(|e| Self::const_num(&e)),
                    ) else {
                        return;
                    };
                    excl.push(Ival {
                        lo: Bound { v: lo, closed: r.start_inclusive() },
                        hi: Bound { v: hi, closed: r.end_inclusive() },
                    });
                    excl_text.push(format!("exclude {}", Self::range_text(&r)));
                }
                // a single excluded VALUE is the degenerate closed interval [v:v]
                Some(ast::ConstraintValue::Val(e)) => {
                    let Some(v) = Self::const_num(&e) else { return };
                    excl.push(Ival {
                        lo: Bound { v, closed: true },
                        hi: Bound { v, closed: true },
                    });
                    excl_text.push(format!("exclude {v}"));
                }
                None => return,
            }
        }
        if excl.is_empty() {
            return;
        }

        if Ival::covered_by(&from, &mut excl) {
            self.tree.diagnostics.push(ItemTreeDiagnostic::ParamExcludeCoversRange {
                ast_id,
                name: name.clone(),
                from: from_text.into_boxed_str(),
                excluded: excl_text.join(" ").into_boxed_str(),
            });
        }
    }

    fn check_paramset_range(
        &mut self,
        name: &Name,
        param_ast: &ast::Param,
        ov_node: &ast::ParamsetOverride,
        ov_id: AstId<ast::ParamsetOverride>,
    ) {
        let Some(val) = ov_node.val().and_then(|e| Self::const_num(&e)) else { return };

        for c in param_ast.constraints() {
            let Some(kind) = c.kind() else { continue };
            let Some(cv) = c.val() else { continue };
            let bad = match (&cv, kind) {
                (ast::ConstraintValue::Range(r), ConstraintKind::From) => {
                    let lo = r.start().and_then(|e| Self::const_num(&e));
                    let hi = r.end().and_then(|e| Self::const_num(&e));
                    let below = lo.is_some_and(|lo| {
                        if r.start_inclusive() { val < lo } else { val <= lo }
                    });
                    let above = hi.is_some_and(|hi| {
                        if r.end_inclusive() { val > hi } else { val >= hi }
                    });
                    (below || above).then(|| Self::range_text(r))
                }
                (ast::ConstraintValue::Range(r), ConstraintKind::Exclude) => {
                    let lo = r.start().and_then(|e| Self::const_num(&e));
                    let hi = r.end().and_then(|e| Self::const_num(&e));
                    let inside = lo.is_some_and(|lo| {
                        if r.start_inclusive() { val >= lo } else { val > lo }
                    }) && hi.is_some_and(|hi| {
                        if r.end_inclusive() { val <= hi } else { val < hi }
                    });
                    inside.then(|| format!("exclude {}", Self::range_text(r)))
                }
                (ast::ConstraintValue::Val(v), ConstraintKind::Exclude) => Self::const_num(v)
                    .is_some_and(|x| x == val)
                    .then(|| format!("exclude {val}")),
                _ => None,
            };
            if let Some(constraint) = bad {
                self.tree.diagnostics.push(ItemTreeDiagnostic::ParamsetOverrideOutOfRange {
                    ast_id: ov_id.into(),
                    name: name.clone(),
                    value: format!("{val}").into_boxed_str(),
                    constraint: constraint.into_boxed_str(),
                });
                return;
            }
        }
    }

    /// Render a declared range the way the model wrote it.
    ///
    /// A bound that is not a numeric literal -- `inf`, `-inf`, a parameter, an
    /// expression -- falls back to its SOURCE TEXT rather than a placeholder, so
    /// `from (0:inf)` reads as `(0:inf)` and not `(0:?)`. Such a bound is still
    /// not *checked* (an unfoldable bound constrains nothing here, which for
    /// `inf` is exactly right), but the message must still quote the range the
    /// reader has to go and look at.
    #[allow(clippy::wrong_self_convention)]
    fn range_text(r: &ast::Range) -> String {
        let f = |e: Option<ast::Expr>| match e {
            None => "?".to_owned(),
            Some(e) => match Self::const_num(&e) {
                Some(v) => format!("{v}"),
                None => e.syntax().text().to_string().split_whitespace().collect::<String>(),
            },
        };
        format!(
            "{}{}:{}{}",
            if r.start_inclusive() { "[" } else { "(" },
            f(r.start()),
            f(r.end()),
            if r.end_inclusive() { "]" } else { ")" }
        )
    }

    /// The numeric value of a literal expression (with an optional leading `-`).
    fn const_num(e: &ast::Expr) -> Option<f64> {
        match e.as_constexprval()? {
            ConstExprValue::Int(i) => Some(i as f64),
            ConstExprValue::Float(f) => Some(*f),
            ConstExprValue::String(_) => None,
        }
    }

    fn lower_discipline(&mut self, decl: ast::DisciplineDecl) -> Option<ItemTreeId<Discipline>> {
        use kw::raw as kw;
        let name = decl.name()?.as_name();
        let ast_id = self.source_ast_id_map.ast_id(&decl);

        let mut potential = None;
        let mut flow = None;
        let mut domain = None;
        let attr_start = self.tree.data.discipline_attrs.next_key();
        for (id, attr) in decl.discipline_attrs().enumerate() {
            if let Some(name) = attr.name() {
                let kind = if let Some(qual) = name.qualifier() {
                    let qual = qual.segment_token();
                    match qual.as_ref().map(|t| t.text()) {
                        Some(kw::potential) => DisciplineAttrKind::PotentialOverwrite,
                        Some(kw::flow) => DisciplineAttrKind::FlowOverwrite,
                        _ => continue,
                    }
                } else {
                    DisciplineAttrKind::UserDefined
                };

                if let Some(name) = name.segment_token().map(|t| t.as_name()) {
                    let ast_id = self.source_ast_id_map.ast_id(&attr);

                    let mut evaluated: Option<ConstExprValue> = None;
                    match &*name {
                        kw::potential if potential.is_none() => {
                            if let Some(name) = attr.val().and_then(Self::lower_nature_expr) {
                                evaluated = Some(ConstExprValue::String(name.name.to_string()));
                                potential = Some((name, id.into()));
                            }
                        }
                        kw::flow if flow.is_none() => {
                            if let Some(name) = attr.val().and_then(Self::lower_nature_expr) {
                                evaluated = Some(ConstExprValue::String(name.name.to_string()));
                                flow = Some((name, id.into()))
                            }
                        }
                        kw::domain if domain.is_none() => {
                            match attr.val().and_then(|e| e.as_ident()).as_deref() {
                                Some(kw::continuous) => {
                                    evaluated =
                                        Some(ConstExprValue::String(kw::continuous.to_string()));
                                    domain = Some((Domain::Continuous, id.into()));
                                }
                                Some(kw::discrete) => {
                                    evaluated =
                                        Some(ConstExprValue::String(kw::discrete.to_string()));
                                    domain = Some((Domain::Discrete, id.into()));
                                }
                                _ => {
                                    // All other attributes - evaluate ast expression
                                    evaluated = attr.val().and_then(|v| v.as_constexprval());
                                }
                            }
                        }

                        _ => (),
                    };

                    self.tree.data.discipline_attrs.push(DisciplineAttr {
                        name: name.clone(),
                        kind,
                        ast_id,
                        value: evaluated,
                    });
                }
            }
        }
        let attr_end = self.tree.data.discipline_attrs.next_key();
        let res = Discipline {
            ast_id,
            name,
            potential,
            flow,
            extra_attrs: IdxRange::new(attr_start..attr_end),
            domain,
        };
        Some(self.tree.data.disciplines.push_and_get_key(res))
    }

    fn lower_nature_path(decl: &ast::Path) -> Option<NatureRef> {
        let mut name = decl.segment_token()?.as_name();

        let kind = match &*name {
            kw::raw::potential => NatureRefKind::DisciplinePotential,
            kw::raw::flow => NatureRefKind::DisciplineFlow,
            _ if decl.qualifier().is_none() && decl.segment_kind()? == PathSegmentKind::Name => {
                NatureRefKind::Nature
            }
            _ => return None,
        };

        if matches!(kind, NatureRefKind::DisciplineFlow | NatureRefKind::DisciplinePotential) {
            let qual = decl.qualifier()?;
            let segment = qual.segment()?;
            if segment.kind == PathSegmentKind::Root || qual.qualifier().is_some() {
                return None;
            }
            name = segment.syntax.as_name();
        }

        Some(NatureRef { name, kind })
    }

    fn lower_nature_expr(decl: ast::Expr) -> Option<NatureRef> {
        if let ast::Expr::PathExpr(path) = decl {
            Self::lower_nature_path(&path.path()?)
        } else {
            None
        }
    }

    fn lower_nature(&mut self, decl: ast::NatureDecl) -> Option<ItemTreeId<Nature>> {
        let name = decl.name()?.as_name();

        let parent = decl.parent().and_then(|it| Self::lower_nature_path(&it));
        let attr_start = self.tree.data.nature_attrs.next_key();

        let mut access = None;
        let mut ddt_nature = None;
        let mut idt_nature = None;
        let mut units = None;
        let mut abstol = None;

        for (id, attr) in decl.nature_attrs().enumerate() {
            if let Some(name) = attr.name().map(|name| name.as_name()) {
                use kw::raw as kw;

                let ast_id = self.source_ast_id_map.ast_id(&attr);
                let mut evaluated: Option<ConstExprValue> = None;
                match &*name {
                    kw::access if access.is_none() => {
                        if let Some(name) = attr.val().and_then(|e| e.as_ident()) {
                            evaluated = Some(ConstExprValue::String(name.to_string()));
                            access = Some((name, id.into()));
                        }
                    }
                    kw::ddt_nature if ddt_nature.is_none() => {
                        if let Some(name) = attr.val().and_then(Self::lower_nature_expr) {
                            evaluated = Some(ConstExprValue::String(name.name.to_string()));
                            ddt_nature = Some((name, id.into()));
                        }
                    }
                    kw::idt_nature if idt_nature.is_none() => {
                        if let Some(name) = attr.val().and_then(Self::lower_nature_expr) {
                            evaluated = Some(ConstExprValue::String(name.name.to_string()));
                            idt_nature = Some((name, id.into()));
                        }
                    }

                    kw::units if units.is_none() => {
                        if let Some(ast::LiteralKind::String(lit)) =
                            attr.val().and_then(|e| e.as_literal())
                        {
                            let s = lit.unescaped_value();
                            evaluated = Some(ConstExprValue::String(s.clone()));
                            units = Some((s, id.into()));
                        }
                    }

                    kw::abstol if abstol.is_none() => {
                        let v1 =
                            attr.val().and_then(|v| v.as_constexprval()).and_then(|v| v.as_real());
                        if let Some(v) = v1 {
                            abstol = Some((OrderedFloat(v), id.into()));
                            evaluated = Some(ConstExprValue::Float(v.into()));
                        }
                    }
                    _ => {
                        // All other attributes - evaluate ast expression
                        evaluated = attr.val().and_then(|v| v.as_constexprval());
                    }
                };

                self.tree.data.nature_attrs.push(NatureAttr { name, ast_id, value: evaluated });
            }
        }

        let attr_end = self.tree.data.nature_attrs.next_key();
        let ast_id = self.source_ast_id_map.ast_id(&decl);

        let res = Nature {
            ast_id,
            name,
            parent,
            access,
            ddt_nature,
            idt_nature,
            abstol,
            units,
            attrs: IdxRange::new(attr_start..attr_end),
        };
        Some(self.tree.data.natures.push_and_get_key(res))
    }

    fn lower_module(&mut self, decl: ast::ModuleDecl) -> Option<ItemTreeId<Module>> {
        let name = decl.name()?.as_name();
        let ast_id = self.source_ast_id_map.ast_id(&decl);

        let mut nodes = TiVec::new();
        // Enhancement-404: name -> first node id, so per-bit lookups are O(1)
        let mut node_index: FxHashMap<Name, LocalNodeId> = FxHashMap::default();
        let mut items = Vec::new();
        let mut buses = Vec::new();
        let mut var_arrays = Vec::new();
        let mut param_arrays = Vec::new();
        let mut genvars = Vec::new();
        // Enhancement-90: for non-ANSI headers (`module m(in, y);` with the
        // width in a body declaration), we need each bus port's width *before*
        // creating its header placeholder so the bits stay contiguous in
        // header-port order. Pre-scan the body port declarations for widths.
        let port_widths = Self::prescan_body_port_widths(decl.module_items());
        if let Some(ports) = decl.module_ports() {
            self.lower_module_ports(
                ports,
                &mut nodes,
                &mut node_index,
                &mut items,
                &mut buses,
                &port_widths,
            );
        }

        let num_ports = nodes.len() as u32;
        self.lower_module_items(
            decl.module_items(),
            &mut nodes,
            &mut node_index,
            &mut items,
            &mut buses,
            &mut var_arrays,
            &mut param_arrays,
            &mut genvars,
        );

        // Enhancement-396: a bus port states its range twice -- once on the
        // direction declaration and once on the net declaration -- and the two
        // used to be reconciled by letting the DIRECTION win. `inout [0:2] b;`
        // beside `electrical [0:4] b;` therefore produced a three-bit port and
        // silently dropped the net's other two bits, so the module had fewer
        // terminals than its own source said. (The opposite order was already
        // caught, but only incidentally, as "no discipline for net 'b[3]'".)
        // Each declaration registers its OWN `BusDecl`, so compare every bus
        // carrying the port's name against the range the direction stated.
        for (name, range) in &port_widths {
            let Some((dir_msb, dir_lsb)) = fold_width_range(range) else { continue };
            for bus in buses.iter().filter(|b| b.base_name == *name) {
                if bus.msb != dir_msb || bus.lsb != dir_lsb {
                    self.tree.diagnostics.push(ItemTreeDiagnostic::PortRangeMismatch {
                        ast_id: bus.ast_id,
                        name: name.clone(),
                        dir_msb,
                        dir_lsb,
                        net_msb: bus.msb,
                        net_lsb: bus.lsb,
                    });
                    break;
                }
            }
        }

        self.check_branch_bus_refs(&items, &buses);
        self.check_alias_cycles(decl.module_items());

        let res =
            Module { name, nodes, items, ast_id, num_ports, buses, var_arrays, param_arrays, genvars };
        Some(self.tree.data.modules.push_and_get_key(res))
    }

    /// Enhancement-414: reports an `aliasparam` chain that closes on itself.
    ///
    /// `aliasparam pp = pp;` -- and any longer cycle -- crashed the compiler. The alias
    /// resolver is a salsa query whose cycle recovery yields "no target", and every
    /// consumer of `AliasParameter::resolve` unwrapped that, so the run ended in a crash
    /// dump with no diagnostic of any kind. Which alias points at which is a purely
    /// syntactic property of the module's own declarations, so the cycle is caught here,
    /// where the whole chain can be named.
    ///
    /// A target that is a system parameter, or a name that is not another alias, always
    /// terminates the chain and is left entirely alone.
    fn check_alias_cycles(&mut self, items: ast::AstChildren<ast::ModuleItem>) {
        let mut targets: FxHashMap<Name, (Name, ErasedAstId)> = FxHashMap::default();
        let mut order: Vec<Name> = Vec::new();
        for item in items {
            let ast::ModuleItem::AliasParam(decl) = item else { continue };
            let (Some(name), Some(ParamRef::Path(path))) = (decl.name(), decl.src()) else {
                continue;
            };
            let Some(target) = Path::resolve(path) else { continue };
            if target.is_root_path || target.segments.len() != 1 {
                continue;
            }
            let name = name.as_name();
            let ast_id: ErasedAstId = self.source_ast_id_map.ast_id(&decl).into();
            order.push(name.clone());
            targets.insert(name, (target.segments[0].clone(), ast_id));
        }

        let mut reported: Vec<Name> = Vec::new();
        for start in &order {
            if reported.contains(start) {
                continue;
            }
            // Walk the chain from `start`. A name seen twice on one walk closes a cycle;
            // a name with no alias target ends the walk with nothing to report.
            let mut seen: Vec<Name> = vec![start.clone()];
            let mut cur = start.clone();
            while let Some((target, ast_id)) = targets.get(&cur) {
                if let Some(pos) = seen.iter().position(|n| n == target) {
                    let mut chain: Vec<String> =
                        seen[pos..].iter().map(|n| n.to_string()).collect();
                    chain.push(target.to_string());
                    reported.extend_from_slice(&seen[pos..]);
                    self.tree.diagnostics.push(ItemTreeDiagnostic::AliasParamCycle {
                        ast_id: *ast_id,
                        name: start.clone(),
                        chain: chain.join(" -> ").into_boxed_str(),
                    });
                    break;
                }
                seen.push(target.clone());
                cur = target.clone();
            }
        }
    }

    fn lower_module_items(
        &mut self,
        items: ast::AstChildren<ast::ModuleItem>,
        nodes: &mut TiVec<LocalNodeId, Node>,
        node_index: &mut FxHashMap<Name, LocalNodeId>,
        dst: &mut Vec<ModuleItem>,
        buses: &mut Vec<BusDecl>,
        var_arrays: &mut Vec<BusDecl>,
        param_arrays: &mut Vec<BusDecl>,
        genvars: &mut Vec<Name>,
    ) {
        for item in items {
            match item {
                ast::ModuleItem::BodyPortDecl(decl) => {
                    if let Some(decl) = decl.port_decl() {
                        self.lower_port_decl(decl, nodes, node_index, dst, buses);
                    }
                }
                ast::ModuleItem::NetDecl(decl) => {
                    self.lower_net_decl(decl, nodes, node_index, dst, buses);
                }
                ast::ModuleItem::AnalogBehaviour(behaviour) => {
                    if let Some(stmt) = behaviour.stmt() {
                        self.lower_stmt(stmt, dst);
                    }
                }
                ast::ModuleItem::VarDecl(var) => {
                    self.lower_var(var, dst, Some(var_arrays));
                }
                ast::ModuleItem::ParamDecl(param) => {
                    self.lower_param(param, dst, Some(param_arrays));
                }
                ast::ModuleItem::Function(fun) => {
                    self.lower_fun(fun, dst);
                }
                ast::ModuleItem::BranchDecl(branch) => self.lower_branch(branch, dst),
                ast::ModuleItem::AliasParam(alias) => self.lower_alias_param(alias, dst),
                ast::ModuleItem::Instantiation(inst) => self.lower_instantiation(inst, dst),
                // `genvar`/`generate for` are always fully elaborated away
                // (text-level, before this stage runs) by
                // `hir::elaborate::elaborate_generates` -- see that module.
                // Reaching here means elaboration bailed out (e.g. a loop
                // bound that didn't constant-fold); drop the construct and
                // leave a diagnostic rather than silently miscompiling.
                ast::ModuleItem::GenvarDecl(ref decl) => {
                    // Enhancement-405: remember the names so an unresolved reference to one
                    // can say what it actually is.
                    genvars.extend(decl.names().map(|n| n.as_name()));
                }
                ast::ModuleItem::GenerateFor(gen) => {
                    let ast_id = self.source_ast_id_map.ast_id(&gen);
                    self.tree
                        .diagnostics
                        .push(ItemTreeDiagnostic::UnelaboratedGenerate { ast_id: ast_id.into() });
                }
                ast::ModuleItem::GenerateIf(gen) => {
                    let ast_id = self.source_ast_id_map.ast_id(&gen);
                    self.tree
                        .diagnostics
                        .push(ItemTreeDiagnostic::UnelaboratedGenerate { ast_id: ast_id.into() });
                }
                ast::ModuleItem::GenerateCase(gen) => {
                    let ast_id = self.source_ast_id_map.ast_id(&gen);
                    self.tree
                        .diagnostics
                        .push(ItemTreeDiagnostic::UnelaboratedGenerate { ast_id: ast_id.into() });
                }
            };
        }
    }

    /// Lowers a module-instantiation statement. Each comma-separated
    /// `InstanceUnit` becomes one or more `Instantiation` item-tree entries
    /// (one per array element for an arrayed instance, mirroring
    /// `expand_bus_names`'s per-bit expansion) all sharing the statement's
    /// `ast_id`, disambiguated by `unit_idx`/`array_index`. Port/parameter
    /// binding details are intentionally *not* captured here: they're read
    /// straight from the AST (via `ast_id`) by name resolution and by the
    /// elaboration pass, exactly like how `Net`/`Port` only cache their
    /// discipline here and leave the rest to the AST.
    fn lower_instantiation(&mut self, decl: ast::Instantiation, dst: &mut Vec<ModuleItem>) {
        let ast_id = self.source_ast_id_map.ast_id(&decl);
        let Some(module) = decl.module().map(|it| it.as_name()) else { return };

        for (unit_idx, unit) in decl.instance_units().enumerate() {
            let Some(name) = unit.name() else { continue };
            let base_name = name.as_name();

            let range = match unit.width() {
                Some(range) => range,
                None => {
                    let id = self.tree.data.instantiations.push_and_get_key(Instantiation {
                        name: base_name,
                        unit_idx,
                        array_index: None,
                        module: module.clone(),
                        ast_id,
                    });
                    dst.push(id.into());
                    continue;
                }
            };

            match fold_width_range(&range) {
                // Enhancement-148: cap instance-array expansion so `dev r[0:100000000]()`
                // is reported instead of materializing millions of instances.
                Some((msb, lsb)) if array_elem_count(&[(msb, lsb)]).is_none() => {
                    self.tree.diagnostics.push(ItemTreeDiagnostic::ArrayTooLarge {
                        ast_id: ast_id.into(),
                        size: (msb as i64 - lsb as i64).abs() + 1,
                    });
                    let id = self.tree.data.instantiations.push_and_get_key(Instantiation {
                        name: base_name.clone(),
                        unit_idx,
                        array_index: None,
                        module: module.clone(),
                        ast_id,
                    });
                    dst.push(id.into());
                }
                Some((msb, lsb)) => {
                    let (lo, hi) = if msb <= lsb { (msb, lsb) } else { (lsb, msb) };
                    for idx in lo..=hi {
                        let id = self.tree.data.instantiations.push_and_get_key(Instantiation {
                            name: super::bus_bit_name(&base_name, idx),
                            unit_idx,
                            array_index: Some(idx),
                            module: module.clone(),
                            ast_id,
                        });
                        dst.push(id.into());
                    }
                }
                None => {
                    self.tree.diagnostics.push(ItemTreeDiagnostic::NonConstantInstanceArrayWidth {
                        ast_id: ast_id.into(),
                    });
                    let id = self.tree.data.instantiations.push_and_get_key(Instantiation {
                        name: base_name,
                        unit_idx,
                        array_index: None,
                        module: module.clone(),
                        ast_id,
                    });
                    dst.push(id.into());
                }
            }
        }
    }

    fn lower_fun(&mut self, fun: ast::Function, dst: &mut Vec<ModuleItem>) {
        let mut items = Vec::new();
        let mut args: TiVec<LocalFunctionArgId, FunctionArg> = TiVec::new();
        // Array-variable declarations local to this function (Enhancement-18): array locals and
        // array-typed arguments expand into element vars here, exactly like `Module::var_arrays`.
        let mut var_arrays = Vec::new();
        // Enhancement-389: the (direction, type) of the last ANSI header entry that
        // stated one, for entries that omit both.
        let mut ansi_carry: Option<(bool, bool, Option<Type>)> = None;
        for item in fun.function_items() {
            match item {
                ast::FunctionItem::ParamDecl(decl) => self.lower_param(decl, &mut items, None),
                ast::FunctionItem::VarDecl(decl) => {
                    self.lower_var(decl, &mut items, Some(&mut var_arrays))
                }
                ast::FunctionItem::FunctionArg(arg) => {
                    let ast_id = self.source_ast_id_map.ast_id(&arg);
                    let direction = arg.direction();
                    // Enhancement-389: an ANSI header entry may restate neither the
                    // direction nor the type -- `f(input real x, y)` gives `y` both
                    // of `x`'s -- so carry the previous entry forward. Only an entry
                    // with NO direction inherits: the separated form always writes
                    // one (`func_arg` requires it), so its untyped `input x;` can
                    // never pick up a stray type from an earlier argument.
                    let (is_in, is_out, explicit_ty) = if direction.is_some() {
                        let cur = (
                            is_input(&direction),
                            is_output(&direction),
                            arg.ty().map(|ty| ty.as_type()),
                        );
                        ansi_carry = Some(cur.clone());
                        cur
                    } else {
                        match ansi_carry.clone() {
                            Some(prev) => prev,
                            // Enhancement-390: an ANSI entry that states no direction and
                            // has none to inherit -- `f(real x)`, the FIRST argument --
                            // is an INPUT. Verilog defaults a function argument to input,
                            // and the alternative was worse than wrong: the argument was
                            // neither input nor output, so nothing was copied in and the
                            // body read 0 while the call still accepted its value.
                            // `f(3.0)` returned 0 instead of 6, silently. The separated
                            // and combined forms reject a direction-less argument
                            // outright; only this path could produce one.
                            None => (true, false, arg.ty().map(|ty| ty.as_type())),
                        }
                    };
                    for (name_idx, name) in arg.names().enumerate() {
                        let name = name.as_name();
                        if let Some(arg) = args.iter_mut().find(|arg| arg.name == name) {
                            // TODO validation
                            arg.ast_ids.push(ast_id)
                        }
                        let arg = args.push_and_get_key(FunctionArg {
                            name,
                            name_idx,
                            is_input: is_in,
                            is_output: is_out,
                            declarations: Vec::new(),
                            explicit_ty: explicit_ty.clone(),
                            ast_ids: vec![ast_id],
                        });
                        items.push(arg.into());
                    }
                }
                ast::FunctionItem::Stmt(stmt) => self.lower_stmt(stmt, &mut items),
            }
        }

        items.retain(|decl| {
            if let FunctionItem::Variable(var) = decl {
                if let Some(arg) = args.iter_mut().find(|arg| arg.name == self.tree[*var].name) {
                    // TODO validation
                    arg.declarations.push(*var);
                    return false;
                }
            };
            true
        });

        if let Some(name) = fun.name() {
            let base_name = name.as_name();
            let ty = fun.ty().map_or(Type::Real, |ty| ty.as_type());

            // Array return `analog function real[0:n] f;` (Enhancement-23): expand the return into
            // element variables `f[i]` (a var_array named after the function, so its elements
            // resolve exactly like an array argument's), and record the return dimensions.
            let ret_widths: Vec<ast::Range> = fun.widths().collect();
            let ret_dims = if ret_widths.is_empty() {
                None
            } else {
                match fold_width_ranges(ret_widths.iter().cloned()) {
                    // Enhancement-148: cap array-return expansion.
                    Some(dims) if array_elem_count(&dims).is_none() => {
                        let fun_ast_id = self.source_ast_id_map.ast_id(&fun);
                        self.tree.diagnostics.push(ItemTreeDiagnostic::ArrayTooLarge {
                            ast_id: fun_ast_id.into(),
                            size: dims.iter().fold(1i64, |a, (m, l)| {
                                a.saturating_mul((*m as i64 - *l as i64).abs() + 1)
                            }),
                        });
                        None
                    }
                    Some(dims) => {
                        let fun_ast_id = self.source_ast_id_map.ast_id(&fun);
                        let arr = BusDecl {
                            base_name: base_name.clone(),
                            msb: dims[0].0,
                            lsb: dims[0].1,
                            dims: dims.clone(),
                            ast_id: fun_ast_id.into(),
                        };
                        // The return element variables have no `ast::Var` declaration node; they
                        // carry the function's id purely as a placeholder (they are always written
                        // by the body before being read, so their default is never lowered — and
                        // `var_body`/nameres fall back gracefully when the node isn't an `ast::Var`).
                        let var_ast_id = AstId::<ast::Var>::from_erased(fun_ast_id.erased());
                        for indices in arr.index_tuples() {
                            let var = Var {
                                name: arr.elem_name(&indices),
                                ast_id: var_ast_id,
                                ty: ty.clone(),
                                // no `ast::Var` node behind it, so there is no initializer
                                // literal to index into
                                array_index: None,
                            };
                            let id = self.tree.data.variables.push_and_get_key(var);
                            items.push(id.into());
                        }
                        var_arrays.push(arr);
                        Some(dims.into_boxed_slice())
                    }
                    None => {
                        let ast_id = self.source_ast_id_map.ast_id(&fun);
                        self.tree
                            .diagnostics
                            .push(ItemTreeDiagnostic::NonConstantBusWidth { ast_id: ast_id.into() });
                        None
                    }
                }
            };

            let fun = Function {
                name: base_name,
                ty,
                args,
                items,
                ast_id: self.source_ast_id_map.ast_id(&fun),
                var_arrays,
                ret_dims,
            };
            let fun = self.tree.data.functions.push_and_get_key(fun);
            dst.push(fun.into())
        }
    }

    /// Resolves a branch endpoint to a `Path`: a plain endpoint resolves its `ast::Path`
    /// normally (a bare reference to a bus base name is detected and diagnosed by the
    /// `finalize_branch_buses` post-pass once all of the module's buses are known); a
    /// bit-select endpoint (`bus[2]`) constant-folds the index and synthesizes the same
    /// `"bus[2]"` path the bus's expanded scalar `Node` was declared under (see
    /// `expand_bus_names`). A non-constant index is diagnosed and fails to resolve (the
    /// branch becomes `BranchKind::Missing`).
    fn resolve_branch_endpoint(
        &mut self,
        endpoint: ast::BranchEndpoint,
        ast_id: ErasedAstId,
    ) -> Option<Path> {
        match endpoint {
            ast::BranchEndpoint::Plain(path) => Path::resolve(path),
            ast::BranchEndpoint::BitSelect(base, index) => {
                let base_name = Path::resolve(base)?.as_ident()?;
                let idx = match index.as_constexprval() {
                    Some(ConstExprValue::Int(i)) => i,
                    _ => {
                        self.tree
                            .diagnostics
                            .push(ItemTreeDiagnostic::NonConstantBranchBitSelect { ast_id });
                        return None;
                    }
                };
                Some(Path::new_ident(super::bus_bit_name(&base_name, idx)))
            }
        }
    }

    fn lower_branch(&mut self, decl: ast::BranchDecl, dst: &mut Vec<ModuleItem>) {
        let ast_id = self.source_ast_id_map.ast_id(&decl);
        let kind = decl
            .branch_kind()
            .and_then(|kind| {
                let res = match kind {
                    ast::BranchKind::PortFlow(flow) => {
                        BranchKind::PortFlow(Path::resolve(flow.port()?)?)
                    }
                    ast::BranchKind::NodeGnd(node) => {
                        BranchKind::NodeGnd(self.resolve_branch_endpoint(node, ast_id.into())?)
                    }
                    ast::BranchKind::Nodes(hi, lo) => BranchKind::Nodes(
                        self.resolve_branch_endpoint(hi, ast_id.into())?,
                        self.resolve_branch_endpoint(lo, ast_id.into())?,
                    ),
                };
                Some(res)
            })
            .unwrap_or(BranchKind::Missing);
        for (name_idx, name) in decl.names().enumerate() {
            let branch = Branch { name: name.as_name(), kind: kind.clone(), ast_id, name_idx };
            let id = self.tree.data.branches.push_and_get_key(branch);
            dst.push(id.into());
        }
    }

    /// Post-pass run once a module's `buses` registry is fully known: diagnoses branch
    /// endpoints that referenced a bus by its bare base name with no bit-select (which
    /// `resolve_branch_endpoint` would otherwise have resolved as an ordinary, and
    /// nonexistent, node path, only to fail name resolution later with a confusing
    /// "not found" error).
    fn check_branch_bus_refs(&mut self, dst: &[ModuleItem], buses: &[BusDecl]) {
        if buses.is_empty() {
            return;
        }
        for item in dst {
            if let ModuleItem::Branch(id) = item {
                let branch = &self.tree.data.branches[*id];
                let ast_id = branch.ast_id.into();
                let endpoints: Vec<&Path> = match &branch.kind {
                    BranchKind::PortFlow(p) | BranchKind::NodeGnd(p) => vec![p],
                    BranchKind::Nodes(p1, p2) => vec![p1, p2],
                    BranchKind::Missing => vec![],
                };
                for path in endpoints {
                    let Some(ident) = path.as_ident() else { continue };
                    if let Some(bus) = buses.iter().find(|b| b.base_name == ident) {
                        // bare reference to a bus base name with no bit-select
                        self.tree.diagnostics.push(ItemTreeDiagnostic::BareBusReferenceInBranch {
                            ast_id,
                            bus_name: bus.base_name.clone(),
                        });
                        continue;
                    }
                    // a synthesized "base[idx]" bit-select path: range-check it against
                    // the bus's declared width, if its base matches a known bus.
                    if let Some((base, idx)) = parse_synthesized_bit_name(&ident) {
                        if let Some(bus) = buses.iter().find(|b| b.base_name == base) {
                            if !bus.contains_bit(idx) {
                                self.tree.diagnostics.push(
                                    ItemTreeDiagnostic::BranchBitSelectOutOfRange {
                                        ast_id,
                                        bus_name: bus.base_name.clone(),
                                        index: idx,
                                        msb: bus.msb,
                                        lsb: bus.lsb,
                                    },
                                );
                            }
                        }
                    }
                }
            }
        }
    }

    /// Pre-scans a module's body port declarations, collecting the declared
    /// width (if any) for each port name. Used by `lower_module_ports` to
    /// expand a non-ANSI header bus port into its bits in header-port order
    /// (Enhancement-90). Only port (direction) declarations carry authoritative
    /// terminal widths; the first width seen for a name wins.
    fn prescan_body_port_widths(
        items: ast::AstChildren<ast::ModuleItem>,
    ) -> Vec<(Name, ast::Range)> {
        let mut res: Vec<(Name, ast::Range)> = Vec::new();
        for item in items {
            let ast::ModuleItem::BodyPortDecl(decl) = item else { continue };
            let Some(decl) = decl.port_decl() else { continue };
            let Some(width) = decl.width() else { continue };
            for name in decl.names() {
                let name = name.as_name();
                if !res.iter().any(|(n, _)| *n == name) {
                    res.push((name, width.clone()));
                }
            }
        }
        res
    }

    fn lower_module_ports(
        &mut self,
        ports: ast::ModulePorts,
        nodes: &mut TiVec<LocalNodeId, Node>,
        node_index: &mut FxHashMap<Name, LocalNodeId>,
        dst: &mut Vec<ModuleItem>,
        buses: &mut Vec<BusDecl>,
        port_widths: &[(Name, ast::Range)],
    ) {
        for port in ports.ports() {
            let ast_id = self.source_ast_id_map.ast_id(&port);
            match port.kind() {
                ast::ModulePortKind::Name(name) => {
                    let name = name.as_name();
                    if !node_index.contains_key(&name) {
                        // Enhancement-90: a non-ANSI header port whose width is
                        // declared in the body. Pre-expand the bus here, in
                        // header order, so its bits stay contiguous. Without
                        // this the header creates a single bare placeholder and
                        // the body's expansion appends the remaining bits at the
                        // end of the node list -- scrambling terminal order for
                        // any bus port that is not the last port, which then
                        // mis-wires the netlist terminals. The `BusDecl` itself
                        // is still registered by the body declaration below.
                        let width = port_widths
                            .iter()
                            .find(|(n, _)| *n == name)
                            .and_then(|(_, w)| fold_width_range(w));
                        match width {
                            // Enhancement-148: cap bus-port expansion.
                            Some((msb, lsb))
                                if array_elem_count(&[(msb, lsb)]).is_none() =>
                            {
                                self.tree.diagnostics.push(ItemTreeDiagnostic::ArrayTooLarge {
                                    ast_id: ast_id.into(),
                                    size: (msb as i64 - lsb as i64).abs() + 1,
                                });
                                let node = Self::push_node(nodes, node_index, Node {
                                    name,
                                    is_port: true,
                                    ast_id: ast_id.into(),
                                    decls: Vec::new(),
                                });
                                dst.push(node.into())
                            }
                            Some((msb, lsb)) => {
                                let (lo, hi) =
                                    if msb >= lsb { (lsb, msb) } else { (msb, lsb) };
                                for bit in lo..=hi {
                                    let node = Self::push_node(nodes, node_index, Node {
                                        name: super::bus_bit_name(&name, bit),
                                        is_port: true,
                                        ast_id: ast_id.into(),
                                        decls: Vec::new(),
                                    });
                                    dst.push(node.into())
                                }
                            }
                            None => {
                                let node = Self::push_node(nodes, node_index, Node {
                                    name,
                                    is_port: true,
                                    ast_id: ast_id.into(),
                                    decls: Vec::new(),
                                });
                                dst.push(node.into())
                            }
                        }
                    }
                }
                ast::ModulePortKind::PortDecl(decl) => {
                    self.lower_port_decl(decl, nodes, node_index, dst, buses);
                }
            }
        }
    }

    /// Expands a (possibly vectored) declaration's name list into the list of
    /// scalar names to actually declare, registering a `BusDecl` (and
    /// diagnosing non-constant widths) as needed. Each entry is
    /// `(name, name_idx)` where `name_idx` mirrors the original `enumerate()`
    /// index of the *declared* (un-expanded) name, matching existing
    /// multi-declaration semantics.
    /// Like the result of expansion, but additionally marks the *first* synthesized bit of
    /// each bus with the original (un-expanded) base name. This lets callers merge a bus's
    /// first bit into a pre-existing module-head port placeholder declared under the bare
    /// base name (e.g. `module m(in, out); output [3:0] out;` — the header's bare `out`
    /// placeholder has to become `out[0]`, not be left dangling), without disturbing the
    /// stable `LocalNodeId` indices any other declaration may already reference.
    fn expand_bus_names(
        &mut self,
        width: Option<ast::Range>,
        names: ast::AstChildren<ast::Name>,
        ast_id: ErasedAstId,
        buses: &mut Vec<BusDecl>,
    ) -> Vec<(Name, usize, Option<Name>)> {
        let Some(width) = width else {
            return names.enumerate().map(|(idx, name)| (name.as_name(), idx, None)).collect();
        };

        let mut res = Vec::new();
        for (name_idx, name) in names.enumerate() {
            let base_name = name.as_name();
            match fold_width_range(&width) {
                // Enhancement-148: cap net/port bus expansion.
                Some((msb, lsb)) if array_elem_count(&[(msb, lsb)]).is_none() => {
                    self.tree.diagnostics.push(ItemTreeDiagnostic::ArrayTooLarge {
                        ast_id,
                        size: (msb as i64 - lsb as i64).abs() + 1,
                    });
                    res.push((base_name, name_idx, None));
                }
                Some((msb, lsb)) => {
                    buses.push(BusDecl {
                        base_name: base_name.clone(),
                        msb,
                        lsb,
                        dims: vec![(msb, lsb)],
                        ast_id,
                    });
                    let (lo, hi) = if msb >= lsb { (lsb, msb) } else { (msb, lsb) };
                    // declare from lsb to msb (ascending), matching natural bit order;
                    // direction of the original [msb:lsb] only affects range checks
                    for bit in lo..=hi {
                        let merge_base = if bit == lo { Some(base_name.clone()) } else { None };
                        res.push((super::bus_bit_name(&base_name, bit), name_idx, merge_base));
                    }
                }
                None => {
                    self.tree
                        .diagnostics
                        .push(ItemTreeDiagnostic::NonConstantBusWidth { ast_id });
                    // fall back to a scalar declaration so compilation proceeds
                    res.push((base_name, name_idx, None));
                }
            }
        }
        res
    }

    /// Finds the node a declared name should attach to: an exact match, or (for the first bit
    /// of a bus) a still-unresolved module-head port placeholder declared under the bus's bare
    /// base name.
    ///
    /// Enhancement-404: `index` maps a node name to the FIRST node carrying it, which is what
    /// the linear `find` this replaces would have returned. Both lookups here used to be
    /// `nodes.iter()` scans run once per declared bit, so a `[N:0]` bus cost O(N^2) -- 32 s for
    /// `[65535:0]`. The scans remain as a fallback for the one case the index cannot answer:
    /// a duplicate name whose first node is already claimed, where the old code would keep
    /// looking for a later unclaimed one. That cannot arise from well-formed input, so the
    /// fallback never runs in practice, but it keeps the semantics identical either way.
    fn find_node_for_decl<'n>(
        nodes: &'n mut TiVec<LocalNodeId, Node>,
        index: &mut FxHashMap<Name, LocalNodeId>,
        name: &Name,
        merge_base: &Option<Name>,
    ) -> Option<&'n mut Node> {
        if let Some(&id) = index.get(name) {
            debug_assert_eq!(&nodes[id].name, name);
            return Some(&mut nodes[id]);
        }
        let base = merge_base.as_ref()?;
        let id = match index.get(base) {
            // the placeholder is still unclaimed -- the common case, and the only one a
            // well-formed header can produce
            Some(&id) if nodes[id].decls.is_empty() => id,
            // a first node under this name exists but is already claimed; fall back to the
            // original scan so a duplicate-name header behaves exactly as it used to
            Some(_) => nodes
                .iter_enumerated()
                .find(|(_, node)| &node.name == base && node.decls.is_empty())
                .map(|(id, _)| id)?,
            None => return None,
        };
        // the placeholder is renamed, so the index must follow it
        index.remove(base);
        index.entry(name.clone()).or_insert(id);
        nodes[id].name = name.clone();
        Some(&mut nodes[id])
    }

    /// Enhancement-404: push a node and keep the name index in step. `or_insert` preserves
    /// "first node wins", matching the `find` semantics the index stands in for.
    fn push_node(
        nodes: &mut TiVec<LocalNodeId, Node>,
        index: &mut FxHashMap<Name, LocalNodeId>,
        node: Node,
    ) -> LocalNodeId {
        let name = node.name.clone();
        let id = nodes.push_and_get_key(node);
        index.entry(name).or_insert(id);
        id
    }

    fn lower_port_decl(
        &mut self,
        decl: ast::PortDecl,
        nodes: &mut TiVec<LocalNodeId, Node>,
        node_index: &mut FxHashMap<Name, LocalNodeId>,
        dst: &mut Vec<ModuleItem>,
        buses: &mut Vec<BusDecl>,
    ) {
        let discipline = decl.discipline().map(|it| it.as_name());
        let direction = decl.direction();

        let is_gnd = decl.net_type_token().map_or(false, |it| it.text() == kw::raw::ground);
        let ast_id = self.source_ast_id_map.ast_id(&decl);
        let names = self.expand_bus_names(decl.width(), decl.names(), ast_id.into(), buses);
        for (name, name_idx, merge_base) in names {
            let id = self.tree.data.ports.push_and_get_key(Port {
                name: name.clone(),
                discipline: discipline.clone(),
                is_input: is_input(&direction),
                is_output: is_output(&direction),
                ast_id,
                name_idx,
                is_gnd,
            });

            match Self::find_node_for_decl(nodes, node_index, &name, &merge_base) {
                Some(node) => node.decls.push(id.into()),
                None => {
                    let node = Self::push_node(nodes, node_index, Node {
                        name,
                        is_port: true,
                        ast_id: ast_id.into(),
                        decls: vec![id.into()],
                    });
                    dst.push(node.into())
                }
            }
        }
    }

    fn lower_net_decl(
        &mut self,
        decl: ast::NetDecl,
        nodes: &mut TiVec<LocalNodeId, Node>,
        node_index: &mut FxHashMap<Name, LocalNodeId>,
        dst: &mut Vec<ModuleItem>,
        buses: &mut Vec<BusDecl>,
    ) {
        let discipline = decl.discipline().map(|it| it.as_name());
        let ast_id = self.source_ast_id_map.ast_id(&decl);

        let is_gnd = decl.net_type_token().map_or(false, |it| it.text() == kw::raw::ground);

        // Nodeset initializers (`electrical a = 5.0;` / `electrical [0:4] b =
        // '{...};`, LRM 3.6.3.2, Enhancement-45): fold each declarator's
        // constant initializer; for a bus, flatten the `'{...}` literal into
        // per-bit leaves in ascending bit order (matching the expansion order
        // below). A non-constant initializer is diagnosed and dropped.
        let declarators = decl.declarators();
        let fold_leaf = |this: &mut Self, e: &ast::Expr| -> Option<f64> {
            match e.as_constexprval() {
                Some(ConstExprValue::Int(i)) => Some(f64::from(i)),
                Some(ConstExprValue::Float(f)) => Some(f.into_inner()),
                _ => {
                    this.tree.diagnostics.push(ItemTreeDiagnostic::NonConstantNodeset {
                        ast_id: ast_id.into(),
                    });
                    None
                }
            }
        };
        let mut init_leaves: Vec<Option<Vec<Option<f64>>>> = Vec::new();
        for (_, init) in &declarators {
            let leaves = init.as_ref().map(|init| match init {
                ast::Expr::ArrayExpr(arr) => {
                    arr.exprs().map(|e| fold_leaf(self, &e)).collect()
                }
                other => vec![fold_leaf(self, other)],
            });
            init_leaves.push(leaves);
        }
        let mut bit_pos: Vec<usize> = vec![0; init_leaves.len()];

        let names = self.expand_bus_names(decl.width(), decl.names(), ast_id.into(), buses);
        for (name, name_idx, merge_base) in names {
            let nodeset = init_leaves.get(name_idx).and_then(|leaves| {
                let leaves = leaves.as_ref()?;
                let pos = bit_pos[name_idx];
                bit_pos[name_idx] += 1;
                leaves.get(pos).copied().flatten()
            });
            let id = self.tree.data.nets.push_and_get_key(Net {
                name: name.clone(),
                discipline: discipline.clone(),
                ast_id,
                is_gnd,
                name_idx,
                nodeset: nodeset.map(OrderedFloat),
            });

            match Self::find_node_for_decl(nodes, node_index, &name, &merge_base) {
                Some(node) => node.decls.push(id.into()),
                None => {
                    let node = Self::push_node(nodes, node_index, Node {
                        name,
                        is_port: false,
                        ast_id: ast_id.into(),
                        decls: vec![id.into()],
                    });
                    dst.push(node.into());
                }
            }
        }
    }

    fn lower_stmt<
        T: From<ItemTreeId<Param>> + From<ItemTreeId<Var>> + From<AstId<ast::BlockStmt>>,
    >(
        &mut self,
        stmt: ast::Stmt,
        parent_scope: &mut Vec<T>,
    ) {
        let mut block_stack = Vec::new();
        let mut block_scope_stack = Vec::new();
        let mut blocks = mem::take(&mut self.tree.blocks);

        for event in stmt.syntax().preorder() {
            match event {
                WalkEvent::Enter(node) => {
                    match_ast! {
                        match node {
                            ast::BlockStmt(block) => {
                                let ast_id = self.source_ast_id_map.ast_id(&block);
                                let name = block.block_scope().and_then(|it| Some(it.name()?.as_name()));
                                let block_info = Block { name: name.clone(), scope_items: Vec::new()};
                                // Enhancement-230: only treat a block as a named item-tree
                                // scope when it actually has a name. A `begin :` with the
                                // scope colon but a missing/invalid name identifier has
                                // `block_scope().is_some()` yet `name == None`; linking it
                                // in here made name resolution later `.expect()` the absent
                                // name and panic ("Item tree must only contain named
                                // blocks"). Gate on `name.is_some()` (the parser already
                                // reports the missing block name separately).
                                if name.is_some() {
                                    match block_scope_stack.last() {
                                        Some(block) => {
                                            let block = blocks.get_mut(block).unwrap();
                                             block.scope_items.push(ast_id.into());
                                        }
                                        None =>  parent_scope.push(ast_id.into()),
                                    };

                                    block_scope_stack.push(ast_id);
                                }

                                blocks.insert(ast_id, block_info);
                                block_stack.push(ast_id);
                            },
                            ast::VarDecl(var) => {
                              match block_stack.last() {
                                    Some(block) => {
                                        let block = blocks.get_mut(block).unwrap();
                                        self.lower_var(var, &mut block.scope_items, None)
                                    }
                                    None => self.lower_var(var, parent_scope, None),
                                }
                            },
                            ast::ParamDecl(param) => {
                              match block_stack.last() {
                                    Some(block) => {
                                        let block = blocks.get_mut(block).unwrap();
                                        self.lower_param(param, &mut block.scope_items, None)
                                    }
                                 None => self.lower_param(param, parent_scope, None),
                                }
                            },
                            _ => ()
                        }
                    }
                }
                WalkEvent::Leave(node) => {
                    if let Some(block) = ast::BlockStmt::cast(node) {
                        block_stack.pop();
                        // Enhancement-230: mirror the `name.is_some()` gate used on
                        // Enter, so the scope stack stays balanced for a nameless
                        // `begin :` (which is pushed on neither side).
                        let named = block.block_scope().and_then(|it| it.name()).is_some();
                        if named {
                            block_scope_stack.pop();
                        }
                    }
                }
            }
        }

        self.tree.blocks = blocks;
    }

    /// Lowers a `VarDecl`. `var_arrays` is `Some` only when called from module body scope
    /// (the only scope where array-variable bit-select resolution is supported, mirroring
    /// `buses`/`find_bus`'s `DefWithBodyId::ModuleId`-only lookup, see `Enhancement-4.md` §3);
    /// `None` from `analog function` bodies and nested `begin..end` blocks, where a width
    /// clause is diagnosed and dropped (falls back to an ordinary scalar declaration).
    fn lower_var<T: From<ItemTreeId<Var>>>(
        &mut self,
        decl: ast::VarDecl,
        dst: &mut Vec<T>,
        mut var_arrays: Option<&mut Vec<BusDecl>>,
    ) {
        let ty = decl.ty().as_type();
        // Array dimensions may be written *before* the name and shared by the whole declaration
        // (`real [0:n] x, y;`, Enhancement-15) or *after* each name (`real x[0:n], m[0:1][0:2];`,
        // the standard Verilog-AMS form, Enhancement-18). Each `[msb:lsb]` clause is one dimension.
        let decl_widths: Vec<ast::Range> = decl.widths().collect();

        for var in decl.vars() {
            let Some(name) = var.name() else { continue };
            let base_name = name.as_name();
            let ast_id = self.source_ast_id_map.ast_id(&var);

            // per-variable dimensions take precedence; otherwise the shared declaration-level ones
            let var_widths: Vec<ast::Range> = var.widths().collect();
            let widths = if var_widths.is_empty() { &decl_widths } else { &var_widths };

            let mut push_scalar = |this: &mut Self| {
                let var =
                    Var { name: base_name.clone(), ast_id, ty: ty.clone(), array_index: None };
                let id = this.tree.data.variables.push_and_get_key(var);
                dst.push(id.into());
            };

            if widths.is_empty() {
                // ordinary (non-array) variable declaration
                push_scalar(self);
                continue;
            }

            let Some(var_arrays) = var_arrays.as_deref_mut() else {
                // a width clause outside module body scope: diagnose and degrade to scalar
                self.tree
                    .diagnostics
                    .push(ItemTreeDiagnostic::ArrayVarUnsupportedScope { ast_id: ast_id.into() });
                push_scalar(self);
                continue;
            };

            match fold_width_ranges(widths.iter().cloned()) {
                Some(dims) => {
                    // Enhancement-148: refuse to materialize an absurdly large array.
                    if array_elem_count(&dims).is_none() {
                        let size = dims.iter().fold(1i64, |a, (m, l)| {
                            a.saturating_mul((*m as i64 - *l as i64).abs() + 1)
                        });
                        self.tree
                            .diagnostics
                            .push(ItemTreeDiagnostic::ArrayTooLarge { ast_id: ast_id.into(), size });
                        push_scalar(self);
                        continue;
                    }
                    let arr = BusDecl {
                        base_name: base_name.clone(),
                        msb: dims[0].0,
                        lsb: dims[0].1,
                        dims,
                        ast_id: ast_id.into(),
                    };
                    // an initializer must supply exactly one leaf per element -- a mismatch
                    // used to crash the compiler once the missing leaves reached lowering
                    if let Some(default) = var.default() {
                        let expected = arr.index_tuples().len() as u32;
                        let found = count_literal_leaves(&default);
                        if found != expected {
                            self.tree.diagnostics.push(
                                ItemTreeDiagnostic::ArrayInitializerLengthMismatch {
                                    ast_id: ast_id.into(),
                                    name: base_name.clone(),
                                    expected,
                                    found,
                                },
                            );
                        }
                    }
                    // one scalar element per index tuple, named `x[i]` / `x[i][j]` / ...; each
                    // carries its flat position so a shared `'{...}` initializer can be split
                    // into per-element leaves, exactly like array parameters (Enhancement-43)
                    for (pos, indices) in arr.index_tuples().iter().enumerate() {
                        let var = Var {
                            name: arr.elem_name(indices),
                            ast_id,
                            ty: ty.clone(),
                            array_index: Some(pos as u32),
                        };
                        let id = self.tree.data.variables.push_and_get_key(var);
                        dst.push(id.into());
                    }
                    var_arrays.push(arr);
                }
                None => {
                    self.tree
                        .diagnostics
                        .push(ItemTreeDiagnostic::NonConstantBusWidth { ast_id: ast_id.into() });
                    // fall back to a scalar declaration so compilation proceeds
                    push_scalar(self);
                }
            }
        }
    }

    /// Lowers a `ParamDecl`. `param_arrays` is `Some` only at module body scope (like `var_arrays`
    /// for `lower_var`): an array-valued parameter (`parameter real [msb:lsb] c = '{...};`) is
    /// registered there and expanded into one scalar parameter per element (`c[lo]`..`c[hi]`), each
    /// carrying its `array_index` (declaration-order position) so it can pick its per-element
    /// default from the `'{...}` literal. A width clause outside module scope, or a non-constant
    /// width, degrades to an ordinary scalar parameter.
    fn lower_param<T: From<ItemTreeId<Param>>>(
        &mut self,
        decl: ast::ParamDecl,
        dst: &mut Vec<T>,
        param_arrays: Option<&mut Vec<BusDecl>>,
    ) {
        let ty = decl.ty().map(|ty| ty.as_type());
        let is_local = decl.localparam_token().is_some();
        // Type-then-range dims (`parameter real [0:2] c`, Enhancement-14/15) are
        // shared by every name in the declaration. Enhancement-102 also allows
        // the name-then-range form (`parameter real c[0:2]`), where each name
        // carries its own dims -- so the width set is resolved per name below.
        let decl_widths: Vec<ast::Range> = decl.widths().collect();
        let has_param_arrays = param_arrays.is_some();

        for param in decl.paras() {
            let Some(name) = param.name() else { continue };
            let base_name = name.as_name();
            let ast_id = self.source_ast_id_map.ast_id(&param);
            self.check_param_range_satisfiable(&base_name, &param, ast_id.into());
            // Enhancement-102: prefer the shared decl-level dims; otherwise fall
            // back to this name's own name-then-range dims (empty for a scalar).
            let widths: Vec<ast::Range> =
                if decl_widths.is_empty() { param.widths().collect() } else { decl_widths.clone() };
            let dims =
                if widths.is_empty() { None } else { fold_width_ranges(widths.iter().cloned()) };

            let push_scalar = |this: &mut Self, dst: &mut Vec<T>| {
                let param = Param {
                    name: base_name.clone(),
                    is_local,
                    ty: ty.clone(),
                    ast_id,
                    array_index: None,
                    override_expr: None,
                };
                let id = this.tree.data.parameters.push_and_get_key(param);
                dst.push(id.into());
            };

            match (widths.is_empty(), has_param_arrays, &dims) {
                // ordinary scalar parameter
                (true, _, _) => push_scalar(self, dst),
                // array-valued parameter at module scope with constant widths
                (false, true, Some(dims)) => {
                    // Enhancement-148: refuse to materialize an absurdly large array param.
                    if array_elem_count(dims).is_none() {
                        let size = dims.iter().fold(1i64, |a, (m, l)| {
                            a.saturating_mul((*m as i64 - *l as i64).abs() + 1)
                        });
                        self.tree
                            .diagnostics
                            .push(ItemTreeDiagnostic::ArrayTooLarge { ast_id: ast_id.into(), size });
                        push_scalar(self, dst);
                        continue;
                    }
                    let arr = BusDecl {
                        base_name: base_name.clone(),
                        msb: dims[0].0,
                        lsb: dims[0].1,
                        dims: dims.clone(),
                        ast_id: ast_id.into(),
                    };
                    // an initializer must supply exactly one leaf per element -- a mismatch
                    // used to crash the compiler once the missing leaves reached lowering
                    // (Enhancement-43; params and vars share the split-literal machinery)
                    if let Some(default) = param.default() {
                        let expected = arr.index_tuples().len() as u32;
                        let found = count_literal_leaves(&default);
                        if found != expected {
                            self.tree.diagnostics.push(
                                ItemTreeDiagnostic::ArrayInitializerLengthMismatch {
                                    ast_id: ast_id.into(),
                                    name: base_name.clone(),
                                    expected,
                                    found,
                                },
                            );
                        }
                    }
                    // one scalar element parameter per index tuple; `array_index` is its flat
                    // declaration-order position, used to pick its default from the (nested) literal
                    for (pos, indices) in arr.index_tuples().iter().enumerate() {
                        let param = Param {
                            name: arr.elem_name(indices),
                            is_local,
                            ty: ty.clone(),
                            ast_id,
                            array_index: Some(pos as u32),
                            override_expr: None,
                        };
                        let id = self.tree.data.parameters.push_and_get_key(param);
                        dst.push(id.into());
                    }
                }
                // width clause but non-constant range or wrong scope: diagnose, degrade to scalar
                (false, _, _) => {
                    self.tree
                        .diagnostics
                        .push(ItemTreeDiagnostic::NonConstantBusWidth { ast_id: ast_id.into() });
                    push_scalar(self, dst);
                }
            }
        }

        // Register the parameter array so `c[i]`/`c[i][j]` bit-selects resolve to
        // the elements. Enhancement-102: the dims are resolved per name (shared
        // decl-level type-then-range, or this name's own name-then-range dims).
        if let Some(param_arrays) = param_arrays {
            for param in decl.paras() {
                let Some(name) = param.name() else { continue };
                let widths: Vec<ast::Range> = if decl_widths.is_empty() {
                    param.widths().collect()
                } else {
                    decl_widths.clone()
                };
                if widths.is_empty() {
                    continue;
                }
                if let Some(dims) = fold_width_ranges(widths.iter().cloned()) {
                    param_arrays.push(BusDecl {
                        base_name: name.as_name(),
                        msb: dims[0].0,
                        lsb: dims[0].1,
                        dims: dims.clone(),
                        ast_id: self.source_ast_id_map.ast_id(&param).into(),
                    });
                }
            }
        }
    }

    fn lower_alias_param<T: From<ItemTreeId<AliasParam>>>(
        &mut self,
        decl: ast::AliasParam,
        dst: &mut Vec<T>,
    ) {
        let name = decl.name();
        let src = decl.src();

        if let (Some(name), Some(src)) = (name, src) {
            let src = match src {
                ParamRef::Path(path) => Path::resolve(path),
                ParamRef::SysFun(fun) => Some(Path::new_ident(fun.as_name())),
            };
            let param = AliasParam {
                name: name.as_name(),
                src,
                ast_id: self.source_ast_id_map.ast_id(&decl),
            };
            let param = self.tree.data.alias_parameters.push_and_get_key(param);
            dst.push(param.into())
        }
    }
}

/// Enhancement-421: just enough interval arithmetic to answer "do these
/// `exclude` clauses cover the whole `from` range?".
///
/// Endpoints carry their inclusivity, because that is where every interesting
/// case lives: `from [0:10] exclude (0:10)` leaves exactly the two endpoints
/// settable and must NOT be reported, while `exclude [0:10]` leaves nothing and
/// must be.
#[derive(Clone, Copy)]
struct Bound {
    v: f64,
    closed: bool,
}

#[derive(Clone, Copy)]
struct Ival {
    lo: Bound,
    hi: Bound,
}

/// A place on the number line that a sweep can stand: either a value itself, or
/// the values immediately above it (which is what "just past an open endpoint"
/// means and what no single float can represent).
#[derive(Clone, Copy, PartialEq)]
struct Pos {
    v: f64,
    /// true  -> the point `v`
    /// false -> the values immediately above `v`
    at_value: bool,
}

impl Pos {
    /// `at_value` sorts before `just above` at the same value.
    fn le(self, other: Pos) -> bool {
        self.v < other.v || (self.v == other.v && (self.at_value || !other.at_value))
    }
}

impl Ival {
    fn start(&self) -> Pos {
        Pos { v: self.lo.v, at_value: self.lo.closed }
    }

    /// The first position NOT covered by this interval.
    fn past_end(&self) -> Pos {
        Pos { v: self.hi.v, at_value: !self.hi.closed }
    }

    fn contains(&self, p: Pos) -> bool {
        if p.at_value {
            (self.lo.v < p.v || (self.lo.v == p.v && self.lo.closed))
                && (self.hi.v > p.v || (self.hi.v == p.v && self.hi.closed))
        } else {
            // the values immediately above `p.v`
            self.lo.v <= p.v && self.hi.v > p.v
        }
    }

    fn ends_at_or_before(&self, p: Pos) -> bool {
        self.past_end().le(p)
    }

    /// Is every value of `self` excluded by some interval in `excl`?
    ///
    /// A left-to-right sweep: hold the lowest position not yet known to be
    /// covered, and walk the exclusions in ascending order. An exclusion that
    /// ends before that position is spent; one that starts after it proves a gap
    /// and answers no; one that contains it pushes it past that exclusion's end.
    fn covered_by(&self, excl: &mut [Ival]) -> bool {
        excl.sort_by(|a, b| {
            a.lo.v
                .partial_cmp(&b.lo.v)
                .unwrap_or(core::cmp::Ordering::Equal)
                // at equal value a CLOSED start comes first: it begins earlier
                .then(b.lo.closed.cmp(&a.lo.closed))
        });
        let mut cur = self.start();
        let end = self.past_end();
        if end.le(cur) {
            // an empty `from` range -- already reported by ParamRangeEmpty
            return false;
        }
        for e in excl.iter() {
            if cur.le(end) && !end.le(cur) {
                // still inside the range
            } else {
                break;
            }
            if e.contains(cur) {
                let nxt = e.past_end();
                if cur.le(nxt) {
                    cur = nxt;
                }
                if end.le(cur) {
                    return true;
                }
            } else if e.ends_at_or_before(cur) {
                continue; // spent
            } else {
                return false; // a gap the exclusions do not reach
            }
        }
        end.le(cur)
    }
}
