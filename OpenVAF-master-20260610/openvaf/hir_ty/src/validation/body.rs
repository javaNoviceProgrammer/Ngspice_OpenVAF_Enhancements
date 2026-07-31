use std::mem::replace;

use ahash::{HashMap, HashSet};
use hir_def::body::Body;
use hir_def::{
    BranchId, BuiltIn, CaseKind, DefWithBodyId, DisciplineId, Expr, ExprId, FunctionArgLoc,
    FunctionId, Literal, Lookup, NatureId, NodeId, ParamId, Path, Stmt, StmtId, Type, VarId,
};
use hir_def::expr::CaseCond;
use stdx::impl_display;
use syntax::ast::{AssignOp, BinaryOp};
use syntax::name::{AsIdent, Name};

use crate::builtin::{
    ABSDELAY_MAX, DDT_TOL, IDT_IC_ASSERT_TOL, NATURE_ACCESS_BRANCH, NATURE_ACCESS_NODES,
    NATURE_ACCESS_NODE_GND, NATURE_ACCESS_PORT_FLOW, NOISE_TABLE_INLINE, NOISE_TABLE_INLINE_NAME,
    TRANSITION_DELAY_RISET_FALLT_TOL,
};
use crate::db::HirTyDB;
use crate::inference::{BranchWrite, InferenceResult, ResolvedFun};
use crate::lower::BranchKind;
use crate::types::{BuiltinInfo, Signature, Ty};

#[derive(PartialEq, Eq, Clone, Debug)]
pub enum IllegalCtxAccessKind {
    NatureAccess,
    AnalogOperator { name: Name, is_standard: bool, non_const_dominator: Box<[ExprId]> },
    AnalysisFun { name: Name },
    Var(VarId),
}

#[derive(PartialEq, Eq, Clone, Debug)]
pub struct IllegalCtxAccess {
    pub kind: IllegalCtxAccessKind,
    pub ctx: BodyCtx,
    pub expr: ExprId,
}

#[derive(PartialEq, Eq, Clone, Debug)]
pub enum BodyValidationDiagnostic {
    ExpectedPort {
        expr: ExprId,
        node: NodeId,
    },
    TrivialBranchAccess {
        branch: BranchWrite,
        expr: ExprId,
        stmt: StmtId,
    },
    PotentialOfPortFlow {
        expr: ExprId,
        branch: Option<BranchId>,
    },
    ContributeToPortFlow {
        expr: ExprId,
        branch: BranchId,
    },
    // Enhancement-97: a contribution whose branch is entirely the `ground`
    // reference (`V(gnd) <+ ...`, `V(gnd, gnd) <+ ...`) -- both endpoints
    // collapse to node 0, so there is no unknown to contribute to. Used to
    // panic (`unreachable!()`) in `lower_contribute_unnamed_branch`.
    ContributeToGround {
        expr: ExprId,
    },
    IllegalContribute {
        stmt: StmtId,
        ctx: BodyCtx,
    },

    WriteToInputArg {
        expr: ExprId,
        arg: FunctionArgLoc,
    },

    IllegalParamAccess {
        def: ParamId,
        expr: ExprId,
        param: ParamId,
    },

    IllegalCtxAccess(IllegalCtxAccess),

    ConstSimparam {
        known: bool,
        expr: ExprId,
        stmt: StmtId,
    },

    UnsupportedFunction {
        expr: ExprId,
        func: BuiltIn,
    },

    IncompatibleNatureAccess {
        candidates: [Option<(Name, Name)>; 2],
        access_nature: Option<NatureId>,
        access_expr: ExprId,
        branch: String,
    },

    IllegalNatureAccess {
        is_pot: bool,
        access_expr: ExprId,
    },

    IncompatibleImplicitBranch {
        access: ExprId,
        node1: NodeId,
        node2: NodeId,
    },

    /// Enhancement-59: a cycle in the analog-function call graph
    /// (`f1` calls `f2` calls `f1`). The LRM forbids recursion; without this
    /// check the recursive inlining in lowering overflows the compiler stack.
    /// `cycle` holds the function names along the cycle, starting and ending
    /// with the offending function. Direct self-recursion never gets here --
    /// inside `f`, `f` resolves to the return variable and is diagnosed at
    /// inference (`InferenceDiagnostic::RecursiveFunctionCall`).
    RecursiveFunctionCall {
        expr: ExprId,
        cycle: Vec<Name>,
    },

    /// Enhancement-85: a part-select (`v[msb:lsb]`) anywhere other than an
    /// instance port connection (which elaboration consumes textually).
    StrayPartSelect {
        expr: ExprId,
    },
    /// Enhancement-78: an integer literal spelled with don't-care digits
    /// (`'b1x?`) anywhere other than directly as a `casex`/`casez` item.
    StrayDontCareLiteral {
        expr: ExprId,
    },
    /// Enhancement-78: an `x` digit in a `casez` item -- only `z`/`?` are
    /// don't-cares under `casez` (use `casex` for `x` as well).
    XDigitInCaseZ {
        expr: ExprId,
    },
    /// Enhancement-78: `casex`/`casez` masks are bitwise, so the
    /// discriminant must be an integer.
    NonIntegerCaseXZ {
        kind: CaseKind,
        discr: ExprId,
    },
    /// Enhancement-375: a loop whose controlling condition provably cannot change
    /// between iterations. `always` distinguishes a condition that is a non-zero
    /// literal (certainly infinite) from one that is merely loop-invariant (either
    /// never entered or never left -- not decidable here, and both are defects).
    ///
    /// This is an ERROR rather than a lint because there is no correct object code
    /// for a model that cannot finish one evaluation. Emitting the loop hangs the
    /// simulator with no diagnostic at all; substituting a value invents a device.
    NonTerminatingLoop {
        cond: ExprId,
        always: bool,
    },
}

