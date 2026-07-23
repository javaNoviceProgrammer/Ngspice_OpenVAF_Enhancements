//! This module is responsible for determining whether an internal unknown needs
//! to be created for an anlog opertor (like ddt) or to turn the analog operator
//! into a separate dimension instead.

use std::mem::{replace, take};

use bitset::SparseBitMatrix;
use hir_lower::{CallBackKind, HirInterner, ImplicitEquationKind, ParamKind, PlaceKind};
use mir::builder::InstBuilder;
use mir::cursor::{Cursor, FuncCursor};
use mir::{
    Block, FuncRef, Function, Inst, InstructionData, Opcode, PhiNode, Value, FALSE, F_ONE, F_ZERO,
    TRUE,
};
use typed_indexmap::TiSet;

use crate::topology::{Contribution, Noise};
use crate::util::{add, update_optbarrier};

#[derive(Debug)]
pub(super) enum Evaluation {
    /// The analog operator must be evaluated as a separate equation
    Equation,
    /// The analog operator can be evaluated as a linear contribution
    /// without the need for an additional unknown
    Linear {
        /// The contribute that this linear equation writes to
        /// Contains a triple of the original contribution, the separate
        /// dimension it was mapped to, and (Enhancement-54) the j*omega
        /// dimension picked up by routing a noise wave through ddt()
        /// (`F_ZERO` when the chain contains no ddt).
        contributes: Box<[(Value, Value, Value)]>,
    },
    /// This operator is not used and can be ignored
    Dead,
}

