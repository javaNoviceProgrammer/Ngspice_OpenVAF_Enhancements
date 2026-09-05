use std::sync::Arc;

use basedb::lints::{Lint, LintSrc};
use hir_def::db::HirDefDB;
pub use hir_def::expr::Event;
use hir_def::{DefWithBodyId, ModuleId};
pub use hir_def::{/*expr::CaseCond,*/ BuiltIn, Case, CaseKind, ExprId, Literal, ParamSysFun, StmtId, Type,};
use hir_ty::db::HirTyDB;
use hir_ty::inference;
use hir_ty::types::{AttrId, Signature, Ty};
pub use syntax::ast::{BinaryOp, UnaryOp};
pub use syntax::name::Name;
use syntax::TextRange;

use crate::{
    Branch, BranchKind, BranchWrite, CompilationDB, DisciplineAttribute, Function, FunctionArg,
    NatureAttribute, Node, Parameter, Variable,
};
use hir_ty::builtin::{NATURE_ACCESS_BRANCH, NATURE_ACCESS_NODES, NATURE_ACCESS_NODE_GND};

#[derive(Debug, Clone)]
pub struct Body {
    body: Arc<hir_def::body::Body>,
    infere: Arc<inference::InferenceResult>,
}
impl Body {
    pub(crate) fn new(id: DefWithBodyId, db: &CompilationDB) -> Body {
        Body { body: db.body(id), infere: db.inference_result(id) }
    }

    pub fn borrow(&self) -> BodyRef<'_> {
        BodyRef { body: &self.body, infere: &self.infere }
    }
}

/// Enhancement-400: one contribution statement, as written in the source.
///
/// Produced by [`crate::Module::contribution_sites`] so that a diagnostic raised in the
/// backend -- which only sees MIR values -- can still point at the statement that wrote
/// the contribution and honour a lint attribute placed on it.
#[derive(Debug, Clone, Copy)]
pub struct ContributionSite {
    /// `true` for a potential contribution (`V(..) <+ ..`), `false` for a flow one.
    pub potential: bool,
    /// `true` for the indirect form (`V(out) : V(a,b) == 0;`).
    pub indirect: bool,
    /// `true` when the contributed expression is a literal zero. Such a contribution
    /// carries no value: `V(a,b) <+ 0` is a node-collapse request, delivered by a
    /// `CollapseHint` callback rather than by the branch's residual, and `I(a,b) <+ 0`
    /// is a no-op. Discarding one discards nothing.
    pub zero: bool,
    /// Enhancement-532: `true` when the contributed expression is noise-only (a noise
    /// function, possibly negated, scaled, or summed with other noise) -- the same
    /// classification `hir_lower::stmt::expr_is_noise_only` applies when it decides
    /// that such a contribution must not reclassify the branch (Enhancement-531).
    /// A discarded noise-only site loses no large-signal value (noise is zero in
    /// every large-signal analysis, LRM 4.6.4) but its NOISE is dropped with it,
    /// which deserves its own words in the report.
    pub noise_only: bool,
    /// Source range of the whole statement.
    pub range: TextRange,
    /// Lint anchor of the statement, so `(* openvaf_allow=".." *)` on it (or on any
    /// enclosing scope) is honoured.
    pub lint_src: LintSrc,
}

/// Every contribution statement of a module's analog blocks, bucketed by the branch it
/// writes.
///
/// Built once per module (see [`crate::Module::contribution_sites`]) and then queried per
/// branch, so a backend that walks every branch does not re-walk the body every time.
#[derive(Debug, Default)]
pub struct ContributionMap {
    branches: Vec<(BranchWrite, Vec<ContributionSite>)>,
}

impl ContributionMap {
    /// The contributions written to `branch`, in source order; empty if there are none.
    pub fn get(&self, db: &CompilationDB, branch: BranchWrite) -> &[ContributionSite] {
        self.branches
            .iter()
            .find(|(candidate, _)| same_branch(db, branch, *candidate))
            .map_or(&[], |(_, sites)| sites.as_slice())
    }

    /// Enhancement-406: a DIFFERENT branch that spans the same nodes as `branch` and
    /// does carry contributions, if there is one.
    ///
    /// Used to tell the deliberate ideal-ammeter idiom (a sense branch nothing else
    /// drives -- supported since E-36 and documented) from the mistake it looks like
    /// (the same node pair driven through the other spelling, so the ammeter shorts it).
    pub fn other_branch_over_same_nodes(
        &self,
        db: &CompilationDB,
        branch: BranchWrite,
    ) -> Option<(BranchWrite, &[ContributionSite])> {
        let want = branch_node_set(db, branch);
        if want.is_empty() {
            return None;
        }
        self.branches
            .iter()
            .find(|(candidate, sites)| {
                !sites.is_empty()
                    && !same_branch(db, branch, *candidate)
                    && branch_node_set(db, *candidate) == want
            })
            .map(|(b, sites)| (*b, sites.as_slice()))
    }