impl BodyValidationDiagnostic {
    pub fn collect(db: &dyn HirTyDB, def: DefWithBodyId) -> Vec<BodyValidationDiagnostic> {
        let body = db.body(def);
        let infere = db.inference_result(def);

        let ctx = match def {
            DefWithBodyId::ModuleId { initial: false, .. } => BodyCtx::AnalogBlock,
            DefWithBodyId::ModuleId { initial: true, .. } => BodyCtx::AnalogInitialBlock,
            DefWithBodyId::FunctionId(_) => BodyCtx::Function,
            _ => BodyCtx::Const,
        };

        let mut validator = BodyValidator {
            db,
            owner: def,
            body: &body,
            infer: &infere,
            diagnostics: Vec::new(),
            ctx,
            loop_depth: 0,
            non_const_dominator: Box::default(),
            non_trivial_branches: HashSet::default(),
            trivial_probes: HashMap::default(),
        };

        for stmt in &*body.entry_stmts {
            validator.validate_stmt(*stmt)
        }

        // Enhancement-78: every don't-care literal that survived collection
        // (i.e. was not consumed as a casex/casez item) is an error
        for &expr in &body.stray_dontcare_literals {
            validator.diagnostics.push(BodyValidationDiagnostic::StrayDontCareLiteral { expr });
        }

        // Enhancement-85: part-selects (`v[msb:lsb]`) are only legal in
        // instance port connections, which elaboration consumes textually --
        // one that reached body lowering is behavioral-code misuse.
        for &expr in &body.stray_part_selects {
            validator.diagnostics.push(BodyValidationDiagnostic::StrayPartSelect { expr });
        }

        // Enhancement-59: reject call-graph cycles among analog functions
        // (mutual recursion) before lowering inlines them forever.
        if let DefWithBodyId::FunctionId(func) = def {
            check_call_cycles(db, func, &infere, &mut validator.diagnostics);
        }

        for (branch, exprs) in validator.trivial_probes {
            for (stmt, expr) in exprs {
                validator.diagnostics.push(BodyValidationDiagnostic::TrivialBranchAccess {
                    branch,
                    expr,
                    stmt,
                })
            }
        }

        validator.diagnostics
    }
}

#[derive(PartialEq, Eq, Clone, Copy, Debug)]
pub enum BodyCtx {
    AnalogBlock,
    AnalogInitialBlock,
    Conditional,
    /// Enhancement-70: the body of a runtime loop (for/while/do-while/
    /// repeat). Same restrictions as `Conditional`, but diagnosed as
    /// "loops" -- an analog operator inside a loop body used to be
    /// reported as "not allowed in conditions", which pointed users at
    /// the wrong construct (LRM 4.5.1 forbids analog operators in
    /// looping statements).
    Loop,
    EventControl,
    Function,
    ConstOrAnalysis,
    Const,
}

impl BodyCtx {
    fn allow_nature_access(self) -> bool {
        matches!(self, Self::AnalogBlock | Self::Conditional | Self::Loop | Self::EventControl)
    }

    fn allow_contribute(self) -> bool {
        matches!(self, Self::AnalogBlock | Self::Conditional | Self::Loop)
    }

    fn allow_analog_operator(self) -> bool {
        matches!(self, Self::AnalogBlock)
    }

    fn allow_analysis_fun(self) -> bool {
        !matches!(self, Self::Const)
    }

    fn allow_var_ref(self) -> bool {
        !matches!(self, Self::Const | Self::ConstOrAnalysis)
    }
}

impl_display! {
    match BodyCtx{
       BodyCtx::AnalogBlock => "analog block";
       BodyCtx::AnalogInitialBlock => "analog initial block";
       BodyCtx::Conditional => "conditions";
       BodyCtx::Loop => "loops";
       BodyCtx::EventControl => "events";
       BodyCtx::Function => "analog functions";
       BodyCtx::ConstOrAnalysis => "constant or analysis";
       BodyCtx::Const => "constants";
    }
}

/// Enhancement-375: does a literal condition select the loop body?
fn literal_is_truthy(lit: &Literal) -> bool {
    match *lit {
        Literal::Int(val) => val != 0,
        Literal::Float(val) => !val.is_zero(),
        // `while ("")` is not meaningful Verilog-A and `$inf` is non-zero; neither
        // is a zero-trip loop, so neither should suppress the diagnostic.
        Literal::String(_) | Literal::Inf => true,
    }
}

/// Enhancement-375: builtins that return a different value on each call, so a
/// condition containing one is not loop-invariant no matter what the body does.
fn builtin_is_impure(builtin: BuiltIn) -> bool {
    matches!(
        builtin,
        BuiltIn::random
            | BuiltIn::arandom
            | BuiltIn::dist_chi_square
            | BuiltIn::dist_exponential
            | BuiltIn::dist_poisson
            | BuiltIn::dist_uniform
            | BuiltIn::dist_erlang
            | BuiltIn::dist_normal
            | BuiltIn::dist_t
            | BuiltIn::rdist_chi_square
            | BuiltIn::rdist_exponential
            | BuiltIn::rdist_poisson
            | BuiltIn::rdist_uniform
            | BuiltIn::rdist_erlang
            | BuiltIn::rdist_normal
            | BuiltIn::rdist_t
    )
}

struct BodyValidator<'a> {
    db: &'a dyn HirTyDB,
    owner: DefWithBodyId,
    body: &'a Body,
    infer: &'a InferenceResult,
    diagnostics: Vec<BodyValidationDiagnostic>,
    ctx: BodyCtx,
    /// Enhancement-330: number of enclosing RUNTIME loops. `ctx` cannot express
    /// this: `validate_condition_in` REPLACES it rather than stacking, so an `if`
    /// nested inside a `for` resets it to `BodyCtx::Conditional`. It also only
    /// becomes `BodyCtx::Loop` when the controlling expression is non-constant,
    /// so `repeat(3)` would be missed.
    loop_depth: u32,
    non_const_dominator: Box<[ExprId]>,
    non_trivial_branches: HashSet<BranchWrite>,
    trivial_probes: HashMap<BranchWrite, Vec<(StmtId, ExprId)>>,
}

