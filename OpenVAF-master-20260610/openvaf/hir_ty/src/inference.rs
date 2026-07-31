use std::borrow::Cow;
use std::mem;
use std::sync::Arc;

/// Enhancement-333: recursion bound for `const_int_expr`. Deep enough for the constant
/// folding real sources do (`-2147483647 - 1`, `1 << (4*8)`), shallow enough that a
/// pathological expression cannot blow the stack.
const CONST_FOLD_DEPTH: u32 = 16;

use ahash::AHashMap;
use arena::ArenaMap;
use hir_def::body::Body;
use hir_def::db::HirDefDB;
use hir_def::expr::{CaseCond, Event, Literal};
use hir_def::nameres::diagnostics::PathResolveError;
use hir_def::nameres::{NatureAccess, ResolvedPath, ScopeDefItem, ScopeDefItemKind};
use hir_def::{
    function_array_arg_vars, BranchId, BuiltIn, BusDecl, DefWithBodyId, Expr, ExprId,
    FunctionArgLoc, FunctionId, LocalFunctionArgId, Lookup, NatureId, NodeId, ParamSysFun, Path,
    Stmt, StmtId, Type, VarId,
};
use stdx::impl_from;
use stdx::iter::zip;
use syntax::ast::{self, BinaryOp, UnaryOp};
use syntax::name::{AsIdent, Name};
use syntax::{TextRange, TextSize};
use typed_index_collections::{TiSlice, TiVec};

use crate::builtin::{
    DDX_FLOW, DDX_POT, DDX_POT_DIFF, DDX_TEMP, LAPALCE_TOL, LAPLACE_NATURE_TOL, LAPLACE_NO_TOL,
    LIMIT_BUILTIN_FUNCTION, LIMIT_USER_FUNCTION, NATURE_ACCESS_BRANCH, NATURE_ACCESS_NODES,
    NATURE_ACCESS_NODE_GND, NATURE_ACCESS_PORT_FLOW,
};
use crate::db::{Alias, HirTyDB};
use crate::diagnostics::{ArrayTypeMismatch, SignatureMismatch, TypeMismatch};
use crate::inference::fmt_parser::parse_fmt_spec;
use crate::lower::{BranchTy, DisciplineAccess};
use crate::types::{default_return_ty, BuiltinInfo, Signature, SignatureData, Ty, TyRequirement};

mod fmt_parser;

#[derive(Debug, Clone, PartialEq, Eq, Copy)]
pub enum ResolvedFun {
    User { func: FunctionId, limit: bool },
    BuiltIn(BuiltIn),
    Param(ParamSysFun),
    InvalidNatureAccess(NatureId),
}

/// Enhancement-325: cap on the number of elements a NUMERIC `{...}` concatenation /
/// `{n{...}}` replication may materialize. Enhancement-314 capped the replication
/// COUNT; this caps the resulting SIZE, which is what actually overflowed the u32
/// array length. The numeric path is linear and cheap (65536 elements compile in
/// ~0.4 s), so this bound only rules out the absurd.
pub const MAX_CONCAT_ELEMS: u64 = 1 << 20;

/// Enhancement-325: cap on the operand count of a STRING concatenation/replication.
/// Much tighter than `MAX_CONCAT_ELEMS` because a string concatenation is lowered to
/// a generated LLVM callback with ONE PARAMETER PER OPERAND (`lower_string_concat`
/// builds an N-operand list and an N-"%s" format string), and LLVM degrades
/// super-linearly in function arity: measured 2000 -> 0.4 s, 8000 -> 2.9 s,
/// 16000 -> 8.6 s, 32000 -> did not finish. 4096 keeps the worst case near a second
/// and is orders of magnitude above any legitimate source-level string literal.
pub const MAX_CONCAT_STR_OPERANDS: u64 = 4096;

#[derive(Debug, Clone, PartialEq, Eq, Copy)]
pub enum AssignDst {
    Var(VarId),
    FunVar { fun: FunctionId, arg: Option<LocalFunctionArgId> },
    Flow(BranchWrite),
    Potential(BranchWrite),
}

/// A *whole-array* assignment (`c = '{...}` or `c = d`, where `c` is a `real/integer [msb:lsb] c;`
/// array variable), decomposed into per-element assignments in declaration order (msb→lsb, the
/// order array literals fill). The destination element `VarId`s come from the bus/array expansion
/// (Enhancement-3/4); the source is either the literal's element value `ExprId`s or, for an
/// array-to-array copy, the source array's element `VarId`s. See `try_infere_array_assignment`.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum ArrayAssign {
    Literal(Vec<(VarId, ExprId)>),
    Copy(Vec<(VarId, VarId)>),
    /// `c = {a, p, 2.0, ...}` where the RHS is a `{...}` concatenation (Enhancement-34):
    /// one source per destination element, each either a scalar expression (lowered and
    /// assigned) or a source array-element variable (copied).
    Concat(Vec<(VarId, ConcatSrc)>),
    /// `c = f(...)` where `f` is an array-returning `analog function` (Enhancement-23): the call
    /// expression (inlined at lowering, writing the function's return element variables) and the
    /// per-element `(destination VarId, function return-element VarId)` pairs to copy afterwards.
    ReturnCall { call: ExprId, pairs: Vec<(VarId, VarId)> },
}

/// One flattened element source of a `{...}` concatenation RHS (Enhancement-34).
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum ConcatSrc {
    Expr(ExprId),
    Var(VarId),
}

/// A dynamic (non-constant-index) array element access `c[i]` / `m[i][j]` (Enhancement-14/15).
/// Because the indices aren't known at compile time, the access can't resolve to a single element
/// `VarId`; instead we record every element `VarId` (flattened in declaration order, matching
/// `BusDecl::index_tuples`), the per-dimension `(msb, lsb)` bounds, and one index expression per
/// dimension. HIR lowering computes the flat element position at runtime and selects. Only
/// *variable* arrays support this — a vectored net/port cannot be dynamically selected.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct DynArrayIndex {
    pub elems: Vec<VarId>,
    pub dims: Vec<(i32, i32)>,
    pub indices: Vec<ExprId>,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct DynArrayIndexAssign {
    pub target: DynArrayIndex,
    pub value: ExprId,
}

#[derive(Debug, Clone, PartialEq, Eq, Copy, Hash)]
pub enum BranchWrite {
    Named(BranchId),
    Unnamed { hi: NodeId, lo: Option<NodeId> },
}

impl AssignDst {
    pub fn ty(&self, db: &dyn HirDefDB) -> Type {
        if let AssignDst::Var(var) = *self {
            let var = var.lookup(db);
            let tree = var.item_tree(db);
            tree[var.id].ty.clone()
        } else {
            Type::Real
        }
    }
}

#[derive(Debug, Clone, PartialEq, Eq, Default)]
pub struct InferenceResult {
    pub expr_types: ArenaMap<Expr, Ty>,
    pub resolved_calls: AHashMap<ExprId, ResolvedFun>,
    pub resolved_signatures: AHashMap<ExprId, Signature>,
    pub assignment_destination: AHashMap<StmtId, AssignDst>,
    /// For `Stmt::Assignment`s with `assignment_kind == AssignOp::IndirectBranch`, the
    /// decomposed `(lhs, rhs)` operands of the required `lhs == rhs` constraint expression.
    pub indirect_branch_constraints: AHashMap<StmtId, (ExprId, ExprId)>,
    pub casts: AHashMap<ExprId, Type>,
    /// For a `laplace_*` `num`/`den` (or `zero`/`pole`) argument that is a bare reference to a
    /// module-body array variable (`coeffs` for `real [0:n] coeffs;`) rather than an array
    /// literal: the variable's expanded scalar `VarId`s, in ascending declared-index order
    /// (`coeffs[0]`, `coeffs[1]`, ...). See `infere_array_arg`.
    pub array_var_refs: AHashMap<ExprId, Vec<VarId>>,
    /// For a whole-array assignment statement (`c = '{...}` or `c = d`): the decomposed
    /// per-element assignments. When present, this statement is a `Stmt::ArrayAssignment` in the
    /// HIR (and `assignment_destination` carries no entry for it). See `try_infere_array_assignment`.
    pub array_assignments: AHashMap<StmtId, ArrayAssign>,
    /// Dynamic array-element *reads* `c[i]` (non-constant `i`). See `DynArrayIndex`.
    pub dynamic_index_refs: AHashMap<ExprId, DynArrayIndex>,
    /// Dynamic array-element *writes* `c[i] = v` (non-constant `i`). See `DynArrayIndexAssign`.
    pub dynamic_index_assignments: AHashMap<StmtId, DynArrayIndexAssign>,
    pub diagnostics: Vec<InferenceDiagnostic>,
}

impl InferenceResult {
    pub fn infere_body_query(db: &dyn HirTyDB, id: DefWithBodyId) -> Arc<InferenceResult> {
        let body = db.body(id);
        let result = InferenceResult {
            expr_types: ArenaMap::from(vec![Ty::Val(Type::Err); body.exprs.len()]),
            ..Default::default()
        };

        let mut ctx = Ctx { result, body: &body, db, expr_stmt_ty: None, owner: id };
        ctx.expr_stmt_ty = match id {
            DefWithBodyId::ParamId(param) => match &db.param_data(param).ty {
                Some(ty) => Some(ty.clone()),
                // parameter type is inferred if omitted
                None => ctx
                    .infere_expr(body.entry_stmts[0], db.param_exprs(param).default)
                    .and_then(|ty| ty.to_value()),
            },
            DefWithBodyId::VarId(var) => Some(db.var_data(var).ty.clone()),
            _ => None,
        };

        for stmt in &*body.entry_stmts {
            ctx.infere_stmt(*stmt);
        }

        Arc::new(ctx.result)
    }
}

struct Ctx<'a> {
    result: InferenceResult,
    body: &'a Body,
    db: &'a dyn HirTyDB,
    /// A Body that only represent expressions have expr stmts as entry_stmts.
    /// These need to be type checked properly.
    /// For behavioural (anlog body and function) and untype (nature attr)
    /// bodys this is simply none
    expr_stmt_ty: Option<Type>,
    owner: DefWithBodyId,
}