    /// Adds every contribution found in `def`'s body.
    ///
    /// Reads `assignment_destination` directly rather than going through
    /// [`BodyRef::get_stmt`]: it must stay total over every statement it meets, and both
    /// the direct (`<+`) and the indirect (`:`) form land in that one map -- the indirect
    /// form contributes too, since `hir_lower::stmt::indirect_contribute` feeds its fresh
    /// implicit unknown through the very same `contribute_value`.
    fn collect_body(&mut self, db: &CompilationDB, def: DefWithBodyId, lint: Lint) {
        let body = db.body(def);
        let sm = db.body_source_map(def);
        let infere = db.inference_result(def);

        for (&stmt, dst) in infere.assignment_destination.iter() {
            let (potential, write) = match *dst {
                inference::AssignDst::Potential(write) => (true, write),
                inference::AssignDst::Flow(write) => (false, write),
                _ => continue,
            };
            let range = match sm.stmt_map_back[stmt].as_ref() {
                Some(ptr) => ptr.range(),
                // a statement with no source position has nothing to point at; leave it
                // out rather than pointing at offset 0
                None => continue,
            };
            // the same literal-zero test `hir_lower::stmt::contribute` applies when it
            // decides a contribution is a collapse request
            let (zero, noise_only) = match body.stmts[stmt] {
                hir_def::Stmt::Assignment { val, .. } => {
                    let zero = match body.exprs[val] {
                        hir_def::Expr::Literal(ref lit) => lit.is_zero(),
                        _ => false,
                    };
                    (zero, expr_is_noise_only(&body, &infere, val))
                }
                _ => (false, false),
            };
            let site = ContributionSite {
                potential,
                indirect: infere.indirect_branch_constraints.contains_key(&stmt),
                zero,
                noise_only,
                range,
                lint_src: sm.lint_src(stmt, lint),
            };
            let write: BranchWrite = write.into();
            match self.branches.iter_mut().find(|(branch, _)| same_branch(db, write, *branch)) {
                Some((_, sites)) => sites.push(site),
                None => self.branches.push((write, vec![site])),
            }
        }
    }

    /// `assignment_destination` is a hash map, so both the bucket order and the order
    /// within a bucket are arbitrary. Only the latter is observable (a report lists a
    /// bucket's sites), so sort each bucket into source order.
    fn sort(&mut self) {
        for (_, sites) in &mut self.branches {
            sites.sort_by_key(|site| site.range.start());
        }
    }
}

/// Enhancement-406: a place where a branch's FLOW is read (`I(br)`, `I(a,b)`).
///
/// Only flow probes are collected. A potential probe cannot change the circuit, but a
/// flow probe on a branch nothing contributes to becomes an ideal ammeter -- a 0 V
/// source -- which SHORTS the branch's nodes.
#[derive(Debug, Clone)]
pub struct FlowProbeSite {
    pub branch: BranchWrite,
    /// Source range of the probe expression.
    pub range: TextRange,
    /// Lint anchor, so `(* openvaf_allow=".." *)` on an enclosing scope is honoured.
    pub lint_src: LintSrc,
}

/// Enhancement-532: is this expression noise-only -- a noise function call, possibly
/// negated, scaled, or summed with other noise? The mirror of
/// `hir_lower::stmt::expr_is_noise_only`, evaluated at the HIR level where source
/// positions still exist, so the contribution map can carry the classification into
/// the Enhancement-400 report.
fn expr_is_noise_only(
    body: &hir_def::body::Body,
    infere: &inference::InferenceResult,
    expr: ExprId,
) -> bool {
    match body.exprs[expr] {
        hir_def::Expr::Call { .. } => matches!(
            infere.resolved_calls.get(&expr),
            Some(inference::ResolvedFun::BuiltIn(
                BuiltIn::white_noise
                    | BuiltIn::flicker_noise
                    | BuiltIn::noise_table
                    | BuiltIn::noise_table_log
            ))
        ),
        hir_def::Expr::UnaryOp { expr, .. } => expr_is_noise_only(body, infere, expr),
        hir_def::Expr::BinaryOp { lhs, rhs, op: Some(op) } => {
            use syntax::ast::BinaryOp::*;
            match op {
                // a scaled noise source is still noise-only as long as ONE side is
                // noise (noise * gain, noise / r); a SUM is noise-only only when
                // both sides are
                Multiplication | Division => {
                    expr_is_noise_only(body, infere, lhs) || expr_is_noise_only(body, infere, rhs)
                }
                Addition | Subtraction => {
                    expr_is_noise_only(body, infere, lhs) && expr_is_noise_only(body, infere, rhs)
                }
                _ => false,
            }
        }
        _ => false,
    }
}