impl BodyValidator<'_> {
    fn validate_stmt(&mut self, stmt: StmtId) {
        let cond = match self.body.stmts[stmt] {
            Stmt::Assignment { dst, val, assignment_kind } => {
                self.validate_expr(val, stmt);

                if assignment_kind == AssignOp::Contribute && !self.ctx.allow_contribute() {
                    self.diagnostics
                        .push(BodyValidationDiagnostic::IllegalContribute { stmt, ctx: self.ctx })
                }
                // avoid duplicate errors
                else if self.infer.assignment_destination.contains_key(&stmt) {
                    self.validate_assignment_dst(dst, stmt);
                }

                return;
            }
            Stmt::EventControl { ref event, body } => {
                event.walk_child_exprs(|e| self.validate_expr(e, stmt));
                let old = replace(&mut self.ctx, BodyCtx::EventControl);
                self.validate_stmt(body);
                self.ctx = old;
                return;
            }
            Stmt::Block { ref body, .. } => {
                body.iter().for_each(|stmt| self.validate_stmt(*stmt));
                return;
            }

            Stmt::Missing | Stmt::Empty | Stmt::Disable { .. } => return,

            Stmt::Expr(e) => {
                self.validate_expr(e, stmt);
                return;
            }

            Stmt::If { cond, .. } => cond,

            Stmt::Case { kind, discr, ref case_arms } => {
                // Enhancement-78: casex/casez restrictions
                if kind != CaseKind::Case {
                    if self.infer.expr_types[discr].to_value() != Some(Type::Integer) {
                        self.diagnostics
                            .push(BodyValidationDiagnostic::NonIntegerCaseXZ { kind, discr });
                    }
                    if kind == CaseKind::CaseZ {
                        for arm in case_arms {
                            if let CaseCond::Vals(vals) = &arm.cond {
                                for (val, mask) in vals.iter().zip(&arm.masks) {
                                    if mask.had_x {
                                        self.diagnostics.push(
                                            BodyValidationDiagnostic::XDigitInCaseZ {
                                                expr: *val,
                                            },
                                        );
                                    }
                                }
                            }
                        }
                    }
                }
                discr
            }

            Stmt::ForLoop { cond, .. }
            | Stmt::WhileLoop { cond, .. }
            | Stmt::DoWhile { cond, .. }
            | Stmt::Repeat { count: cond, .. } => {
                // Enhancement-375: reject a loop that provably cannot finish before
                // it can be emitted into a model that hangs the simulator.
                self.check_loop_termination(stmt, cond);

                // Enhancement-70: loop bodies get their own ctx so the
                // analog-operator restriction is reported against "loops"
                // (LRM 4.5.1), not "conditions".
                self.loop_depth += 1;
                self.validate_condition_in(BodyCtx::Loop, cond, stmt, |s| {
                    s.body.stmts[stmt].walk_child_stmts(|stmt| s.validate_stmt(stmt))
                });
                self.loop_depth -= 1;
                return;
            }
        };

        self.validate_condition(cond, stmt, |s| {
            s.body.stmts[stmt].walk_child_stmts(|stmt| s.validate_stmt(stmt))
        });
    }

    /// Enhancement-375: flag a loop whose controlling condition cannot change.
    ///
    /// A Verilog-A module body must finish one evaluation; a loop that cannot exit
    /// makes that impossible. The compiler used to panic on these (an `unwrap()` on
    /// a loop-exit block that was never created); after the CFG repair in
    /// Enhancement-363 it instead emitted a well-formed `.osdi` containing the
    /// infinite loop, and ngspice hung on the first device evaluation with no
    /// diagnostic. That is strictly worse than the crash, hence this check.
    ///
    /// The analysis is deliberately SOUND IN THE REJECT DIRECTION -- every bail-out
    /// below means "say nothing", so it can miss a hang but must not reject a model
    /// that terminates:
    ///
    ///   * `repeat (n)` is counted and always terminates -- exempt.
    ///   * a literal-zero condition is a zero-trip loop, not an infinite one.
    ///   * `$finish`, `$stop` and `$fatal` leave the loop (and compile today).
    ///     `disable` is handled separately -- see `collect_loop_writes`.
    ///   * a user function call may write through an OUTPUT ARGUMENT, so every name
    ///     passed to one counts as written. A user call in the CONDITION could do
    ///     the same, so that abandons the check outright.
    ///   * `$random`/`$dist_*`/`$rdist_*` return a fresh value per call, so a
    ///     condition containing one is not invariant.
    ///
    /// Names are matched SYNTACTICALLY rather than resolved to `VarId`s, which errs
    /// the safe way: a shadowing declaration in a nested block makes an unrelated
    /// name look written, which suppresses the diagnostic rather than inventing one.
    ///
    /// NOT DETECTED, and undecidable in general: a loop whose condition variables
    /// are written but never toward the exit -- notably nested loops sharing an
    /// index, where termination depends on the two bounds
    /// (`for(i=0;i<10;i=i+1) for(i=0;i<3;i=i+1)` runs forever, but the same shape
    /// with the bounds swapped terminates). Those still reach the simulator.
    fn check_loop_termination(&mut self, stmt: StmtId, cond: ExprId) {
        let (body, incr) = match self.body.stmts[stmt] {
            Stmt::WhileLoop { body, .. } | Stmt::DoWhile { body, .. } => (body, None),
            Stmt::ForLoop { body, incr, .. } => (body, Some(incr)),
            // `repeat (n)` is a counted loop: it terminates by construction.
            _ => return,
        };

        // `while (0)` never runs. It is dead code, not a hang -- not this check's
        // business, and reporting it as non-terminating would be plainly wrong.
        if let Expr::Literal(ref lit) = self.body.exprs[cond] {
            if !literal_is_truthy(lit) {
                return;
            }
        }

        let mut reads = HashSet::default();
        if !self.collect_cond_reads(cond, &mut reads) {
            return;
        }

        let mut writes = HashSet::default();
        let mut escapes = false;
        self.collect_loop_writes(body, &mut writes, &mut escapes);
        // The `for` INCREMENT counts, but the INIT must not: `for (i=0; i<10; j=j+1)`
        // never changes `i`, and folding init into the write set would hide exactly
        // the bug this check exists to find.
        if let Some(incr) = incr {
            self.collect_loop_writes(incr, &mut writes, &mut escapes);
        }
        if escapes || reads.iter().any(|name| writes.contains(name)) {
            return;
        }

        let always =
            matches!(self.body.exprs[cond], Expr::Literal(ref lit) if literal_is_truthy(lit));
        self.diagnostics.push(BodyValidationDiagnostic::NonTerminatingLoop { cond, always });
    }

    /// Names read by a loop condition. Returns `false` when the condition cannot be
    /// treated as invariant at all, in which case the caller says nothing.
    fn collect_cond_reads(&self, expr: ExprId, out: &mut HashSet<Name>) -> bool {
        match self.body.exprs[expr] {
            Expr::Path { ref path, .. } => {
                if let Some(name) = path.segments.last() {
                    out.insert(name.clone());
                }
            }
            Expr::BitSelect { ref base, .. } => {
                if let Some(name) = base.segments.last() {
                    out.insert(name.clone());
                }
            }
            Expr::Call { .. } => match self.infer.resolved_calls.get(&expr) {
                // an output argument could rewrite what the condition reads
                Some(ResolvedFun::User { .. }) => return false,
                Some(ResolvedFun::BuiltIn(builtin)) if builtin_is_impure(*builtin) => return false,
                _ => {}
            },
            _ => {}
        }

        let mut invariant = true;
        self.body.exprs[expr].walk_child_exprs(|child| {
            if !self.collect_cond_reads(child, out) {
                invariant = false;
            }
        });
        invariant
    }

    /// Names a loop body can write, plus whether it can leave the loop early.
    fn collect_loop_writes(&self, stmt: StmtId, out: &mut HashSet<Name>, escapes: &mut bool) {
        match self.body.stmts[stmt] {
            Stmt::Assignment { dst, val, .. } => {
                // Enhancement-389: a write that provably cannot change the value is
                // not progress toward the exit, so it must not count as one.
                if let Some(name) = self.root_name(dst) {
                    if !self.assignment_is_noop(dst, val) {
                        out.insert(name);
                    }
                }
            }
            // `disable <block>` (LRM 5.4) is Verilog-AMS's loop break, and it is
            // deliberately NOT treated as an escape here. It works, and keeps
            // working, for a loop that can also finish normally -- such a loop's
            // condition changes, so this check never looks at it.
            //
            // As the SOLE exit from a loop whose condition cannot change it does
            // not work today: the code after the loop is then reachable only
            // through the `disable` edge, and OSDI codegen aborts on it with
            // `unreachable!("attempted to read undefined value")`
            // (mir_llvm/src/builder.rs). Verified on the shipped binary for a
            // literal `while (1)`, a constant-folding `while (1 > 0)` and a
            // non-constant `while (i < 10)` whose `i` is never written -- 3/3
            // crash, with and without the loop result being used.
            //
            // So reporting it here cannot regress a working program: there is no
            // such program. It replaces a compiler crash with an actionable error.
            _ => {}
        }
        self.body.stmts[stmt].walk_child_exprs(|e| self.scan_call_effects(e, out, escapes));
        self.body.stmts[stmt].walk_child_stmts(|s| self.collect_loop_writes(s, out, escapes));
    }

    fn scan_call_effects(&self, expr: ExprId, out: &mut HashSet<Name>, escapes: &mut bool) {
        if let Expr::Call { ref args, .. } = self.body.exprs[expr] {
            match self.infer.resolved_calls.get(&expr) {
                Some(ResolvedFun::BuiltIn(
                    BuiltIn::finish | BuiltIn::stop | BuiltIn::fatal,
                )) => *escapes = true,
                Some(ResolvedFun::User { .. }) => {
                    // Any argument may be an output argument. Assuming they all are
                    // is the safe direction: it can only suppress the diagnostic.
                    for &arg in args {
                        if let Some(name) = self.root_name(arg) {
                            out.insert(name);
                        }
                    }
                }
                _ => {}
            }
        }
        self.body.exprs[expr].walk_child_exprs(|e| self.scan_call_effects(e, out, escapes));
    }

    /// Enhancement-389: does this assignment provably leave its destination at the
    /// value it already had?
    ///
    /// `collect_loop_writes` treats any assignment to a condition variable as
    /// progress and then says nothing. That is right for `k = k + 1` and wrong for
    /// `k = k` and `k = k + 0`, which WRITE `k` without CHANGING it: the loop runs
    /// forever, the check stays silent, and the model compiles into an `.osdi` that
    /// hangs ngspice at the operating point with no diagnostic -- the exact outcome
    /// Enhancement-375 exists to prevent, reached by a different shape.
    ///
    /// Only value-preserving forms count, and the arithmetic ones only on INTEGERS.
    /// On reals `k = k + 0.0` is not quite the identity -- it turns `-0.0` into
    /// `+0.0`, and a condition can observe that (`1.0/k < 0` flips from `-inf` to
    /// `+inf`), so a loop really can terminate because of it. Contrived, but this
    /// analysis is sound in the REJECT direction, so reals get only the exact copy
    /// `k = k`, which is a bit-for-bit move for every value including NaN.
    fn assignment_is_noop(&self, dst: ExprId, val: ExprId) -> bool {
        // `a[i] = a[i]` would additionally require proving the two indices equal.
        let name = match self.body.exprs[dst] {
            Expr::Path { ref path, .. } => match path.segments.last() {
                Some(name) => name.clone(),
                None => return false,
            },
            _ => return false,
        };
        self.expr_reproduces(val, &name)
    }

    /// Does `expr` evaluate to exactly the current value of `name`?
    fn expr_reproduces(&self, expr: ExprId, name: &Name) -> bool {
        match self.body.exprs[expr] {
            Expr::Path { .. } => self.is_var(expr, name),
            Expr::BinaryOp { lhs, rhs, op: Some(op) } => {
                if self.infer.expr_types[expr].to_value() != Some(Type::Integer) {
                    return false;
                }
                let l = self.is_var(lhs, name);
                let r = self.is_var(rhs, name);
                match op {
                    // `k + 0`, `0 + k`
                    BinaryOp::Addition => {
                        (l && self.is_int_lit(rhs, 0)) || (r && self.is_int_lit(lhs, 0))
                    }
                    // `k - 0` only; `0 - k` negates.
                    BinaryOp::Subtraction => l && self.is_int_lit(rhs, 0),
                    // `k * 1`, `1 * k`
                    BinaryOp::Multiplication => {
                        (l && self.is_int_lit(rhs, 1)) || (r && self.is_int_lit(lhs, 1))
                    }
                    // `k / 1` only; `1 / k` does not reproduce `k`.
                    BinaryOp::Division => l && self.is_int_lit(rhs, 1),
                    _ => false,
                }
            }
            _ => false,
        }
    }

    fn is_var(&self, expr: ExprId, name: &Name) -> bool {
        matches!(self.body.exprs[expr], Expr::Path { ref path, .. }
            if path.segments.last() == Some(name))
    }

    fn is_int_lit(&self, expr: ExprId, want: i32) -> bool {
        matches!(self.body.exprs[expr], Expr::Literal(Literal::Int(val)) if val == want)
    }

    /// The variable a write lands on: `x` for `x = ...`, `a` for `a[i] = ...`.
    fn root_name(&self, expr: ExprId) -> Option<Name> {
        match self.body.exprs[expr] {
            Expr::Path { ref path, .. } => path.segments.last().cloned(),
            Expr::BitSelect { ref base, .. } => base.segments.last().cloned(),
            _ => None,
        }
    }

    fn validate_condition(
        &mut self,
        cond: ExprId,
        stmt: StmtId,
        f: impl FnOnce(&mut Self),
    ) -> Option<Box<[ExprId]>> {
        self.validate_condition_in(BodyCtx::Conditional, cond, stmt, f)
    }

    /// Like `validate_condition`, entering `enter_ctx` for the guarded body
    /// when the condition is non-constant (Enhancement-70: loops enter
    /// `BodyCtx::Loop`, ifs/cases `BodyCtx::Conditional`).
    fn validate_condition_in(
        &mut self,
        enter_ctx: BodyCtx,
        cond: ExprId,
        stmt: StmtId,
        f: impl FnOnce(&mut Self),
    ) -> Option<Box<[ExprId]>> {
        if matches!(self.ctx, BodyCtx::AnalogBlock | BodyCtx::Conditional | BodyCtx::Loop) {
            let mut non_const_access = Vec::new();
            ExprValidator {
                parent: self,
                cond_diagnostic_sink: Some(&mut non_const_access),
                write: false,
                stmt,
            }
            .validate_expr(cond);

            if !non_const_access.is_empty() {
                let non_const_dominator =
                    replace(&mut self.non_const_dominator, non_const_access.into_boxed_slice());
                let ctx = replace(&mut self.ctx, enter_ctx);
                f(self);
                self.ctx = ctx;
                return Some(replace(&mut self.non_const_dominator, non_const_dominator));
            }
        } else {
            self.validate_expr(cond, stmt);
        }

        f(self);
        None
    }

    fn validate_expr(&mut self, expr: ExprId, stmt: StmtId) {
        ExprValidator { parent: self, cond_diagnostic_sink: None, write: false, stmt }
            .validate_expr(expr)
    }

    fn validate_assignment_dst(&mut self, expr: ExprId, stmt: StmtId) {
        ExprValidator { parent: self, cond_diagnostic_sink: None, write: true, stmt }
            .validate_expr(expr)
    }
}