impl<'a> super::Builder<'a> {
    /// Build topology for a list of analog operators (noise and ddt) with a predetermined evaluation.
    pub(super) fn builid_analog_operators(
        &mut self,
        analog_operators: Vec<(Inst, Evaluation)>,
        intern: &mut HirInterner,
    ) {
        let mut ssa_builder = mir_build::SSAVariableBuilder::new(self.cfg);
        // Iterated by index (rather than consuming the vec) so that handling one operator
        // can fix up the entries still pending behind it -- see `retarget_pending` below.
        let mut analog_operators = analog_operators;
        for op_idx in 0..analog_operators.len() {
            let operator_inst = analog_operators[op_idx].0;
            let evaluation = replace(&mut analog_operators[op_idx].1, Evaluation::Dead);
            // `noise_table`/`noise_table_log` carry their data in the callback
            // and take no MIR value args, so guard against an empty arg list.
            // `arg0` is only consumed by the non-noise (ddt) branch below,
            // which always has an argument.
            let arg0 =
                self.func.dfg.instr_args(operator_inst).first().copied().unwrap_or(F_ZERO);
            let cb = self.func.dfg.func_ref(operator_inst).unwrap();
            let is_noise = intern.callbacks[cb].is_noise();
            // Enhancement-293: an operator's result may be recorded as the `dimension` of a
            // LATER
            // operator's `Evaluation::Linear` -- that happens whenever one analog
            // operator sits directly inside another (`ddt(ddt(x))`; with anything in
            // between, such as `ddt(2*ddt(x))`, the replay yields a fresh value and the
            // situation never arises). Those dimensions live in the `contributes`
            // triples, i.e. OUTSIDE the DFG, so `replace_uses` cannot reach them -- and
            // both arms below drop the operator's result and delete its instruction.
            // Left alone, the pending entry keeps naming a removed instruction's result
            // and everything derived from it surfaced later as "invalid argument vN"
            // when the init function was validated. Retarget them by hand.
            macro_rules! retarget_pending {
                ($old: expr, $new: expr) => {
                    let (old, new) = ($old, $new);
                    for (_, ev) in &mut analog_operators[op_idx + 1..] {
                        if let Evaluation::Linear { contributes } = ev {
                            for (_, dimension, dimension_react) in contributes.iter_mut() {
                                if *dimension == old {
                                    *dimension = new;
                                }
                                if *dimension_react == old {
                                    *dimension_react = new;
                                }
                            }
                        }
                    }
                };
            }
            match evaluation {
                Evaluation::Dead => {
                    cov_mark::hit!(dead_noise);
                    let val = self.func.dfg.first_result(operator_inst);
                    retarget_pending!(val, F_ZERO);
                    self.func.dfg.replace_uses(val, F_ZERO);
                }
                Evaluation::Linear { contributes } => {
                    cov_mark::hit!(linear_operator);
                    let cb = &intern.callbacks[cb];
                    for (contribute, mut dimension, mut dimension_react) in &*contributes {
                        let resistive_contribute = *contribute;
                        let inst = self.func.dfg.value_def(resistive_contribute).inst().unwrap();
                        let kind = self.topology.as_contribution(*contribute).unwrap();
                        let contribute = self.topology.get_mut(kind);
                        if is_noise {
                            dimension = FuncCursor::new(self.func)
                                .after_inst(inst)
                                .ins()
                                .ensure_optbarrier(dimension);
                            if dimension_react != F_ZERO {
                                dimension_react = FuncCursor::new(self.func)
                                    .after_inst(inst)
                                    .ins()
                                    .ensure_optbarrier(dimension_react);
                            }
                            let noise = Noise::new(
                                operator_inst,
                                cb,
                                dimension,
                                dimension_react,
                                &mut ssa_builder,
                                self.func,
                            );
                            contribute.noise.push(noise)
                        } else {
                            // ddt chains never contain a nested ddt, so no
                            // j*omega dimension can appear here
                            debug_assert_eq!(dimension_react, F_ZERO);
                            update_optbarrier(
                                self.func,
                                &mut contribute.react,
                                |mut val, cursor| {
                                    add(cursor, &mut val, dimension, false);
                                    val
                                },
                            );
                            // Enhancement-54: the react optbarrier this move creates
                            // (or rewrites) was never registered in `contributes`, so
                            // `prune_small_signal` could not find it via
                            // `as_contribution` -- a noise wave reaching a branch
                            // through ddt() lost its coupling entirely (the
                            // small-signal dimension twin was built and then dropped,
                            // leaving a hole in the Jacobian and zero transferred
                            // noise). Register it under the reactive twin of `kind`.
                            let react_val = contribute.react;
                            let react_kind = match kind {
                                super::ContributeKind::Branch { id, is_voltage_src, .. } => {
                                    super::ContributeKind::Branch {
                                        id,
                                        is_voltage_src,
                                        is_reactive: true,
                                    }
                                }
                                super::ContributeKind::ImplicitEquation { equation, .. } => {
                                    super::ContributeKind::ImplicitEquation {
                                        equation,
                                        is_reactive: true,
                                    }
                                }
                            };
                            self.topology.contributes.insert(react_val, react_kind);
                        }
                    }
                }
                Evaluation::Equation => {
                    let eq = if is_noise {
                        ImplicitEquationKind::NoiseSrc
                    } else {
                        ImplicitEquationKind::Ddt
                    };
                    let eq = intern.implicit_equations.push_and_get_key(eq);
                    let eq_val =
                        intern.ensure_param(&mut self.func, ParamKind::ImplicitUnknown(eq));
                    let res = self.func.dfg.first_result(operator_inst);
                    // `eq_val` -- the implicit unknown this operator became -- is exactly
                    // what a nested operator's reactive contribution should now use, so
                    // this both removes the dangling reference and states the right
                    // second-derivative formulation.
                    retarget_pending!(res, eq_val);
                    self.func.dfg.replace_uses(res, eq_val);
                    let collapse =
                        ssa_builder.define_at_exit(self.func, TRUE, FALSE, operator_inst);
                    if collapse != FALSE {
                        cov_mark::hit!(collapsible_ddt);
                        debug_assert_ne!(collapse, TRUE);
                        intern
                            .outputs
                            .insert(PlaceKind::CollapseImplicitEquation(eq), collapse.into());
                    }

                    let neg_eq_val = FuncCursor::new(self.func).at_exit().ins().fneg(eq_val);
                    let contributions = if is_noise {
                        self.topology.small_signal_vals.insert(eq_val);
                        Contribution {
                            unknown: Some(eq_val),
                            resist: neg_eq_val,
                            noise: vec![Noise::new(
                                operator_inst,
                                &intern.callbacks[cb],
                                F_ONE,
                                F_ZERO,
                                &mut ssa_builder,
                                self.func,
                            )],
                            ..Contribution::default()
                        }
                    } else {
                        let arg0 =
                            ssa_builder.define_at_exit(self.func, F_ZERO, arg0, operator_inst);
                        Contribution {
                            unknown: Some(eq_val),
                            resist: neg_eq_val,
                            react: arg0,
                            ..Contribution::default()
                        }
                    };

                    self.topology.new_implicit_equation(eq, contributions);
                }
            }
            // not needed anymore, wipe the callback
            self.func.dfg.zap_inst(operator_inst);
            self.func.layout.remove_inst(operator_inst);
        }
    }

