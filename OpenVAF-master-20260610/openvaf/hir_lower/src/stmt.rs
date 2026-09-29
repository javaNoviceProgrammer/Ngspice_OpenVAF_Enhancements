use hir::{
    ArrayAssignElem, BranchWrite, BuiltIn, Case, CaseCond, CaseKind, CaseMask, ContributeKind,
    Event, Expr, ExprId, GlobalEvent, Literal, Node, ResolvedFun, Stmt, StmtId, Type,
};
use mir::builder::InstBuilder;
use mir::cursor::{Cursor, FuncCursor};
use mir::{Opcode, Value, FALSE, F_ONE, F_ZERO, INFINITY, TRUE};

use crate::body::BodyLoweringCtx;
use crate::ctx::LoweringCtx;
use crate::{CallBackKind, CurrentKind, ParamKind, PlaceKind};

/// `a && b` built from already-lowered `Value`s (as opposed to
/// `BodyLoweringCtx::lower_bin_op`'s `BooleanAnd`, which lowers an as-yet
/// unlowered `ExprId` inside the branch) -- used by `lower_event_control`'s
/// `cross`/`above`/`timer` edge-detection logic, which combines several
/// already-computed boolean `Value`s rather than source-level expressions.
/// Enhancement-759: see `event_prev_sample`.
struct EventSample {
    prev_eval: Value,
    /// the slot `prev_eval` is read from (rewritten at a retry's first iterate)
    prev_idx: u32,
    /// this iterate's value of the expression
    current: Value,
    acc: Value,
    is_initial: Value,
    in_tran: Value,
    new_point: Value,
    /// the first iterate of an attempt (a new point, or a retry's new time)
    first_iter: Value,
    accepted_rule: Value,
}

/// Enhancement-759: what `event_landing_context` decided for one iterate.
struct LandingCtx {
    /// this iterate may ask for a landing
    may_request: Value,
    /// this iterate may run the body (an edge and no request of its own)
    may_fire: Value,
    /// the body runs now: the last request was DECLINED (the point it asked
    /// to redo was accepted), so the crossing has been passed without it
    fire_declined: Value,
    /// this attempt is a landing this event asked for
    landing_att: Value,
    /// what a request made at this iterate writes to the pending slot: 1,
    /// or 2 for a refinement asked from a landing attempt
    request_gen: Value,
    first_iter: Value,
    pend_idx: u32,
    /// the margin the last request used
    margin_idx: u32,
    short_idx: u32,
    fired_idx: u32,
    req_idx: u32,
    stamp_idx: u32,
    abstime: Value,
}

pub(crate) fn bool_and(ctx: &mut LoweringCtx, a: Value, b: Value) -> Value {
    ctx.make_select(a, |_, branch| if branch { b } else { FALSE })
}

/// `a || b`, see `bool_and`.
pub(crate) fn bool_or(ctx: &mut LoweringCtx, a: Value, b: Value) -> Value {
    ctx.make_select(a, |_, branch| if branch { TRUE } else { b })
}