struct ExprValidator<'a, 'b> {
    parent: &'a mut BodyValidator<'b>,
    cond_diagnostic_sink: Option<&'a mut Vec<ExprId>>,
    write: bool,
    stmt: StmtId,
}

impl ExprValidator<'_, '_> {
    fn report_illegal_access(&mut self, kind: IllegalCtxAccessKind, expr: ExprId) {
        // `ctx` only reaches `BodyCtx::Loop` when the loop's controlling
        // expression is non-constant, so a `repeat (3)` reported via `loop_depth`
        // would otherwise be described as being in an "analog block" -- naming the
        // wrong construct and omitting the loop rule the user needs. Report the
        // context the check actually used.
        let ctx = if self.parent.loop_depth != 0 && self.parent.ctx.allow_analog_operator() {
            BodyCtx::Loop
        } else {
            self.parent.ctx
        };
        let err = IllegalCtxAccess { kind, ctx, expr };
        self.report(BodyValidationDiagnostic::IllegalCtxAccess(err));
    }

    fn check_access(
        &mut self,
        kind: impl FnOnce(&Self) -> IllegalCtxAccessKind,
        expr: ExprId,
        allowed: bool,
    ) {
        if let Some(sink) = &mut self.cond_diagnostic_sink {
            sink.push(expr)
        }

        if !allowed {
            self.report_illegal_access(kind(self), expr)
        }
    }

