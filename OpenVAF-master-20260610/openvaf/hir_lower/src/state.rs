use hir::{CompilationDB, ParamSysFun, Parameter, Variable};
use lasso::Rodeo;
use mir::builder::InstBuilder;
use mir::cursor::{Cursor, FuncCursor};
use mir::{Function, Value, F_ZERO};
use mir_build::{FunctionBuilder, FunctionBuilderContext};

use crate::ctx::LoweringCtx;
use crate::{HirInterner, ParamKind, PlaceKind};

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
    pub fn insert_var_init(
        &mut self,
        db: &CompilationDB,
        func: &mut Function,
        literals: &mut Rodeo,
    ) {
        let mut ctx = FunctionBuilderContext::default();
        let (builder, term) = FunctionBuilder::edit(func, literals, &mut ctx, false);
        let mut ctx = LoweringCtx::new(db, builder, true, self);
        for (kind, param) in ctx.intern.params.clone().iter() {
            if let ParamKind::HiddenState(var) = *kind {
                if ctx.dfg().value_dead(*param) {
                    continue;
                }

                let init_val = ctx.lower_expr_body(var.init(db).borrow(), 0);
                let is_initial = ctx.use_param(ParamKind::IsInitialStep);

                // Snapshot the pre-existing uses of `*param` BEFORE building the
                // select below, since the select's own "else" branch also
                // references `*param` -- if that new use were included in the
                // rewrite it would create a self-referencing cycle.
                let existing_uses: Vec<_> = ctx.dfg().values.uses(*param).collect();

                // Enhancement-579: both values are already computed, so this is a
                // plain `select` -- one instruction per retained variable instead
                // of a three-block diamond and a phi, which for an array of N
                // elements (N hidden-state variables) put 3N blocks into the
                // evaluation function before the body was even lowered.
                let selected = ctx.ins().select(is_initial, init_val, *param);

                for use_ in existing_uses {
                    ctx.dfg_mut().use_set_value(use_, selected);
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
