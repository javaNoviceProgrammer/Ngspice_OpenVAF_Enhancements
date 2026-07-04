use hir::{CompilationDB, ParamSysFun, Parameter};
use lasso::Rodeo;
use mir::builder::InstBuilder;
use mir::Function;
use mir_build::{FunctionBuilder, FunctionBuilderContext};

use crate::ctx::LoweringCtx;
use crate::{HirInterner, ParamKind};

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

                let selected =
                    ctx.make_select(is_initial, |_, branch| if branch { init_val } else { *param });

                for use_ in existing_uses {
                    ctx.dfg_mut().use_set_value(use_, selected);
                }
            }
        }

        ctx.ensured_sealed();
        let final_block = ctx.current_block();
        ctx.func.func.layout.append_inst_to_bb(term, final_block);
    }
}

impl HirInterner {
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

            for use_ in existing_uses {
                ctx.dfg_mut().use_set_value(use_, composed);
            }
        }

        ctx.ensured_sealed();
        let final_block = ctx.current_block();
        ctx.func.func.layout.append_inst_to_bb(term, final_block);
    }
}