    fn report(&mut self, diagnostic: BodyValidationDiagnostic) {
        self.parent.diagnostics.push(diagnostic)
    }

    fn report_illegal_nature_access(
        &mut self,
        branch: String,
        discipline: DisciplineId,
        access_nature: Option<NatureId>,
        access_expr: ExprId,
    ) {
        let db = self.parent.db;
        let discipline = db.discipline_info(discipline);

        let nature_info = |nature: NatureId| {
            let nature = nature.lookup(db.upcast());
            let nature = &nature.item_tree(db.upcast())[nature.id];
            Some((nature.name.clone(), nature.access.clone()?.0))
        };
        let pot = discipline.potential.and_then(nature_info);
        let flow = discipline.flow.and_then(nature_info);
        self.parent.diagnostics.push(BodyValidationDiagnostic::IncompatibleNatureAccess {
            candidates: [pot, flow],
            access_nature,
            access_expr,
            branch,
        })
    }

    fn validate_implicit_branch(
        &mut self,
        expr: ExprId,
        node1: NodeId,
        node2: NodeId,
    ) -> Option<DisciplineId> {
        if let Some(discipline1) = self.parent.db.node_discipline(node1) {
            if let Some(discipline2) = self.parent.db.node_discipline(node2) {
                let discipline2 = self.parent.db.discipline_info(discipline2);
                if !discipline2.compatible(discipline1, self.parent.db) {
                    self.report(BodyValidationDiagnostic::IncompatibleImplicitBranch {
                        access: expr,
                        node1,
                        node2,
                    });
                } else {
                    return Some(discipline1);
                }
            }
        }

        None
    }

    fn lint_trivial_branch(&mut self, branch: BranchWrite, call: BuiltIn, expr: ExprId) {
        let is_flow = call == BuiltIn::flow;
        if self.write {
            self.parent.non_trivial_branches.insert(branch);
            self.parent.trivial_probes.remove(&branch);
        } else if is_flow && !self.parent.non_trivial_branches.contains(&branch) {
            self.parent.trivial_probes.entry(branch).or_default().push((self.stmt, expr))
        }
    }

    fn validate_flow_or_pot(&mut self, expr: ExprId, call: BuiltIn, discipline: DisciplineId) {
        let is_pot = call == BuiltIn::potential;
        let discipline_ = self.parent.db.discipline_info(discipline);
        if discipline_.potential.is_none() && is_pot || discipline_.flow.is_none() && !is_pot {
            self.report(BodyValidationDiagnostic::IllegalNatureAccess { is_pot, access_expr: expr })
        }
    }

