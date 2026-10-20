use ahash::AHashMap;
use hir::{CompilationDB, ParamSysFun, Parameter, Type, Variable};
use lasso::Rodeo;
use mir::builder::InstBuilder;
use mir::cursor::{Cursor, FuncCursor};
use mir::{Function, Use, Value, FALSE, F_ZERO, TRUE};
use mir_build::{FunctionBuilder, FunctionBuilderContext};

use crate::ctx::LoweringCtx;
use crate::{CallBackKind, HirInterner, ParamKind, PlaceKind};

impl LoweringCtx<'_, '_> {
    /// Enhancement-909 (correctness campaign of 2026-10-19, F1): the persistent
    /// values a rejected attempt changed are put back at the retry.
    ///
    /// A variable keeps its value from one evaluation to the next (E-7), and a
    /// `timer` its next event time (E-8). Both were stored at the end of EVERY
    /// evaluation, so what a rejected transient attempt did to them survived
    /// into the attempt that replaced it: an event body that ran in the
    /// discarded attempt had run for good, and when the retry reached the same
    /// event it ran again. Two `cross` events crossing in one step at
    /// different margins (one asks to land, the other already fired) counted
    /// 30 crossings for 20; E-678 met the same in an `idt` reset.
    ///
    /// The attempt structure E-759 reads is used here for the module as a
    /// whole: ngspice's accepted-point count (`$osdi$point`) moved since the
    /// last evaluation -- a NEW POINT, whose previous evaluation belonged to
    /// the accepted attempt, so each value it stored is the accepted value and
    /// is copied aside -- or it did not while the time did -- a RETRY, which
    /// starts from those copies. Within an attempt, between its Newton
    /// iterates, nothing changes. Outside a transient past t = 0, and on a
    /// simulator that does not serve the count, the stored values are read as
    /// before (a dc sweep carries its variables, E-820).
    ///
    /// `targets` holds (the read, integer typed, its pre-existing uses);
    /// returns the value each read is to be replaced with.
    pub(crate) fn rollback_at_retry(&mut self, targets: &[(Value, bool, Vec<Use>)]) -> Vec<Value> {
        if targets.is_empty() {
            return Vec::new();
        }
        let and = |ctx: &mut LoweringCtx, a: Value, b: Value| ctx.ins().select(a, b, FALSE);
        let slot = |ctx: &mut LoweringCtx| {
            let idx = ctx.intern.event_state_count;
            ctx.intern.event_state_count += 1;
            (ctx.use_param(ParamKind::EventState(idx)), idx)
        };
        // the two callbacks are tracked, which is what keeps them in the
        // evaluation (the edit context is built without equations)
        let no_equations = std::mem::replace(&mut self.no_equations, false);
        let key = self.sconst("$osdi$point");
        let minus_one = self.fconst(-1.0);
        let point = self.call1(CallBackKind::SimParamOpt, &[key, minus_one]);
        let served = self.ins().fge(point, F_ZERO);
        let (raw_point, pt_idx) = slot(self);
        let is_initial = self.use_param(ParamKind::IsInitialStep);
        let point_changed = self.ins().fne(point, raw_point);
        let new_point = self.ins().select(is_initial, TRUE, point_changed);
        let (raw_time, time_idx) = slot(self);
        let abstime = self.use_param(ParamKind::Abstime);
        let time_changed = self.ins().fne(abstime, raw_time);
        let name = self.sconst("tran");
        let tran_hit = self.call1(CallBackKind::Analysis, &[name]);
        self.no_equations = no_equations;
        let zero = self.iconst(0);
        let is_tran = self.ins().ine(tran_hit, zero);
        let t_pos = self.ins().fgt(abstime, F_ZERO);
        let in_tran = and(self, is_tran, t_pos);
        let accepted_rule = and(self, in_tran, served);
        let not_new = self.ins().select(new_point, FALSE, TRUE);
        let retry = and(self, time_changed, not_new);
        let retry = and(self, retry, accepted_rule);
        let point_out = self.ins().optbarrier(point);
        self.def_output(PlaceKind::EventState(pt_idx), point_out);
        let time_out = self.ins().optbarrier(abstime);
        self.def_output(PlaceKind::EventState(time_idx), time_out);

        let mut rolled = Vec::with_capacity(targets.len());
        for &(stored, integer, _) in targets {
            let (raw_acc, acc_idx) = slot(self);
            let stored_f = if integer { self.ins().ifcast(stored) } else { stored };
            let acc_next = self.ins().select(new_point, stored_f, raw_acc);
            let acc_out = self.ins().optbarrier(acc_next);
            self.def_output(PlaceKind::EventState(acc_idx), acc_out);
            let restored = if integer { self.ins().ficast(raw_acc) } else { raw_acc };
            rolled.push(self.ins().select(retry, restored, stored));
        }
        rolled
    }
}