impl Ctx<'_> {
    pub fn infere_stmt(&mut self, stmt: StmtId) {
        match self.body.stmts[stmt] {
            Stmt::Expr(expr) => {
                // TODO lint for side effect free expressions
                self.infere_assignment(stmt, expr, self.expr_stmt_ty.clone());
            }
            Stmt::Assignment { dst, val, assignment_kind: ast::AssignOp::IndirectBranch } => {
                let dst_ty =
                    self.infere_assignment_dst(stmt, dst, ast::AssignOp::IndirectBranch);
                self.infere_indirect_branch_constraint(stmt, val, dst_ty);
            }
            Stmt::Assignment { dst, val, assignment_kind } => {
                if !self.try_infere_array_assignment(stmt, dst, val)
                    && !self.try_infere_dynamic_index_assignment(stmt, dst, val)
                {
                    let dst_ty = self.infere_assignment_dst(stmt, dst, assignment_kind);
                    self.infere_assignment(stmt, val, dst_ty);
                }
            }
            Stmt::ForLoop { cond, .. }
            | Stmt::If { cond, .. }
            | Stmt::WhileLoop { cond, .. }
            | Stmt::DoWhile { cond, .. } => {
                self.infere_cond(stmt, cond)
            }
            Stmt::Repeat { count, .. } => {
                self.infere_expr(stmt, count);
            }

            Stmt::EventControl { ref event, .. } => self.infere_event_control(stmt, event),

            Stmt::Case { discr, ref case_arms, .. } => {
                // Enhancement-33: infer the discriminant and case items with the
                // array-aware helper, so whole-array variable references are accepted
                // (and registered in `array_var_refs`) alongside array literals and
                // ordinary scalars — enabling the element-wise array `case` in
                // `hir_lower::stmt::lower_case`. Scalars take the same path as before
                // (the helper falls through to `infere_expr`).
                if let Some(ty) = self.infere_array_arg(stmt, discr) {
                    let req = ty.to_value().map_or(TyRequirement::AnyVal, TyRequirement::Val);
                    for case in case_arms {
                        if let CaseCond::Vals(vals) = &case.cond {
                            for val in vals {
                                if let Some(val_ty) = self.infere_array_arg(stmt, *val) {
                                    self.expect::<false>(
                                        *val,
                                        None,
                                        val_ty,
                                        Cow::Owned(vec![req.clone()]),
                                    );
                                }
                            }
                        }
                    }
                }
            }
            _ => (),
        };

        self.body.stmts[stmt].walk_child_stmts(|stmt| self.infere_stmt(stmt));
    }

    fn infere_assignment(&mut self, stmt: StmtId, val: ExprId, dst_ty: Option<Type>) {
        if let Some(val_ty) = self.infere_expr(stmt, val) {
            if let Some(value_ty) = val_ty.to_value() {
                if let Some(dst_ty) = dst_ty {
                    if dst_ty.is_assignable_to(&value_ty) {
                        if dst_ty != value_ty {
                            self.result.casts.insert(val, dst_ty);
                        }
                    } else {
                        self.result.diagnostics.push(
                            TypeMismatch {
                                expected: Cow::Owned(vec![TyRequirement::Val(dst_ty)]),
                                found_ty: val_ty,
                                expr: val,
                            }
                            .into(),
                        );
                    }
                }
            } else {
                let expected = dst_ty.map_or(TyRequirement::AnyVal, TyRequirement::Val);
                self.result.diagnostics.push(
                    TypeMismatch {
                        expected: Cow::Owned(vec![expected]),
                        found_ty: val_ty,
                        expr: val,
                    }
                    .into(),
                );
            }
        }
    }

    /// Type checks the constraint of an indirect branch assignment
    /// (`<dst> : <val>;`). `val` must be a top-level `==` expression; its
    /// two operands are type checked as `Real` (matching `dst_ty`, which is
    /// always `Type::Real` for a valid branch-access destination) and
    /// recorded in `indirect_branch_constraints` for later use by HIR
    /// lowering, instead of being type checked as a single boolean value.
    fn infere_indirect_branch_constraint(
        &mut self,
        stmt: StmtId,
        val: ExprId,
        dst_ty: Option<Type>,
    ) {
        let (lhs, rhs) = match self.body.exprs[val] {
            Expr::BinaryOp { lhs, rhs, op: Some(BinaryOp::EqualityTest) } => (lhs, rhs),
            _ => {
                self.result
                    .diagnostics
                    .push(InferenceDiagnostic::IndirectAssignRequiresEquality { e: val });
                return;
            }
        };

        for operand in [lhs, rhs] {
            if let Some(operand_ty) = self.infere_expr(stmt, operand) {
                if let Some(value_ty) = operand_ty.to_value() {
                    if let Some(dst_ty) = dst_ty.clone() {
                        if dst_ty.is_assignable_to(&value_ty) {
                            if dst_ty != value_ty {
                                self.result.casts.insert(operand, dst_ty);
                            }
                        } else {
                            self.result.diagnostics.push(
                                TypeMismatch {
                                    expected: Cow::Owned(vec![TyRequirement::Val(dst_ty)]),
                                    found_ty: operand_ty,
                                    expr: operand,
                                }
                                .into(),
                            );
                        }
                    }
                } else {
                    let expected = dst_ty.clone().map_or(TyRequirement::AnyVal, TyRequirement::Val);
                    self.result.diagnostics.push(
                        TypeMismatch {
                            expected: Cow::Owned(vec![expected]),
                            found_ty: operand_ty,
                            expr: operand,
                        }
                        .into(),
                    );
                }
            }
        }

        self.result.indirect_branch_constraints.insert(stmt, (lhs, rhs));
    }

    pub fn infere_assignment_dst(
        &mut self,
        stmt: StmtId,
        expr: ExprId,
        assignment_kind: ast::AssignOp,
    ) -> Option<Type> {
        let e = self.infere_expr(stmt, expr);

        let (dst, ty) = match e? {
            Ty::Var(ty, var) => (AssignDst::Var(var), ty),
            Ty::FunctionVar { fun, ty, arg } => (AssignDst::FunVar { fun, arg }, ty),
            Ty::Val(Type::Real)
                if matches!(
                    self.result.resolved_calls.get(&expr),
                    Some(ResolvedFun::BuiltIn(BuiltIn::potential | BuiltIn::flow))
                ) =>
            {
                let mut args = Vec::new();
                self.body.exprs[expr].walk_child_exprs(|e| args.push(&self.result.expr_types[e]));
                let kind = match *self.result.resolved_signatures.get(&expr)? {
                    NATURE_ACCESS_BRANCH => BranchWrite::Named(args[0].unwrap_branch()),
                    NATURE_ACCESS_NODES => BranchWrite::Unnamed {
                        hi: args[0].unwrap_node(),
                        lo: Some(args[1].unwrap_node()),
                    },

                    NATURE_ACCESS_NODE_GND => {
                        BranchWrite::Unnamed { hi: args[0].unwrap_node(), lo: None }
                    }

                    NATURE_ACCESS_PORT_FLOW => {
                        self.result.diagnostics.push(InferenceDiagnostic::InvalidAssignDst {
                            e: expr,
                            maybe_different_operand: None,
                            assignment_kind,
                        });
                        return None;
                    }
                    _ => unreachable!(),
                };

                let dst = match self.result.resolved_calls[&expr] {
                    ResolvedFun::BuiltIn(BuiltIn::potential) => AssignDst::Potential(kind),
                    ResolvedFun::BuiltIn(BuiltIn::flow) => AssignDst::Flow(kind),
                    _ => unreachable!(),
                };
                (dst, Type::Real)
            }
            _ => {
                self.result.diagnostics.push(InferenceDiagnostic::InvalidAssignDst {
                    e: expr,
                    maybe_different_operand: None,
                    assignment_kind,
                });
                return None;
            }
        };

        // check that the correct operator is used
        match (&dst, assignment_kind) {
            (
                AssignDst::Var(_) | AssignDst::FunVar { .. },
                ast::AssignOp::Contribute | ast::AssignOp::IndirectBranch,
            ) => {
                self.result.diagnostics.push(InferenceDiagnostic::InvalidAssignDst {
                    e: expr,
                    maybe_different_operand: Some(ast::AssignOp::Assign),
                    assignment_kind,
                });
            }
            (AssignDst::Flow(_) | AssignDst::Potential(_), ast::AssignOp::Assign) => {
                self.result.diagnostics.push(InferenceDiagnostic::InvalidAssignDst {
                    e: expr,
                    maybe_different_operand: Some(ast::AssignOp::Contribute),
                    assignment_kind,
                });
            }
            _ => {
                self.result.assignment_destination.insert(stmt, dst);
            }
        }
        Some(ty)
    }

    fn infere_cond(&mut self, stmt: StmtId, expr: ExprId) {
        if let Some(ty) = self.infere_expr(stmt, expr) {
            self.expect::<false>(expr, None, ty, Cow::Borrowed(&[TyRequirement::Condition]));
        }
    }

    /// Type-checks the arguments of `@(cross(...))`/`@(above(...))`/
    /// `@(timer(...))` -- all real-valued (a watched signal expression, an
    /// optional constant direction, a time, an optional constant period) --
    /// the same self-referential `infere_expr` + `expect` pattern used for
    /// e.g. `laplace`'s numerator/denominator arguments
    /// (`infere_array_arg`). `Event::Global` carries no exprs and is
    /// a no-op here.
    fn infere_event_control(&mut self, stmt: StmtId, event: &Event) {
        let mut exprs = Vec::new();
        event.walk_child_exprs(|e| exprs.push(e));
        for expr in exprs {
            if let Some(ty) = self.infere_expr(stmt, expr) {
                self.expect::<false>(expr, None, ty, Cow::Borrowed(&[TyRequirement::Val(Type::Real)]));
            }
        }
    }

    fn infere_expr(&mut self, stmt: StmtId, expr: ExprId) -> Option<Ty> {
        let ty = match self.body.exprs[expr] {
            Expr::Missing => return None,
            Expr::Path { ref path, port: true } => {
                let port = self.resolve_item_path(stmt, expr, path)?;
                Ty::PortFlow(port)
            }

            Expr::Path { ref path, port: false } => {
                // A whole-array reference pre-resolved as a function-call array argument
                // (Enhancement-18): return its already-recorded array type instead of the
                // bare-array error.
                if self.result.array_var_refs.contains_key(&expr) {
                    return Some(self.result.expr_types[expr].clone());
                }
                if let Some(name) = path.as_ident() {
                    if self.find_bus(&name).is_some()
                        || self.find_var_array(&name).is_some()
                        || self.find_param_array(&name).is_some()
                    {
                        self.result
                            .diagnostics
                            .push(InferenceDiagnostic::BareBusReference { expr, name });
                        return None;
                    }
                }
                match self.resolve_path(stmt, expr, path)? {
                ScopeDefItem::BlockId(_)
                | ScopeDefItem::ModuleId(_)
                | ScopeDefItem::InstantiationId(_) => Ty::Scope,
                ScopeDefItem::NatureId(nature) => Ty::Nature(nature),
                ScopeDefItem::DisciplineId(discipline) => Ty::Discipline(discipline),
                ScopeDefItem::NodeId(node) => Ty::Node(node),
                ScopeDefItem::VarId(var) => Ty::Var(self.db.var_data(var).ty.clone(), var),
                ScopeDefItem::ParamId(param) => Ty::Param(self.db.param_ty(param), param),
                ScopeDefItem::AliasParamId(param) => match self.db.resolve_alias(param)? {
                    Alias::Cycel => return None,
                    Alias::Param(param) => Ty::Param(self.db.param_ty(param), param),
                    Alias::ParamSysFun(param) => {
                        self.result.resolved_calls.insert(expr, ResolvedFun::Param(param));
                        Ty::Val(Type::Real)
                    }
                },
                ScopeDefItem::BranchId(branch) => Ty::Branch(branch),
                ScopeDefItem::BuiltIn(_) | ScopeDefItem::NatureAccess(_) => Ty::BuiltInFunction,

                ScopeDefItem::FunctionId(fun) => Ty::UserFunction(fun),
                ScopeDefItem::FunctionReturn(fun) => Ty::FunctionVar {
                    fun,
                    ty: self.db.function_data(fun).return_ty.clone(),
                    arg: None,
                },
                ScopeDefItem::FunctionArgId(arg) => {
                    let FunctionArgLoc { fun, id } = arg.lookup(self.db.upcast());
                    Ty::FunctionVar {
                        fun,
                        ty: self.db.function_data(fun).args[id].ty.clone(),
                        arg: Some(id),
                    }
                }
                ScopeDefItem::NatureAttrId(attr) => {
                    Ty::NatureAttr(self.db.nature_attr_ty(attr)?, attr)
                }
                ScopeDefItem::ParamSysFun(_) => Ty::Val(Type::Real),
                }
            }

            Expr::BitSelect { ref base, ref indices } => {
                self.infere_bit_select(stmt, expr, base, indices)?
            }

            Expr::BinaryOp { op: None, lhs, rhs } => {
                self.infere_expr(stmt, lhs);
                self.infere_expr(stmt, rhs);
                return None;
            }

            Expr::BinaryOp { lhs, rhs, op: Some(op) } => {
                // Enhancement-333: an integer `/` or `%` by a LITERAL zero has no value
                // and must not reach code generation. LLVM treats `sdiv x, 0` as
                // immediate undefined behaviour and lowers it to poison ->
                // `unreachable` -> a `brk`, so the compiled .osdi killed the host
                // simulator with SIGTRAP and no diagnostic at all, from a model
                // openvaf had accepted with exit 0.
                //
                // Enhancement-286 deliberately let this through, reasoning that "a
                // runtime zero divisor has always been accepted, so a literal one must
                // be too". Both halves of that turned out to be wrong: the literal case
                // is NOT the runtime case (only the literal one is UB the optimiser can
                // exploit), and runtime acceptance is itself target-specific -- AArch64
                // returns a value where x86 raises SIGFPE, and this project ships x86
                // builds for macOS, Linux and Windows. There is no portable value to
                // fold to, so the honest answer is to reject it.
                //
                // LITERAL only, which is exactly the UB surface: a localparam, a
                // parameter, or a derived constant (`3 - 3`) is lowered as a runtime
                // value, so the optimiser never sees a constant-zero divisor and none
                // of those trap (each verified).
                // All three shapes below are the SAME defect: an integer operation whose
                // operands the code generator can see, and whose result LLVM defines as
                // poison. Enhancement-286's comment named all three -- a zero divisor,
                // `i32::MIN / -1`, and a shift distance outside 0..32 -- and declined to
                // fold each one, which is precisely what leaves the poison in the IR.
                match op {
                    BinaryOp::Division | BinaryOp::Remainder => {
                        let is_rem = matches!(op, BinaryOp::Remainder);
                        match self.const_int_expr(rhs, CONST_FOLD_DEPTH) {
                            Some(0) => {
                                self.result.diagnostics.push(
                                    InferenceDiagnostic::DivisionByZero { expr, rhs, is_remainder: is_rem },
                                );
                            }
                            // `i32::MIN / -1` overflows: the true result is 2^31, which
                            // is not representable, and LLVM makes `sdiv` of it poison.
                            Some(-1)
                                if self.const_int_expr(lhs, CONST_FOLD_DEPTH) == Some(i32::MIN) =>
                            {
                                self.result.diagnostics.push(
                                    InferenceDiagnostic::IntegerDivisionOverflow { expr, is_remainder: is_rem },
                                );
                            }
                            _ => {}
                        }
                    }
                    BinaryOp::LeftShift
                    | BinaryOp::RightShift
                    | BinaryOp::ArithmeticLeftShift
                    | BinaryOp::ArithmeticRightShift => {
                        // A Verilog-A `integer` is 32 bit, so only 0..=31 is meaningful;
                        // anything else is poison in LLVM. (At RUNTIME the same distance
                        // is silently masked to 5 bits instead -- a separate wrong-answer
                        // defect that this check does not address.)
                        if let Some(dist) = self.const_int_expr(rhs, CONST_FOLD_DEPTH) {
                            if !(0..32).contains(&dist) {
                                self.result.diagnostics.push(
                                    InferenceDiagnostic::ShiftOutOfRange { expr, rhs, dist },
                                );
                            }
                        }
                    }
                    _ => {}
                }
                self.infere_bin_op(stmt, expr, lhs, rhs, op)?
            }

            Expr::UnaryOp { expr: arg, op: UnaryOp::Identity } => self.infere_expr(stmt, arg)?,
            Expr::UnaryOp { expr: arg, op: UnaryOp::Neg } => {
                let ty = self.infere_expr(stmt, arg)?;
                let variant = self.expect::<false>(
                    arg,
                    Some(expr),
                    ty,
                    Cow::Borrowed(&[
                        TyRequirement::Val(Type::Integer),
                        TyRequirement::Val(Type::Real),
                    ]),
                )?;
                let ty = match variant {
                    0 => Type::Integer,
                    1 => Type::Real,
                    _ => unreachable!(),
                };
                Ty::Val(ty)
            }

            Expr::UnaryOp { expr: arg, op: UnaryOp::BitNegate } => {
                let ty = self.infere_expr(stmt, arg)?;
                // TODO bool
                self.expect::<false>(
                    arg,
                    Some(expr),
                    ty,
                    Cow::Borrowed(&[TyRequirement::Val(Type::Integer)]),
                );
                Ty::Val(Type::Integer)
            }

            Expr::UnaryOp { expr: arg, op: UnaryOp::Not } => {
                let ty = self.infere_expr(stmt, arg)?;
                self.expect::<false>(
                    arg,
                    Some(expr),
                    ty,
                    Cow::Borrowed(&[TyRequirement::Condition]),
                );
                Ty::Val(Type::Bool)
            }

            Expr::Select { cond, then_val, else_val } => {
                self.infere_cond(stmt, cond);
                self.resolve_function_args(
                    stmt,
                    expr,
                    &[then_val, else_val],
                    Cow::Borrowed(TiSlice::from_ref(SignatureData::SELECT)),
                    None,
                )
                .0?
            }

            Expr::Call { ref fun, ref args } => {
                self.infere_fun_call(stmt, expr, fun.as_ref()?, args)?
            }
            Expr::Array(ref args) if args.is_empty() => Ty::Val(Type::EmptyArray),
            Expr::Array(ref args) => self.infere_array(stmt, args)?,
            // Enhancement-34: `{...}` concatenation / `{n{...}}` replication
            Expr::Concat { .. } => self.infere_concat(stmt, expr)?,
            Expr::Literal(Literal::Float(_)) => Ty::Literal(Type::Real),
            Expr::Literal(Literal::Int(_)) => Ty::Literal(Type::Integer),
            // +/- inf can only appear in param bounds.
            // This is checked during ast validation and when it appears it is always correct
            Expr::Literal(Literal::Inf) => {
                if let Some(ty) = &self.expr_stmt_ty {
                    self.result.expr_types[expr] = Ty::Val(ty.clone());
                }
                return None;
            }
            Expr::Literal(Literal::String(_)) => Ty::Literal(Type::String),
        };

        self.result.expr_types[expr] = ty.clone();

        Some(ty)
    }

    fn infere_fun_call(
        &mut self,
        stmt: StmtId,
        expr: ExprId,
        fun: &Path,
        args: &[ExprId],
    ) -> Option<Ty> {
        let def = self.resolve_path(stmt, expr, fun)?;
        match def {
            ScopeDefItem::NatureAccess(access) => {
                self.infere_nature_access(stmt, expr, access, args);
                Some(Ty::Val(Type::Real))
            }
            ScopeDefItem::FunctionId(fun) => self.infere_user_fun_call(stmt, expr, fun, args),
            ScopeDefItem::BuiltIn(builtin) => {
                self.result.resolved_calls.insert(expr, ResolvedFun::BuiltIn(builtin));
                self.infere_builtin(stmt, expr, builtin, args).0
            }
            ScopeDefItem::ParamSysFun(param) => {
                self.result.resolved_calls.insert(expr, ResolvedFun::Param(param));
                if !args.is_empty() {
                    let err = InferenceDiagnostic::ArgCntMismatch {
                        expected: 0,
                        found: args.len(),
                        expr,
                        exact: true,
                    };
                    self.result.diagnostics.push(err);
                }
                Some(Ty::Val(Type::Real))
            }
            found => {
                let name = fun.segments.last().unwrap().to_owned();
                // Enhancement-59: inside an analog function, the function's own
                // name resolves to its return variable, so a recursive call
                // lands here disguised as "found variable" -- diagnose the
                // actual mistake (the LRM forbids recursion) instead.
                if let DefWithBodyId::FunctionId(owner) = self.owner {
                    if self.db.function_data(owner).name == name {
                        self.result
                            .diagnostics
                            .push(InferenceDiagnostic::RecursiveFunctionCall { expr, name });
                        return None;
                    }
                }
                self.result.diagnostics.push(InferenceDiagnostic::PathResolveError {
                    err: PathResolveError::ExpectedItemKind {
                        expected: "a function",
                        found: ResolvedPath::ScopeDefItem(found),
                        name,
                    },
                    expr,
                });
                None
            }
        }
    }

    fn infere_user_fun_call(
        &mut self,
        stmt: StmtId,
        expr: ExprId,
        func: FunctionId,
        args: &[ExprId],
    ) -> Option<Ty> {
        self.result.resolved_calls.insert(expr, ResolvedFun::User { func, limit: false });
        let fun_info = self.db.function_data(func);
        if fun_info.args.len() != args.len() {
            self.result.diagnostics.push(InferenceDiagnostic::ArgCntMismatch {
                expected: fun_info.args.len(),
                found: args.len(),
                expr,
                exact: true,
            });
            return Some(Ty::Val(fun_info.return_ty.clone()));
        }

        // Pre-resolve whole-array arguments (Enhancement-18): a bare array reference passed to an
        // array-typed formal is resolved to its element variables so the generic argument matching
        // accepts it as an array value (rather than emitting the "requires a bit-select" error).
        for (arg_info, &actual) in fun_info.args.iter().zip(args) {
            if let Type::Array { ref ty, len } = arg_info.ty {
                self.pre_resolve_array_call_arg(stmt, actual, ty, len);
            }
        }

        let signature = fun_info
            .args
            .iter()
            .enumerate()
            .map(|(i, arg)| {
                if arg.is_output && !matches!(arg.ty, Type::Array { .. }) {
                    // Output arguments must be variables.
                    TyRequirement::Var(arg.ty.clone())
                } else if arg.is_output
                    && args.get(i).map_or(true, |a| {
                        !self.result.array_var_refs.contains_key(a)
                    })
                {
                    // Enhancement-33: an array output/inout formal needs a caller
                    // *variable* array to write back into. Pre-resolved whole-array
                    // references are typed `Val(Array)` (so a `Var` requirement can't
                    // see them and they take the branch below); anything else — e.g.
                    // an array literal, which has no storage — must be rejected here
                    // instead of silently skipping the writeback.
                    TyRequirement::Var(arg.ty.clone())
                } else {
                    TyRequirement::Val(arg.ty.clone())
                }
            })
            .collect();

        self.resolve_function_args(
            stmt,
            expr,
            args,
            Cow::Owned(TiVec::from(vec![SignatureData {
                args: Cow::Owned(signature),
                return_ty: fun_info.return_ty.clone(),
            }])),
            Some(func),
        )
        .0
    }

    /// Resolves a bare array reference passed as a whole-array function argument to its element
    /// `VarId`s (recorded in `array_var_refs`) and types the argument expression as an array, so it
    /// satisfies an array-typed formal. Leaves the expression untouched (to be diagnosed normally)
    /// if it isn't a caller array of the expected length.
    fn pre_resolve_array_call_arg(&mut self, stmt: StmtId, actual: ExprId, elem_ty: &Type, len: u32) {
        let name = match &self.body.exprs[actual] {
            Expr::Path { path, port: false } => path.as_ident(),
            _ => return,
        };
        let Some(arr) = name.and_then(|n| self.find_var_array(&n)) else { return };
        let Some(elems) = self.array_elem_vars_flat(stmt, actual, &arr) else { return };
        if elems.len() as u32 != len {
            return;
        }
        self.result.array_var_refs.insert(actual, elems);
        self.result.expr_types[actual] =
            Ty::Val(Type::Array { ty: Box::new(elem_ty.clone()), len });
    }

    fn infere_nature_access(
        &mut self,
        stmt: StmtId,
        expr: ExprId,
        access: NatureAccess,
        args: &[ExprId],
    ) {
        // resolve as flow first because we don't yet know if this is a flow or pot access
        // This choice is arbitrary (but must be consistent with the code below
        if !self.infere_builtin(stmt, expr, BuiltIn::flow, args).1 {
            return;
        }

        let nature = access.0.lookup(self.db.upcast()).nature;
        // Now that we know that the arguments are valid actually resolve whether this is flow or
        // pot access
        let access = self.infere_access_kind(nature, expr, args[0]);

        // update resolved_calls in case this is actually a pot and not a flow access
        match access {
            Some(DisciplineAccess::Potential) => {
                self.result.resolved_calls.insert(expr, ResolvedFun::BuiltIn(BuiltIn::potential));
            }

            Some(DisciplineAccess::Flow) => {
                self.result.resolved_calls.insert(expr, ResolvedFun::BuiltIn(BuiltIn::flow));
            }

            None => {
                self.result.resolved_calls.insert(expr, ResolvedFun::InvalidNatureAccess(nature));
            }
        }
    }

    fn infere_access_kind(
        &self,
        nature: NatureId,
        expr: ExprId,
        arg: ExprId,
    ) -> Option<DisciplineAccess> {
        let signature = self.result.resolved_signatures.get(&expr);
        let node = match *signature? {
            NATURE_ACCESS_BRANCH => {
                let branch = self.result.expr_types[arg].unwrap_branch();
                let branch_info = self.db.branch_info(branch)?;
                return branch_info.access(nature, self.db);
            }

            NATURE_ACCESS_NODES | NATURE_ACCESS_NODE_GND => {
                self.result.expr_types[arg].unwrap_node()
            }

            NATURE_ACCESS_PORT_FLOW => self.result.expr_types[arg].unwrap_port_flow(),
            var => unreachable!("{:?}", var),
        };

        let discipline = self.db.node_discipline(node)?;
        self.db.discipline_info(discipline).access(nature, self.db)
    }

    fn infere_builtin(
        &mut self,
        stmt: StmtId,
        expr: ExprId,
        builtin: BuiltIn,
        args: &[ExprId],
    ) -> (Option<Ty>, bool) {
        let info: BuiltinInfo = builtin.into();

        let exact = Some(info.min_args) == info.max_args;
        if args.len() < info.min_args {
            let err = InferenceDiagnostic::ArgCntMismatch {
                expected: info.min_args,
                found: args.len(),
                expr,
                exact,
            };
            self.result.diagnostics.push(err);
            return (default_return_ty(info.signatures), false);
        }

        if info.max_args.map_or(false, |max_args| max_args < args.len()) {
            self.result.diagnostics.push(InferenceDiagnostic::ArgCntMismatch {
                expected: info.min_args,
                found: args.len(),
                expr,
                exact,
            });
            return (default_return_ty(info.signatures), false);
        }

        let mut infere_args = args;
        let signatures = match builtin {
            BuiltIn::ddx => {
                self.infere_ddx(stmt, expr, args[0], args[1]);
                return (Some(Ty::Val(Type::Real)), true);
            }

            BuiltIn::laplace_nd | BuiltIn::laplace_np | BuiltIn::laplace_zd
            | BuiltIn::laplace_zp => {
                return self.infere_laplace(stmt, expr, builtin, args);
            }

            BuiltIn::limit => {
                if args.len() >= 2 {
                    infere_args = &args[0..2];
                }
                Cow::Borrowed(TiSlice::from_ref(info.signatures))
            }

            // Enhancement-40: `$table_model` is variadic so tables of ANY dimension
            // work. This arm owns EVERY table_model call (the generic varargs
            // fallthrough below would resize-and-truncate the listed signatures,
            // making 2-arg calls ambiguous): the 1-D inline-array form and the small
            // file forms resolve against the listed signatures unchanged; N-D file
            // forms (>= 4 non-array arguments — note a 5-argument call is ambiguous
            // by arity alone: 3-D+file+ctrl vs 4-D+file) get the exact signature
            // `[Real x ndim, Literal(String)(, Literal(String))]` synthesised from
            // the argument SHAPES, where the trailing string literals are the
            // data-file name and the optional control string.
            // Enhancement-389: the runtime-array form `$table_model(x, xs, ys[, "ctrl"])`
            // (LRM p274). Like `laplace_*`, it cannot use the generic
            // `resolve_function_args` path: that calls `infere_expr` on every argument,
            // which rejects a bare array-variable reference with "requires a bit-select"
            // before `infere_array_arg` can special-case it.
            BuiltIn::table_model
                if args.len() >= 3 && self.is_bare_array_ref(args[1]) =>
            {
                return self.infere_table_model_runtime(stmt, expr, args);
            }

            BuiltIn::table_model => {
                let is_arr =
                    args.len() >= 2 && matches!(self.body.exprs[args[1]], Expr::Array(_));
                if is_arr || args.len() < 4 {
                    Cow::Borrowed(TiSlice::from_ref(info.signatures))
                } else {
                    let is_str = |e: ExprId| {
                        matches!(self.body.exprs[e], Expr::Literal(Literal::String(_)))
                    };
                    let last = args.len() - 1;
                    let n_str = if is_str(args[last]) && is_str(args[last - 1]) { 2 } else { 1 };
                    let ndim = args.len() - n_str;
                    let mut sig_args = vec![TyRequirement::Val(Type::Real); ndim];
                    sig_args.push(TyRequirement::Literal(Type::String));
                    if n_str == 2 {
                        sig_args.push(TyRequirement::Literal(Type::String));
                    }
                    Cow::Owned(TiVec::from(vec![SignatureData {
                        args: Cow::Owned(sig_args),
                        return_ty: Type::Real,
                    }]))
                }
            }

            _ if info.max_args.is_none() => {
                let mut signatures = Vec::from(info.signatures);
                for sig in &mut signatures {
                    sig.args.to_mut().resize(args.len(), TyRequirement::AnyVal)
                }
                Cow::Owned(TiVec::from(signatures))
            }
            _ => Cow::Borrowed(TiSlice::from_ref(info.signatures)),
        };

        debug_assert_ne!(&signatures.raw, &[]);

        let (ty, valid) = if let (Some(ty), valid) =
            self.resolve_function_args(stmt, expr, infere_args, signatures, None)
        {
            (ty, valid)
        } else {
            return (default_return_ty(info.signatures), false);
        };

        match builtin {
            BuiltIn::limit => self.infere_limit(stmt, expr, args),
            BuiltIn::write
            | BuiltIn::display
            | BuiltIn::strobe
            | BuiltIn::monitor
            | BuiltIn::debug
            | BuiltIn::warning
            | BuiltIn::error
            | BuiltIn::info
            | BuiltIn::fatal
            // Enhancement-313: the file ($fdisplay/$fwrite/$fstrobe/$fmonitor/
            // $fdebug) and string ($swrite/$sformat) format tasks were NOT
            // routed through infere_display, so their format arguments never got
            // the type check + implicit cast the console tasks record here. A
            // %g/%e/%f/%r conversion fed an integer therefore stayed integer,
            // while the callback types its parameter from the conversion (double
            // for %g) -- so lowering passed a raw i32 to a double parameter,
            // producing invalid LLVM IR (caught by the verifier debug_assert; a
            // malformed .osdi shipped silently in release). infere_display scans
            // for string-LITERAL format strings, so the leading file descriptor
            // (integer) or destination (string variable) argument is naturally
            // skipped and the real format string is found.
            | BuiltIn::fdisplay
            | BuiltIn::fwrite
            | BuiltIn::fstrobe
            | BuiltIn::fmonitor
            | BuiltIn::fdebug
            | BuiltIn::swrite
            | BuiltIn::sformat => self.infere_display(stmt, args),

            _ => (),
        }

        (Some(ty), valid)
    }

    fn check_display_dynamic_arg(&mut self, fmt_expr: ExprId, arg: Option<ExprId>, off: TextSize) {
        let arg = if let Some(arg) = arg {
            arg
        } else {
            self.result.diagnostics.push(InferenceDiagnostic::MissingFmtArg {
                fmt_lit: fmt_expr,
                lit_range: TextRange::at(off, 1u32.into()),
            });

            return;
        };
        match self.result.expr_types[arg].to_value() {
            Some(Type::Integer) => (),

            Some(ty) if ty.is_convertible_to(&Type::Integer) => {
                self.result.casts.insert(arg, Type::Integer);
            }
            _ => self.result.diagnostics.push(InferenceDiagnostic::DisplayTypeMismatch {
                err: TypeMismatch {
                    expected: Cow::Borrowed(&[TyRequirement::Val(Type::Integer)]),
                    found_ty: self.result.expr_types[arg].clone(),
                    expr: arg,
                },
                fmt_lit: fmt_expr,
                lit_range: TextRange::at(off, 1u32.into()),
                lint_ctx: None,
            }),
        }
    }

    fn check_display_arg_val(
        &mut self,
        stmt: StmtId,
        fmt_expr: ExprId,
        arg: Option<ExprId>,
        lit_range: TextRange,
        ty: Type,
    ) {
        let arg = if let Some(arg) = arg {
            arg
        } else {
            self.result
                .diagnostics
                .push(InferenceDiagnostic::MissingFmtArg { fmt_lit: fmt_expr, lit_range });

            return;
        };
        match self.result.expr_types[arg].to_value() {
            Some(ty_) if ty_ == ty => (),

            Some(ty_) if ty_.is_convertible_to(&ty) => {
                self.result.casts.insert(arg, ty);
            }

            Some(ty_) if ty_.is_assignable_to(&ty) => {
                self.result.casts.insert(arg, ty.clone());
                self.result.diagnostics.push(InferenceDiagnostic::DisplayTypeMismatch {
                    err: TypeMismatch {
                        expected: Cow::Owned(vec![TyRequirement::Val(ty)]),
                        found_ty: self.result.expr_types[arg].clone(),
                        expr: arg,
                    },
                    fmt_lit: fmt_expr,
                    lit_range,
                    lint_ctx: Some(stmt),
                })
            }
            _ => self.result.diagnostics.push(InferenceDiagnostic::DisplayTypeMismatch {
                err: TypeMismatch {
                    expected: Cow::Owned(vec![TyRequirement::Val(ty)]),
                    found_ty: self.result.expr_types[arg].clone(),
                    expr: arg,
                },
                fmt_lit: fmt_expr,
                lit_range,
                lint_ctx: None,
            }),
        }
    }

    fn infere_display(&mut self, stmt: StmtId, args: &[ExprId]) {
        let mut i = 0;
        while let Some(fmt_expr) = args.get(i) {
            i += 1;
            if let Expr::Literal(Literal::String(ref lit)) = self.body.exprs[*fmt_expr] {
                let mut chars = lit.char_indices();
                while let Some((start, c)) = chars.next() {
                    if c == '%' {
                        let pos = chars.next();
                        let mut end: TextSize = (start + 2).try_into().unwrap();
                        let ty = match pos.map(|(_, c)| c) {
                            Some('%' | 'm' | 'M' | 'l' | 'L') => continue, // escape sequences, always correct
                            Some('d' | 'D' | 'h' | 'H' | 'o' | 'O' | 'b' | 'B' | 'c' | 'C') => {
                                Type::Integer
                            }
                            Some('s' | 'S') => Type::String,
                            _ => {
                                let res = parse_fmt_spec(start as u32, *fmt_expr, pos, &mut chars);
                                if let Some(err) = res.err {
                                    self.result.diagnostics.push(err);
                                    i += 1 + res.dynamic_args.len();
                                    continue;
                                }

                                for pos in res.dynamic_args {
                                    self.check_display_dynamic_arg(
                                        *fmt_expr,
                                        args.get(i).copied(),
                                        pos,
                                    );
                                    i += 1;
                                }

                                end = res.end;
                                // Enhancement-71: flags/width/precision are
                                // legal for every conversion; the argument
                                // type follows the conversion character.
                                match res.conversion {
                                    'd' | 'D' | 'h' | 'H' | 'o' | 'O' | 'b' | 'B' | 'c' | 'C' => {
                                        Type::Integer
                                    }
                                    's' | 'S' => Type::String,
                                    _ => Type::Real,
                                }
                            }
                        };

                        let arg = args.get(i).copied();
                        let range = TextRange::new(start.try_into().unwrap(), end);
                        self.check_display_arg_val(stmt, *fmt_expr, arg, range, ty);

                        i += 1;
                    }
                }
            }
        }
    }
    fn infere_limit(&mut self, stmt: StmtId, expr: ExprId, args: &[ExprId]) {
        let sig = if let Some(sig) = self.result.resolved_signatures.get(&expr) {
            *sig
        } else {
            // already reported an error no need to repeat
            return;
        };

        let probe = args[0];
        if self.result.expr_types[probe] != Ty::Val(Type::Err)
            && !matches!(
                self.result.resolved_calls.get(&probe),
                Some(ResolvedFun::BuiltIn(BuiltIn::potential | BuiltIn::flow))
            )
        {
            self.result.diagnostics.push(InferenceDiagnostic::ExpectedProbe { e: probe })
        }

        if args.len() == 1 {
            // only one argument (no limit function specified)
        } else if let Some(Ty::UserFunction(func)) = self.result.expr_types.get(args[1]).cloned() {
            debug_assert_eq!(sig, LIMIT_USER_FUNCTION);
            let fun_info = self.db.function_data(func);

            // user-function needs two extra arguments but $limit also accepts two arguments that are
            // not passed directly to the function so these must just be equal
            if fun_info.args.len() != args.len() {
                self.result.diagnostics.push(InferenceDiagnostic::ArgCntMismatch {
                    expected: fun_info.args.len(),
                    found: args.len(),
                    expr,
                    exact: true,
                });
                return;
            }

            let output_args: Vec<_> = fun_info
                .args
                .iter_enumerated()
                .filter_map(|(id, info)| info.is_output.then_some(id))
                .collect();

            let invalid_ret = !matches!(fun_info.return_ty, Type::Real | Type::Err);
            let invalid_arg0 = !matches!(fun_info.args.raw[0].ty, Type::Real | Type::Err);
            let invalid_arg1 = !matches!(fun_info.args.raw[1].ty, Type::Real | Type::Err);

            if invalid_ret || invalid_arg0 || invalid_arg1 || !output_args.is_empty() {
                self.result.diagnostics.push(InferenceDiagnostic::InvalidLimitFunction {
                    expr,
                    func,
                    invalid_arg0,
                    invalid_arg1,
                    invalid_ret,
                    output_args,
                })
            }

            let signature = fun_info.args.raw[2..]
                .iter()
                .map(|arg| TyRequirement::Val(arg.ty.clone()))
                .collect();

            self.resolve_function_args(
                stmt,
                expr,
                &args[2..],
                Cow::Owned(TiVec::from(vec![SignatureData {
                    args: Cow::Owned(signature),
                    return_ty: fun_info.return_ty.clone(),
                }])),
                Some(func),
            );

            self.result.resolved_calls.insert(expr, ResolvedFun::User { func, limit: true });
        } else if sig == LIMIT_BUILTIN_FUNCTION {
            self.resolve_function_args(
                stmt,
                expr,
                &args[2..],
                Cow::Owned(TiVec::from(vec![SignatureData {
                    args: Cow::Owned(vec![TyRequirement::Val(Type::Real); args.len() - 2]),
                    return_ty: Type::Real,
                }])),
                None,
            );
        }
    }

    fn infere_ddx(&mut self, stmt: StmtId, expr: ExprId, val: ExprId, unknown: ExprId) {
        if let Some(ty) = self.infere_expr(stmt, val) {
            // Enhancement-313: record the "must be real" requirement (and its
            // integer->real cast) on `val` -- the argument being differentiated --
            // NOT on `expr`, the ddx call itself. `expr` already has type Real, so
            // an integer `val` (e.g. `ddx(n, V(b))`) inserted a Real cast onto a
            // Real-typed expression; `needs_cast` then saw src == dst == Real and
            // tripped its debug_assert, and the release build crashed downstream.
            // Casting `val` instead coerces the integrand to real where it belongs.
            self.expect::<false>(val, None, ty, Cow::Borrowed(&[TyRequirement::Val(Type::Real)]));
        }

        let ty = self.infere_expr(stmt, unknown);
        if ty.is_some() {
            let (call, signature) = if let (Some(ResolvedFun::BuiltIn(fun)), Some(signature)) = (
                self.result.resolved_calls.get(&unknown),
                self.result.resolved_signatures.get(&unknown),
            ) {
                (*fun, *signature)
            } else {
                // `unknown` did not resolve to a probe access function (V()/I()/
                // $temperature). If it is not even a call (a literal like `ddx(f, 5)`,
                // a plain variable, ...) it is definitely an invalid ddx unknown -- emit
                // the diagnostic. (A call that failed to resolve already has its own
                // error, so don't double-report.) This guard previously tested `expr`
                // -- the ddx call itself, which is ALWAYS a Call -- so the diagnostic was
                // dead code and `ddx(f, <non-probe>)` slipped through to hir_lower, where
                // unwrap_node()/unwrap_param() panicked.
                if !matches!(&self.body.exprs[unknown], Expr::Call { .. }) {
                    self.result
                        .diagnostics
                        .push(InferenceDiagnostic::InvalidUnknown { e: unknown });
                }
                return;
            };

            let signature = match (call, signature) {
                (BuiltIn::potential, NATURE_ACCESS_NODES) => {
                    self.result
                        .diagnostics
                        .push(InferenceDiagnostic::NonStandardUnknown { e: unknown, stmt });
                    DDX_POT_DIFF
                }
                (BuiltIn::potential, NATURE_ACCESS_NODE_GND) => DDX_POT,
                (BuiltIn::flow, NATURE_ACCESS_BRANCH) => DDX_FLOW,
                (BuiltIn::temperature, _) => {
                    self.result
                        .diagnostics
                        .push(InferenceDiagnostic::NonStandardUnknown { e: unknown, stmt });
                    DDX_TEMP
                }
                _ => {
                    self.result
                        .diagnostics
                        .push(InferenceDiagnostic::InvalidUnknown { e: unknown });
                    return;
                }
            };

            self.result.resolved_signatures.insert(expr, signature);
        }
    }

    /// Type-checks a `laplace_*(in, num, den[, tol|nature])` call. `num`/`den` are handled by
    /// `infere_array_arg` (array literal *or* bare array-variable reference, see there);
    /// this can't go through the generic `resolve_function_args` machinery (used by every other
    /// builtin) because that always calls `infere_expr` on every argument, which would reject a
    /// bare array-variable reference with `BareBusReference` before `infere_array_arg`
    /// gets a chance to special-case it.
    fn infere_laplace(
        &mut self,
        stmt: StmtId,
        expr: ExprId,
        kind: BuiltIn,
        args: &[ExprId],
    ) -> (Option<Ty>, bool) {
        let mut valid = true;

        if let Some(ty) = self.infere_expr(stmt, args[0]) {
            self.expect::<false>(args[0], None, ty, Cow::Borrowed(&[TyRequirement::Val(Type::Real)]));
        } else {
            valid = false;
        }

        // In the `*_np`/`*_zp` forms the denominator argument holds *poles* (roots), not
        // polynomial coefficients; an empty pole list is legal (denominator polynomial 1).
        let den_is_roots = matches!(kind, BuiltIn::laplace_np | BuiltIn::laplace_zp);

        for (i, &arg) in args[1..3].iter().enumerate() {
            let is_den = i == 1; // args[1] = numerator, args[2] = denominator
            match self.infere_array_arg(stmt, arg) {
                None => valid = false,
                Some(ty) => {
                    // A num/den (pole/zero) argument must be a real coefficient vector
                    // (LRM 9.19): a real/integer array, or a scalar accepted as a length-1
                    // vector. `infere_array_arg` is a shared helper (also used by `case`
                    // discriminants/items and concatenations) whose fallback just returns
                    // the inferred type, so a *net* reference (`laplace_nd(x, 1.0, p)`), a
                    // branch, or a string slips through here. Left unchecked it reaches
                    // `hir_lower`, which lowers the coefficient elements as values and panics
                    // resolving a bare net reference ("invalid HIR: path .. was not
                    // resolved"). Require a numeric value/array here so an invalid
                    // coefficient raises the normal "expected real value but found .."
                    // type-mismatch instead — the same diagnostic every ordinary value
                    // context (and the `laplace_*` input argument) already produces.
                    let val = ty.to_value();
                    let is_coeff = match &val {
                        Some(Type::Real) | Some(Type::Integer) | Some(Type::EmptyArray) => true,
                        Some(Type::Array { ty, .. }) => matches!(**ty, Type::Real | Type::Integer),
                        _ => false,
                    };
                    // An empty *direct* denominator (`'{}`) has no leading coefficient: the
                    // state-space realization computes `den.len() - 1` and reads `den[n]`,
                    // which underflows / indexes out of bounds and crashes. An empty
                    // numerator is fine (H(s) = 0), and an empty pole list is handled by
                    // `den_is_roots` above, so reject only this one shape.
                    let empty_direct_den =
                        is_den && !den_is_roots && matches!(val, Some(Type::EmptyArray));
                    if !is_coeff || empty_direct_den {
                        self.result.diagnostics.push(
                            TypeMismatch {
                                expected: Cow::Owned(vec![TyRequirement::Val(Type::Real)]),
                                found_ty: ty,
                                expr: arg,
                            }
                            .into(),
                        );
                        valid = false;
                    }
                }
            }
        }

        // optional trailing tolerance (real) or nature argument; still required to be a
        // constant expression (validated separately in hir_ty::validation::body), since unlike
        // num/den it isn't used by the state-space realization at all (see Enhancement-4.md §1.3)
        let signature = if let Some(&tol_or_nature) = args.get(3) {
            match self.infere_expr(stmt, tol_or_nature) {
                Some(ty @ Ty::Nature(_)) => {
                    self.result.expr_types[tol_or_nature] = ty;
                    LAPLACE_NATURE_TOL
                }
                Some(ty) => {
                    self.expect::<false>(
                        tol_or_nature,
                        None,
                        ty,
                        Cow::Borrowed(&[TyRequirement::Val(Type::Real), TyRequirement::Nature]),
                    );
                    LAPALCE_TOL
                }
                None => {
                    valid = false;
                    LAPALCE_TOL
                }
            }
        } else {
            LAPLACE_NO_TOL
        };
        self.result.resolved_signatures.insert(expr, signature);

        (Some(Ty::Val(Type::Real)), valid)
    }

    /// Type-checks a single `num`/`den` (or `zero`/`pole`) argument of a `laplace_*` call.
    /// Accepts two shapes:
    /// - an array-literal expression (`'{...}'`/`{...}`), handled exactly as before via
    ///   `infere_array`;
    /// - a bare reference to a module-body array variable (`coeffs` for `real [0:n] coeffs;`,
    ///   declared via Enhancement-4's array-variable support) — equivalent to writing out
    ///   `'{coeffs[0], coeffs[1], ..., coeffs[n]}'` by hand. The expanded `VarId`s (ascending
    ///   declared-index order) are recorded in `InferenceResult::array_var_refs` for
    ///   `hir_lower` to read directly via `coeffs[i]`-equivalent variable reads, with no MIR
    ///   array-value representation needed (mirroring how literal-array elements are lowered).
    ///
    /// Anything else falls back to ordinary `infere_expr`, preserving the normal
    /// "expected array" diagnostic from signature mismatch (e.g. a plain scalar argument, or a
    /// genuine typo that doesn't name a known array variable).
    /// Enhancement-389: is this argument a bare reference to an array variable
    /// (`xs` for `real xs[0:2];`), as opposed to a literal, a file name or a scalar?
    /// Decided syntactically, before any inference runs, so it can select the
    /// argument-checking path.
    fn is_bare_array_ref(&mut self, arg: ExprId) -> bool {
        if let Expr::Path { ref path, port: false } = self.body.exprs[arg] {
            if let Some(name) = path.as_ident() {
                return self.find_var_array(&name).is_some();
            }
        }
        false
    }

    /// Type-checks `$table_model(x, xs, ys[, "ctrl"])` with runtime array data.
    ///
    /// `xs`/`ys` go through `infere_array_arg` (which records their element `VarId`s
    /// in `array_var_refs` for `hir_lower`); `x` is an ordinary real value and the
    /// optional control string is a string literal, exactly as in the file form.
    fn infere_table_model_runtime(
        &mut self,
        stmt: StmtId,
        expr: ExprId,
        args: &[ExprId],
    ) -> (Option<Ty>, bool) {
        let mut valid = true;

        if let Some(ty) = self.infere_expr(stmt, args[0]) {
            self.expect::<false>(
                args[0],
                None,
                ty,
                Cow::Borrowed(&[TyRequirement::Val(Type::Real)]),
            );
        } else {
            valid = false;
        }

        // Both data arguments must be arrays. `xs` is a bare array reference by
        // construction (that is what selected this path); `ys` is checked here, so
        // `$table_model(x, xs, 1.0)` still gets an ordinary type-mismatch rather than
        // silently interpolating a one-element table.
        for &arg in &args[1..3] {
            match self.infere_array_arg(stmt, arg) {
                None => valid = false,
                Some(ty) => {
                    let ok = matches!(
                        ty.to_value(),
                        Some(Type::Array { .. }) | Some(Type::EmptyArray)
                    );
                    if !ok {
                        self.expect::<false>(
                            arg,
                            None,
                            ty,
                            Cow::Owned(vec![TyRequirement::Val(Type::Array {
                                ty: Box::new(Type::Real),
                                len: 0,
                            })]),
                        );
                        valid = false;
                    }
                }
            }
        }

        if let Some(&ctrl) = args.get(3) {
            if let Some(ty) = self.infere_expr(stmt, ctrl) {
                self.expect::<false>(
                    ctrl,
                    None,
                    ty,
                    Cow::Borrowed(&[TyRequirement::Literal(Type::String)]),
                );
            } else {
                valid = false;
            }
        }

        if args.len() > 4 {
            self.result.diagnostics.push(InferenceDiagnostic::ArgCntMismatch {
                expected: 4,
                found: args.len(),
                expr,
                exact: false,
            });
            valid = false;
        }

        (Some(Ty::Val(Type::Real)), valid)
    }

    fn infere_array_arg(&mut self, stmt: StmtId, arg: ExprId) -> Option<Ty> {
        if let Expr::Array(ref elems) = self.body.exprs[arg] {
            let elems = elems.clone();
            let ty = if elems.is_empty() {
                Ty::Val(Type::EmptyArray)
            } else {
                self.infere_array(stmt, &elems)?
            };
            self.result.expr_types[arg] = ty.clone();
            return Some(ty);
        }

        if let Expr::Path { ref path, port: false } = self.body.exprs[arg] {
            if let Some(name) = path.as_ident() {
                if let Some(arr) = self.find_var_array(&name) {
                    let (lo, hi) = arr.min_max();
                    let mut vars = Vec::with_capacity((hi - lo + 1) as usize);
                    for bit in lo..=hi {
                        let synth_path = Path::new_ident(arr.bit_name(bit));
                        match self.resolve_path(stmt, arg, &synth_path)? {
                            ScopeDefItem::VarId(var) => vars.push(var),
                            _ => return None,
                        }
                    }
                    let len = vars.len() as u32;
                    // Enhancement-33: type the array from its actual element variables.
                    // The element type was hardcoded `Real`, which let an *integer*
                    // array reach lowering typed as real — an integer-array `case`
                    // discriminant then compared its i32 elements with `feq`
                    // ("invalid int operation feq" panic in const-eval).
                    let elem_ty = self.db.var_data(vars[0]).ty.clone();
                    self.result.array_var_refs.insert(arg, vars);
                    let ty = Ty::Val(Type::Array { ty: Box::new(elem_ty), len });
                    self.result.expr_types[arg] = ty.clone();
                    return Some(ty);
                }
            }
        }

        self.infere_expr(stmt, arg)
    }

    /// Enhancement-34: evaluates a `{n{...}}` replication count. Must be a positive
    /// compile-time integer literal; `None` (no replication) counts as 1.
    /// Enhancement-325: the largest number of elements a `{...}` concatenation /
    /// `{n{...}}` replication may materialize. Enhancement-314 capped the replication
    /// COUNT at 2^20, but the count is only one factor of the final size: nesting
    /// (`{1<<20{{1<<20{1.0}}}}` = 2^40) or a long operand list multiplies past it. The
    /// materialized size is what actually costs -- it is the array length (a u32, which
    /// overflowed: a panic under overflow-checks, a silent wrap to 0 in release) and,
    /// for strings, the ARITY of a generated LLVM callback (200000 operands hung the
    /// compiler in LLVM, and crashed the shipped build with a SIGSEGV-class failure).
    /// No legitimate model materializes more than 2^20 elements from one literal.
    fn concat_rep_count(&mut self, rep: Option<ExprId>) -> Option<u32> {
        let Some(rep) = rep else { return Some(1) };
        if let Expr::Literal(Literal::Int(n)) = self.body.exprs[rep] {
            // Enhancement-314: a `{N{...}}` replication materializes N copies of its
            // operands at compile time (`lower_string_concat`/`infere_concat` build an
            // N*|elems|-element list and, for strings, an N*|elems|-char format string).
            // A huge literal count -- e.g. `{'d999999999{"x"}}` -- otherwise allocated
            // gigabytes and HUNG the compiler (a shipped DoS on ~1 line of source). Cap
            // it: no legitimate source-level replication needs more than 2^20 copies, and
            // the runtime object would be absurd anyway. Reject the abusive count cleanly.
            const MAX_REP: i32 = 1 << 20;
            if (1..=MAX_REP).contains(&n) {
                self.result.expr_types[rep] = Ty::Val(Type::Integer);
                return Some(n as u32);
            }
        }
        self.result.diagnostics.push(InferenceDiagnostic::InvalidReplicationCount { expr: rep });
        None
    }

    /// Enhancement-34: types a `{...}` concatenation / `{n{...}}` replication.
    ///
    /// String mode: if any operand is a string, all operands must be strings and the
    /// result is a `String` (the runtime concatenation of the operands, repeated `n`
    /// times). Otherwise the result is a flat 1-D array: scalar operands contribute one
    /// element, array operands (literals, whole-array variables — registered in
    /// `array_var_refs` by `infere_array_arg` — or nested concatenations) contribute
    /// their elements in order. The element type is `real` if any operand is real
    /// (integer *scalars* are cast; an integer *array* mixed into a real concatenation
    /// is a type error, since array elements have no per-element cast machinery).
    fn infere_concat(&mut self, stmt: StmtId, expr: ExprId) -> Option<Ty> {
        let (rep, elems) = match self.body.exprs[expr] {
            Expr::Concat { rep, ref elems } => (rep, elems.clone()),
            _ => unreachable!("infere_concat on a non-concat expression"),
        };
        if elems.is_empty() {
            self.result.diagnostics.push(InferenceDiagnostic::EmptyConcat { expr });
            return None;
        }
        let rep_cnt = self.concat_rep_count(rep)?;

        let mut tys: Vec<Option<Ty>> = Vec::with_capacity(elems.len());
        for &e in &elems {
            tys.push(self.infere_array_arg(stmt, e));
        }

        // string concatenation?
        if tys.iter().any(|t| t.as_ref().and_then(|t| t.to_value()) == Some(Type::String)) {
            for (&e, ty) in elems.iter().zip(&tys) {
                if let Some(ty) = ty {
                    if ty.to_value() != Some(Type::String) {
                        self.result.diagnostics.push(
                            TypeMismatch {
                                expected: Cow::Owned(vec![TyRequirement::Val(Type::String)]),
                                found_ty: ty.clone(),
                                expr: e,
                            }
                            .into(),
                        );
                    }
                }
            }
            // Enhancement-325: a string concatenation is materialized as ONE generated
            // LLVM callback per operand copy -- `lower_string_concat` builds an
            // `elems.len() * rep_cnt` operand list AND a format string of that many
            // "%s", which becomes the callback's ARITY. `{200000{"x"}}` therefore hung
            // the compiler inside LLVM (and crashed the shipped build). Bound the
            // materialized operand count, not just the replication factor.
            let flat = (elems.len() as u64).saturating_mul(rep_cnt as u64);
            if flat > MAX_CONCAT_STR_OPERANDS {
                self.result.diagnostics.push(InferenceDiagnostic::ConcatTooLarge {
                    expr,
                    elems: flat,
                    limit: MAX_CONCAT_STR_OPERANDS,
                });
                return None;
            }
            return Some(Ty::Val(Type::String));
        }

        // numeric: flatten scalars + arrays
        let mut any_real = false;
        let mut total: u64 = 0;
        for (&e, ty) in elems.iter().zip(&tys) {
            match ty.as_ref().and_then(|t| t.to_value()) {
                Some(Type::Real) => {
                    any_real = true;
                    total += 1;
                }
                Some(Type::Integer) => total += 1,
                Some(Type::Array { ty: ref ety, len }) => {
                    if **ety == Type::Real {
                        any_real = true;
                    }
                    // Enhancement-325: u64 + saturating, so a long operand list cannot
                    // wrap the running total before the cap below is consulted.
                    total = total.saturating_add(len as u64);
                }
                _ => {
                    if let Some(ty) = ty {
                        self.result.diagnostics.push(
                            TypeMismatch {
                                expected: Cow::Borrowed(&[TyRequirement::AnyVal]),
                                found_ty: ty.clone(),
                                expr: e,
                            }
                            .into(),
                        );
                    }
                    return None;
                }
            }
        }

        let elem = if any_real { Type::Real } else { Type::Integer };
        for (&e, ty) in elems.iter().zip(&tys) {
            match ty.as_ref().and_then(|t| t.to_value()) {
                // integer scalar promoted into a real concatenation: ordinary cast
                Some(Type::Integer) if elem == Type::Real => {
                    self.result.casts.insert(e, Type::Real);
                }
                // integer array mixed into a real concatenation: no per-element casts
                Some(Type::Array { ty: ref ety, len }) if **ety != elem => {
                    self.result.diagnostics.push(
                        TypeMismatch {
                            expected: Cow::Owned(vec![TyRequirement::Val(Type::Array {
                                ty: Box::new(elem.clone()),
                                len,
                            })]),
                            found_ty: ty.clone().unwrap(),
                            expr: e,
                        }
                        .into(),
                    );
                    return None;
                }
                _ => (),
            }
        }

        // Enhancement-325: `total * rep_cnt` was an unchecked u32 multiply -- it panicked
        // under overflow-checks and WRAPPED in the shipped release (2^20 * 2^20 = 2^40
        // wrapped to 0, yielding a confusing "expected real[0:2], found real[0:0]"
        // instead of a real diagnostic). Compute in u64, bound the materialized size,
        // and only then narrow to the u32 array length.
        let flat = total.saturating_mul(rep_cnt as u64);
        if flat > MAX_CONCAT_ELEMS {
            self.result.diagnostics.push(InferenceDiagnostic::ConcatTooLarge {
                expr,
                elems: flat,
                limit: MAX_CONCAT_ELEMS,
            });
            return None;
        }
        Some(Ty::Val(Type::Array { ty: Box::new(elem), len: flat as u32 }))
    }

    /// Enhancement-34: expands a (typed) `{...}` concatenation into one source per
    /// flattened element for an array assignment — `ConcatSrc::Var` for the elements of
    /// whole-array variable operands (copied), `ConcatSrc::Expr` for scalar operands and
    /// aggregate-literal leaves (lowered and assigned; integer scalars are cast when the
    /// destination is real). Returns `false` (with a diagnostic) on an element-type
    /// conflict with the destination.
    fn concat_sources(&mut self, val: ExprId, want: &Type, out: &mut Vec<ConcatSrc>) -> bool {
        let (rep, elems) = match self.body.exprs[val] {
            Expr::Concat { rep, ref elems } => (rep, elems.clone()),
            _ => unreachable!("concat_sources on a non-concat expression"),
        };
        let rep_cnt = self.concat_rep_count(rep).unwrap_or(1);

        let mut unit: Vec<ConcatSrc> = Vec::new();
        for &e in &elems {
            if let Some(vars) = self.result.array_var_refs.get(&e).cloned() {
                let ety = vars
                    .first()
                    .map(|&v| self.db.var_data(v).ty.clone())
                    .unwrap_or(Type::Err);
                if &ety != want {
                    self.result.diagnostics.push(
                        TypeMismatch {
                            expected: Cow::Owned(vec![TyRequirement::Val(Type::Array {
                                ty: Box::new(want.clone()),
                                len: vars.len() as u32,
                            })]),
                            found_ty: self.result.expr_types[e].clone(),
                            expr: e,
                        }
                        .into(),
                    );
                    return false;
                }
                unit.extend(vars.into_iter().map(ConcatSrc::Var));
            } else if matches!(self.body.exprs[e], Expr::Concat { .. }) {
                if !self.concat_sources(e, want, &mut unit) {
                    return false;
                }
            } else if matches!(self.body.exprs[e], Expr::Array(_)) {
                for leaf in self.flatten_array_literal(e) {
                    self.cast_scalar_concat_leaf(leaf, want);
                    unit.push(ConcatSrc::Expr(leaf));
                }
            } else {
                self.cast_scalar_concat_leaf(e, want);
                unit.push(ConcatSrc::Expr(e));
            }
        }
        for _ in 0..rep_cnt {
            out.extend(unit.iter().copied());
        }
        true
    }

    /// Records an `integer -> real` cast for a scalar concatenation leaf when the
    /// destination element type is real (mirrors the aggregate-literal Case 1 casts).
    fn cast_scalar_concat_leaf(&mut self, e: ExprId, want: &Type) {
        if *want == Type::Real
            && self.result.expr_types[e].to_value() == Some(Type::Integer)
        {
            self.result.casts.insert(e, Type::Real);
        }
    }

    fn infere_array(&mut self, stmt: StmtId, args: &[ExprId]) -> Option<Ty> {
        let infere_value_ty = |sel: &mut Self, arg| -> Option<Type> {
            sel.infere_expr(stmt, arg).and_then(|ty| {
                let res = ty.to_value();
                if res.is_none() {
                    sel.result.diagnostics.push(
                        TypeMismatch {
                            expected: Cow::Borrowed(&[TyRequirement::AnyVal]),
                            found_ty: ty,
                            expr: arg,
                        }
                        .into(),
                    )
                }
                res
            })
        };

        let mut iter = args.iter();
        let (ty, first_expr) = loop {
            let arg = match iter.next() {
                Some(arg) => arg,
                None => return None,
            };

            if let Some(ty) = infere_value_ty(self, *arg) {
                break (ty, *arg);
            }
        };

        let ty = iter.fold(ty, |ty, arg| {
            let arg_ty = match infere_value_ty(self, *arg) {
                Some(arg_ty) => arg_ty,
                None => return ty,
            };
            match ty.union(&arg_ty) {
                Some(ty) => ty,
                None => {
                    self.result.diagnostics.push(
                        ArrayTypeMismatch {
                            expected: ty.clone(),
                            found_ty: arg_ty,
                            found_expr: *arg,
                            expected_expr: first_expr,
                        }
                        .into(),
                    );
                    ty
                }
            }
        });

        for arg in args {
            if let Some(arg_ty) = self.result.expr_types[*arg].to_value() {
                if arg_ty != ty {
                    self.result.casts.insert(*arg, ty.clone());
                }
            }
        }

        Some(Ty::Val(Type::Array { ty: Box::new(ty), len: args.len() as u32 }))
    }

    fn infere_bin_op(
        &mut self,
        stmt: StmtId,
        expr: ExprId,
        lhs: ExprId,
        rhs: ExprId,
        op: BinaryOp,
    ) -> Option<Ty> {
        let signatures = match op {
            BinaryOp::BooleanOr | BinaryOp::BooleanAnd => &[SignatureData::CONDITIONAL_BIN_OP],

            BinaryOp::LesserEqualTest
            | BinaryOp::GreaterEqualTest
            | BinaryOp::LesserTest
            | BinaryOp::GreaterTest => SignatureData::RELATIONAL_COMPARISON,

            BinaryOp::Addition
            | BinaryOp::Multiplication
            | BinaryOp::Subtraction
            | BinaryOp::Division
            | BinaryOp::Remainder => SignatureData::NUMERIC_BIN_OP,

            BinaryOp::LeftShift
            | BinaryOp::RightShift
            | BinaryOp::ArithmeticLeftShift
            | BinaryOp::ArithmeticRightShift
            | BinaryOp::BitwiseXor
            | BinaryOp::BitwiseEq
            | BinaryOp::BitwiseOr
            | BinaryOp::BitwiseAnd => &[SignatureData::INT_BIN_OP],
            BinaryOp::Power => &[SignatureData::REAL_BIN_OP],
            BinaryOp::EqualityTest | BinaryOp::NegatedEqualityTest => SignatureData::ANY_COMPARISON,
        };
        let signatures = Cow::Borrowed(TiSlice::from_ref(signatures));

        self.resolve_function_args(stmt, expr, &[lhs, rhs], signatures, None).0
    }

    /// Resolves the arguments of a function Call
    /// **NOTE** The argument count needs to be check otherwise useless error messages will be
    /// produced
    fn resolve_function_args(
        &mut self,
        stmt: StmtId,
        expr: ExprId,
        args: &[ExprId],
        signatures: Cow<'static, TiSlice<Signature, SignatureData>>,
        src: Option<FunctionId>,
    ) -> (Option<Ty>, bool) {
        debug_assert!(signatures.iter().any(|sig| sig.args.len() == args.len()));
        let arg_types: Vec<_> = args.iter().map(|arg| self.infere_expr(stmt, *arg)).collect();
        let mut valid_args = true;

        let mut candidates: Vec<_> = signatures.keys().collect();
        let mut new_candidates = Vec::new();
        let mut errors = Vec::new();
        for (i, (arg, ty)) in zip(args, &arg_types).enumerate() {
            if let Some(ty) = ty {
                new_candidates.clone_from(&candidates);
                new_candidates.retain(|candidate| {
                    signatures[*candidate]
                        .args
                        .get(i)
                        .map_or(false, |req| ty.satisfies_with_conversion(req))
                });
                if new_candidates.is_empty() {
                    let candidate_types: Vec<TyRequirement> = candidates
                        .iter()
                        .filter_map(|candidate| signatures[*candidate].args.get(i).cloned())
                        .collect();
                    debug_assert_ne!(&candidate_types, &[]);
                    errors.push(TypeMismatch {
                        expected: Cow::from(candidate_types),
                        found_ty: ty.clone(),
                        expr: *arg,
                    });
                } else {
                    mem::swap(&mut new_candidates, &mut candidates)
                }
            } else {
                valid_args = false;
            }
        }

        candidates.retain(|sig| signatures[*sig].args.len() == args.len());

        if !errors.is_empty() || candidates.is_empty() {
            self.result.diagnostics.push(
                SignatureMismatch {
                    type_mismatches: errors.into_boxed_slice(),
                    signatures: signatures.clone(),
                    src,
                    found: arg_types
                        .iter()
                        .map(|it| it.clone().unwrap_or(Ty::Val(Type::Err)))
                        .collect(),
                }
                .into(),
            );
            return (default_return_ty(&signatures.raw), false);
        }

        let res = match candidates.as_slice() {
            [] => {
                unreachable!()
            }
            [res] => *res,
            _ if arg_types.iter().any(|ty| ty.is_none()) => {
                return (default_return_ty(&signatures.raw), false)
            }
            _ => {
                new_candidates.clone_from(&candidates);
                candidates.retain(|candidate| {
                    zip(&arg_types, signatures[*candidate].args.as_ref())
                        .all(|(ty, req)| ty.as_ref().map_or(false, |ty| ty.satisfies_semantic(req)))
                });

                // Enhancement-220: if NO candidate satisfies the arguments
                // semantically, fall back to the pre-filter set so `candidates[0]`
                // below cannot index an empty vector -- a call whose arguments
                // match no overload otherwise panicked here (a compiler crash on
                // malformed input). Inference then reports the mismatch as usual.
                // Mirrors the existing restore after the exact-match retain.
                if candidates.is_empty() {
                    candidates.clone_from(&new_candidates);
                }

                if candidates.len() > 1 {
                    new_candidates.clone_from(&candidates);
                    candidates.retain(|candidate| {
                        zip(&arg_types, signatures[*candidate].args.as_ref()).all(|(ty, req)| {
                            ty.as_ref().map_or(false, |ty| ty.satisfies_exact(req))
                        })
                    });
                    if candidates.is_empty() {
                        candidates = new_candidates;
                    }
                }

                candidates[0]
            }
        };

        for (dst, (src, arg)) in zip(signatures[res].args.as_ref(), zip(arg_types, args)) {
            if let Some(src) = src.and_then(|ty| ty.to_value()) {
                if let Some(cast) = dst.cast(&src) {
                    self.result.casts.insert(*arg, cast);
                }
            }
        }

        if signatures.len() > 1 {
            self.result.resolved_signatures.insert(expr, res);
        }

        (Some(Ty::Val(signatures[res].return_ty.clone())), valid_args)
    }

    fn expect<const EXACT: bool>(
        &mut self,
        expr: ExprId,
        parent_fun: Option<ExprId>,
        ty: Ty,
        req: Cow<'static, [TyRequirement]>,
    ) -> Option<usize> {
        let fun = if EXACT { Ty::satisfies_semantic } else { Ty::satisfies_with_conversion };

        let res = req.iter().position(|req| fun(&ty, req));
        match res {
            Some(matched) => {
                if !EXACT {
                    if let Some(parent_fun) = parent_fun {
                        self.result
                            .resolved_signatures
                            .insert(parent_fun, Signature::from(matched));
                    }
                    if let Some(ty) = ty.to_value() {
                        if let Some(cast) = req[matched].cast(&ty) {
                            self.result.casts.insert(expr, cast);
                        }
                    }
                }
            }
            None => self
                .result
                .diagnostics
                .push(TypeMismatch { expected: req, found_ty: ty, expr }.into()),
        }

        res
    }

    fn resolve_path(&mut self, stmt: StmtId, expr: ExprId, path: &Path) -> Option<ScopeDefItem> {
        let resolved_path = match self.body.stmt_scopes[stmt].resolve_path(self.db.upcast(), path) {
            Ok(resolved_path) => resolved_path,
            Err(err) => {
                self.result.diagnostics.push(InferenceDiagnostic::PathResolveError { err, expr });
                return None;
            }
        };

        let attr = match resolved_path {
            ResolvedPath::FlowAttriubte { branch, ref name } => {
                BranchTy::flow_attr(self.db, branch, name)?
            }

            ResolvedPath::PotentialAttribute { branch, ref name } => {
                BranchTy::potential_attr(self.db, branch, name)?
            }

            // Net attribute access (LRM 5.5.3, Enhancement-45)
            ResolvedPath::NetFlowAttribute { node, ref name } => {
                crate::lower::net_nature_attr(self.db, node, name, false)?
            }
            ResolvedPath::NetPotentialAttribute { node, ref name } => {
                crate::lower::net_nature_attr(self.db, node, name, true)?
            }

            ResolvedPath::ScopeDefItem(def) => return Some(def),
        };

        match attr {
            Ok(attr) => Some(attr.into()),
            Err(err) => {
                self.result.diagnostics.push(InferenceDiagnostic::PathResolveError { err, expr });
                None
            }
        }
    }

    /// Looks up a vectored net/port declaration by its base name in the module that owns the
    /// current body. Returns `None` outside a module body or if `name` isn't a known bus.
    fn find_bus(&self, name: &Name) -> Option<BusDecl> {
        let DefWithBodyId::ModuleId { module, .. } = self.owner else { return None };
        let loc = module.lookup(self.db.upcast());
        let tree = loc.item_tree(self.db.upcast());
        tree[loc.id].buses.iter().find(|bus| &bus.base_name == name).cloned()
    }

    /// Same as `find_bus`, but for module-body-scope array-variable declarations
    /// (`real [msb:lsb] x;`) instead of vectored nets/ports.
    /// Whether a bit-select index is written as a (possibly negated) *literal*. Such an index is a
    /// compile-time-constant attempt — even if it doesn't fold to a valid `i32` (e.g. an oversized
    /// literal) — so it must be diagnosed as a bad constant index rather than treated as a genuine
    /// runtime (dynamic) index.
    fn is_literal_index(&self, index: ExprId) -> bool {
        match self.body.exprs[index] {
            Expr::Literal(_) => true,
            Expr::UnaryOp { expr: inner, op: UnaryOp::Neg } => {
                matches!(self.body.exprs[inner], Expr::Literal(_))
            }
            _ => false,
        }
    }

    /// A bit-select index that constant-folds to an integer literal (optionally negated), or `None`.
    /// Enhancement-333: fold an integer expression built ONLY from literals.
    ///
    /// Deliberately limited to literals and `+ - *` over them, because that is exactly
    /// the set the code generator sees as a compile-time constant. A localparam,
    /// parameter or any identifier is lowered as a RUNTIME value and never becomes a
    /// constant operand in the IR, so it is not part of the undefined-behaviour surface
    /// this guards -- and treating it as one would reject working models (verified: a
    /// parameter, a localparam and `3 - 3` all compile and simulate).
    ///
    /// Wrapping arithmetic, to match what the generated code computes. `depth` bounds
    /// the recursion so a pathological expression cannot blow the stack.
    fn const_int_expr(&self, expr: ExprId, depth: u32) -> Option<i32> {
        if depth == 0 {
            return None;
        }
        match self.body.exprs[expr] {
            Expr::Literal(Literal::Int(i)) => Some(i),
            Expr::UnaryOp { expr: inner, op: UnaryOp::Neg } => {
                self.const_int_expr(inner, depth - 1).map(i32::wrapping_neg)
            }
            Expr::UnaryOp { expr: inner, op: UnaryOp::Identity } => {
                self.const_int_expr(inner, depth - 1)
            }
            Expr::BinaryOp { lhs, rhs, op: Some(op) } => {
                let l = self.const_int_expr(lhs, depth - 1)?;
                let r = self.const_int_expr(rhs, depth - 1)?;
                match op {
                    BinaryOp::Addition => Some(l.wrapping_add(r)),
                    BinaryOp::Subtraction => Some(l.wrapping_sub(r)),
                    BinaryOp::Multiplication => Some(l.wrapping_mul(r)),
                    _ => None,
                }
            }
            _ => None,
        }
    }

    fn const_int_index(&self, index: ExprId) -> Option<i32> {
        match self.body.exprs[index] {
            Expr::Literal(Literal::Int(i)) => Some(i),
            Expr::UnaryOp { expr: inner, op: UnaryOp::Neg } => match self.body.exprs[inner] {
                Expr::Literal(Literal::Int(i)) => Some(-i),
                _ => None,
            },
            _ => None,
        }
    }

    /// Handles a dynamic-index array *write* `c[i] = v` / `m[i][j] = v` (at least one non-constant
    /// index, `c`/`m` a variable array). Returns `true` if recognised (recorded in
    /// `dynamic_index_assignments`); `false` if the destination isn't a non-constant bit-select of a
    /// variable array (all-constant writes and non-array targets fall through to the normal path).
    fn try_infere_dynamic_index_assignment(&mut self, stmt: StmtId, dst: ExprId, val: ExprId) -> bool {
        let (arr, indices) = match &self.body.exprs[dst] {
            Expr::BitSelect { base, indices } => {
                match base.as_ident().and_then(|n| self.find_var_array(&n)) {
                    Some(arr) => (arr, indices.clone()),
                    None => return false,
                }
            }
            _ => return false,
        };
        // Wrong number of indices, or all-constant / bad-literal indices: let the normal read path
        // (`infere_bit_select`) resolve or diagnose it.
        if indices.len() != arr.ndim() {
            return false;
        }
        let all_const = indices.iter().all(|&i| self.const_int_index(i).is_some());
        let has_bad_literal = indices
            .iter()
            .any(|&i| self.const_int_index(i).is_none() && self.is_literal_index(i));
        if all_const || has_bad_literal {
            return false;
        }

        let Some(elems) = self.array_elem_vars_flat(stmt, dst, &arr) else { return true };
        if elems.is_empty() {
            return true;
        }
        let elem_ty = self.db.var_data(elems[0]).ty.clone();
        // Type-check and coerce every index to an integer.
        for &index in &indices {
            if let Some(idx_ty) = self.infere_expr(stmt, index).and_then(|t| t.to_value()) {
                if idx_ty != Type::Integer {
                    self.result.casts.insert(index, Type::Integer);
                }
            }
        }
        // The assigned value is type-checked against the element type.
        if let Some(vty) = self.infere_expr(stmt, val).and_then(|t| t.to_value()) {
            if elem_ty.is_assignable_to(&vty) {
                if elem_ty != vty {
                    self.result.casts.insert(val, elem_ty.clone());
                }
            } else {
                self.result.diagnostics.push(
                    TypeMismatch {
                        expected: Cow::Owned(vec![TyRequirement::Val(elem_ty.clone())]),
                        found_ty: self.result.expr_types[val].clone(),
                        expr: val,
                    }
                    .into(),
                );
            }
        }
        self.result.expr_types[dst] = Ty::Val(elem_ty);
        self.result.dynamic_index_assignments.insert(
            stmt,
            DynArrayIndexAssign {
                target: DynArrayIndex { elems, dims: arr.dims.clone(), indices },
                value: val,
            },
        );
        true
    }

    /// Flattens an array literal to its leaf value expressions in row-major order, descending into
    /// nested literals: `'{a, b}` → `[a, b]`, `'{'{a, b}, '{c, d}}` → `[a, b, c, d]`.
    fn flatten_array_literal(&self, expr: ExprId) -> Vec<ExprId> {
        match &self.body.exprs[expr] {
            Expr::Array(elems) => {
                elems.iter().flat_map(|&e| self.flatten_array_literal(e)).collect()
            }
            _ => vec![expr],
        }
    }

    /// Resolves an array's scalar element `VarId`s, flattened in *declaration order* (each
    /// dimension `msb`→`lsb`, outermost slowest — `BusDecl::index_tuples`), the order a (nested)
    /// array literal `'{...}` fills. Works for 1-D and multi-dimensional arrays.
    fn array_elem_vars_flat(
        &mut self,
        stmt: StmtId,
        ref_expr: ExprId,
        arr: &BusDecl,
    ) -> Option<Vec<VarId>> {
        let mut vars = Vec::with_capacity(arr.elem_count());
        for indices in arr.index_tuples() {
            let synth = Path::new_ident(arr.elem_name(&indices));
            match self.resolve_path(stmt, ref_expr, &synth)? {
                ScopeDefItem::VarId(var) => vars.push(var),
                _ => return None,
            }
        }
        Some(vars)
    }

    /// Handles a *whole-array* assignment (`c = '{...}` or `c = d`), where the destination `dst`
    /// is a bare reference to a `real/integer [msb:lsb] c;` array variable. Returns `true` if the
    /// statement was recognised as such (and thus fully type-checked and recorded in
    /// `array_assignments`); `false` if `dst` is not an array variable and the caller should fall
    /// back to ordinary scalar-assignment inference.
    fn try_infere_array_assignment(&mut self, stmt: StmtId, dst: ExprId, val: ExprId) -> bool {
        // The destination must be a bare reference to a module-body array variable.
        let arr = match &self.body.exprs[dst] {
            Expr::Path { path, port: false } => path.as_ident().and_then(|n| self.find_var_array(&n)),
            _ => None,
        };
        let Some(arr) = arr else { return false };

        // From here on this *is* an array assignment, so we own its diagnostics.
        let Some(dst_vars) = self.array_elem_vars_flat(stmt, dst, &arr) else { return true };
        if dst_vars.is_empty() {
            return true;
        }
        let elem_ty = self.db.var_data(dst_vars[0]).ty.clone();
        let dst_len = dst_vars.len() as u32;
        let dst_array_ty =
            || Type::Array { ty: Box::new(elem_ty.clone()), len: dst_len };
        // Record the destination as an array-typed value so downstream passes don't treat the
        // bare array reference as an error (we deliberately bypass `infere_expr` on `dst`).
        self.result.expr_types[dst] = Ty::Val(dst_array_ty());

        // Case 1: RHS is an array literal — flat `'{e0, e1, ...}` or nested `'{'{..},'{..}}` for a
        // multi-dimensional array. It is flattened (declaration order) to one leaf value per element.
        if matches!(self.body.exprs[val], Expr::Array(_)) {
            let elems = self.flatten_array_literal(val);
            for &elem in &elems {
                if let Some(ty) = self.infere_expr(stmt, elem) {
                    if let Some(vty) = ty.to_value() {
                        if elem_ty.is_assignable_to(&vty) {
                            if elem_ty != vty {
                                self.result.casts.insert(elem, elem_ty.clone());
                            }
                        } else {
                            self.result.diagnostics.push(
                                TypeMismatch {
                                    expected: Cow::Owned(vec![TyRequirement::Val(elem_ty.clone())]),
                                    found_ty: ty,
                                    expr: elem,
                                }
                                .into(),
                            );
                        }
                    }
                }
            }
            self.result.expr_types[val] =
                Ty::Val(Type::Array { ty: Box::new(elem_ty.clone()), len: elems.len() as u32 });
            if elems.len() as u32 != dst_len {
                self.result.diagnostics.push(
                    TypeMismatch {
                        expected: Cow::Owned(vec![TyRequirement::Val(dst_array_ty())]),
                        found_ty: Ty::Val(Type::Array {
                            ty: Box::new(elem_ty),
                            len: elems.len() as u32,
                        }),
                        expr: val,
                    }
                    .into(),
                );
                return true;
            }
            let pairs = dst_vars.into_iter().zip(elems).collect();
            self.result.array_assignments.insert(stmt, ArrayAssign::Literal(pairs));
            return true;
        }

        // Case 1.5 (Enhancement-34): RHS is a `{...}` concatenation / `{n{...}}`
        // replication. Type it as a whole, check the flattened shape against the
        // destination, then expand into one source (scalar expression or source
        // element variable) per destination element.
        if matches!(self.body.exprs[val], Expr::Concat { .. }) {
            let Some(ty) = self.infere_concat(stmt, val) else { return true };
            self.result.expr_types[val] = ty.clone();
            let len = match ty {
                Ty::Val(Type::Array { len, .. }) => len,
                _ => {
                    self.result.diagnostics.push(
                        TypeMismatch {
                            expected: Cow::Owned(vec![TyRequirement::Val(dst_array_ty())]),
                            found_ty: ty,
                            expr: val,
                        }
                        .into(),
                    );
                    return true;
                }
            };
            if len != dst_len {
                self.result.diagnostics.push(
                    TypeMismatch {
                        expected: Cow::Owned(vec![TyRequirement::Val(dst_array_ty())]),
                        found_ty: Ty::Val(Type::Array { ty: Box::new(elem_ty), len }),
                        expr: val,
                    }
                    .into(),
                );
                return true;
            }
            let mut srcs = Vec::with_capacity(dst_len as usize);
            if !self.concat_sources(val, &elem_ty, &mut srcs) {
                return true;
            }
            debug_assert_eq!(srcs.len() as u32, dst_len);
            let pairs = dst_vars.into_iter().zip(srcs).collect();
            self.result.array_assignments.insert(stmt, ArrayAssign::Concat(pairs));
            return true;
        }

        // Case 2: RHS is a bare reference to another array variable (`c = d`).
        let rhs_array_name = match &self.body.exprs[val] {
            Expr::Path { path, port: false } => path.as_ident(),
            _ => None,
        };
        if let Some(src_arr) = rhs_array_name.and_then(|n| self.find_var_array(&n)) {
            let Some(src_vars) = self.array_elem_vars_flat(stmt, val, &src_arr) else { return true };
            let src_elem_ty =
                src_vars.first().map(|&v| self.db.var_data(v).ty.clone()).unwrap_or(Type::Err);
            self.result.expr_types[val] =
                Ty::Val(Type::Array { ty: Box::new(src_elem_ty.clone()), len: src_vars.len() as u32 });
            if src_vars.len() as u32 != dst_len || src_elem_ty != elem_ty {
                self.result.diagnostics.push(
                    TypeMismatch {
                        expected: Cow::Owned(vec![TyRequirement::Val(dst_array_ty())]),
                        found_ty: Ty::Val(Type::Array {
                            ty: Box::new(src_elem_ty),
                            len: src_vars.len() as u32,
                        }),
                        expr: val,
                    }
                    .into(),
                );
                return true;
            }
            let pairs = dst_vars.into_iter().zip(src_vars).collect();
            self.result.array_assignments.insert(stmt, ArrayAssign::Copy(pairs));
            return true;
        }

        // Case 3 (Enhancement-23): RHS is a call to an array-returning `analog function`
        // (`c = f(...)`). Infer the call normally (types/resolves its arguments), then bind the
        // destination elements to the function's return-array element variables.
        if matches!(self.body.exprs[val], Expr::Call { .. }) {
            self.infere_expr(stmt, val);
            if let Some(ResolvedFun::User { func, .. }) = self.result.resolved_calls.get(&val).copied()
            {
                let name = self.db.function_data(func).name.clone();
                if self.db.function_data(func).ret_len.is_some() {
                    let ret_vars = function_array_arg_vars(self.db.upcast(), func, &name);
                    if ret_vars.len() as u32 != dst_len {
                        self.result.diagnostics.push(
                            TypeMismatch {
                                expected: Cow::Owned(vec![TyRequirement::Val(dst_array_ty())]),
                                found_ty: Ty::Val(Type::Array {
                                    ty: Box::new(elem_ty),
                                    len: ret_vars.len() as u32,
                                }),
                                expr: val,
                            }
                            .into(),
                        );
                        return true;
                    }
                    let pairs = dst_vars.into_iter().zip(ret_vars).collect();
                    self.result.array_assignments.insert(stmt, ArrayAssign::ReturnCall { call: val, pairs });
                    return true;
                }
            }
            return true;
        }

        // Case 4: RHS is neither an array literal, an array variable, nor an array-returning call
        // → type mismatch.
        if let Some(ty) = self.infere_expr(stmt, val) {
            self.result.diagnostics.push(
                TypeMismatch {
                    expected: Cow::Owned(vec![TyRequirement::Val(dst_array_ty())]),
                    found_ty: ty,
                    expr: val,
                }
                .into(),
            );
        }
        true
    }

    fn find_var_array(&self, name: &Name) -> Option<BusDecl> {
        // Array variables live at module body scope and, since Enhancement-18, inside `analog
        // function` bodies (locals and array-typed arguments).
        match self.owner {
            DefWithBodyId::ModuleId { module, .. } => {
                let loc = module.lookup(self.db.upcast());
                let tree = loc.item_tree(self.db.upcast());
                tree[loc.id].var_arrays.iter().find(|arr| &arr.base_name == name).cloned()
            }
            DefWithBodyId::FunctionId(function) => {
                let loc = function.lookup(self.db.upcast());
                let tree = loc.item_tree(self.db.upcast());
                tree[loc.id].var_arrays.iter().find(|arr| &arr.base_name == name).cloned()
            }
            _ => None,
        }
    }

    /// Like `find_var_array`, but for array-valued *parameters* (`parameter real [msb:lsb] c`).
    fn find_param_array(&self, name: &Name) -> Option<BusDecl> {
        let DefWithBodyId::ModuleId { module, .. } = self.owner else { return None };
        let loc = module.lookup(self.db.upcast());
        let tree = loc.item_tree(self.db.upcast());
        tree[loc.id].param_arrays.iter().find(|arr| &arr.base_name == name).cloned()
    }

    fn infere_bit_select(
        &mut self,
        stmt: StmtId,
        expr: ExprId,
        base: &Path,
        indices: &[ExprId],
    ) -> Option<Ty> {
        let Some(base_name) = base.as_ident() else {
            self.result.diagnostics.push(InferenceDiagnostic::InvalidBusReference { expr });
            return None;
        };

        let is_net = self.find_bus(&base_name).is_some();
        let bus = self
            .find_bus(&base_name)
            .or_else(|| self.find_var_array(&base_name))
            .or_else(|| self.find_param_array(&base_name));
        let Some(bus) = bus else {
            // Not a known bus/array: resolve normally so an ordinary "unresolved identifier"
            // diagnostic is produced (e.g. for a genuine typo), rather than a bus-specific one.
            self.resolve_path(stmt, expr, base)?;
            return None;
        };

        // Type-check every index expression (so bad sub-expressions still get ordinary diagnostics).
        for &index in indices {
            self.infere_expr(stmt, index);
        }

        // The number of `[..]` clauses must match the array's dimensionality.
        if indices.len() != bus.ndim() {
            self.result.diagnostics.push(InferenceDiagnostic::WrongArrayDimensions {
                expr,
                expected: bus.ndim(),
                found: indices.len(),
            });
            return None;
        }

        // Try to constant-fold every index.
        let const_idxs: Option<Vec<i32>> =
            indices.iter().map(|&i| self.const_int_index(i)).collect();

        let Some(idxs) = const_idxs else {
            // At least one index is non-constant. Runtime (dynamic) indexing is supported for
            // *variable* arrays (Enhancement-14/15); a vectored net/port needs constant indices
            // (its bits map to distinct simulator unknowns), and a non-constant *literal* (e.g. an
            // oversized integer) is a bad constant rather than a runtime index.
            let has_bad_literal = indices
                .iter()
                .any(|&i| self.const_int_index(i).is_none() && self.is_literal_index(i));
            if is_net || has_bad_literal || self.find_var_array(&base_name).is_none() {
                self.result
                    .diagnostics
                    .push(InferenceDiagnostic::NonConstantBitSelectIndex { expr });
                return None;
            }
            return self.infere_dynamic_bit_select(stmt, expr, &bus, indices);
        };

        if !bus.contains(&idxs) {
            // Report the first out-of-range index against its dimension.
            let (bad_idx, (msb, lsb)) = idxs
                .iter()
                .zip(&bus.dims)
                .find(|(&i, &(msb, lsb))| {
                    let (lo, hi) = if msb >= lsb { (lsb, msb) } else { (msb, lsb) };
                    i < lo || i > hi
                })
                .map(|(&i, &d)| (i, d))
                .unwrap_or((idxs[0], bus.dims[0]));
            self.result.diagnostics.push(InferenceDiagnostic::BitSelectOutOfRange {
                expr,
                index: bad_idx,
                msb,
                lsb,
            });
            return None;
        }

        let synth_path = Path::new_ident(bus.elem_name(&idxs));
        match self.resolve_path(stmt, expr, &synth_path)? {
            ScopeDefItem::NodeId(node) => Some(Ty::Node(node)),
            ScopeDefItem::VarId(var) => Some(Ty::Var(self.db.var_data(var).ty.clone(), var)),
            ScopeDefItem::ParamId(param) => Some(Ty::Param(self.db.param_ty(param), param)),
            _ => None,
        }
    }

    /// A dynamic-index array *read* `c[i]` (non-constant `i`, `c` a variable array): records the
    /// element `VarId`s + index in `dynamic_index_refs` for the runtime select chain built by HIR
    /// lowering, and types the access as the element type. The index is coerced to an integer.
    fn infere_dynamic_bit_select(
        &mut self,
        stmt: StmtId,
        expr: ExprId,
        arr: &BusDecl,
        indices: &[ExprId],
    ) -> Option<Ty> {
        let elems = self.array_elem_vars_flat(stmt, expr, arr)?;
        let elem_ty = self.db.var_data(elems[0]).ty.clone();
        for &index in indices {
            if self.result.expr_types[index].to_value() != Some(Type::Integer) {
                self.result.casts.insert(index, Type::Integer);
            }
        }
        self.result.dynamic_index_refs.insert(
            expr,
            DynArrayIndex { elems, dims: arr.dims.clone(), indices: indices.to_vec() },
        );
        Some(Ty::Val(elem_ty))
    }

    fn resolve_item_path<T: ScopeDefItemKind>(
        &mut self,
        stmt: StmtId,
        expr: ExprId,
        path: &Path,
    ) -> Option<T> {
        match self.body.stmt_scopes[stmt].resolve_item_path(self.db.upcast(), path) {
            Ok(item) => Some(item),
            Err(err) => {
                self.result.diagnostics.push(InferenceDiagnostic::PathResolveError { err, expr });
                None
            }
        }
    }

    // fn collect_fmt_literal(&mut self, stmt: StmtId, args: &[ExprId]){
    //     self.body
    // }
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum InferenceDiagnostic {
    InvalidAssignDst {
        e: ExprId,
        maybe_different_operand: Option<ast::AssignOp>,
        assignment_kind: ast::AssignOp,
    },
    PathResolveError {
        err: PathResolveError,
        expr: ExprId,
    },
    ArgCntMismatch {
        expected: usize,
        found: usize,
        expr: ExprId,
        exact: bool,
    },

    ExpectedProbe {
        e: ExprId,
    },

    IndirectAssignRequiresEquality {
        e: ExprId,
    },

    /// A bus bit-select (`bus[i]`) was used but `bus` is not a known vectored net/port.
    InvalidBusReference {
        expr: ExprId,
    },

    /// A bus bit-select index was not a compile-time-constant integer literal.
    NonConstantBitSelectIndex {
        expr: ExprId,
    },

    /// Enhancement-333: integer `/` or `%` by a compile-time-constant zero. It has no
    /// value, and leaving it in the IR is undefined behaviour the optimiser turns into
    /// a trap that kills the host simulator.
    DivisionByZero {
        expr: ExprId,
        rhs: ExprId,
        is_remainder: bool,
    },

    /// Enhancement-333: `i32::MIN / -1` (or `%`) with compile-time-constant operands.
    /// The true result 2^31 is not representable, and LLVM makes it poison.
    IntegerDivisionOverflow {
        expr: ExprId,
        is_remainder: bool,
    },

    /// Enhancement-333: a shift by a compile-time-constant distance outside 0..=31.
    /// A Verilog-A `integer` is 32 bit, so anything else is poison in LLVM.
    ShiftOutOfRange {
        expr: ExprId,
        rhs: ExprId,
        dist: i32,
    },

    /// A bus bit-select index was outside the bus's declared `[msb:lsb]` width.
    BitSelectOutOfRange {
        expr: ExprId,
        index: i32,
        msb: i32,
        lsb: i32,
    },

    /// An array/bus was indexed with the wrong number of `[...]` clauses for its dimensionality
    /// (e.g. `m[i]` on a 2-D array, or `bus[i][j]` on a 1-D net).
    WrongArrayDimensions {
        expr: ExprId,
        expected: usize,
        found: usize,
    },

    /// Enhancement-34: a `{n{...}}` replication count that isn't a positive
    /// compile-time integer literal.
    InvalidReplicationCount {
        expr: ExprId,
    },

    /// Enhancement-34: an empty `{}` concatenation.
    EmptyConcat {
        expr: ExprId,
    },

    /// Enhancement-325: a `{...}` concatenation / `{n{...}}` replication whose
    /// MATERIALIZED size exceeds what the compiler will expand. Enhancement-314
    /// capped the replication COUNT, but the count is only one factor: nesting
    /// (`{1<<20{{1<<20{1.0}}}}`) or a large operand list multiplies out to a size
    /// that overflowed the u32 length (a panic under overflow-checks, a silent
    /// wrap to 0 in release), and for strings became the ARITY of a generated
    /// LLVM callback, which hung the compiler.
    ConcatTooLarge {
        expr: ExprId,
        elems: u64,
        limit: u64,
    },

    /// A vectored net/port was referenced by its base name without a bit-select.
    BareBusReference {
        expr: ExprId,
        name: Name,
    },

    /// Enhancement-59: an analog function calling itself. The LRM forbids
    /// recursion; without this the call surfaces as the puzzling "expected a
    /// function but found variable" (the name resolves to the return variable).
    RecursiveFunctionCall {
        expr: ExprId,
        name: Name,
    },

    InvalidLimitFunction {
        expr: ExprId,
        func: FunctionId,
        invalid_arg0: bool,
        invalid_arg1: bool,
        invalid_ret: bool,
        output_args: Vec<LocalFunctionArgId>,
    },

    DisplayTypeMismatch {
        err: TypeMismatch,
        fmt_lit: ExprId,
        lit_range: TextRange,
        lint_ctx: Option<StmtId>,
    },

    MissingFmtArg {
        fmt_lit: ExprId,
        lit_range: TextRange,
    },

    InvalidFmtSpecifierChar {
        fmt_lit: ExprId,
        lit_range: TextRange,
        err_char: char,
        candidates: &'static [char],
    },

    InvalidFmtSpecifierEnd {
        fmt_lit: ExprId,
        lit_range: TextRange,
    },

    TypeMismatch(TypeMismatch),
    SignatureMismatch(SignatureMismatch),
    ArrayTypeMismatch(ArrayTypeMismatch),
    InvalidUnknown {
        e: ExprId,
    },
    NonStandardUnknown {
        e: ExprId,
        stmt: StmtId,
    },
}

impl_from!(TypeMismatch,SignatureMismatch, ArrayTypeMismatch for InferenceDiagnostic);