    fn validate_nature_access(
        &mut self,
        access_nature: NatureId,
        access_expr: ExprId,
        args: &[ExprId],
    ) {
        match self.parent.infer.resolved_signatures.get(&access_expr).copied() {
            Some(NATURE_ACCESS_BRANCH) => {
                let branch = match self.parent.infer.expr_types[args[0]] { Ty::Branch(id) => id, _ => return };
                if let Some(branch_info) = self.parent.db.branch_info(branch) {
                    self.report_illegal_nature_access(
                        self.parent.db.branch_data(branch).name.to_string(),
                        branch_info.discipline,
                        Some(access_nature),
                        access_expr,
                    )
                }
            }

            Some(NATURE_ACCESS_NODE_GND) => {
                let node = match self.parent.infer.expr_types[args[0]] { Ty::Node(id) => id, _ => return };
                if let Some(discipline) = self.parent.db.node_discipline(node) {
                    let node = self.parent.db.node_data(node);
                    self.report_illegal_nature_access(
                        format!("({})", node.name),
                        discipline,
                        Some(access_nature),
                        access_expr,
                    )
                }
            }

            Some(NATURE_ACCESS_NODES) => {
                let node1 = match self.parent.infer.expr_types[args[0]] { Ty::Node(id) => id, _ => return };
                let node2 = match self.parent.infer.expr_types[args[0]] { Ty::Node(id) => id, _ => return };
                if let Some(discipline1) = self.parent.db.node_discipline(node1) {
                    if let Some(discipline2) = self.parent.db.node_discipline(node2) {
                        let discipline2 = self.parent.db.discipline_info(discipline2);
                        if discipline2.compatible(discipline1, self.parent.db) {
                            let node1 = self.parent.db.node_data(node1);
                            let node2 = self.parent.db.node_data(node2);
                            self.report_illegal_nature_access(
                                format!("({}, {})", node1.name, node2.name),
                                discipline1,
                                Some(access_nature),
                                access_expr,
                            )
                        } else {
                            self.report(BodyValidationDiagnostic::IncompatibleImplicitBranch {
                                access: access_expr,
                                node1,
                                node2,
                            })
                        }
                    }
                }
            }

            Some(NATURE_ACCESS_PORT_FLOW) => {
                let node = match self.parent.infer.expr_types[args[0]] { Ty::PortFlow(id) => id, _ => return };
                if let Some(discipline) = self.parent.db.node_discipline(node) {
                    let node = self.parent.db.node_data(node);
                    self.report_illegal_nature_access(
                        format!("(<{}>)", node.name),
                        discipline,
                        Some(access_nature),
                        access_expr,
                    )
                }
            }
            Some(_) => unreachable!(),
            None => (),
        };
    }

    fn validate_expr(&mut self, expr: ExprId) {
        match self.parent.body.exprs[expr] {
            Expr::Call { ref fun, ref args, .. } => {
                match self.parent.infer.resolved_calls.get(&expr) {
                    Some(ResolvedFun::BuiltIn(builtin)) => {
                        let signature = self.parent.infer.resolved_signatures.get(&expr);
                        self.validate_builtin(fun, expr, args, *builtin, signature.cloned());
                        return;
                    }
                    Some(ResolvedFun::InvalidNatureAccess(nature)) => {
                        self.validate_nature_access(*nature, expr, args);
                        return;
                    }
                    _ => (),
                }
            }

            Expr::Select { cond, then_val, else_val } => {
                if let Some(non_const_dominators) =
                    self.parent.validate_condition(cond, self.stmt, |s| {
                        let mut validator = ExprValidator {
                            parent: s,
                            cond_diagnostic_sink: self.cond_diagnostic_sink.as_deref_mut(),
                            write: false,
                            stmt: self.stmt,
                        };
                        validator.validate_expr(then_val);
                        validator.validate_expr(else_val);
                    })
                {
                    if let Some(sink) = &mut self.cond_diagnostic_sink {
                        sink.extend(non_const_dominators.to_vec())
                    }
                }
                // Robustness fix: the arm above already validates cond, then_val and
                // else_val (via validate_condition). Falling through to the generic
                // walk_child_exprs below would validate then_val/else_val a SECOND
                // time, so a chain of N nested ternaries was validated 2^N times --
                // an exponential-time hang. Return like the Call / Path arms do.
                return;
            }

            Expr::Path { port: false, .. } => {
                match self.parent.infer.expr_types[expr] {
                    Ty::FunctionVar { arg: Some(arg), fun, .. } => {
                        let is_output = self.parent.db.function_data(fun).args[arg].is_output;
                        if self.write && !is_output {
                            self.report(BodyValidationDiagnostic::WriteToInputArg {
                                expr,
                                arg: FunctionArgLoc { fun, id: arg },
                            })
                        }
                    }

                    Ty::Var(_, var) => {
                        self.check_access(
                            |__| IllegalCtxAccessKind::Var(var),
                            expr,
                            self.parent.ctx.allow_var_ref(),
                        );
                    }
                    Ty::Param(_, param) => {
                        if let DefWithBodyId::ParamId(def) = self.parent.owner {
                            if def.lookup(self.parent.db.upcast()).id
                                < param.lookup(self.parent.db.upcast()).id
                            {
                                self.report(BodyValidationDiagnostic::IllegalParamAccess {
                                    def,
                                    expr,
                                    param,
                                })
                            }
                        }
                    }
                    _ => (),
                };
                return;
            }

            _ => (),
        }

        self.parent.body.exprs[expr].walk_child_exprs(|child| self.validate_expr(child))
    }