    pub(super) fn analog_operator_evaluations(
        &mut self,
        postdom_frontiers: &SparseBitMatrix<Block, Block>,
        intern: &mut HirInterner,
    ) -> Vec<(Inst, Evaluation)> {
        let mut analog_operators = Vec::new();

        // Iterate all analog operators, determining if they can be
        // lineraized/turned into dimensions. Note that `determine_evaluation`
        // DOES mutate the function for Linear results (the dimension replay
        // runs inside it, and it detaches the operator's result), so ordering
        // matters. Enhancement-54: all NOISE operators are processed before
        // any ddt operator -- callbacks used to be visited in registration
        // order, and a shared-`FuncRef` ddt evaluated between two noise calls
        // detached the second wave's path to its contribution mid-flight,
        // misclassifying it as Dead (the source was silently lost). Noise
        // replays only zero the waves, which is exactly what the subsequent
        // ddt pass should see (the wave's coupling lives in the noise factor).
        for noise_pass in [true, false] {
            for (cb, uses) in intern.callback_uses.iter_mut_enumerated() {
                match intern.callbacks[cb] {
                    CallBackKind::TimeDerivative if !noise_pass => {
                        for inst in take(uses) {
                            if self.func.layout.inst_block(inst).is_none() {
                                continue;
                            }
                            if self.func.dfg.instr_safe_to_remove(inst)
                                || !self.op_dependent_insts.contains(inst)
                            {
                                let result = self.func.dfg.first_result(inst);
                                self.func.dfg.replace_uses(result, F_ZERO);
                                self.func.dfg.zap_inst(inst);
                                self.func.layout.remove_inst(inst);
                                continue;
                            }
                            analog_operators.push((
                                inst,
                                self.determine_evaluation(
                                    false,
                                    inst,
                                    postdom_frontiers,
                                    &intern.callbacks,
                                ),
                            ));
                        }
                    }
                    CallBackKind::WhiteNoise { .. }
                    | CallBackKind::FlickerNoise { .. }
                    | CallBackKind::NoiseTable(_)
                    | CallBackKind::AcStim { .. }
                        if noise_pass =>
                    {
                        for inst in take(uses) {
                            analog_operators.push((
                                inst,
                                self.determine_evaluation(
                                    true,
                                    inst,
                                    postdom_frontiers,
                                    &intern.callbacks,
                                ),
                            ));
                        }
                    }
                    _ => continue,
                }
            }
        }
        analog_operators
    }