impl HirInterner {
    /// Enhancement-7: previously this unconditionally replaced every use of
    /// `ParamKind::HiddenState(var)` with `var`'s declared initializer
    /// expression -- meaning every analog-block variable was silently reset to
    /// its initial value on *every* evaluation, not just the first, with no
    /// real cross-evaluation persistence at all (the `HiddenState` parameter,
    /// which `openvaf/osdi/src/eval.rs` now wires up to genuinely read back
    /// the value stored by the previous evaluation, was discarded before
    /// codegen ever saw it). Now the initializer is applied only when
    /// `ParamKind::IsInitialStep` is true, and the genuine cross-evaluation
    /// read is used otherwise -- see `openvaf/osdi/src/inst_data.rs`'s
    /// `hidden_state`/`read_hidden_state`/`store_hidden_state`.
    ///
    /// Enhancement-820 (hunt 2026-10-08 F4): on `ParamKind::IsAnalysisStart`,
    /// not `IsInitialStep`. A `.dc temp` or `.dc @n1[p]` sweep re-fires the
    /// initial step at every point, and every variable read its initializer
    /// there: a counter read 1 at each point, where a source sweep carried it.
    /// LRM 4.6.2 carries variables from one dc point to the next.
    pub fn insert_var_init(
        &mut self,
        db: &CompilationDB,
        func: &mut Function,
        literals: &mut Rodeo,
    ) {
        let mut ctx = FunctionBuilderContext::default();
        let (builder, term) = FunctionBuilder::edit(func, literals, &mut ctx, false);
        let mut ctx = LoweringCtx::new(db, builder, true, self);

        // Enhancement-909: what every persistent value reads -- the stored one,
        // or at a retry its value at the last accepted point. The pre-existing
        // uses are snapshotted before anything below adds uses of its own.
        let mut targets = Vec::new();
        let mut slots = Vec::new();
        for (kind, param) in ctx.intern.params.clone().iter() {
            if ctx.dfg().value_dead(*param) {
                continue;
            }
            let integer = match *kind {
                ParamKind::HiddenState(var) => match var.ty(db) {
                    Type::Real => false,
                    Type::Integer => true,
                    _ => continue,
                },
                ParamKind::EventState(idx) if ctx.intern.rollback_event_slots.contains(&idx) => {
                    false
                }
                _ => continue,
            };
            let uses: Vec<_> = ctx.dfg().values.uses(*param).collect();
            slots.push(matches!(*kind, ParamKind::EventState(_)));
            targets.push((*param, integer, uses));
        }
        let rolled = ctx.rollback_at_retry(&targets);
        let target_of: AHashMap<Value, usize> =
            targets.iter().enumerate().map(|(i, t)| (t.0, i)).collect();
        // a variable no path of the body writes is stored as it was read
        for val in ctx.intern.outputs.values_mut() {
            if let Some(&i) = val.expand().and_then(|v| target_of.get(&v)) {
                *val = rolled[i].into();
            }
        }

        for (kind, param) in ctx.intern.params.clone().iter() {
            if let ParamKind::HiddenState(var) = *kind {
                if ctx.dfg().value_dead(*param) {
                    continue;
                }

                let init_val = ctx.lower_expr_body(var.init(db).borrow(), 0);
                let is_initial = ctx.use_param(ParamKind::IsAnalysisStart);

                // Snapshot the pre-existing uses of `*param` BEFORE building the
                // select below, since the select's own "else" branch also
                // references `*param` -- if that new use were included in the
                // rewrite it would create a self-referencing cycle. A rolled-back
                // variable's snapshot was taken before the rollback was built.
                let (stored, existing_uses) = match target_of.get(param) {
                    Some(&i) => (rolled[i], targets[i].2.clone()),
                    None => (*param, ctx.dfg().values.uses(*param).collect()),
                };

                // Enhancement-579: both values are already computed, so this is a
                // plain `select` -- one instruction per retained variable instead
                // of a three-block diamond and a phi, which for an array of N
                // elements (N hidden-state variables) put 3N blocks into the
                // evaluation function before the body was even lowered.
                let selected = ctx.ins().select(is_initial, init_val, stored);

                for use_ in existing_uses {
                    ctx.dfg_mut().use_set_value(use_, selected);
                }
            }
        }
        // the rolled-back event slots (a timer's schedule) read the restored value
        for (i, (_, _, uses)) in targets.iter().enumerate() {
            if slots[i] {
                for use_ in uses {
                    ctx.dfg_mut().use_set_value(*use_, rolled[i]);
                }
            }
        }

        // Enhancement-702 (hunt F6 of 2026-09-21): a run-time `$table_model`'s
        // "data captured" flag (see `expr::capture_table_data`) is cleared at every
        // `IsInitialStep`, here in the entry block, so the capture happens afresh at
        // the first evaluation of each analysis even when that evaluation does not
        // reach the call site (a table inside a region `if`). Between two setups
        // the slot keeps its value, as every `EventState` slot does.
        let flags = ctx.intern.table_capture_flags.clone();
        if !flags.is_empty() {
            for (kind, param) in ctx.intern.params.clone().iter() {
                let ParamKind::EventState(idx) = *kind else { continue };
                if !flags.contains(&idx) || ctx.dfg().value_dead(*param) {
                    continue;
                }
                let is_initial = ctx.use_param(ParamKind::IsInitialStep);
                let existing_uses: Vec<_> = ctx.dfg().values.uses(*param).collect();
                let cleared = ctx.ins().select(is_initial, F_ZERO, *param);
                for use_ in existing_uses {
                    ctx.dfg_mut().use_set_value(use_, cleared);
                }
            }
        }

        ctx.ensured_sealed();
        let final_block = ctx.current_block();
        ctx.func.func.layout.append_inst_to_bb(term, final_block);
    }
}