/// The ground-free, order-free node set a branch spans, as the DAE sees it.
///
/// Enhancement-406: this is deliberately NOT [`same_branch`]. That answers "are these the
/// same branch object", where a declared `branch (a,b) br` and the node pair `(a,b)` are
/// DIFFERENT branches -- which is correct, and what the DAE, the E-400 contribution map
/// and the LRM compliance notes all agree on. This answers the other question: "do these
/// two different branches span the same two nodes", which is what makes one of them
/// shorting the other a surprise rather than a parallel network.
fn branch_node_set(db: &CompilationDB, branch: BranchWrite) -> Vec<Node> {
    let (hi, lo) = branch.nodes(db);
    let mut res: Vec<Node> = [Some(hi), lo]
        .into_iter()
        .flatten()
        .filter(|node| !node.is_gnd(db))
        .collect();
    res.sort_by_key(|n| format!("{:?}", n));
    res.dedup();
    res
}

/// Enhancement-406: every flow probe in a module's bodies.
///
/// Mirrors the branch resolution `hir_lower::expr` performs for `BuiltIn::flow`, so a
/// probe is attributed to exactly the branch the backend will key its unknown on: a
/// declared branch stays `Named`, a node pair stays `Unnamed`, and the two are NOT folded
/// together -- that separation is the whole point of the check.
///
/// A named branch declared over a PORT (`branch (<p>) name;`) is skipped: lowering routes
/// it to the port's own flow, which `build_port_flow_equations` defines, so it is never a
/// probe-only branch and can never short anything.
pub(crate) fn collect_flow_probes(
    db: &CompilationDB,
    module: ModuleId,
    lint: Lint,
) -> Vec<FlowProbeSite> {
    let mut res = Vec::new();
    for initial in [true, false] {
        let def = DefWithBodyId::ModuleId { initial, module };
        let body = db.body(def);
        let sm = db.body_source_map(def);
        let infere = db.inference_result(def);

        for (expr, call) in infere.resolved_calls.iter() {
            if !matches!(call, inference::ResolvedFun::BuiltIn(BuiltIn::flow)) {
                continue;
            }
            let Some(&signature) = infere.resolved_signatures.get(expr) else { continue };
            let hir_def::Expr::Call { ref args, .. } = body.exprs[*expr] else { continue };
            let bodyref = BodyRef { body: &body, infere: &infere };

            let branch = if signature == NATURE_ACCESS_BRANCH {
                let branch = bodyref.into_branch(args[0]);
                // a port branch is the port's flow, never a probe-only branch
                if matches!(branch.kind(db), BranchKind::PortFlow(_)) {
                    continue;
                }
                BranchWrite::Named(branch)
            } else if signature == NATURE_ACCESS_NODES {
                BranchWrite::Unnamed {
                    hi: bodyref.into_node(args[0]),
                    lo: Some(bodyref.into_node(args[1])),
                }
            } else if signature == NATURE_ACCESS_NODE_GND {
                BranchWrite::Unnamed { hi: bodyref.into_node(args[0]), lo: None }
            } else {
                // NATURE_ACCESS_PORT_FLOW -- `I(<p>)`, defined by the port flow equations
                continue;
            };

            let Some(ptr) = sm.expr_map_back[*expr].as_ref() else { continue };
            let range = ptr.range();
            // Lint attributes attach to STATEMENTS, not expressions, so anchor the probe
            // on the innermost statement containing it. That makes
            // `(* openvaf_allow="probe_only_branch_short" *)` work on the probing
            // statement and on every enclosing scope, exactly as it does elsewhere.
            let mut lint_src = LintSrc::GLOBAL;
            let mut best: Option<TextRange> = None;
            for (stmt, ptr) in sm.stmt_map_back.iter_enumerated() {
                let Some(sr) = ptr.as_ref().map(|p| p.range()) else { continue };
                if sr.contains_range(range) && best.map_or(true, |b| sr.len() < b.len()) {
                    best = Some(sr);
                    lint_src = sm.lint_src(stmt, lint);
                }
            }
            res.push(FlowProbeSite { branch, range, lint_src });
        }
    }
    res.sort_by_key(|p| p.range.start());
    res
}

pub(crate) fn collect_contributions(
    db: &CompilationDB,
    module: ModuleId,
    lint: Lint,
) -> ContributionMap {
    let mut res = ContributionMap::default();
    for initial in [true, false] {
        res.collect_body(db, DefWithBodyId::ModuleId { initial, module }, lint);
    }
    res.sort();
    res
}

/// Do two branch writes name the same branch?
///
/// `hir_lower::stmt::lower_contribute_unnamed_branch` drops ground references and folds
/// `(lo,hi)` onto an already-seen `(hi,lo)`, so the branch the backend reports may be
/// spelled differently from the statement that wrote it. Compare the way lowering does:
/// ground-free, order-free.
fn same_branch(db: &CompilationDB, a: BranchWrite, b: BranchWrite) -> bool {
    match (a, b) {
        (BranchWrite::Named(a), BranchWrite::Named(b)) => a == b,
        (
            BranchWrite::Unnamed { hi: a_hi, lo: a_lo },
            BranchWrite::Unnamed { hi: b_hi, lo: b_lo },
        ) => {
            let nodes = |hi: Node, lo: Option<Node>| {
                let mut res: Vec<Node> = Vec::with_capacity(2);
                for node in [Some(hi), lo].into_iter().flatten() {
                    if !node.is_gnd(db) {
                        res.push(node)
                    }
                }
                res
            };
            let (a, b) = (nodes(a_hi, a_lo), nodes(b_hi, b_lo));
            match (a.len(), b.len()) {
                (1, 1) => a[0] == b[0],
                (2, 2) => (a[0] == b[0] && a[1] == b[1]) || (a[0] == b[1] && a[1] == b[0]),
                _ => false,
            }
        }
        _ => false,
    }
}

