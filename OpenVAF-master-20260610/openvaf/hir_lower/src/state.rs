use hir::CompilationDB;
use lasso::Rodeo;
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
        ctx.func.func.layout.append_inst_to_bb(term, ctx.current_block())
    }
}