impl HirInterner {
    /// Enhancement-814 (hunt 2026-10-08 F23): the REPORTED value of every output
    /// variable with an LRM 3.2.1 `multiplicity` attribute -- the variable times
    /// (`"multiply"`) or over (`"divide"`) the effective multiplicity -- added as a
    /// `PlaceKind::OpVarReport` output, which the operating-point slot stores in
    /// place of the variable's own value.
    ///
    /// The variable itself is untouched: the model's own reads of it, a hidden
    /// state it carries between evaluations and a parent's hierarchical reference
    /// all keep the per-device value; only the report is scaled. The factor is
    /// the module's `$mfactor` -- so this must run BEFORE
    /// `insert_paramset_sys_fun_overrides`, which then composes a paramset's
    /// `.$mfactor` into it like every other read -- or, for an inlined child's
    /// variable, the final value of the elaborator's `<prefix>$mfactor`, which
    /// already holds that child's `#(.$mfactor(...))` composed with the module's.
    ///
    /// `reports` holds (variable, multiply, child's multiplicity variable). The
    /// new values are returned for the caller to keep live.
    pub fn insert_opvar_multiplicity(
        &mut self,
        func: &mut Function,
        reports: &[(Variable, bool, Option<Variable>)],
    ) -> Vec<Value> {
        let mut added = Vec::new();
        if reports.is_empty() {
            return added;
        }
        // At the very end -- the function's last block, where the body jumps
        // when it is done -- the variables' final values are computed by then
        // (`FunctionBuilder::edit` builds in a fresh ENTRY block, which suits
        // composing parameters, not reading results).
        let Some(end) = func.layout.last_block() else { return added };
        let before = func
            .layout
            .last_inst(end)
            .filter(|&inst| func.dfg.insts[inst].is_terminator());
        let output = |intern: &HirInterner, var| {
            intern.outputs.get(&PlaceKind::Var(var)).and_then(|val| val.expand())
        };
        for &(var, multiply, mfactor_var) in reports {
            let Some(val) = output(self, var) else { continue };
            let m = match mfactor_var.and_then(|mv| output(self, mv)) {
                Some(m) => m,
                None => {
                    let len = self.params.len();
                    *self
                        .params
                        .raw
                        .entry(ParamKind::ParamSysFun(ParamSysFun::mfactor))
                        .or_insert_with(|| func.dfg.make_param(len.into()))
                }
            };
            let mut cursor = match before {
                Some(inst) => FuncCursor::new(func).at_inst(inst),
                None => FuncCursor::new(func).at_bottom(end),
            };
            let scaled =
                if multiply { cursor.ins().fmul(val, m) } else { cursor.ins().fdiv(val, m) };
            let scaled = cursor.ins().optbarrier(scaled);
            self.outputs.insert(PlaceKind::OpVarReport(var), scaled.into());
            added.push(scaled);
        }
        added
    }

