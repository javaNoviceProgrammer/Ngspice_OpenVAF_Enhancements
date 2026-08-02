use hir::{
    ArrayAssignElem, BranchWrite, Case, CaseCond, CaseKind, CaseMask, ContributeKind, Event, Expr,
    ExprId, GlobalEvent, Literal, Node, Stmt, StmtId, Type,
};
use mir::builder::InstBuilder;
use mir::cursor::{Cursor, FuncCursor};
use mir::{Opcode, Value, FALSE, F_ZERO, INFINITY, TRUE};

use crate::body::BodyLoweringCtx;
use crate::ctx::LoweringCtx;
use crate::{CallBackKind, CurrentKind, ParamKind, PlaceKind};

/// `a && b` built from already-lowered `Value`s (as opposed to
/// `BodyLoweringCtx::lower_bin_op`'s `BooleanAnd`, which lowers an as-yet
/// unlowered `ExprId` inside the branch) -- used by `lower_event_control`'s
/// `cross`/`above`/`timer` edge-detection logic, which combines several
/// already-computed boolean `Value`s rather than source-level expressions.
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
                let flat = self.lower_flat_array_index(&dims, &indices);
                for (k, var) in elems.into_iter().enumerate() {
                    let target = self.ctx.iconst(k as i32);
                    let is_k = self.ctx.ins().binary1(Opcode::Ieq, flat, target);
                    let cur = self.ctx.read_variable(var);
                    let new = self.ctx.make_select(is_k, move |_ctx, branch| if branch { v } else { cur });
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
                self.lower_stmt(init);
                self.lower_loop(cond, |s| {
                    s.lower_stmt(body);
                    s.lower_stmt(incr);
                });
            }
            Stmt::WhileLoop { cond, body } => self.lower_loop(cond, |s| s.lower_stmt(body)),
            Stmt::DoWhile { cond, body } => self.lower_do_while(cond, |s| s.lower_stmt(body)),
            Stmt::Repeat { count, body } => self.lower_repeat(count, body),
            Stmt::Case { kind, discr, case_arms } => self.lower_case(kind, discr, case_arms),
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

        self.ctx.make_cond(fired, |ctx, branch| {
            if branch {
                BodyLoweringCtx { ctx, body: self.body, path: self.path }.lower_stmt(body);
            }
        });
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
            Event::Cross { expr, dir, .. } => self.lower_cross(*expr, *dir),
            Event::Above { expr, .. } => self.lower_above(*expr),
            Event::Timer { t0, period, .. } => self.lower_timer(*t0, *period),
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
    fn new_event_state(&mut self) -> (Value, u32) {
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
    fn lower_above(&mut self, expr: ExprId) -> Value {
        let current = self.lower_expr(expr);
        let (raw_prev, idx) = self.new_event_state();
        let is_initial = self.ctx.use_param(ParamKind::IsInitialStep);
        let prev = self.ctx.make_select(is_initial, |_, branch| if branch { current } else { raw_prev });

        let was_below = self.ctx.ins().fle(prev, F_ZERO);
        let is_above = self.ctx.ins().fgt(current, F_ZERO);
        let fired = bool_and(self.ctx, was_below, is_above);

        self.ctx.def_place(PlaceKind::EventState(idx), current);
        fired
    }

    /// Lowers `@(cross(expr, dir))`: fires on any evaluation-to-evaluation zero-crossing of
    /// `expr` (same persistence granularity as `lower_above`), filtered by `dir` (`< 0`:
    /// falling only, `> 0`: rising only, `== 0`/absent: either -- `dir` is read as an
    /// ordinary runtime `Value`, not assumed constant, mirroring how `last_crossing`'s own
    /// `dir` argument is handled in `hir_lower::expr::lower_last_crossing`).
    fn lower_cross(&mut self, expr: ExprId, dir: Option<ExprId>) -> Value {
        let current = self.lower_expr(expr);
        let (raw_prev, idx) = self.new_event_state();
        let is_initial = self.ctx.use_param(ParamKind::IsInitialStep);
        let prev = self.ctx.make_select(is_initial, |_, branch| if branch { current } else { raw_prev });

        let prev_le = self.ctx.ins().fle(prev, F_ZERO);
        let cur_gt = self.ctx.ins().fgt(current, F_ZERO);
        let rising = bool_and(self.ctx, prev_le, cur_gt);

        let prev_ge = self.ctx.ins().fge(prev, F_ZERO);
        let cur_lt = self.ctx.ins().flt(current, F_ZERO);
        let falling = bool_and(self.ctx, prev_ge, cur_lt);

        let either = bool_or(self.ctx, rising, falling);

        let fired = if let Some(dir) = dir {
            let dir = self.lower_expr(dir);
            let dir_pos = self.ctx.ins().fgt(dir, F_ZERO);
            let dir_neg = self.ctx.ins().flt(dir, F_ZERO);
            let fired_pos = bool_and(self.ctx, dir_pos, rising);
            let fired_neg = bool_and(self.ctx, dir_neg, falling);
            let dir_le = self.ctx.ins().fle(dir, F_ZERO);
            let dir_ge = self.ctx.ins().fge(dir, F_ZERO);
            let dir_is_zero = bool_and(self.ctx, dir_le, dir_ge);
            let fired_either = bool_and(self.ctx, dir_is_zero, either);
            let fired_pos_or_neg = bool_or(self.ctx, fired_pos, fired_neg);
            bool_or(self.ctx, fired_pos_or_neg, fired_either)
        } else {
            either
        };

        self.ctx.def_place(PlaceKind::EventState(idx), current);
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
    fn lower_timer(&mut self, t0: ExprId, period: Option<ExprId>) -> Value {
        let t0 = self.lower_expr(t0);
        let (raw_next, idx) = self.new_event_state();
        let is_initial = self.ctx.use_param(ParamKind::IsInitialStep);
        let next = self.ctx.make_select(is_initial, |_, branch| if branch { t0 } else { raw_next });

        let abstime = self.ctx.use_param(ParamKind::Abstime);
        let fired = self.ctx.ins().fge(abstime, next);

        let rescheduled = if let Some(period) = period {
            let period = self.lower_expr(period);
            self.ctx.ins().fadd(next, period)
        } else {
            INFINITY
        };
        let new_next = self.ctx.make_select(fired, |_, branch| if branch { rescheduled } else { next });

        self.ctx.def_place(PlaceKind::EventState(idx), new_next);
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
        let discr_ty = self.body.expr_type(discr);
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

    fn lower_loop(&mut self, cond: ExprId, lower_body: impl FnOnce(&mut Self)) {
        let loop_cond_head = self.ctx.create_block();
        let loop_body_head = self.ctx.create_block();
        let loop_end = self.ctx.create_block();

        self.ctx.ins().jump(loop_cond_head);
        self.ctx.switch_to_block(loop_cond_head);

        let cond = self.lower_expr(cond);
        self.ctx.ins().br_loop(cond, loop_body_head, loop_end);
        self.ctx.seal_block(loop_body_head);
        self.ctx.seal_block(loop_end);

        self.ctx.switch_to_block(loop_body_head);
        lower_body(self);
        self.ctx.ins().jump(loop_cond_head);

        self.ctx.seal_block(loop_cond_head);

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
        lower_body(self);
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
        self.ctx.seal_block(loop_end);

        self.ctx.switch_to_block(body_head);
        self.lower_stmt(body);
        let one = self.ctx.iconst(1);
        let dec = self.ctx.ins().binary1(Opcode::Isub, counter, one);
        let body_tail = self.ctx.current_block();
        self.ctx.ins().jump(cond_head);
        self.ctx.seal_block(cond_head);

        // counter = phi [ (entry, n), (body_tail, dec) ], inserted at the top of
        // the loop header so it dominates the `counter > 0` test above.
        FuncCursor::new(&mut self.ctx.func.func)
            .at_first_inst(cond_head)
            .ins()
            .with_result(counter)
            .phi(&[(entry, n), (body_tail, dec)]);

        self.ctx.switch_to_block(loop_end);
    }

    fn contribute(&mut self, voltage_src: bool, write: BranchWrite, rhs: ExprId) {
        let is_zero = self.body.get_expr(rhs).is_zero();
        let rhs = self.lower_expr(rhs);
        self.contribute_value(voltage_src, write, rhs, is_zero)
    }

    /// Stamps `rhs_value` into `write`'s branch as a contribution, exactly like
    /// `V(write) <+ rhs_value` (or `I(write) <+ rhs_value` for current contributions),
    /// but taking an already-lowered MIR value instead of an `ExprId`. Used both by
    /// `contribute` (normal `<+` statements) and by indirect branch assignment, which
    /// contributes a fresh implicit unknown instead of an evaluated expression.
    fn contribute_value(
        &mut self,
        voltage_src: bool,
        mut write: BranchWrite,
        rhs: Value,
        is_zero: bool,
    ) {
        let mut negate = false;
        if let BranchWrite::Unnamed { hi, lo } = &mut write {
            self.lower_contribute_unnamed_branch(&mut negate, hi, lo, voltage_src)
        }
        self.ctx.def_place(PlaceKind::IsVoltageSrc(write), voltage_src.into());

        let (mut hi, mut lo) = write.nodes(self.ctx.db);
        if voltage_src && is_zero {
            if matches!(write, BranchWrite::Named(_)) {
                self.lower_contribute_unnamed_branch(&mut negate, &mut hi, &mut lo, voltage_src)
            }
            // TODO: make this a place instead?
            self.ctx.call(CallBackKind::CollapseHint(hi, lo), &[]);
        }

        self.ctx.def_place(
            PlaceKind::Contribute { dst: write, reactive: false, voltage_src: !voltage_src },
            F_ZERO,
        );

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