#[derive(Debug, Clone, Copy)]
pub struct BodyRef<'a> {
    body: &'a hir_def::body::Body,
    infere: &'a inference::InferenceResult,
}

impl<'a> BodyRef<'a> {
    pub fn entry(&self) -> &'a [StmtId] {
        &self.body.entry_stmts
    }

    /// Returns the type that was inferred for this expression
    pub fn expr_type(&self, expr: ExprId) -> Type {
        self.infere.expr_types[expr].to_value().unwrap()
    }

    /// Returns whether the result of an expression
    /// needs to be cast to a different type before use.
    pub fn needs_cast(&self, expr: ExprId) -> Option<(Type, &'a Type)> {
        let dst = self.infere.casts.get(&expr)?;
        let src = self.expr_type(expr);
        debug_assert_ne!(&src, dst, "cast types must be different");
        Some((src, dst))
    }

    /// For a `laplace_*` `num`/`den` argument that is a bare reference to a module-body array
    /// variable (rather than an array literal): the variable's expanded scalar elements, in
    /// ascending declared-index order. See `hir_ty::inference::InferenceResult::array_var_refs`.
    pub fn array_var_ref(&self, expr: ExprId) -> Option<Vec<Variable>> {
        let ids = self.infere.array_var_refs.get(&expr)?;
        Some(ids.iter().map(|&id| Variable { id }).collect())
    }

    /// The parameter-array twin of [`Self::array_var_ref`]: LRM 4.5.1 allows an array
    /// PARAMETER wherever an array variable is allowed as a filter / `noise_table`
    /// argument.
    pub fn array_param_ref(&self, expr: ExprId) -> Option<Vec<Parameter>> {
        let ids = self.infere.array_param_refs.get(&expr)?;
        Some(ids.iter().map(|&id| Parameter { id }).collect())
    }

    /// For a dynamic-index array *read* `c[i]` / `m[i][j]` (non-constant indices): the element
    /// variables flattened in declaration order, the per-dimension `(msb, lsb)` bounds, and one
    /// index expression per dimension. HIR lowering computes the flat position at runtime.
    pub fn dynamic_index(&self, expr: ExprId) -> Option<(Vec<Variable>, Vec<(i32, i32)>, Vec<ExprId>)> {
        let d = self.infere.dynamic_index_refs.get(&expr)?;
        let elems = d.elems.iter().map(|&id| Variable { id }).collect();
        Some((elems, d.dims.clone(), d.indices.clone()))
    }

    /// Enhancement-405: same as [`Self::dynamic_index`], for a `parameter`/`localparam`
    /// array. Read-only by construction -- there is no assignment counterpart.
    pub fn dynamic_param_index(
        &self,
        expr: ExprId,
    ) -> Option<(Vec<Parameter>, Vec<(i32, i32)>, Vec<ExprId>)> {
        let d = self.infere.dynamic_param_index_refs.get(&expr)?;
        let elems = d.elems.iter().map(|&id| Parameter { id }).collect();
        Some((elems, d.dims.clone(), d.indices.clone()))
    }

    /// Enhancement-546: the module parameters read and the user functions called
    /// inside the expression trees rooted at `roots` -- every expression of the
    /// body when `roots` is `None`, which is what a function body needs.
    ///
    /// These are the dependency edges of a parameter's default and range
    /// (`sim_back::module_info` follows them to find the parameters that read an
    /// instance parameter). It works from the INFERENCE result rather than
    /// [`Self::get_expr`] so that it is total and complete: a parameter-typed path
    /// (which is also what `$param_given(p)` receives), a whole array parameter
    /// handed to a filter (`array_param_refs`) and a dynamically indexed element
    /// (`dynamic_param_index_refs`) all count as reads. Function-local parameters
    /// (LRM 4.7.1) are returned like any other; the caller decides what a read of
    /// one means.
    /// Enhancement-555: the parameters whose givenness this body tests with
    /// `$param_given(p)`. A model that picks a default that way runs a
    /// different branch once the simulator marks the parameter given, so the
    /// OSDI side-table says which statistical parameters are tested.
    pub fn param_given_tests(&self) -> Vec<Parameter> {
        let mut res = Vec::new();
        for (expr, call) in self.infere.resolved_calls.iter() {
            if !matches!(call, inference::ResolvedFun::BuiltIn(BuiltIn::param_given)) {
                continue;
            }
            let hir_def::Expr::Call { ref args, .. } = self.body.exprs[*expr] else { continue };
            for arg in args.iter() {
                if let Some(Ty::Param(_, id)) = self.infere.expr_types.get(*arg) {
                    let param = Parameter { id: *id };
                    if !res.contains(&param) {
                        res.push(param);
                    }
                }
            }
        }
        res
    }

    pub fn param_reads_and_calls(
        &self,
        roots: Option<&[ExprId]>,
    ) -> (Vec<Parameter>, Vec<Function>) {
        let mut params = Vec::new();
        let mut funcs = Vec::new();
        let mut visit = |expr: ExprId| {
            if let Some(Ty::Param(_, id)) = self.infere.expr_types.get(expr) {
                params.push(Parameter { id: *id });
            }
            if let Some(ids) = self.infere.array_param_refs.get(&expr) {
                params.extend(ids.iter().map(|&id| Parameter { id }));
            }
            if let Some(dyn_index) = self.infere.dynamic_param_index_refs.get(&expr) {
                params.extend(dyn_index.elems.iter().map(|&id| Parameter { id }));
            }
            if let Some(inference::ResolvedFun::User { func, .. }) =
                self.infere.resolved_calls.get(&expr)
            {
                funcs.push(Function { id: *func });
            }
        };
        match roots {
            None => {
                for (i, _) in self.body.exprs.iter().enumerate() {
                    visit(ExprId::from(i));
                }
            }
            Some(roots) => {
                let mut stack: Vec<ExprId> = roots.to_vec();
                while let Some(expr) = stack.pop() {
                    visit(expr);
                    self.body.exprs[expr].walk_child_exprs(|child| stack.push(child));
                }
            }
        }
        (params, funcs)
    }

    fn resolve_path(&self, expr: ExprId) -> Ref {
        match self.infere.expr_types[expr] {
            Ty::Var(_, id) => Ref::Variable(Variable { id }),
            Ty::Param(_, id) => Ref::Parameter(Parameter { id }),
            Ty::FunctionVar { fun, arg: Some(arg), .. } => {
                Ref::FunctionArg(FunctionArg { fun_id: fun, arg_id: arg })
            }
            Ty::FunctionVar { fun, .. } => Ref::FunctionReturn(Function { id: fun }),
            // Round-4 audit: the reference may be the nature's own attribute
            // or a discipline's override of it (LRM 3.6.2.5); both read as a
            // constant-expression body.
            Ty::NatureAttr(_, AttrId::Nature(id)) => Ref::NatureAttr(NatureAttribute { id }),
            Ty::NatureAttr(_, AttrId::Discipline(id)) => {
                Ref::DisciplineAttr(DisciplineAttribute { id })
            }

            ref it => {
                if let Some(&inference::ResolvedFun::Param(param)) =
                    self.infere.resolved_calls.get(&expr)
                {
                    return Ref::ParamSysFun(param);
                }
                panic!("invalid HIR: path {:?} was not resolved {:?}", self.body.exprs[expr], it)
            }
        }
    }

    pub fn get_call_signature(&self, expr: ExprId) -> Signature {
        self.infere.resolved_signatures.get(&expr).copied().unwrap_or(Signature(u32::MAX))
    }

    pub fn as_literal(&self, expr: ExprId) -> Option<&'a Literal> {
        match &self.body.exprs[expr] {
            hir_def::Expr::Literal(lit) => Some(lit),
            _ => None,
        }
    }

    // AB: get integer literal
    pub fn as_literalint(&self, &expr1: &ExprId) -> Option<i32> {
        match &self.body.exprs[expr1] {
            hir_def::Expr::Literal(lit) => match &lit {
                Literal::Int(ii) => Some(*ii), // Int literal
                _ => None,                     // other literals
            },
            _ => None, // not a literal
        }
    }

    // AB: get integer literal with optional negative sign
    pub fn as_literalsignedint(&self, &expr1: &ExprId) -> Option<i32> {
        match &self.body.exprs[expr1] {
            hir_def::Expr::Literal(lit) => match &lit {
                // Literal
                Literal::Int(ii) => Some(*ii), // Int literal
                _ => None,                     // other literals
            },
            hir_def::Expr::UnaryOp { expr, op } => {
                // UnaryOp
                match op {
                    UnaryOp::Neg => match self.as_literalint(expr) {
                        // Neg
                        Some(ii) => Some(-ii), // Neg Int literal
                        _ => None,             // Neg anything else
                    },
                    _ => None, // Other UnaryOp
                }
            }
            _ => None, // Neither Literal nor UnaryOp
        }
    }

    pub fn into_node(&self, expr: ExprId) -> Node {
        let id = self.infere.expr_types[expr].unwrap_node();
        Node { id }
    }

    pub fn into_port_flow(&self, expr: ExprId) -> Node {
        let id = self.infere.expr_types[expr].unwrap_port_flow();
        Node { id }
    }

    pub fn into_parameter(&self, expr: ExprId) -> Parameter {
        let id = self.infere.expr_types[expr].unwrap_param();
        Parameter { id }
    }

    /// The variable referenced by a `Var(..)` builtin argument (e.g. the
    /// destination string of `$swrite`/`$sformat`/`$fgets`, an inout `$sscanf`
    /// target, or `$ferror`'s message string).
    pub fn into_variable(&self, expr: ExprId) -> Variable {
        let id = self.infere.expr_types[expr].unwrap_var();
        Variable { id }
    }

    pub fn into_branch(&self, expr: ExprId) -> Branch {
        let id = self.infere.expr_types[expr].unwrap_branch();
        Branch { id }
    }

    pub fn get_expr(&self, expr: ExprId) -> Expr<'a> {
        // Enhancement-328: a dynamically-indexed array read has no `Ref` -- inference
        // types it `Ty::Val(..)` and records it in `dynamic_index_refs` -- so routing it
        // into `resolve_path` below panicked ("invalid HIR: path BitSelect .. was not
        // resolved"). Answer the SHAPE question here instead, which keeps `get_expr`
        // total for every caller; the value itself is still lowered by `lower_expr`'s
        // `dynamic_index()` short-circuit, exactly as before.
        if self.infere.dynamic_index_refs.contains_key(&expr)
            || self.infere.dynamic_param_index_refs.contains_key(&expr)
        {
            return Expr::DynIndexRead;
        }
        match self.body.exprs[expr] {
            hir_def::Expr::Path { .. } | hir_def::Expr::BitSelect { .. } => {
                Expr::Read(self.resolve_path(expr))
            }
            hir_def::Expr::BinaryOp { lhs, rhs, op: Some(op) } => Expr::BinaryOp { lhs, rhs, op },
            hir_def::Expr::UnaryOp { expr, op } => Expr::UnaryOp { expr, op },
            hir_def::Expr::Select { cond, then_val, else_val } => {
                Expr::Select { cond, then_val, else_val }
            }
            hir_def::Expr::Call { ref args, .. } => {
                let fun = match self.infere.resolved_calls[&expr] {
                    inference::ResolvedFun::User { func, limit } => {
                        ResolvedFun::User { func: Function { id: func }, limit }
                    }
                    inference::ResolvedFun::BuiltIn(builtin) => ResolvedFun::BuiltIn(builtin),
                    // this is a special case, the VAMS standard allows these parameters
                    // to be called like functions (but its the same as direct access)
                    // we hide that detail from downstream users here
                    inference::ResolvedFun::Param(param) => {
                        return Expr::Read(Ref::ParamSysFun(param))
                    }
                    inference::ResolvedFun::InvalidNatureAccess(_) => {
                        panic!("invalid HIR: invalid nature access {:?}", self.body.exprs[expr])
                    }
                };
                Expr::Call { fun, args }
            }
            hir_def::Expr::Array(ref args) => Expr::Array(args),
            hir_def::Expr::Concat { rep, ref elems } => Expr::Concat { rep, elems },
            hir_def::Expr::Literal(ref literal) => Expr::Literal(literal),
            _ => panic!("invalid HIR: {:?}", self.body.exprs[expr]),
        }
    }

    pub fn get_entry_stmt(&self, i: usize) -> Option<Stmt<'a>> {
        self.get_stmt(self.entry()[i])
    }

    pub fn get_entry_expr(&self, i: usize) -> ExprId {
        self.get_stmt(self.entry()[i]).unwrap().unwrap_expr()
    }

    pub fn get_stmt(&self, stmnt: StmtId) -> Option<Stmt<'a>> {
        match self.body.stmts[stmnt] {
            hir_def::Stmt::Empty | hir_def::Stmt::Missing => None,
            hir_def::Stmt::Expr(e) => Some(Stmt::Expr(e)),
            hir_def::Stmt::EventControl { ref event, body } => {
                Some(Stmt::EventControl { event, body })
            }
            hir_def::Stmt::Assignment { val, .. } => {
                if let Some(arr) = self.infere.array_assignments.get(&stmnt) {
                    match arr {
                        inference::ArrayAssign::Literal(pairs) => {
                            let assigns = pairs
                                .iter()
                                .map(|&(dst, val)| ArrayAssignElem::Val {
                                    dst: Variable { id: dst },
                                    val,
                                })
                                .collect();
                            return Some(Stmt::ArrayAssignment { assigns });
                        }
                        // `c = {a, p, ...}` concatenation RHS (Enhancement-34): each
                        // destination element is either assigned a scalar expression or
                        // copied from a source array element.
                        inference::ArrayAssign::Concat(pairs) => {
                            let assigns = pairs
                                .iter()
                                .map(|&(dst, src)| match src {
                                    inference::ConcatSrc::Expr(val) => ArrayAssignElem::Val {
                                        dst: Variable { id: dst },
                                        val,
                                    },
                                    inference::ConcatSrc::Var(src) => ArrayAssignElem::Copy {
                                        dst: Variable { id: dst },
                                        src: Variable { id: src },
                                    },
                                })
                                .collect();
                            return Some(Stmt::ArrayAssignment { assigns });
                        }
                        inference::ArrayAssign::Copy(pairs) => {
                            let assigns = pairs
                                .iter()
                                .map(|&(dst, src)| ArrayAssignElem::Copy {
                                    dst: Variable { id: dst },
                                    src: Variable { id: src },
                                })
                                .collect();
                            return Some(Stmt::ArrayAssignment { assigns });
                        }
                        // `c = f(...)` for an array-returning function (Enhancement-23): the call is
                        // inlined at lowering (writing the return element vars), then copied out.
                        inference::ArrayAssign::ReturnCall { call, pairs } => {
                            let assigns = pairs
                                .iter()
                                .map(|&(dst, src)| ArrayAssignElem::Copy {
                                    dst: Variable { id: dst },
                                    src: Variable { id: src },
                                })
                                .collect();
                            return Some(Stmt::ArrayReturnAssignment { call: *call, assigns });
                        }
                    }
                }
                if let Some(dyn_assign) = self.infere.dynamic_index_assignments.get(&stmnt) {
                    let elems =
                        dyn_assign.target.elems.iter().map(|&id| Variable { id }).collect();
                    return Some(Stmt::DynArrayAssignment {
                        elems,
                        dims: dyn_assign.target.dims.clone(),
                        indices: dyn_assign.target.indices.clone(),
                        value: dyn_assign.value,
                    });
                }
                if let Some(&(constraint_lhs, constraint_rhs)) =
                    self.infere.indirect_branch_constraints.get(&stmnt)
                {
                    let stmt = match self.infere.assignment_destination[&stmnt] {
                        inference::AssignDst::Flow(branch) => Stmt::IndirectContribute {
                            kind: ContributeKind::Flow,
                            branch: branch.into(),
                            constraint_lhs,
                            constraint_rhs,
                        },
                        inference::AssignDst::Potential(branch) => Stmt::IndirectContribute {
                            kind: ContributeKind::Potential,
                            branch: branch.into(),
                            constraint_lhs,
                            constraint_rhs,
                        },
                        _ => unreachable!("invalid HIR: indirect branch dst must be a branch access"),
                    };
                    return Some(stmt);
                }

                let stmt = match self.infere.assignment_destination[&stmnt] {
                    inference::AssignDst::Var(id) => {
                        Stmt::Assignment { lhs: AssignmentLhs::Variable(Variable { id }), rhs: val }
                    }
                    inference::AssignDst::FunVar { fun, arg: None } => Stmt::Assignment {
                        lhs: AssignmentLhs::FunctionReturn(Function { id: fun }),
                        rhs: val,
                    },
                    inference::AssignDst::FunVar { fun, arg: Some(arg) } => Stmt::Assignment {
                        lhs: AssignmentLhs::FunctionArg(FunctionArg { fun_id: fun, arg_id: arg }),
                        rhs: val,
                    },
                    inference::AssignDst::Flow(branch) => Stmt::Contribute {
                        kind: ContributeKind::Flow,
                        branch: branch.into(),
                        rhs: val,
                    },
                    inference::AssignDst::Potential(branch) => Stmt::Contribute {
                        kind: ContributeKind::Potential,
                        branch: branch.into(),
                        rhs: val,
                    },
                };
                Some(stmt)
            }
            hir_def::Stmt::Block { ref name, ref body } => {
                Some(Stmt::Block { name: name.as_ref(), body })
            }
            hir_def::Stmt::Disable { ref name } => Some(Stmt::Disable { name }),
            hir_def::Stmt::If { cond, then_branch, else_branch } => {
                Some(Stmt::If { cond, then_branch, else_branch })
            }
            hir_def::Stmt::ForLoop { init, cond, incr, body } => {
                Some(Stmt::ForLoop { init, cond, incr, body })
            }
            hir_def::Stmt::WhileLoop { cond, body } => Some(Stmt::WhileLoop { cond, body }),
            hir_def::Stmt::DoWhile { cond, body } => Some(Stmt::DoWhile { cond, body }),
            hir_def::Stmt::Repeat { count, body } => Some(Stmt::Repeat { count, body }),
            hir_def::Stmt::Case { kind, discr, ref case_arms } => {
                Some(Stmt::Case { kind, discr, case_arms })
            }
            // VAMS-2023 jump statements (LRM 5.11)
            hir_def::Stmt::Break => Some(Stmt::Break),
            hir_def::Stmt::Continue => Some(Stmt::Continue),
            hir_def::Stmt::Return { expr } => Some(Stmt::Return { expr }),
        }
    }
}