    fn validate_builtin(
        &mut self,
        name: &Option<Path>,
        expr: ExprId,
        mut args: &[ExprId],
        call: BuiltIn,
        signature: Option<Signature>,
    ) {
        // Enhancement-220: the arms below index args[0..2] on the assumption that
        // the call has as many arguments as the builtin requires. A call with too
        // few arguments (e.g. `$simparam()`, `$port_connected()`) would index out
        // of bounds and crash the compiler. Inference already reports the
        // ArgCntMismatch for such a call (resolve_function_args), so skip the
        // builtin-specific validation rather than panic.
        if args.len() < BuiltinInfo::from(call).min_args {
            return;
        }
        match call {
            _ if call.is_unsupported() => self
                .parent
                .diagnostics
                .push(BodyValidationDiagnostic::UnsupportedFunction { expr, func: call }),
            BuiltIn::potential | BuiltIn::flow => self.check_access(
                |_| IllegalCtxAccessKind::NatureAccess,
                expr,
                self.parent.ctx.allow_nature_access(),
            ),

            // Enhancement-330: `ddx` is exempt from the general analog-operator
            // context restriction below -- it is symbolic and stateless, and the
            // industry CMC corpus uses it inside `if` in 192 places, so that
            // exemption must stay. It is NOT valid inside a runtime loop: a back
            // edge lets the differentiated expression depend on the ddx result
            // itself, so `live_derivative_fixpoint` requests a new derivative one
            // order higher every round -- it grows the very lattice it iterates
            // over, so it has no fixed point and the compiler HANGS forever
            // (confirmed: 99.8% of samples in raise_order_with, RSS climbing, no
            // termination at 15 min). Every other analog operator is already
            // rejected here; `ddx` was the lone hole.
            //
            // The same `loop_depth` test now covers EVERY analog operator, not just
            // `ddx`. The generic arm below asks `ctx.allow_analog_operator()`, and
            // `ctx` only becomes `BodyCtx::Loop` when the loop's controlling
            // expression is NON-CONSTANT -- so `repeat (3)` (or any loop with a
            // constant bound) slipped past it. `ddt` inside such a loop compiled
            // silently and produced the WRONG CHARGE, where the identical `for`
            // and `while` spellings were correctly rejected. `loop_depth` counts
            // every loop form, so the diagnostic no longer depends on whether the
            // trip count happens to be a literal.
            _ if (call.is_analog_operator() || call.is_analog_operator_sysfun())
                && self.parent.loop_depth != 0 =>
            {
                self.report_illegal_access(
                    IllegalCtxAccessKind::AnalogOperator {
                        name: name.as_ref().and_then(|p| p.as_ident()).unwrap(),
                        is_standard: call.is_analog_operator(),
                        non_const_dominator: self.parent.non_const_dominator.clone(),
                    },
                    expr,
                )
            }

            _ if call.is_analog_operator() && call != BuiltIn::ddx
                || call.is_analog_operator_sysfun() =>
            {
                // let non_const_dominator = if self.cond_diagnostic_sink.is_none() {
                // self.parent.non_const_dominator.clone()
                // } else {
                // vec![].into_boxed_slice()
                // };

                self.check_access(
                    |sel| IllegalCtxAccessKind::AnalogOperator {
                        name: name.as_ref().and_then(|p| p.as_ident()).unwrap(),
                        is_standard: call.is_analog_operator(),
                        non_const_dominator: sel.parent.non_const_dominator.clone(),
                    },
                    expr,
                    self.parent.ctx.allow_analog_operator(),
                )
            }

            _ if call.is_analysis_var() && !self.parent.ctx.allow_analysis_fun() => self
                .report_illegal_access(
                    IllegalCtxAccessKind::AnalysisFun {
                        name: name.as_ref().and_then(|p| p.as_ident()).unwrap(),
                    },
                    expr,
                ),
            _ => (),
        }

        match (call, signature) {
            (BuiltIn::potential | BuiltIn::flow, Some(NATURE_ACCESS_NODES)) => {
                let hi = match self.parent.infer.expr_types[args[0]] { Ty::Node(id) => id, _ => return };
                let lo = match self.parent.infer.expr_types[args[1]] { Ty::Node(id) => id, _ => return };
                // Enhancement-97: contributing to a branch whose endpoints are
                // both `ground` (e.g. `V(gnd, gnd) <+ ...`) has no unknown to
                // stamp and used to panic during lowering.
                if self.write
                    && self.parent.db.node_data(hi).is_gnd
                    && self.parent.db.node_data(lo).is_gnd
                {
                    self.report(BodyValidationDiagnostic::ContributeToGround { expr });
                    return;
                }
                let branch = if hi >= lo {
                    BranchWrite::Unnamed { hi, lo: Some(lo) }
                } else {
                    BranchWrite::Unnamed { hi: lo, lo: Some(hi) }
                };
                self.lint_trivial_branch(branch, call, expr);
                if let Some(discipline) = self.validate_implicit_branch(expr, hi, lo) {
                    self.validate_flow_or_pot(expr, call, discipline)
                }
            }

            (BuiltIn::potential | BuiltIn::flow, Some(NATURE_ACCESS_NODE_GND)) => {
                let node = match self.parent.infer.expr_types[args[0]] { Ty::Node(id) => id, _ => return };
                // Enhancement-97: `V(gnd) <+ ...` -- the single node is the
                // ground reference, so the implicit node-to-ground branch is
                // ground-to-ground (no unknown; used to panic during lowering).
                if self.write && self.parent.db.node_data(node).is_gnd {
                    self.report(BodyValidationDiagnostic::ContributeToGround { expr });
                    return;
                }
                if let Some(discipline) = self.parent.db.node_discipline(node) {
                    self.lint_trivial_branch(
                        BranchWrite::Unnamed { hi: node, lo: None },
                        call,
                        expr,
                    );
                    self.validate_flow_or_pot(expr, call, discipline)
                }
            }

            (BuiltIn::flow, Some(NATURE_ACCESS_PORT_FLOW)) => {
                let node = match self.parent.infer.expr_types[args[0]] { Ty::PortFlow(id) => id, _ => return };
                let node_data = self.parent.db.node_data(node);
                if !(node_data.is_input | node_data.is_output) {
                    self.report(BodyValidationDiagnostic::ExpectedPort { node, expr })
                }

                if let Some(discipline) = self.parent.db.node_discipline(node) {
                    self.validate_flow_or_pot(expr, BuiltIn::flow, discipline)
                }
            }

            (BuiltIn::potential, Some(NATURE_ACCESS_PORT_FLOW)) => {
                self.report(BodyValidationDiagnostic::PotentialOfPortFlow { expr, branch: None })
            }

            (BuiltIn::potential | BuiltIn::flow, Some(NATURE_ACCESS_BRANCH)) => {
                let branch = match self.parent.infer.expr_types[args[0]] { Ty::Branch(id) => id, _ => return };

                if let Some(branch_info) = self.parent.db.branch_info(branch) {
                    match branch_info.kind {
                        BranchKind::PortFlow(_) => {
                            if call == BuiltIn::potential {
                                self.report(BodyValidationDiagnostic::PotentialOfPortFlow {
                                    expr,
                                    branch: Some(branch),
                                })
                            } else if self.write {
                                // Port branches are probe-only (LRM 5.4.3.1): the port
                                // flow is defined by the connected network, so
                                // contributing to it is illegal (and used to panic in
                                // BranchWrite::nodes during lowering).
                                self.report(BodyValidationDiagnostic::ContributeToPortFlow {
                                    expr,
                                    branch,
                                })
                            } else {
                                self.validate_flow_or_pot(
                                    expr,
                                    BuiltIn::flow,
                                    branch_info.discipline,
                                )
                            }
                        }
                        BranchKind::NodeGnd(node) => {
                            self.lint_trivial_branch(
                                BranchWrite::Unnamed { hi: node, lo: None },
                                call,
                                expr,
                            );
                            self.validate_flow_or_pot(expr, call, branch_info.discipline)
                        }
                        BranchKind::Nodes(hi, lo) => {
                            let branch = if hi >= lo {
                                BranchWrite::Unnamed { hi, lo: Some(lo) }
                            } else {
                                BranchWrite::Unnamed { hi: lo, lo: Some(hi) }
                            };
                            self.lint_trivial_branch(branch, call, expr);
                            self.validate_flow_or_pot(expr, call, branch_info.discipline)
                        }
                    }
                }
            }

            (BuiltIn::port_connected, _) => {
                let node = match self.parent.infer.expr_types[args[0]] { Ty::Node(id) => id, _ => return };
                let node_data = self.parent.db.node_data(node);
                if !(node_data.is_input | node_data.is_output) {
                    self.report(BodyValidationDiagnostic::ExpectedPort { node, expr })
                }
            }

            (
                BuiltIn::noise_table | BuiltIn::noise_table_log,
                Some(NOISE_TABLE_INLINE | NOISE_TABLE_INLINE_NAME),
            ) => self.validate_const_expr(args[0]),
            (func @ (BuiltIn::simparam | BuiltIn::simparam_str), _) => {
                if self.parent.ctx == BodyCtx::Const {
                    let known = if let Expr::Literal(Literal::String(name)) =
                        &self.parent.body.exprs[args[0]]
                    {
                        matches!(
                            (func, &**name),
                            (
                                BuiltIn::simparam,
                                "minr"
                                    | "imelt"
                                    | "shrink"
                                    | "imax"
                                    | "rthresh"
                                    | "scale"
                                    | "simulatorSubversion"
                                    | "simulatorVersion"
                                    | "tnom"
                            ) | (BuiltIn::simparam_str, "cwd" | "module" | "instance" | "path")
                        )
                    } else {
                        false
                    };

                    self.report(BodyValidationDiagnostic::ConstSimparam {
                        known,
                        expr,
                        stmt: self.stmt,
                    });
                }
            }

            (BuiltIn::absdelay, Some(ABSDELAY_MAX))
            | (BuiltIn::transition, Some(TRANSITION_DELAY_RISET_FALLT_TOL))
            | (BuiltIn::ddt, Some(DDT_TOL))
            | (BuiltIn::idt | BuiltIn::idtmod, Some(IDT_IC_ASSERT_TOL)) => {
                if let [other_args @ .., const_expr] = args {
                    // Do not type check const expr twice
                    args = other_args;
                    self.validate_const_expr(*const_expr);
                };
            }

            (
                BuiltIn::laplace_nd | BuiltIn::laplace_np | BuiltIn::laplace_zp | BuiltIn::laplace_zd,
                Some(_),
            ) => {
                // args[0] (input signal) and args[1]/args[2] (num/den, or zero/pole) are
                // validated normally below: num/den may be either an array literal (whose
                // elements may be ordinary runtime expressions, e.g. parameters) or a bare
                // reference to a module-body array variable (Enhancement-4) -- neither is
                // required to be a compile-time constant, since each element is lowered as an
                // ordinary MIR value, not constant-folded. Only the optional trailing
                // tolerance/nature argument (unused, see Enhancement-4.md §1.3) still must be
                // constant.
                if let [_in, _num, _den, const_args @ ..] = args {
                    args = &args[..3];
                    for arg in const_args {
                        self.validate_const_expr(*arg)
                    }
                }
            }

            (
                BuiltIn::zi_nd | BuiltIn::zi_np | BuiltIn::zi_zd | BuiltIn::zi_zp,
                Some(_),
            ) => {
                if let [_expr, const_args @ ..] = args {
                    args = &args[..1];
                    for arg in const_args {
                        self.validate_const_expr(*arg)
                    }
                }
            }

            _ => (),
        }

        for arg in args {
            self.validate_expr(*arg)
        }
    }