    fn determine_evaluation(
        &mut self,
        noise: bool,
        inst: Inst,
        postdom_frontiers: &SparseBitMatrix<Block, Block>,
        callbacks: &TiSet<FuncRef, CallBackKind>,
    ) -> Evaluation {
        let Self { func, output_values, scratch_buf, postorder, .. } = self;

        postorder.clear();
        scratch_buf.clear();
        let mut transversal =
            func.dfg.inst_uses_postorder_with(inst, (take(scratch_buf), Vec::new()), |_| true);
        postorder.extend(&mut transversal);
        *scratch_buf = transversal.visited;
        let visisted = scratch_buf;

        let is_op_dependent = |val| {
            if let Some(inst) = func.dfg.value_def(val).inst() {
                self.op_dependent_insts.contains(inst)
            } else {
                self.op_dependent_vals.contains(&val)
            }
        };

        let val_visisted =
            |val| func.dfg.value_def(val).inst().map_or(false, |inst| visisted.contains(inst));

        // Enhancement-54: a noise wave may pass through at most ONE ddt() --
        // its factor becomes `re + j*omega*im`, which the simulator folds into
        // the power per frequency. `ac_stim` is excluded (complex RHS, not a
        // power). Nested ddt ((j*omega)^2 needs an omega^2 real part) and a
        // post-ddt value feeding a phi (the replay would need react-aware phi
        // construction) fall back to the extra-unknown Equation path.
        let this_cb = func.dfg.func_ref(inst).unwrap();
        let allow_ddt =
            noise && !matches!(callbacks[this_cb], CallBackKind::AcStim { .. });
        if noise {
            let has_ddt = postorder.iter().any(|&inst| {
                matches!(func.dfg.insts[inst], InstructionData::Call { func_ref, .. }
                    if callbacks[func_ref] == CallBackKind::TimeDerivative)
            });
            if has_ddt {
                if !allow_ddt {
                    return Evaluation::Equation;
                }
                let mut post_ddt: ahash::AHashSet<Value> = ahash::AHashSet::new();
                for &inst in postorder.iter().rev() {
                    let any_arg_post = func
                        .dfg
                        .instr_args(inst)
                        .iter()
                        .any(|arg| post_ddt.contains(arg));
                    match func.dfg.insts[inst] {
                        InstructionData::Call { func_ref, .. }
                            if callbacks[func_ref] == CallBackKind::TimeDerivative =>
                        {
                            if any_arg_post {
                                // nested ddt: (j*omega)^2 is not representable
                                return Evaluation::Equation;
                            }
                            post_ddt.insert(func.dfg.first_result(inst));
                        }
                        InstructionData::PhiNode(ref phi) => {
                            if func.dfg.phi_edges(phi).any(|(_, val)| post_ddt.contains(&val)) {
                                return Evaluation::Equation;
                            }
                        }
                        InstructionData::Binary { .. }
                        | InstructionData::Unary { .. } => {
                            if any_arg_post {
                                post_ddt.insert(func.dfg.first_result(inst));
                            }
                        }
                        _ => (),
                    }
                }
            }
        }
        let mut contributes = Vec::new();
        for &inst in postorder.iter() {
            match func.dfg.insts[inst] {
                InstructionData::Binary { opcode: Opcode::Fadd | Opcode::Fsub, .. } => (),
                // for noise phis don't matter at all
                // since its a small signal value (so doesn't need to be consistently
                // maintained across multiple iterations). I am not quite sure if this
                // plays nice with transient noise and other more advanced simulation
                // types but I can't see why it wouldn't (also the language standard
                // specifically calls these small signal sources).
                InstructionData::PhiNode(_)
                | InstructionData::Branch { .. }
                | InstructionData::Binary {
                    opcode: Opcode::Flt | Opcode::Fle | Opcode::Fgt | Opcode::Fge,
                    ..
                } if noise => (),
                InstructionData::Unary { opcode: Opcode::Fneg, .. } => {}
                // noise is always zero when these are evaluated
                InstructionData::Call { func_ref, .. }
                    if noise && callbacks[func_ref] != CallBackKind::TimeDerivative => {}
                // Enhancement-54 (the old "complex noise power" TODO): ONE ddt() in a
                // noise chain is representable as a j*omega component of the factor
                // (validated below); `ac_stim` keeps the Equation fallback since its
                // injection is a complex RHS pair, not a power.
                InstructionData::Call { func_ref, .. }
                    if allow_ddt && callbacks[func_ref] == CallBackKind::TimeDerivative => {}
                InstructionData::Binary { opcode: Opcode::Fmul, args } => {
                    if noise {
                        // Enhancement-54: for a NOISE wave the factor may be
                        // op-dependent -- it is replayed into a per-instance value
                        // evaluated at the operating point (`gm * white_noise(..)`
                        // stays linear, no extra unknown). Only a product of two
                        // wave-derived values is nonlinear in the wave.
                        if val_visisted(args[0]) && val_visisted(args[1]) {
                            return Evaluation::Equation;
                        }
                    } else if is_op_dependent(args[0]) && is_op_dependent(args[1]) {
                        // for ddt the op-dependence check must stay:
                        // g(v)*ddt(q) != ddt(g(v)*q)
                        return Evaluation::Equation;
                    }
                }
                InstructionData::Binary { opcode: Opcode::Fdiv, args } => {
                    if noise {
                        // dividing BY the wave is nonlinear; an op-dependent divisor
                        // is just a factor (see Fmul above)
                        if val_visisted(args[1]) {
                            return Evaluation::Equation;
                        }
                    } else if is_op_dependent(args[1]) {
                        return Evaluation::Equation;
                    }
                }
                InstructionData::PhiNode(ref phi) => {
                    // phis are pretty complex to figure out. The most correct
                    // implementation is to check if a phi is operating point
                    // dependent. To determine that we check whether any of
                    // the control dependencies of the edge are operating point
                    // dependent.
                    //
                    // However, to avoid cerating many unnecessary implicit
                    // equiation a special optimization for chains of additions
                    // is necessary. Chains of addition/subtraction where only one
                    // summand depends on the analog operator don't need an equation.
                    // This optimizes the following (common) case:
                    //
                    // I(x) <+ ddt(foo);
                    // if (op_denpendent)
                    //    I(x) <+ bar;
                    //
                    // this will create an (op dependent) phi [ddt(foo), ddt(foo) + bar].
                    // This does not change the ddt state and therefore doesn't require
                    // introduction of state.

                    let mut op_dependent = false;
                    for (pred, _) in func.dfg.phi_edges(phi) {
                        // check if this edge is operating point dependent
                        if !op_dependent {
                            if let Some(control_deps) = postdom_frontiers.row(pred) {
                                for control_dep in control_deps.iter() {
                                    if let Some((cond, _, _)) = func
                                        .layout
                                        .block_terminator(control_dep)
                                        .and_then(|inst| func.dfg.as_branch(inst))
                                    {
                                        if is_op_dependent(cond) {
                                            op_dependent = true;
                                            break;
                                        }
                                    }
                                }
                            }
                        }
                    }

                    self.val_map.clear();
                    if op_dependent
                        && phi_add_chain_start(
                            func,
                            phi.clone(),
                            &val_visisted,
                            &mut |phi, enter| {
                                if enter {
                                    self.val_map.insert(phi, F_ZERO).is_none()
                                } else {
                                    self.val_map.remove(&phi).is_some()
                                }
                            },
                        )
                        .is_none()
                    {
                        cov_mark::hit!(conditional_phi);
                        return Evaluation::Equation;
                    }
                }
                InstructionData::Unary { opcode: Opcode::OptBarrier, .. } => {
                    // if used in multiple outputs its safe to assume that this
                    // needs its own node.
                    // TODO: ignore
                    let val = func.dfg.first_result(inst);
                    let is_output = if noise {
                        self.topology.as_contribution(val).is_some()
                    } else {
                        output_values.contains(val)
                    };
                    if is_output {
                        // multiple uses of a noise source indicate
                        // correlated noise, for now just create a correlation network
                        if noise && !contributes.is_empty() {
                            return Evaluation::Equation;
                        } else if self
                            .topology
                            .as_contribution(val)
                            .map_or(false, |it| !it.is_reactive())
                        {
                            contributes.push((val, F_ZERO, F_ZERO))
                        } else {
                            return Evaluation::Equation;
                        }
                    }
                }
                _ => {
                    return Evaluation::Equation;
                }
            }
        }
        if contributes.is_empty() {
            // Enhancement-307: this used to `assert!(noise, ...)`, on the assumption that
            // only a noise source could reach here with no contributions and that any
            // other operator would already have been dead-code eliminated. That does not
            // hold: a `ddt` whose result never reaches a contribution can survive DCE
            // (found by fuzzing -- e.g. one feeding a variable that is only read back by
            // control flow, in a module that contributes nothing). It was a plain
            // `assert!`, not `debug_assert!`, so it fired in the SHIPPED build and the
            // compiler died with "OpenVAF encountered a problem and has crashed!".
            //
            // No contributions means the operator's value reaches no device equation, so
            // it contributes nothing and the existing `Dead` handling -- replace the
            // result with zero and retarget pending uses -- is exactly right for it too;
            // that is already what the noise case does here.
            return Evaluation::Dead;
        }
        self.create_dimension(
            if noise { F_ONE } else { self.func.dfg.instr_args(inst)[0] },
            self.func.dfg.first_result(inst),
            Some(callbacks),
        );
        for (contrib, dim, dim_react) in &mut contributes {
            *dim = self.val_map.get(&*contrib).copied().unwrap_or(F_ZERO);
            *dim_react = self.val_map_react.get(&*contrib).copied().unwrap_or(F_ZERO);
        }
        Evaluation::Linear { contributes: contributes.into_boxed_slice() }
    }
}