impl BodyLoweringCtx<'_, '_, '_> {
    pub(super) fn lower_stmt(&mut self, stmnt: StmtId) {
        // TODO(msrv): let .. else
        let stmnt = if let Some(stmnt) = self.body.get_stmt(stmnt) {
            stmnt
        } else {
            return;
        };
        match stmnt {
            Stmt::Expr(expr) => {
                self.lower_expr(expr);
            }
            Stmt::EventControl { event, body } => self.lower_event_control(event, body),
            Stmt::Assignment { lhs, rhs } => {
                let val_ = self.lower_expr(rhs);
                self.ctx.def_place(lhs.into(), val_);
            }
            Stmt::ArrayAssignment { assigns } => {
                // A whole-array assignment (`c = '{...}` / `c = d`) is lowered as its
                // decomposed per-element scalar assignments, in declaration order.
                for elem in assigns {
                    match elem {
                        ArrayAssignElem::Val { dst, val } => {
                            let v = self.lower_expr(val);
                            self.ctx.def_place(PlaceKind::Var(dst), v);
                        }
                        ArrayAssignElem::Copy { dst, src } => {
                            let v = self.ctx.read_variable(src);
                            self.ctx.def_place(PlaceKind::Var(dst), v);
                        }
                    }
                }
            }
            Stmt::ArrayReturnAssignment { call, assigns } => {
                // `c = f(...)` for an array-returning function (Enhancement-23): lower the call
                // (which inlines the body and writes the function's return element variables),
                // then copy each return element into the destination array element.
                let _ = self.lower_expr(call);
                for elem in assigns {
                    if let ArrayAssignElem::Copy { dst, src } = elem {
                        let v = self.ctx.read_variable(src);
                        self.ctx.def_place(PlaceKind::Var(dst), v);
                    }
                }
            }
            Stmt::DynArrayAssignment { elems, dims, indices, value } => {
                // A dynamic-index write `c[i] = v` / `m[i][j] = v` updates each element
                // conditionally: element `elems[k]` becomes `v` when the flat runtime position
                // equals `k`, else keeps its value.
                let v = self.lower_expr(value);
                let name = elems[0].name(self.ctx.db);
                let base = name.split('[').next().unwrap_or(&name).to_owned();
                let flat = self.lower_flat_array_index(&base, &dims, &indices, true);
                for (k, var) in elems.into_iter().enumerate() {
                    let target = self.ctx.iconst(k as i32);
                    let is_k = self.ctx.ins().binary1(Opcode::Ieq, flat, target);
                    let cur = self.ctx.read_variable(var);
                    // Enhancement-579: a branchless `select` per element -- see
                    // `InstructionData::Select`.
                    let new = self.ctx.ins().select(is_k, v, cur);
                    self.ctx.def_place(PlaceKind::Var(var), new);
                }
            }
            Stmt::Contribute { kind, branch, rhs } => {
                self.contribute(kind == ContributeKind::Potential, branch, rhs)
            }
            Stmt::IndirectContribute { kind, branch, constraint_lhs, constraint_rhs } => {
                self.indirect_contribute(
                    kind == ContributeKind::Potential,
                    branch,
                    constraint_lhs,
                    constraint_rhs,
                )
            }

            Stmt::Block { name, body } => match name {
                // A *named* block gets an explicit exit block that `disable
                // <name>` can branch to; execution continues there once the
                // block finishes (whether by falling off the end or by a
                // `disable`).
                Some(name) => {
                    let exit = self.ctx.create_block();
                    self.ctx.disable_scopes.push((name.clone(), exit));
                    for stmt in body {
                        self.lower_stmt(*stmt);
                    }
                    self.ctx.disable_scopes.pop();
                    self.ctx.ins().jump(exit);
                    self.ctx.seal_block(exit);
                    self.ctx.switch_to_block(exit);
                }
                None => {
                    for stmt in body {
                        self.lower_stmt(*stmt);
                    }
                }
            },
            Stmt::Disable { name } => {
                // Branch to the exit of the nearest enclosing named block with
                // this name. The rest of the current block is unreachable (it
                // has no incoming edges and is removed from the MIR). An
                // unresolved name degrades to a no-op (soft, like other
                // lowering-level degradations in this crate).
                if let Some(&(_, exit)) =
                    self.ctx.disable_scopes.iter().rev().find(|(n, _)| n == name)
                {
                    self.ctx.ins().jump(exit);
                    let unreachable_bb = self.ctx.create_block();
                    self.ctx.switch_to_block(unreachable_bb);
                    self.ctx.seal_block(unreachable_bb);
                }
            }
            Stmt::If { cond, then_branch, else_branch } => {
                // A literal condition -- `if (0)`, and the `(1)`/`(0)` that
                // `$port_connected` resolves to during flattening -- lowers to
                // just the taken branch. The dead arm must not reach the MIR
                // at all: its analog operators (transition, ddt, ...) would
                // survive const-folding as interned ops whose state setup
                // reads optimized-away values and aborts codegen.
                if let Expr::Literal(Literal::Int(i)) = self.body.get_expr(cond) {
                    self.lower_stmt(if *i != 0 { then_branch } else { else_branch });
                } else {
                    let cond_ = self.lower_expr(cond);

                    self.ctx.make_cond(cond_, |ctx, branch| {
                        let stmt = if branch { then_branch } else { else_branch };
                        BodyLoweringCtx { body: self.body, path: self.path, ctx }
                            .lower_stmt(stmt);
                    });
                }
            }
            Stmt::ForLoop { init, cond, incr, body } => {
                self.lower_for(init, cond, incr, body);
            }
            Stmt::WhileLoop { cond, body } => self.lower_loop(cond, |s| s.lower_stmt(body)),
            Stmt::DoWhile { cond, body } => self.lower_do_while(cond, |s| s.lower_stmt(body)),
            Stmt::Repeat { count, body } => self.lower_repeat(count, body),
            Stmt::Case { kind, discr, case_arms } => self.lower_case(kind, discr, case_arms),
            // VAMS-2023 jump statements (LRM 5.11). Same shape as `disable`:
            // jump to the recorded target and continue lowering into a fresh
            // block with no incoming edges (removed from the MIR). Validation
            // has already errored when no enclosing scope exists; degrade to a
            // no-op here like an unresolved `disable`.
            Stmt::Break | Stmt::Continue => {
                let is_break = matches!(stmnt, Stmt::Break);
                if let Some(&(continue_target, break_target)) = self.ctx.loop_scopes.last() {
                    let target = if is_break { break_target } else { continue_target };
                    self.ctx.ins().jump(target);
                    let unreachable_bb = self.ctx.create_block();
                    self.ctx.switch_to_block(unreachable_bb);
                    self.ctx.seal_block(unreachable_bb);
                }
            }
            Stmt::Return { expr } => {
                if let Some(&(fun, exit)) = self.ctx.return_scopes.last() {
                    if let Some(expr) = expr {
                        let val = self.lower_expr(expr);
                        self.ctx.def_place(PlaceKind::FunctionReturn(fun), val);
                    }
                    self.ctx.ins().jump(exit);
                    let unreachable_bb = self.ctx.create_block();
                    self.ctx.switch_to_block(unreachable_bb);
                    self.ctx.seal_block(unreachable_bb);
                }
            }
        }
    }

    /// Lowers `@(event) body;`. `@(initial_step)` gates `body` on
    /// `ParamKind::IsInitialStep`, a simulator-provided flag that is true only
    /// on an instance's first evaluation (see `openvaf/osdi/src/eval.rs` and
    /// `ngspice-46/src/osdi/osdiload.c` -- a one-shot, per-instance
    /// approximation of the LRM's "fires once per analysis" semantics).
    /// `@(final_step)` (Enhancement-53) gates on `ParamKind::IsFinalStep`, set by
    /// the simulator on a dedicated post-analysis evaluation whose results are not
    /// loaded into the matrix/RHS (ngspice's `OSDIfinalStep`, called at the
    /// successful end of tran/op/dc/ac). Before E-53 it never fired -- E-7's
    /// documented fail-safe.
    ///
    /// Analysis-phase lists (`@(initial_step("tran","ac"))`, LRM 5.10.2) AND the
    /// step flag with the same per-name `CallBackKind::Analysis` matcher that
    /// `analysis()` uses (Enhancement-30), OR-ed across the listed names. An empty
    /// list fires in every analysis. Before E-53 the parsed list was silently
    /// dropped (the "scaffolded-but-unwired" pattern: `Event::Global` always
    /// carried `phases`, this match ignored them).
    fn lower_event_control(&mut self, event: &Event, body: StmtId) {
        let fired = self.lower_event_fired(event);

        // Display statements inside the event body are tagged immediate: the
        // event fires on its own Newton iteration, so deferring their output
        // to the accepted iteration (LRM 9.4.6) would drop it entirely.
        let outer = self.ctx.in_event_ctx;
        self.ctx.in_event_ctx = true;
        self.ctx.make_cond(fired, |ctx, branch| {
            if branch {
                BodyLoweringCtx { ctx, body: self.body, path: self.path }.lower_stmt(body);
            }
        });
        self.ctx.in_event_ctx = outer;
    }

    /// Lowers one event (or an `or` list of them, Enhancement-59) to its
    /// "fired this evaluation" boolean.
    fn lower_event_fired(&mut self, event: &Event) -> Value {
        match event {
            Event::Global { kind, phases } => {
                let step = match kind {
                    GlobalEvent::InitialStep => self.ctx.use_param(ParamKind::IsInitialStep),
                    GlobalEvent::FinalStep => self.ctx.use_param(ParamKind::IsFinalStep),
                };
                match self.lower_phase_filter(phases) {
                    Some(phase_hit) => self.ctx.ins().iand(step, phase_hit),
                    None => step,
                }
            }
            // LRM 5.10.3: every monitored event takes an optional trailing
            // `enable` -- "the enable argument, if specified, shall evaluate to an
            // integer" -- and the event is live only while it is non-zero. It used
            // to be parsed as surplus and rejected, so an event could not be gated
            // at all. Wrapping the BODY in an `if` is not equivalent: the event
            // still fires and still controls the timestep. Gating the FIRED bool
            // leaves the event itself dormant.
            Event::Cross { expr, dir, time_tol, expr_tol, enable, .. } => {
                let fired = self.lower_cross(*expr, *dir, *time_tol, *expr_tol);
                self.gate_on_enable(fired, *enable)
            }
            Event::Above { expr, time_tol, expr_tol, enable, .. } => {
                let fired = self.lower_above(*expr, *time_tol, *expr_tol);
                self.gate_on_enable(fired, *enable)
            }
            Event::Timer { t0, period, enable, .. } => {
                let fired = self.lower_timer(*t0, *period);
                self.gate_on_enable(fired, *enable)
            }
            // Enhancement-59: `@(ev1 or ev2 ...)` fires when ANY member fires.
            // Each member keeps its own event state/phase machinery; the fired
            // bools simply OR together.
            Event::Or(events) => {
                let mut acc: Option<Value> = None;
                for ev in events.iter() {
                    let hit = self.lower_event_fired(ev);
                    acc = Some(match acc {
                        None => hit,
                        // `bool_or`, not a raw `ior`: the members are i1 values
                        // and may const-fold (e.g. `initial_step` at t=0 paths);
                        // the const evaluator has no Bool arm for `ior`
                        Some(prev) => bool_or(self.ctx, prev, hit),
                    });
                }
                acc.expect("the grammar guarantees a non-empty or-list")
            }
            // LRM audit (events): an unrecognizable event expression.
            // `hir_ty::validation` has already reported it as an error (the
            // compile aborts before codegen); lowering keeps total by never
            // firing, where the old None-degradation ran the body on EVERY
            // evaluation.
            Event::Invalid { .. } => FALSE,
            // `Event` is `#[non_exhaustive]` (hir_def/src/expr.rs) for forward-compatibility
            // with unimplemented LRM event kinds; every variant that actually exists today is
            // handled above.
            _ => unreachable!("all Event variants are handled above"),
        }
    }

    /// Lowers a step event's analysis-phase list to a bool that is true iff the
    /// running analysis matches any listed name (`None` for an empty list = no
    /// filter). Same OR-of-`CallBackKind::Analysis` shape as `analysis(a, b, ...)`
    /// in expr lowering (Enhancement-30); the callback returns an integer, so the
    /// accumulated hit is converted with `!= 0` before feeding the `iand` gate.
    fn lower_phase_filter(&mut self, phases: &[String]) -> Option<Value> {
        let mut acc: Option<Value> = None;
        for phase in phases {
            let name = self.ctx.sconst(phase);
            let hit = self.ctx.call1(CallBackKind::Analysis, &[name]);
            acc = Some(match acc {
                None => hit,
                Some(prev) => self.ctx.ins().ior(prev, hit),
            });
        }
        let zero = self.ctx.iconst(0);
        acc.map(|hits| self.ctx.ins().ine(hits, zero))
    }

    /// Allocates a fresh `ParamKind::EventState(i)`/`PlaceKind::EventState(i)` persistent
    /// storage slot (see their doc comments) and returns `(raw_prev, idx)`, where `raw_prev`
    /// is the *unconditional* read of the slot -- garbage/zero-initialized on an instance's
    /// true first evaluation, since OSDI instance memory starts zeroed and `EventState` has
    /// no source-level initializer to select on the way `HiddenState(var)` does (see
    /// `state::insert_var_init`). Callers must combine `raw_prev` with
    /// `ParamKind::IsInitialStep` themselves to get a *meaningful* "previous" value (e.g.
    /// seeding it with the current value on the first evaluation, so no spurious edge fires) --
    /// there's no single sensible default across `cross`/`above`/`timer`, so it isn't baked
    /// in here.
    pub(crate) fn new_event_state(&mut self) -> (Value, u32) {
        let idx = self.ctx.intern.event_state_count;
        self.ctx.intern.event_state_count += 1;
        (self.ctx.use_param(ParamKind::EventState(idx)), idx)
    }

    /// Lowers `@(above(expr))`: fires on the evaluation where `expr` transitions from `<= 0`
    /// to `> 0`, relative to the *previous evaluation's* value (not the previous accepted
    /// timepoint -- same per-`eval()`-call persistence granularity Enhancement-7 established
    /// for ordinary variable persistence; see `hir_lower/src/state.rs`). The first evaluation
    /// never fires (there is no real "previous" sample yet): `raw_prev` is seeded with the
    /// current value itself on `IsInitialStep`, making the first "transition" trivially a
    /// non-transition.
    fn lower_above(
        &mut self,
        expr: ExprId,
        time_tol: Option<ExprId>,
        expr_tol: Option<ExprId>,
    ) -> Value {
        let current = self.lower_expr(expr);
        // Enhancement-759: the accepted sample beside the previous evaluation's,
        // and the landing context (see `event_landing_context`)
        let smp = self.event_prev_sample(current);
        let is_initial = smp.is_initial;
        let lc = self.event_landing_context(&smp);
        let prev = smp.prev_eval;

        // Enhancement-587 (hunt F3 of 2026-09-07): a crossing needs a previous
        // sample on the OTHER side. `prev <= 0 && cur > 0` counted an expression
        // that STARTS exactly at zero (a sine whose offset equals the threshold)
        // as crossing on the first step after t = 0 -- prev was the seeded 0.
        // Strict on the previous side, inclusive on the current side: a sample
        // that lands exactly on zero coming from below fires once, at that
        // sample, and not again when the next one is positive.
        let was_below = self.ctx.ins().flt(prev, F_ZERO);
        let is_at_or_above = self.ctx.ins().fge(current, F_ZERO);
        let fired = bool_and(self.ctx, was_below, is_at_or_above);
        let is_above = self.ctx.ins().fgt(current, F_ZERO);

        // LRM 5.10.3.2 (events audit): "If the expression is positive at the
        // conclusion of the initial condition analysis that precedes a
        // transient analysis, the above() function shall generate an event."
        // Seeding prev with current made the first evaluation a non-edge BY
        // CONSTRUCTION, so an expression positive from the very first iterate
        // never produced the mandated initialization event -- it only fired
        // when the Newton trajectory happened to cross the threshold while
        // converging from the 0 initial guess (solver luck, not the rule).
        // Enhancement-587: at t = 0 of a TRANSIENT the only rule is the
        // initialization one above. The Newton iterations of that operating
        // point start from the zero guess and walk the expression through the
        // threshold, and the evaluation-to-evaluation edge fired on that walk
        // -- so an expression that is exactly zero at t = 0 (a sine whose
        // offset is the threshold) was counted once too often. `cross` has
        // gated its edge on `tran && t > 0` since the events audit; `above`
        // keeps its edges in dc sweeps, where every point is a real solution.
        let name = self.ctx.sconst("tran");
        let tran_hit = self.ctx.call1(CallBackKind::Analysis, &[name]);
        let zero = self.ctx.iconst(0);
        let is_tran = self.ctx.ins().ine(tran_hit, zero);
        let abstime = self.ctx.use_param(ParamKind::Abstime);
        let t_pos = self.ctx.ins().fgt(abstime, F_ZERO);
        let not_tran = self.ctx.ins().inot(is_tran);
        let edge_ok = bool_or(self.ctx, not_tran, t_pos);
        // ... except that the LRM's initialization event is judged on the
        // CONVERGED value ("positive at the conclusion of the initial condition
        // analysis"), which no single evaluation can see. An edge on the t = 0
        // walk therefore still counts when the value it lands on is strictly
        // positive -- that is the initialization event -- and is dropped when
        // it lands exactly on zero, which is the case that was over-counted.
        let edge_ok = bool_or(self.ctx, edge_ok, is_above);
        let fired = bool_and(self.ctx, fired, edge_ok);

        let init_pos = bool_and(self.ctx, is_initial, is_above);

        // Enhancement-759: in a transient the rise between the accepted sample
        // and this iterate is landed on (see `event_landing_context`); the
        // initialization event is untouched
        let and = |ctx: &mut LoweringCtx, a: Value, b: Value| ctx.ins().select(a, b, FALSE);
        let acc_below = self.ctx.ins().flt(smp.acc, F_ZERO);
        let present = and(self.ctx, acc_below, is_at_or_above);
        let present = and(self.ctx, present, smp.in_tran);
        let ask = and(self.ctx, present, lc.may_request);
        let requested = self.localise_crossing(ask, smp.acc, current, time_tol, expr_tol, &lc);
        let not_requested = self.ctx.ins().select(requested, FALSE, TRUE);
        let fired = and(self.ctx, fired, not_requested);
        let fired = and(self.ctx, fired, lc.may_fire);
        let fired = self.ctx.ins().select(lc.fire_declined, TRUE, fired);
        self.event_landing_record(&lc, present, requested, fired);
        bool_or(self.ctx, fired, init_pos)
    }

    /// Lowers `@(cross(expr, dir))`: fires on any evaluation-to-evaluation zero-crossing of
    /// `expr` (same persistence granularity as `lower_above`), filtered by `dir` (`< 0`:
    /// falling only, `> 0`: rising only, `== 0`/absent: either -- `dir` is read as an
    /// ordinary runtime `Value`, not assumed constant, mirroring how `last_crossing`'s own
    /// `dir` argument is handled in `hir_lower::expr::lower_last_crossing`).
        // Enhancement-506: the direction is dispatched by SIGN, and nothing
        // checked that it is one of the three values the LRM defines.
        //
        // hir_ty refuses a literal ("the direction must be -1 (falling), 0
        // (either) or +1 (rising)") but sees only a literal or a localparam. From
        // the deck the same value went unexamined and was simply interpreted: a
        // direction of 7 fired on RISING edges and -3 on FALLING ones, each giving
        // a plausible count from a spec the compiler calls an outright error, and
        // a NaN direction made every comparison false so the event went silently
        // DEAD. Sign is not a projection of {-1, 0, +1} -- it is a guess at what a
        // seventh direction might have meant -- so the run time says what the
        // compiler says and aborts.
    ///
    /// Shared by `@(cross)` and `last_crossing`, which take the same argument and
    /// had the same hole.
    pub(crate) fn guard_event_direction(&mut self, name: &str, dir: Value) -> Value {
        let minus_one = self.ctx.fconst(-1.0);
        let is_rising = self.ctx.ins().feq(dir, F_ONE);
        let is_falling = self.ctx.ins().feq(dir, minus_one);
        let is_either = self.ctx.ins().feq(dir, F_ZERO);
        // Every comparison is false for NaN, so NaN lands in the refusing branch.
        let ok = bool_or(self.ctx, is_rising, is_falling);
        let ok = bool_or(self.ctx, ok, is_either);
        let msg = format!(
            "{name}: the direction must be -1 (falling), 0 (either) or +1 (rising), but is"
        );
        self.ctx.make_select(ok, |ctx, branch| {
            if branch {
                dir
            } else {
                ctx.runtime_fatal(&msg, Some(dir));
                F_ZERO
            }
        })
    }

    /// Enhancement-759 (speed hunt F2 of 2026-09-28): what an event needs to
    /// know about the point it is evaluated at, beside the previous
    /// evaluation's value of its expression.
    ///
    /// An event's edge used to be detected between consecutive EVALUATIONS,
    /// whatever point they belonged to. Three things followed. The edge was
    /// gone by the CONVERGED iterate of the point that crossed (its
    /// successors compare with each other), which is the one iterate whose
    /// step bound the simulator reads, so nothing could land the step on the
    /// crossing. A rejected attempt's iterate served as "previous" for the
    /// retry, so a retry that sat before the crossing saw a phantom edge back
    /// across it. And the body ran at whichever attempt first saw the edge,
    /// so a `$strobe` or `$finish` in it was discarded with a rejected
    /// attempt.
    ///
    /// The simulator counts accepted points (`$osdi$point`, ngspice's
    /// osdiaccept.c) and serves the step under way (`$osdi$delta`, E-678).
    /// The value the expression had at the last ACCEPTED point is kept
    /// (`acc`): when the count changes, the previous evaluation was the
    /// accepted point's; while the count stands -- the iterates of one
    /// attempt, a rejected attempt and its retry -- the sample stands. The
    /// first iterate of an attempt is the one whose time is new. Outside a
    /// transient past t = 0, or where the count is not served, `acc` is not
    /// used and the events keep E-587's evaluation-to-evaluation rules.
    fn event_prev_sample(&mut self, current: Value) -> EventSample {
        let (raw_prev, idx) = self.new_event_state();
        let (raw_acc, acc_idx) = self.new_event_state();
        let (raw_point, pt_idx) = self.new_event_state();
        let is_initial = self.ctx.use_param(ParamKind::IsInitialStep);
        let prev_eval = self.ctx.ins().select(is_initial, current, raw_prev);
        let key = self.ctx.sconst("$osdi$point");
        let minus_one = self.ctx.fconst(-1.0);
        let point = self.ctx.call1(CallBackKind::SimParamOpt, &[key, minus_one]);
        let served = self.ctx.ins().fge(point, F_ZERO);
        let point_changed = self.ctx.ins().fne(point, raw_point);
        let new_point = self.ctx.ins().select(is_initial, TRUE, point_changed);
        let acc = self.ctx.ins().select(new_point, prev_eval, raw_acc);
        let (raw_time, time_idx) = self.new_event_state();
        let abstime = self.ctx.use_param(ParamKind::Abstime);
        let time_changed = self.ctx.ins().fne(abstime, raw_time);
        let first_iter = self.ctx.ins().select(new_point, TRUE, time_changed);
        let name = self.ctx.sconst("tran");
        let tran_hit = self.ctx.call1(CallBackKind::Analysis, &[name]);
        let zero = self.ctx.iconst(0);
        let is_tran = self.ctx.ins().ine(tran_hit, zero);
        let t_pos = self.ctx.ins().fgt(abstime, F_ZERO);
        let in_tran = self.ctx.ins().select(is_tran, t_pos, FALSE);
        let accepted_rule = self.ctx.ins().select(in_tran, served, FALSE);
        self.ctx.def_place(PlaceKind::EventState(idx), current);
        self.ctx.def_place(PlaceKind::EventState(acc_idx), acc);
        self.ctx.def_place(PlaceKind::EventState(pt_idx), point);
        self.ctx.def_place(PlaceKind::EventState(time_idx), abstime);
        EventSample {
            prev_eval,
            prev_idx: idx,
            current,
            acc,
            is_initial,
            in_tran,
            new_point,
            first_iter,
            accepted_rule,
        }
    }

    /// The `cross` edge between `prev` and `current`, filtered by `dir`
    /// (E-587's rule: strict on the previous side, inclusive on the current).
    fn cross_edge(&mut self, prev: Value, current: Value, dir: Option<Value>) -> Value {
        let and = |ctx: &mut LoweringCtx, a: Value, b: Value| ctx.ins().select(a, b, FALSE);
        let or = |ctx: &mut LoweringCtx, a: Value, b: Value| ctx.ins().select(a, TRUE, b);
        let prev_lt = self.ctx.ins().flt(prev, F_ZERO);
        let cur_ge = self.ctx.ins().fge(current, F_ZERO);
        let rising = and(self.ctx, prev_lt, cur_ge);
        let prev_gt = self.ctx.ins().fgt(prev, F_ZERO);
        let cur_le = self.ctx.ins().fle(current, F_ZERO);
        let falling = and(self.ctx, prev_gt, cur_le);
        let either = or(self.ctx, rising, falling);
        match dir {
            Some(dir) => {
                let dir_pos = self.ctx.ins().fgt(dir, F_ZERO);
                let dir_neg = self.ctx.ins().flt(dir, F_ZERO);
                let fired_pos = and(self.ctx, dir_pos, rising);
                let fired_neg = and(self.ctx, dir_neg, falling);
                let dir_le = self.ctx.ins().fle(dir, F_ZERO);
                let dir_ge = self.ctx.ins().fge(dir, F_ZERO);
                let dir_is_zero = and(self.ctx, dir_le, dir_ge);
                let fired_either = and(self.ctx, dir_is_zero, either);
                let fired_pos_or_neg = or(self.ctx, fired_pos, fired_neg);
                or(self.ctx, fired_pos_or_neg, fired_either)
            }
            None => either,
        }
    }

    /// Enhancement-759: land the simulator on the crossing, and say whether
    /// this iterate asked for it. `present` says the crossing lies between
    /// the last accepted sample `acc` and `current`; the crossing sits
    /// `delta * acc / (acc - current)` after the last accepted point, `delta`
    /// the step under way. When this attempt overshoots that by more than
    /// half the margin -- the event's `time_tol`, else a thousandth of the
    /// step -- a LANDING REQUEST is written into the bound-step slot as
    /// `-(2 + t)`, `t` the offset to land at (the crossing plus the margin), a
    /// value no bound can be (a bound is positive, E-24's discontinuity
    /// sentinel is -1). ngspice's OSDItrunc turns it into a forced rejection
    /// of this attempt and a retry of exactly that size, however close to the
    /// step it is. The earliest of several requests in one evaluation wins.
    /// `present` is already gated by `event_landing_context`'s rules (no
    /// request from a retry's first iterate, a landing attempt, or an attempt
    /// a body fired in); none either when `|current|` is within `expr_tol`.
    /// LRM 5.10.3: the simulator shall place a timepoint at the crossing,
    /// within the tolerances; it used to resolve it to the step grid.
    fn localise_crossing(
        &mut self,
        present: Value,
        acc: Value,
        current: Value,
        time_tol: Option<ExprId>,
        expr_tol: Option<ExprId>,
        lc: &LandingCtx,
    ) -> Value {
        let and = |ctx: &mut LoweringCtx, a: Value, b: Value| ctx.ins().select(a, b, FALSE);
        let zero = self.ctx.fconst(0.0);
        let key = self.ctx.sconst("$osdi$delta");
        let delta = self.ctx.call1(CallBackKind::SimParamOpt, &[key, F_ZERO]);
        let have_delta = self.ctx.ins().fgt(delta, zero);
        let diff = self.ctx.ins().fsub(acc, current);
        let frac = self.ctx.ins().fdiv(acc, diff);
        let off = self.ctx.ins().fmul(delta, frac);
        let ttol = match time_tol {
            Some(e) => self.lower_expr(e),
            None => zero,
        };
        // the margin: time_tol when given, else a thousandth of the step; never
        // below a billionth of it
        let rel = self.ctx.fconst(1.0e-3);
        let m_rel = self.ctx.ins().fmul(delta, rel);
        let tol_given = self.ctx.ins().fgt(ttol, zero);
        let margin = self.ctx.ins().select(tol_given, ttol, m_rel);
        let rel_floor = self.ctx.fconst(1.0e-9);
        let m_floor = self.ctx.ins().fmul(delta, rel_floor);
        let below_floor = self.ctx.ins().flt(margin, m_floor);
        let margin = self.ctx.ins().select(below_floor, m_floor, margin);
        let target = self.ctx.ins().fadd(off, margin);
        let over = self.ctx.ins().fsub(delta, target);
        let half = self.ctx.fconst(0.5);
        let half_margin = self.ctx.ins().fmul(margin, half);
        // a landing attempt is judged against the margin its request used (a
        // whole one, not half): the margin follows the step, and the landing
        // step is shorter than the step that asked, so an exact landing --
        // the requested margin past the crossing -- would look overshot by
        // the shorter margin and be refined for nothing
        let stored = self.ctx.use_param(ParamKind::EventState(lc.margin_idx));
        let threshold = self.ctx.ins().select(lc.landing_att, stored, half_margin);
        let overshot = self.ctx.ins().fgt(over, threshold);
        let etol = match expr_tol {
            Some(e) => self.lower_expr(e),
            None => zero,
        };
        let neg_cur = self.ctx.ins().fneg(current);
        let cur_neg = self.ctx.ins().flt(current, zero);
        let acur = self.ctx.ins().select(cur_neg, neg_cur, current);
        let outside = self.ctx.ins().fgt(acur, etol);
        let refine = and(self.ctx, present, have_delta);
        let refine = and(self.ctx, refine, overshot);
        let refine = and(self.ctx, refine, outside);
        let two = self.ctx.fconst(2.0);
        let enc = self.ctx.ins().fadd(two, target);
        let request = self.ctx.ins().fneg(enc);
        let cur_bound = self.ctx.use_place(PlaceKind::BoundStep);
        let minus_one = self.ctx.fconst(-1.0);
        let has_req = self.ctx.ins().flt(cur_bound, minus_one);
        let mine_later = self.ctx.ins().flt(request, cur_bound);
        let keep_old = and(self.ctx, has_req, mine_later);
        let chosen = self.ctx.ins().select(keep_old, cur_bound, request);
        let bound = self.ctx.ins().select(refine, chosen, cur_bound);
        self.ctx.def_place(PlaceKind::BoundStep, bound);
        let margin_next = self.ctx.ins().select(refine, margin, stored);
        self.ctx.def_place(PlaceKind::EventState(lc.margin_idx), margin_next);
        refine
    }

    /// Enhancement-759: the module's attempt flags (see `HirInterner::
    /// event_attempt_flags`), allocated on first use. Returns the slot
    /// indices (fired, requested, stamp).
    fn event_attempt_flags(&mut self) -> (u32, u32, u32) {
        if let Some(slots) = self.ctx.intern.event_attempt_flags {
            return slots;
        }
        let (_, fired) = self.new_event_state();
        let (_, requested) = self.new_event_state();
        let (_, stamp) = self.new_event_state();
        self.ctx.intern.event_attempt_flags = Some((fired, requested, stamp));
        (fired, requested, stamp)
    }

    /// Enhancement-759: what a `cross`/`above` may do at this iterate. The
    /// edge stays E-587's, between consecutive evaluations, with these rules
    /// in a transient where the accepted-point count is served:
    ///
    /// * a RETRY's first iterate (`retry`: the time changed, no point was
    ///   accepted) is skipped -- ngspice starts a redone attempt's Newton
    ///   iteration from the REJECTED attempt's solution, so the expression
    ///   this iterate sees is that attempt's (past the crossing that made it
    ///   ask, or wherever the LTE rejection left it), not a value at the new
    ///   time. The iterate neither fires nor requests, and the "previous
    ///   evaluation" the next iterate is compared against is the last
    ///   ACCEPTED sample, so an edge the landing reaches reappears there --
    ///   which is where the body belongs, its `$abstime` the crossing's --
    ///   and a retry that landed short sees no phantom edge back across the
    ///   threshold;
    /// * a LANDING ATTEMPT (a retry this event asked for) may ask ONCE more
    ///   when it still overshoots the crossing by more than half the margin
    ///   -- the linear interpolation over a curved expression (a sine over a
    ///   60 ns step) lands 0.2 ns past it, the second interpolation, over
    ///   the short interval, within the margin; the refinement's landing
    ///   makes no request of its own (the pending slot carries the
    ///   generation: 1 a request, 2 a refinement);
    /// * an iterate that asks for a landing does not fire -- the attempt is
    ///   about to be redone at the crossing;
    /// * the module's ATTEMPT FLAGS: once any body has fired in this attempt,
    ///   no event asks for a landing until the attempt is over -- an
    ///   interpolation over an attempt whose bodies changed the model (a
    ///   reset that drops the expression through a second threshold at the
    ///   same instant) locates nothing, and the crossing fires as E-587 did;
    ///   and once any event has asked, no later body fires in the attempt,
    ///   which is being discarded;
    /// * a request ngspice DECLINED -- the point it asked to redo was
    ///   accepted instead (the landing would sit under the step floor, E-504,
    ///   or the step is already at its minimum) -- has passed the crossing
    ///   without the body: it runs at the next point's first iterate, on the
    ///   accepted solution (`fire_declined`), as E-587's rule would have run
    ///   it one point earlier;
    /// * a landing that fell SHORT of its crossing (the expression is not
    ///   linear over the step: an exponential reset) is not chased -- the
    ///   next attempt makes no request and the crossing fires where it
    ///   appears (`short_idx`: 2 written by the short landing, 1 while the
    ///   attempt after it runs, 0 again after that).
    ///
    /// Everything else (the operating point, dc sweeps, a simulator without
    /// the count) is as before.
    fn event_landing_context(&mut self, smp: &EventSample) -> LandingCtx {
        let and = |ctx: &mut LoweringCtx, a: Value, b: Value| ctx.ins().select(a, b, FALSE);
        let (raw_pending, pend_idx) = self.new_event_state();
        let (raw_landing, land_idx) = self.new_event_state();
        let (raw_short, short_idx) = self.new_event_state();
        let (_, margin_idx) = self.new_event_state();
        let (fired_idx, req_idx, stamp_idx) = self.event_attempt_flags();
        let zero = self.ctx.fconst(0.0);
        let one = self.ctx.fconst(1.0);
        let two = self.ctx.fconst(2.0);
        let not_new = self.ctx.ins().select(smp.new_point, FALSE, TRUE);
        let retry = and(self.ctx, smp.first_iter, not_new);
        let retry = and(self.ctx, retry, smp.accepted_rule);
        let pending = self.ctx.ins().fgt(raw_pending, zero);
        let landing_start = and(self.ctx, retry, pending);
        // the generation of the landing under way: what the request wrote
        let gen_start = self.ctx.ins().select(landing_start, raw_pending, zero);
        let gen_att = self.ctx.ins().select(smp.first_iter, gen_start, raw_landing);
        let refinement = self.ctx.ins().fgt(gen_att, one);
        // a declined request: the point was accepted with the request standing
        let declined = and(self.ctx, smp.new_point, pending);
        let declined = and(self.ctx, declined, smp.accepted_rule);
        // a landing that fell short holds the next attempt back
        let short_first = self.ctx.ins().feq(raw_short, two);
        let short_later = self.ctx.ins().fgt(raw_short, zero);
        let short_hold = self.ctx.ins().select(smp.first_iter, short_first, short_later);
        let landing_att = self.ctx.ins().fgt(gen_att, zero);
        self.ctx.def_place(PlaceKind::EventState(land_idx), gen_att);
        // the next iterate of a retry is compared against the accepted sample
        let prev_next = self.ctx.ins().select(retry, smp.acc, smp.current);
        self.ctx.def_place(PlaceKind::EventState(smp.prev_idx), prev_next);
        // the attempt flags, valid while stamped with this attempt's time
        let abstime = self.ctx.use_param(ParamKind::Abstime);
        let stamp = self.ctx.use_place(PlaceKind::EventState(stamp_idx));
        let same_attempt = self.ctx.ins().feq(stamp, abstime);
        let raw_fired = self.ctx.use_place(PlaceKind::EventState(fired_idx));
        let raw_req = self.ctx.use_place(PlaceKind::EventState(req_idx));
        let fired_any = self.ctx.ins().select(same_attempt, raw_fired, zero);
        let req_any = self.ctx.ins().select(same_attempt, raw_req, zero);
        let fired_any = self.ctx.ins().fgt(fired_any, zero);
        let req_any = self.ctx.ins().fgt(req_any, zero);
        let not_retry = self.ctx.ins().select(retry, FALSE, TRUE);
        let not_refinement = self.ctx.ins().select(refinement, FALSE, TRUE);
        let not_fired_any = self.ctx.ins().select(fired_any, FALSE, TRUE);
        let not_short = self.ctx.ins().select(short_hold, FALSE, TRUE);
        let may_request = and(self.ctx, smp.accepted_rule, not_retry);
        let may_request = and(self.ctx, may_request, not_refinement);
        let may_request = and(self.ctx, may_request, not_fired_any);
        let may_request = and(self.ctx, may_request, not_short);
        let not_req_any = self.ctx.ins().select(req_any, FALSE, TRUE);
        let may_fire = and(self.ctx, not_retry, not_req_any);
        // the short-landing memory: 1 while the attempt after a short landing
        // runs (a landing attempt itself rewrites it, see `event_landing_record`)
        let hold_next = self.ctx.ins().select(short_hold, one, zero);
        self.ctx.def_place(PlaceKind::EventState(short_idx), hold_next);
        LandingCtx {
            may_request,
            may_fire,
            fire_declined: declined,
            landing_att,
            request_gen: self.ctx.ins().select(landing_att, two, one),
            first_iter: smp.first_iter,
            pend_idx,
            margin_idx,
            short_idx,
            fired_idx,
            req_idx,
            stamp_idx,
            abstime,
        }
    }

    /// Enhancement-759: records this event's request and firing in its
    /// pending slot and the module's attempt flags, and whether a landing
    /// attempt fell short of its crossing (`present`: the crossing lies
    /// between the accepted sample and this iterate; a landing attempt's
    /// last iterate decides).
    fn event_landing_record(
        &mut self,
        lc: &LandingCtx,
        present: Value,
        requested: Value,
        fired: Value,
    ) {
        let zero = self.ctx.fconst(0.0);
        let one = self.ctx.fconst(1.0);
        let two = self.ctx.fconst(2.0);
        let pend_next = self.ctx.ins().select(requested, lc.request_gen, zero);
        self.ctx.def_place(PlaceKind::EventState(lc.pend_idx), pend_next);
        let not_first = self.ctx.ins().select(lc.first_iter, FALSE, TRUE);
        let judge = self.ctx.ins().select(lc.landing_att, not_first, FALSE);
        let short_now = self.ctx.ins().select(present, zero, two);
        let cur_short = self.ctx.use_place(PlaceKind::EventState(lc.short_idx));
        let short_next = self.ctx.ins().select(judge, short_now, cur_short);
        self.ctx.def_place(PlaceKind::EventState(lc.short_idx), short_next);
        let stamp = self.ctx.use_place(PlaceKind::EventState(lc.stamp_idx));
        let same_attempt = self.ctx.ins().feq(stamp, lc.abstime);
        let raw_fired = self.ctx.use_place(PlaceKind::EventState(lc.fired_idx));
        let raw_req = self.ctx.use_place(PlaceKind::EventState(lc.req_idx));
        let fired_any = self.ctx.ins().select(same_attempt, raw_fired, zero);
        let req_any = self.ctx.ins().select(same_attempt, raw_req, zero);
        let fired_next = self.ctx.ins().select(fired, one, fired_any);
        let req_next = self.ctx.ins().select(requested, one, req_any);
        self.ctx.def_place(PlaceKind::EventState(lc.fired_idx), fired_next);
        self.ctx.def_place(PlaceKind::EventState(lc.req_idx), req_next);
        self.ctx.def_place(PlaceKind::EventState(lc.stamp_idx), lc.abstime);
    }

    fn lower_cross(
        &mut self,
        expr: ExprId,
        dir: Option<ExprId>,
        time_tol: Option<ExprId>,
        expr_tol: Option<ExprId>,
    ) -> Value {
        let current = self.lower_expr(expr);
        let smp = self.event_prev_sample(current);
        let dir = match dir {
            Some(dir) => {
                let dir = self.lower_expr(dir);
                Some(self.guard_event_direction("@(cross)", dir))
            }
            None => None,
        };
        let and = |ctx: &mut LoweringCtx, a: Value, b: Value| ctx.ins().select(a, b, FALSE);
        // Enhancement-759: the landing context (see `event_landing_context`)
        let lc = self.event_landing_context(&smp);
        // LRM 5.10.3.2 (events audit): "The cross() function will not
        // generate events for non-transient analyses, such as ac, dc, or
        // noise" and it "can only generate an event after the simulation time
        // has advanced from zero". The FIRED bool is gated -- not the state,
        // which keeps tracking through DC and the operating point.
        let fired = self.cross_edge(smp.prev_eval, current, dir);
        let fired = and(self.ctx, fired, smp.in_tran);
        // the crossing between the accepted sample and this iterate is what
        // the step is landed on
        let present = self.cross_edge(smp.acc, current, dir);
        let present = and(self.ctx, present, smp.in_tran);
        let ask = and(self.ctx, present, lc.may_request);
        let requested = self.localise_crossing(ask, smp.acc, current, time_tol, expr_tol, &lc);
        let not_requested = self.ctx.ins().select(requested, FALSE, TRUE);
        let fired = and(self.ctx, fired, not_requested);
        let fired = and(self.ctx, fired, lc.may_fire);
        let fired = self.ctx.ins().select(lc.fire_declined, TRUE, fired);
        self.event_landing_record(&lc, present, requested, fired);
        fired
    }

    /// Lowers `@(timer(t0, period))`: fires on the first evaluation whose `Abstime >=` the
    /// next scheduled fire time (initially `t0`); a periodic timer (`period` present)
    /// reschedules by one `period` each time it fires, a one-shot timer (`period` absent)
    /// reschedules to `INFINITY` (never fires again). Like `above`/`cross`, detection happens
    /// at `eval()`-call granularity -- the simulator's own (adaptive) timestep, not an
    /// exact forced breakpoint; see `Enhancement-8.md`'s known limitations for why exact
    /// breakpoint-forcing (`CKTsetBreak`) was descoped in favor of this simpler, still-real
    /// mechanism.
    /// LRM 5.10.3: `enable` is an integer expression; the event is live only
    /// while it is non-zero. Absent, the event is always live.
    ///
    /// Combined with `bool_and`, NOT a raw `iand`. Both operands are i1 values
    /// and a literal `enable` const-folds -- and the const evaluator has no Bool
    /// arm for `iand`, so folding one crashed the compiler outright. That is the
    /// same reason `Event::Or` below uses `bool_or` rather than a raw `ior`.
    ///
    /// The gate is applied to the FIRED bool rather than to the event's internal
    /// state, so a disabled event keeps its schedule rather than restarting: a
    /// `@(timer)` held low resumes on its original grid, and a `@(cross)` keeps
    /// tracking the sign of its expression, so re-enabling never replays a
    /// crossing that happened while it was disabled -- only crossings that occur
    /// while enabled fire, which is what LRM 5.10.3.2 asks for.
    fn gate_on_enable(&mut self, fired: Value, enable: Option<ExprId>) -> Value {
        let Some(enable) = enable else { return fired };
        // Already an i1: inference requires `enable` as a `Condition`, so the
        // non-zero test is the cast to `Type::Bool` it inserted.
        let live = self.lower_expr(enable);
        bool_and(self.ctx, fired, live)
    }

    fn lower_timer(&mut self, t0: ExprId, period: Option<ExprId>) -> Value {
        let t0 = self.lower_expr(t0);
        let (raw_next, idx) = self.new_event_state();
        let is_initial = self.ctx.use_param(ParamKind::IsInitialStep);
        let next = self.ctx.make_select(is_initial, |_, branch| if branch { t0 } else { raw_next });

        let abstime = self.ctx.use_param(ParamKind::Abstime);

        // Enhancement-427: compare with a relative tolerance, not exactly.
        //
        // `next` is built by REPEATED ADDITION (`fadd` below, once per fire), so
        // after N periods it has accumulated N roundings and is a couple of ULP
        // away from the exact N*period. When a run's `tstop` is an exact
        // multiple of the period -- the ordinary case, `tran 2n 1u` with a 10 ns
        // timer -- the schedule lands just PAST tstop and the last event never
        // fires: 100 ticks instead of 101, silently. Measured for dt = 1e-8,
        // 2e-8, 3e-8 and 4e-8 (over by 3e-22..6e-22), while 5e-9, 1e-7 and 1e-9
        // happen to accumulate at or below tstop and were correct -- which is
        // why it looked sporadic. `@(final_step)` fires at that same instant, so
        // the timepoint IS reached; only this comparison rejects it.
        //
        // 1e-12 relative is ~4 orders of magnitude above the observed drift and
        // far below any physical timescale (1 ps early on a 1 s period). Written
        // as a MULTIPLY rather than `next - eps` so that a one-shot timer that
        // has already fired -- `next` is INFINITY -- stays INFINITY instead of
        // becoming INF-INF = NaN. A `next` of exactly 0 (t0 = 0) is unmoved.
        let tol = self.ctx.fconst(1.0 - 1e-12);
        let threshold = self.ctx.ins().fmul(next, tol);
        let fired = self.ctx.ins().fge(abstime, threshold);

        let rescheduled = if let Some(period) = period {
            let period = self.lower_expr(period);
            // LRM 5.10.3.3: "If the period expression evaluates to a value less
            // than or equal to 0.0, the timer shall trigger only once at the
            // specified start_time." A non-positive period is not an error -- it
            // is how a ONE-SHOT is written when the period is computed rather
            // than omitted. `@(timer(t0))` already means exactly that, and this
            // routes to the same INFINITY sentinel.
            //
            // Decided at RUN TIME rather than by folding, because the LRM speaks
            // of what the expression "evaluates to": `@(timer(t0, p))` with a
            // parameter `p` must fire once when p <= 0 and repeat when it is
            // raised, without recompiling.
            let zero = self.ctx.fconst(0.0);
            let repeats = self.ctx.ins().fgt(period, zero);
            let periodic = self.ctx.ins().fadd(next, period);
            self.ctx.make_select(repeats, |_, branch| if branch { periodic } else { INFINITY })
        } else {
            INFINITY
        };
        let new_next = self.ctx.make_select(fired, |_, branch| if branch { rescheduled } else { next });

        self.ctx.def_place(PlaceKind::EventState(idx), new_next);

        // Enhancement-415: stop the solver stepping OVER the event.
        //
        // A timer has no signal to watch, so unlike `cross`/`above` -- where a sign
        // change across an accepted interval is still noticed -- an event the solver
        // never stops near simply never happens. The simulator is not told when the
        // next one is due, and a compact model cannot register a breakpoint, so a
        // 10 ns timer in a run whose natural step is 1 us fired 109 times out of
        // 1000: 891 events silently dropped, and a model implementing a clock or a
        // sampled system ran at whatever rate the step controller happened to pick.
        //
        // The step bound already plumbed through for `$bound_step` (Enhancement-24)
        // is exactly the channel needed: asking for at most `next_event - now`
        // makes the following timepoint land on the event. Combined with `min` --
        // never a bare overwrite -- so a model's own `$bound_step`, and a second
        // timer, both still hold. A pending time of INFINITY (a one-shot that has
        // already fired) is not smaller than the incumbent bound and so changes
        // nothing.
        let zero = self.ctx.fconst(0.0);
        let dt = self.ctx.ins().fsub(new_next, abstime);
        let ahead = self.ctx.ins().fgt(dt, zero);
        let inf = self.ctx.fconst(f64::INFINITY);
        let cand = self.ctx.make_select(ahead, |_, branch| if branch { dt } else { inf });
        let cur = self.ctx.use_place(PlaceKind::BoundStep);
        let tighter = self.ctx.ins().flt(cand, cur);
        let bound = self.ctx.make_select(tighter, |_, branch| if branch { cand } else { cur });
        self.ctx.def_place(PlaceKind::BoundStep, bound);

        fired
    }

    fn lower_case(&mut self, kind: CaseKind, discr: ExprId, case_arms: &[Case]) {
        // Enhancement-33: a `case` over an array (literal or whole-array variable — type
        // inference guarantees every case item has the identical array type) compares
        // ELEMENT-WISE: the arm matches iff all elements are equal. The discriminant and
        // each item are lowered to their element `Value`s and the per-element equalities
        // are AND-combined into the single branch condition; everything else (block
        // structure, default handling) is shared with the scalar path, which is just the
        // one-element case. Previously an array discriminant hit `todo!()` and crashed.
        // Enhancement-647: an integer discriminant compared with a real item carries a
        // cast to real (inference recorded it, `lower_expr` applies it), so the
        // comparison's type is the cast's target, not the expression's own.
        let discr_ty = match self.body.needs_cast(discr) {
            Some((_, dst)) => dst.clone(),
            None => self.body.expr_type(discr),
        };
        let is_array = matches!(discr_ty, Type::Array { .. });
        let discr_op = match discr_ty.base_type() {
            Type::Real => Opcode::Feq,
            Type::Integer => Opcode::Ieq,
            Type::Bool => Opcode::Beq,
            Type::String => Opcode::Seq,
            ty => unreachable!("Invalid type {}", ty),
        };
        let discr_vals = if is_array {
            self.lower_array_elems(discr)
        } else {
            vec![self.lower_expr(discr)]
        };
        let end = self.ctx.create_block();

        for arm in case_arms {
            let Case { cond, body, masks } = arm;
            // TODO does default mean that further cases are ignored?
            // standard seems to suggest that no matter where the default case is placed that all
            // other conditions are tested prior
            let vals = match cond {
                CaseCond::Vals(vals) => vals,
                CaseCond::Default => continue,
            };

            // Create the body block
            let body_head = self.ctx.create_block();

            for (val_idx, val) in vals.iter().enumerate() {

                // Enhancement-78: a casex/casez item literal with don't-care
                // digits compares only its care bits -- (discr & care) ==
                // (item & care); validation guarantees an integer scalar
                let mask = if kind == CaseKind::Case {
                    CaseMask::FULL
                } else {
                    masks.get(val_idx).copied().unwrap_or(CaseMask::FULL)
                };

                // Lower the condition (val == discriminant); for arrays, all elements equal.
                //
                // The comparison opcode above comes from the DISCRIMINANT's type, so a real
                // discriminant emits `feq` and needs real item elements. An integer-literal
                // array item -- `case(r) {1}:` where `r` is a real array -- infers as an
                // *integer* array, and while inference does record a cast for it, that cast
                // lands on the item's array expression as a whole; `lower_array_elems`
                // decomposes the array and lowers each element on its own, so the cast never
                // reaches them and `feq` got an i32 ("invalid operation feq Int(1)" in
                // const-eval). Coerce the elements to match the opcode. Scalar items are
                // unaffected: they go through `lower_expr`, which applies the recorded cast.
                let val_elems = if is_array {
                    self.lower_array_elems_impl(*val, discr_op == Opcode::Feq)
                } else {
                    vec![self.lower_expr(*val)]
                };
                debug_assert_eq!(val_elems.len(), discr_vals.len());

                let old_loc = self.ctx.get_srcloc();
                self.ctx.set_srcloc(mir::SourceLoc::new(u32::from(*val) as i32 + 1));
                let mut cond = None;
                for (&val_, &discr_) in val_elems.iter().zip(&discr_vals) {
                    let (val_, discr_) = if mask.care != !0 && discr_op == Opcode::Ieq {
                        let care = self.ctx.iconst(mask.care);
                        (self.ctx.ins().iand(val_, care), self.ctx.ins().iand(discr_, care))
                    } else {
                        (val_, discr_)
                    };
                    let eq = self.ctx.ins().binary1(discr_op, val_, discr_);
                    cond = Some(match cond {
                        None => eq,
                        Some(acc) => bool_and(self.ctx, acc, eq),
                    });
                }
                let cond = cond.expect("case item with no elements");
                self.ctx.set_srcloc(old_loc);

                // Create the next block
                let next_block = self.ctx.create_block();
                self.ctx.ins().branch(cond, body_head, next_block, false);

                // Enhancement-291: the branch just emitted is the ONLY way into `next_block`, so all of its
                // predecessors are already known and it can be sealed right away. Leaving it
                // to the `ensured_sealed()` calls (top of the next iteration, or after the
                // default arm) breaks on the last item when the default arm's body itself
                // opens blocks -- `max`/`min`/`abs` lower to a select with real control flow
                // (`make_cond`) -- because the body leaves `position` on ITS merge block, so
                // the trailing `ensured_sealed()` seals that already-sealed block and this
                // one stays unsealed, tripping "block N is not sealed" when the builder is
                // finalized. `pow` and friends, which emit no branch, never exposed it.
                self.ctx.seal_block(next_block);

                self.ctx.switch_to_block(next_block);
            }

            self.ctx.seal_block(body_head);

            // lower the body
            let next = self.ctx.current_block();
            self.ctx.switch_to_block(body_head);
            self.lower_stmt(*body);
            self.ctx.ins().jump(end);
            self.ctx.switch_to_block(next);
        }

        if let Some(default_case) =
            case_arms.iter().find(|arm| matches!(arm.cond, CaseCond::Default))
        {
            self.lower_stmt(default_case.body);
        }

        // Enhancement-390: NO `ensured_sealed()` here, and none at the top of the
        // arm loop above. `ensured_sealed` seals the CURRENT block, which on the
        // first arm is still the CALLER's block -- and when a `case` is the first
        // statement of a `do-while` body that block is the loop's body head, which
        // must stay unsealed until the back edge is added. Sealing it here completed
        // its phis against the entry edge alone, so a variable updated in the loop
        // read back as its pre-loop value: `while (k < 3)` folded to a constant true
        // and the loop became `jmp` to itself. Every block this function creates is
        // sealed explicitly (`body_head` below, `next_block` per Enhancement-291,
        // and `end` here), so nothing needs the blanket call.
        self.ctx.ins().jump(end);

        self.ctx.seal_block(end);
        self.ctx.switch_to_block(end);
    }

    /// Lowers `while (cond) body`. `loop_end` and `loop_cond_head` are sealed
    /// only AFTER the body is lowered: a `break` adds an edge into `loop_end`
    /// and a `continue` into `loop_cond_head` (LRM 5.11), and sealing a block
    /// declares its predecessor set final.
    fn lower_loop(&mut self, cond: ExprId, lower_body: impl FnOnce(&mut Self)) {
        let loop_cond_head = self.ctx.create_block();
        let loop_body_head = self.ctx.create_block();
        let loop_end = self.ctx.create_block();

        self.ctx.ins().jump(loop_cond_head);
        self.ctx.switch_to_block(loop_cond_head);

        let cond = self.lower_expr(cond);
        self.ctx.ins().br_loop(cond, loop_body_head, loop_end);
        self.ctx.seal_block(loop_body_head);

        self.ctx.switch_to_block(loop_body_head);
        self.ctx.loop_scopes.push((loop_cond_head, loop_end));
        lower_body(self);
        self.ctx.loop_scopes.pop();
        self.ctx.ins().jump(loop_cond_head);

        self.ctx.seal_block(loop_cond_head);
        self.ctx.seal_block(loop_end);

        self.ctx.switch_to_block(loop_end);
    }

    /// Lowers `for (init; cond; incr) body` with the increment in its own
    /// block, so `continue` re-enters at the increment (LRM 5.11) rather than
    /// skipping it into an infinite loop.
    fn lower_for(&mut self, init: StmtId, cond: ExprId, incr: StmtId, body: StmtId) {
        self.lower_stmt(init);

        let loop_cond_head = self.ctx.create_block();
        let loop_body_head = self.ctx.create_block();
        let loop_incr_head = self.ctx.create_block();
        let loop_end = self.ctx.create_block();

        self.ctx.ins().jump(loop_cond_head);
        self.ctx.switch_to_block(loop_cond_head);

        let cond = self.lower_expr(cond);
        self.ctx.ins().br_loop(cond, loop_body_head, loop_end);
        self.ctx.seal_block(loop_body_head);

        self.ctx.switch_to_block(loop_body_head);
        self.ctx.loop_scopes.push((loop_incr_head, loop_end));
        self.lower_stmt(body);
        self.ctx.loop_scopes.pop();
        self.ctx.ins().jump(loop_incr_head);
        self.ctx.seal_block(loop_incr_head);

        self.ctx.switch_to_block(loop_incr_head);
        self.lower_stmt(incr);
        self.ctx.ins().jump(loop_cond_head);

        self.ctx.seal_block(loop_cond_head);
        self.ctx.seal_block(loop_end);

        self.ctx.switch_to_block(loop_end);
    }

    /// Lowers `do body while (cond);` (Enhancement-19): like `lower_loop`, but the body runs once
    /// before the first condition test. The body block is the loop header (it has both the entry
    /// edge and the back-edge from the condition), so it is sealed last.
    fn lower_do_while(&mut self, cond: ExprId, lower_body: impl FnOnce(&mut Self)) {
        let loop_body_head = self.ctx.create_block();
        let loop_cond_head = self.ctx.create_block();
        let loop_end = self.ctx.create_block();

        // enter the body unconditionally
        self.ctx.ins().jump(loop_body_head);
        self.ctx.switch_to_block(loop_body_head);
        // `continue` re-tests the condition, `break` leaves (LRM 5.11)
        self.ctx.loop_scopes.push((loop_cond_head, loop_end));
        lower_body(self);
        self.ctx.loop_scopes.pop();
        self.ctx.ins().jump(loop_cond_head);

        // then test the condition and loop back to the body if true
        self.ctx.switch_to_block(loop_cond_head);
        self.ctx.seal_block(loop_cond_head);
        let cond = self.lower_expr(cond);
        self.ctx.ins().br_loop(cond, loop_body_head, loop_end);
        self.ctx.seal_block(loop_body_head);
        self.ctx.seal_block(loop_end);

        self.ctx.switch_to_block(loop_end);
    }

    /// Lowers `repeat (count) body`. `count` is evaluated once (truncated to an
    /// integer, per the LRM) and `body` is executed that many times. Built as a
    /// counted loop with an integer counter carried by a header phi:
    ///
    /// ```text
    ///   entry:      n = int(count); jump cond_head
    ///   cond_head:  counter = phi [n (entry)], [dec (body_tail)]
    ///               br_loop counter > 0, body_head, loop_end
    ///   body_head:  <body>; dec = counter - 1; jump cond_head
    ///   loop_end:   ...
    /// ```
    fn lower_repeat(&mut self, count: ExprId, body: StmtId) {
        // Evaluate the count once, coerced to an integer (repeat truncates).
        let count_ty = self.body.expr_type(count);
        let mut n = self.lower_expr(count);
        if count_ty == Type::Real {
            n = self.ctx.insert_cast(n, &Type::Real, &Type::Integer);
        }
        let entry = self.ctx.current_block();

        let cond_head = self.ctx.create_block();
        let body_head = self.ctx.create_block();
        // The decrement lives in its own latch block so `continue` still
        // counts the iteration (LRM 5.11) instead of looping forever.
        let latch = self.ctx.create_block();
        let loop_end = self.ctx.create_block();

        self.ctx.ins().jump(cond_head);
        self.ctx.switch_to_block(cond_head);

        // Header phi placeholder for the counter; its definition is spliced in
        // at the top of `cond_head` once the back-edge value is known.
        let counter = self.ctx.func.make_param(0u32.into());
        let zero = self.ctx.iconst(0);
        let cond = self.ctx.ins().binary1(Opcode::Igt, counter, zero);
        self.ctx.ins().br_loop(cond, body_head, loop_end);
        self.ctx.seal_block(body_head);

        self.ctx.switch_to_block(body_head);
        self.ctx.loop_scopes.push((latch, loop_end));
        self.lower_stmt(body);
        self.ctx.loop_scopes.pop();
        self.ctx.ins().jump(latch);
        self.ctx.seal_block(latch);

        self.ctx.switch_to_block(latch);
        let one = self.ctx.iconst(1);
        let dec = self.ctx.ins().binary1(Opcode::Isub, counter, one);
        self.ctx.ins().jump(cond_head);
        self.ctx.seal_block(cond_head);
        self.ctx.seal_block(loop_end);

        // counter = phi [ (entry, n), (latch, dec) ], inserted at the top of
        // the loop header so it dominates the `counter > 0` test above.
        FuncCursor::new(&mut self.ctx.func.func)
            .at_first_inst(cond_head)
            .ins()
            .with_result(counter)
            .phi(&[(entry, n), (latch, dec)]);

        self.ctx.switch_to_block(loop_end);
    }

    fn contribute(&mut self, voltage_src: bool, write: BranchWrite, rhs: ExprId) {
        let is_zero = self.body.get_expr(rhs).is_zero();
        let is_noise_only = self.expr_is_noise_only(rhs);
        let rhs = self.lower_expr(rhs);
        self.contribute_value_(voltage_src, write, rhs, is_zero, is_noise_only)
    }

    /// Bug-hunt F7: is this contribution PURELY a noise source (a noise
    /// function call, possibly scaled/negated/summed with other noise calls)?
    ///
    /// LRM 4.6.4 makes noise functions ZERO in every large-signal analysis, so
    /// such a contribution carries no large-signal content -- and it must not
    /// flip the branch's voltage/current classification. BSIM4's access-region
    /// noise is the motivating case:
    ///
    ///     else begin V(d,di) <+ 0.0; end   // collapse hint (rdsMod = 0)
    ///     ...
    ///     I(di,d) <+ white_noise(4*`P_K*T*gdpr, "Rd");
    ///
    /// The unconditional noise line lowered AFTER the conditional voltage
    /// contribution and, through the last-write-wins `IsVoltageSrc` place,
    /// reclassified the branch as never-a-voltage-source: the collapse
    /// vanished from the topology, `di`/`si` floated, and the compiled BSIM4
    /// conducted exactly ZERO at every bias -- with no diagnostic anywhere.
    fn expr_is_noise_only(&self, expr: ExprId) -> bool {
        match self.body.get_expr(expr) {
            Expr::Call { fun: ResolvedFun::BuiltIn(builtin), .. } => matches!(
                builtin,
                BuiltIn::white_noise
                    | BuiltIn::flicker_noise
                    | BuiltIn::noise_table
                    | BuiltIn::noise_table_log
            ),
            Expr::UnaryOp { expr, .. } => self.expr_is_noise_only(expr),
            Expr::BinaryOp { lhs, rhs, op } => {
                use syntax::ast::BinaryOp::*;
                match op {
                    // a scaled noise source is still noise-only as long as ONE
                    // side is noise (noise * gain, noise / r); a SUM is
                    // noise-only only when both sides are
                    Multiplication | Division => {
                        self.expr_is_noise_only(lhs) || self.expr_is_noise_only(rhs)
                    }
                    Addition | Subtraction => {
                        self.expr_is_noise_only(lhs) && self.expr_is_noise_only(rhs)
                    }
                    _ => false,
                }
            }
            _ => false,
        }
    }

    /// Stamps `rhs_value` into `write`'s branch as a contribution, exactly like
    /// `V(write) <+ rhs_value` (or `I(write) <+ rhs_value` for current contributions),
    /// but taking an already-lowered MIR value instead of an `ExprId`. Used both by
    /// `contribute` (normal `<+` statements) and by indirect branch assignment, which
    /// contributes a fresh implicit unknown instead of an evaluated expression.
    fn contribute_value(
        &mut self,
        voltage_src: bool,
        write: BranchWrite,
        rhs: Value,
        is_zero: bool,
    ) {
        self.contribute_value_(voltage_src, write, rhs, is_zero, false)
    }

    fn contribute_value_(
        &mut self,
        voltage_src: bool,
        mut write: BranchWrite,
        rhs: Value,
        is_zero: bool,
        is_noise_only: bool,
    ) {
        let mut negate = false;
        if let BranchWrite::Unnamed { hi, lo } = &mut write {
            self.lower_contribute_unnamed_branch(&mut negate, hi, lo, voltage_src)
        }
        // Bug-hunt F7: a noise-only contribution to a branch that already has
        // a large-signal classification must not RECLASSIFY it (LRM 4.6.4:
        // noise is zero in large-signal analyses, so it carries no source
        // kind). A branch whose ONLY contributions are noise still gets its
        // classification defined below, exactly as before.
        // Round-4 audit: the question is whether a classification REACHES this
        // point, not whether the place exists. `get_place` is monotonic, so a
        // classification made in one arm of an `if` made its own SIBLING look
        // classified -- and a noise-only contribution alone in that sibling
        // (`else V(p,n) <+ white_noise(...)`) was suppressed, leaving the
        // branch a pure flow source and dropping the arm's noise entirely.
        // In an arm where nothing reaches, the contribution's own kind is the
        // only information there is: LRM 4.6.4 makes the noise zero in large
        // signal, so that arm is a 0 V source (5.6.1.3), which is a real
        // switch branch.
        let keep_classification = is_noise_only && self.ctx.classification_reaches(write);
        if !keep_classification {
            self.ctx.record_classification(write);
            self.ctx.def_place(PlaceKind::IsVoltageSrc(write), voltage_src.into());
        }

        let (mut hi, mut lo) = write.nodes(self.ctx.db);
        if voltage_src && is_zero {
            if matches!(write, BranchWrite::Named(_)) {
                self.lower_contribute_unnamed_branch(&mut negate, &mut hi, &mut lo, voltage_src)
            }
            // TODO: make this a place instead?
            self.ctx.call(CallBackKind::CollapseHint(hi, lo), &[]);
        }

        if !keep_classification {
            self.ctx.def_place(
                PlaceKind::Contribute { dst: write, reactive: false, voltage_src: !voltage_src },
                F_ZERO,
            );
        }

        if rhs == F_ZERO {
            return;
        }

        let place = PlaceKind::Contribute { dst: write, reactive: false, voltage_src };
        let old = self.ctx.use_place(place);
        let new = if negate {
            self.ctx.ins().fsub(old, rhs)
        } else if old == F_ZERO {
            rhs
        } else {
            self.ctx.ins().fadd(old, rhs)
        };
        self.ctx.def_place(place, new);
    }

    /// Lowers an indirect branch assignment `<dst> : <constraint_lhs> == <constraint_rhs>;`.
    ///
    /// Introduces one new free unknown `u`, contributes it into `branch` exactly like a
    /// normal `<+` contribution (reusing `contribute_value`, so the backend's existing
    /// voltage-src/current-src stamping - including automatic implicit current-unknown
    /// augmentation for voltage contributions - applies unchanged), and adds an implicit
    /// equation enforcing `constraint_lhs - constraint_rhs == 0`, which is solved for `u`.
    fn indirect_contribute(
        &mut self,
        voltage_src: bool,
        branch: BranchWrite,
        constraint_lhs: ExprId,
        constraint_rhs: ExprId,
    ) {
        let idx = self.ctx.intern.indirect_branch_equations.len() as u32;
        let (eq, u) =
            self.ctx.implicit_equation(crate::ImplicitEquationKind::IndirectBranch(idx));
        self.ctx.intern.indirect_branch_equations.push(eq);

        self.contribute_value(voltage_src, branch, u, false);

        let lhs = self.lower_expr(constraint_lhs);
        let rhs = self.lower_expr(constraint_rhs);
        let residual = self.ctx.ins().fsub(lhs, rhs);
        self.ctx.def_resist_residual(residual, eq);
    }

    fn lower_contribute_unnamed_branch(
        &mut self,
        negate: &mut bool,
        hi: &mut Node,
        lo: &mut Option<Node>,
        voltage_src: bool,
    ) {
        let hi_ = self.ctx.node(*hi);
        let lo_ = lo.and_then(|lo| self.ctx.node(lo));
        (*hi, *lo) = match (hi_, lo_) {
            (Some(hi), None) => (hi, None),
            (None, Some(lo)) => {
                *negate = true;
                (lo, None)
            }
            (Some(hi), Some(lo)) => {
                let negate_known = self
                    .ctx
                    .get_place(PlaceKind::Contribute {
                        dst: BranchWrite::Unnamed { hi: lo, lo: Some(hi) },
                        reactive: false,
                        voltage_src,
                    })
                    .is_some();
                if negate_known {
                    *negate = true;
                    (lo, Some(hi))
                } else {
                    let param_kind = if voltage_src {
                        ParamKind::Voltage { hi, lo: Some(lo) }
                    } else {
                        ParamKind::Current(CurrentKind::Unnamed { hi, lo: Some(lo) })
                    };
                    self.ctx.use_param(param_kind);
                    (hi, Some(lo))
                }
            }
            (None, None) => unreachable!(),
        };
    }
}