    fn validate_const_expr(&mut self, expr: ExprId) {
        let old = replace(&mut self.parent.ctx, BodyCtx::Const);
        let sink = self.cond_diagnostic_sink.take();
        self.validate_expr(expr);
        self.cond_diagnostic_sink = sink;
        self.parent.ctx = old;
    }
}

/// Enhancement-59: for each user-function call in `func`'s body, walk the
/// callee's own (independently inferred) call graph; if `func` is reachable
/// the program is mutually recursive -- report it on the call expression that
/// enters the cycle. Each function body's `InferenceResult` is a separate
/// salsa query that never recurses into other bodies, so querying callees
/// here cannot cycle.
fn check_call_cycles(
    db: &dyn HirTyDB,
    func: FunctionId,
    infere: &InferenceResult,
    diagnostics: &mut Vec<BodyValidationDiagnostic>,
) {
    for (expr, resolved) in infere.resolved_calls.iter() {
        let ResolvedFun::User { func: callee, .. } = resolved else { continue };
        let mut path = vec![*callee];
        let mut visited = HashSet::default();
        if calls_reach(db, *callee, func, &mut visited, &mut path) {
            let mut cycle = vec![db.function_data(func).name.clone()];
            cycle.extend(path.iter().map(|f| db.function_data(*f).name.clone()));
            diagnostics.push(BodyValidationDiagnostic::RecursiveFunctionCall {
                expr: *expr,
                cycle,
            });
            return; // one report per function is plenty
        }
    }
}

/// DFS through resolved user-function calls: does `from`'s call graph reach
/// `target`? On success `path` holds the functions along the way (ending in
/// `target`).
fn calls_reach(
    db: &dyn HirTyDB,
    from: FunctionId,
    target: FunctionId,
    visited: &mut HashSet<FunctionId>,
    path: &mut Vec<FunctionId>,
) -> bool {
    if from == target {
        return true;
    }
    if !visited.insert(from) {
        return false;
    }
    let infere = db.inference_result(DefWithBodyId::FunctionId(from));
    for resolved in infere.resolved_calls.values() {
        let ResolvedFun::User { func: callee, .. } = resolved else { continue };
        path.push(*callee);
        if calls_reach(db, *callee, target, visited, path) {
            return true;
        }
        path.pop();
    }
    false
}