fn phi_add_chain_start(
    func: &Function,
    phi: PhiNode,
    val_visited: &impl Fn(Value) -> bool,
    handle_loops: &mut impl FnMut(Value, bool) -> bool,
) -> Option<Value> {
    let mut add_chain_start = None;
    for (_, mut edge) in func.dfg.phi_edges(&phi) {
        if !val_visited(edge) {
            return None;
        }
        edge = follow_add_chain(func, edge, val_visited, &mut *handle_loops);
        match add_chain_start {
            Some(chain_start) => {
                if chain_start != edge {
                    return None;
                }
            }
            None => add_chain_start = Some(edge),
        }
    }
    add_chain_start
}

fn follow_add_chain(
    func: &Function,
    mut val: Value,
    val_visited: &impl Fn(Value) -> bool,
    handle_loops: &mut impl FnMut(Value, bool) -> bool,
) -> Value {
    while let Some(inst) = func.dfg.value_def(val).inst() {
        match func.dfg.insts[inst] {
            InstructionData::Binary { opcode: Opcode::Fadd, args: [lhs, rhs] } => {
                if !val_visited(lhs) {
                    val = rhs;
                    continue;
                }
                if !val_visited(rhs) {
                    val = lhs;
                    continue;
                }
            }
            InstructionData::Binary { opcode: Opcode::Fsub, args: [lhs, rhs] } => {
                if !val_visited(rhs) {
                    val = lhs;
                    continue;
                }
            }
            InstructionData::PhiNode(ref phi) => {
                if handle_loops(val, true) {
                    let add_chain_start =
                        phi_add_chain_start(func, phi.clone(), val_visited, &mut *handle_loops);
                    handle_loops(val, false);
                    if let Some(add_chain_start) = add_chain_start {
                        val = add_chain_start;
                        continue;
                    }
                }
            }
            _ => (),
        }
        break;
    }
    val
}