#[derive(Debug, Clone, PartialEq, Eq, Copy)]
pub enum AssignmentLhs {
    Variable(Variable),
    FunctionReturn(Function),
    FunctionArg(FunctionArg),
}

/// One element of a whole-array assignment (`c = '{...}` / `c = d`): the destination element
/// variable and its source, either a literal value expression or another array's element variable.
#[derive(Debug, Clone, PartialEq, Eq, Copy)]
pub enum ArrayAssignElem {
    Val { dst: Variable, val: ExprId },
    Copy { dst: Variable, src: Variable },
}

#[derive(Debug, Clone, Eq, PartialEq)]
pub enum ContributeKind {
    Flow,
    Potential,
}

#[derive(Debug, Clone, Eq, PartialEq)]
pub enum Stmt<'a> {
    Expr(ExprId),
    EventControl { event: &'a Event, body: StmtId },
    Contribute { kind: ContributeKind, branch: BranchWrite, rhs: ExprId },
    IndirectContribute {
        kind: ContributeKind,
        branch: BranchWrite,
        constraint_lhs: ExprId,
        constraint_rhs: ExprId,
    },
    Assignment { lhs: AssignmentLhs, rhs: ExprId },
    ArrayAssignment { assigns: Vec<ArrayAssignElem> },
    /// `c = f(...)` for an array-returning `analog function` (Enhancement-23): `call` is the call
    /// expression (inlined during lowering, which writes the function's return element variables),
    /// and `assigns` copies each return element into the destination array element.
    ArrayReturnAssignment { call: ExprId, assigns: Vec<ArrayAssignElem> },
    /// A dynamic-index array write `c[i] = value` / `m[i][j] = value` (non-constant indices): the
    /// element variables (declaration order), per-dimension `(msb, lsb)` bounds, one index
    /// expression per dimension, and the value expression.
    DynArrayAssignment {
        elems: Vec<Variable>,
        dims: Vec<(i32, i32)>,
        indices: Vec<ExprId>,
        value: ExprId,
    },
    Block { name: Option<&'a Name>, body: &'a [StmtId] },
    Disable { name: &'a Name },
    If { cond: ExprId, then_branch: StmtId, else_branch: StmtId },
    ForLoop { init: StmtId, cond: ExprId, incr: StmtId, body: StmtId },
    WhileLoop { cond: ExprId, body: StmtId },
    DoWhile { cond: ExprId, body: StmtId },
    Repeat { count: ExprId, body: StmtId },
    Case { kind: CaseKind, discr: ExprId, case_arms: &'a [Case] }, // TODO lint on unreachable
    /// VAMS-2023 jump statements (LRM 5.11)
    Break,
    Continue,
    Return { expr: Option<ExprId> },
}
impl Stmt<'_> {
    #[inline]
    pub fn unwrap_expr(&self) -> ExprId {
        if let Stmt::Expr(e) = self {
            *e
        } else {
            unreachable!("Called unwrap_expr on {:?}", self)
        }
    }
}

#[derive(Debug, Clone, Eq, PartialEq)]
pub enum Expr<'a> {
    Read(Ref),
    BinaryOp { lhs: ExprId, rhs: ExprId, op: BinaryOp },
    UnaryOp { expr: ExprId, op: UnaryOp },
    Select { cond: ExprId, then_val: ExprId, else_val: ExprId },
    Call { fun: ResolvedFun, args: &'a [ExprId] },
    Array(&'a [ExprId]),
    /// Enhancement-34: `{...}` concatenation / `{n{...}}` replication (`rep` = the
    /// constant repetition-count expression of the replication form).
    Concat { rep: Option<ExprId>, elems: &'a [ExprId] },
    Literal(&'a Literal),
    /// Enhancement-328: a dynamically-indexed array read, `c[i]` / `m[i][j]` with a
    /// non-constant index. It has no `Ref`: inference types it `Ty::Val(..)` and records
    /// the element variables, bounds and index expressions out-of-band in
    /// `InferenceResult::dynamic_index_refs` (reachable via [`BodyRef::dynamic_index`]),
    /// from which `lower_expr` builds a runtime select chain.
    ///
    /// It exists as a variant so that [`BodyRef::get_expr`] stays TOTAL. `get_expr`
    /// previously funnelled every `BitSelect` into `resolve_path`, which only knows how
    /// to resolve `Ty::Var`/`Ty::Param`/... and `panic!`s otherwise -- so any caller that
    /// merely probes an expression's SHAPE (a literal-zero test, a literal-condition
    /// fold, an aggregate check) crashed the compiler on a perfectly legal dynamic array
    /// read. `lower_expr` never hit it only because it short-circuits on
    /// `dynamic_index()` before consulting `get_expr`.
    DynIndexRead,
}
impl Expr<'_> {
    pub fn is_zero(&self) -> bool {
        if let Expr::Literal(lit) = self {
            lit.is_zero()
        } else {
            false
        }
    }

    pub fn as_assignment_lhs(&self) -> AssignmentLhs {
        match *self {
            Expr::Read(Ref::Variable(var)) => AssignmentLhs::Variable(var),
            Expr::Read(Ref::FunctionArg(arg)) => AssignmentLhs::FunctionArg(arg),
            Expr::Read(Ref::FunctionReturn(fun)) => AssignmentLhs::FunctionReturn(fun),
            _ => panic!("{self:?} is not a lhs reference"),
        }
    }
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum Ref {
    Variable(Variable),
    Parameter(Parameter),
    FunctionArg(FunctionArg),
    FunctionReturn(Function),
    NatureAttr(NatureAttribute),
    DisciplineAttr(DisciplineAttribute),
    ParamSysFun(ParamSysFun),
}

#[derive(Debug, Clone, PartialEq, Eq, Copy)]
pub enum ResolvedFun {
    User { func: Function, limit: bool },
    BuiltIn(BuiltIn),
}