    /// Enhancement-44: composes a paramset's hierarchical system parameter
    /// overrides (`.$mfactor = 8;`) with the instance-level values.
    ///
    /// Each override lives in the twin module as a hidden localparam named
    /// `$paramset$<name>` (see `lower_paramset`); this pass rewrites every use
    /// of the corresponding `ParamKind::ParamSysFun` value -- explicit `$mfactor`
    /// reads in the body, the DAE builder's automatic flow/noise scaling, and
    /// the derivative code, which is why it must run *after* the DAE system is
    /// built -- with the composed value: multiplied for `$mfactor`/`$hflip`/
    /// `$vflip` (multiplicities and flips multiply down the hierarchy), added
    /// for `$xposition`/`$yposition`/`$angle`. The OSDI-visible built-in
    /// instance parameter keeps holding the raw netlist value (`m=3`), so
    /// `m=3` on a `.$mfactor = 8` paramset yields an effective 24.
    pub fn insert_paramset_sys_fun_overrides(
        &mut self,
        db: &CompilationDB,
        func: &mut Function,
        literals: &mut Rodeo,
        overrides: &[(ParamSysFun, Parameter)],
    ) {
        if overrides.is_empty() {
            return;
        }
        let mut fb_ctx = FunctionBuilderContext::default();
        let (builder, term) = FunctionBuilder::edit(func, literals, &mut fb_ctx, false);
        let mut ctx = LoweringCtx::new(db, builder, true, self);

        for &(sys, param) in overrides {
            let sys_val = ctx
                .intern
                .params
                .clone()
                .iter()
                .find_map(|(kind, val)| (*kind == ParamKind::ParamSysFun(sys)).then_some(*val));
            let Some(sys_val) = sys_val else { continue };
            if ctx.dfg().value_dead(sys_val) {
                continue;
            }

            let ov_val = ctx.use_param(ParamKind::Param(param));

            // Snapshot the pre-existing uses BEFORE creating the composition
            // instruction, which itself uses `sys_val`.
            let existing_uses: Vec<_> = ctx.dfg().values.uses(sys_val).collect();

            let composed = if sys.composes_multiplicatively() {
                ctx.ins().fmul(sys_val, ov_val)
            } else {
                ctx.ins().fadd(sys_val, ov_val)
            };
            // LRM 9.18 Table 9-29: the additive rule for `$angle` is a sum
            // "modulo 360 degrees" (round-3 audit -- the sum was applied and
            // the modulo was not). The other two additive parameters,
            // $xposition and $yposition, are "Any".
            let composed = if sys == ParamSysFun::angle {
                ctx.normalize_angle(composed)
            } else {
                composed
            };

            for use_ in existing_uses {
                ctx.dfg_mut().use_set_value(use_, composed);
            }
        }

        ctx.ensured_sealed();
        let final_block = ctx.current_block();
        ctx.func.func.layout.append_inst_to_bb(term, final_block);
    }
}
