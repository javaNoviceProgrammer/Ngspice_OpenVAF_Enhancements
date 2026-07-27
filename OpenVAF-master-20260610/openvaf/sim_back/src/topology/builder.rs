use ahash::AHashMap;
use bitset::BitSet;
use hir::CompilationDB;
use hir_lower::CallBackKind;
use mir::builder::InstBuilder;
use mir::cursor::{Cursor, FuncCursor};
use mir::{
    Block, ControlFlowGraph, FuncRef, Function, Inst, InstructionData, Opcode, Value, F_ZERO,
};
use typed_indexmap::TiSet;

use crate::topology::Topology;

/// Order `insts` so that every instruction comes after the instructions (within
/// the same set) that produce its operands -- a topological order of the
/// data-flow sub-graph.
///
/// `create_dimension`'s replay is only correct in such an order; see the comment
/// at its call site for why the traversal's own postorder does not provide one.
/// Instructions left over by a dependency cycle (phi back edges) are appended in
/// their original relative order rather than dropped.
fn dfg_topo_order(func: &Function, insts: &[Inst]) -> Vec<Inst> {
    let mut in_set = BitSet::new_empty(func.dfg.num_insts());
    for &inst in insts {
        in_set.insert(inst);
    }
    let mut indeg: AHashMap<Inst, u32> = AHashMap::with_capacity(insts.len());
    let mut succs: AHashMap<Inst, Vec<Inst>> = AHashMap::with_capacity(insts.len());
    for &inst in insts {
        indeg.entry(inst).or_insert(0);
    }
    for &inst in insts {
        for &arg in func.dfg.instr_args(inst) {
            if let Some(def) = func.dfg.value_def(arg).inst() {
                if in_set.contains(def) {
                    // one edge PER OPERAND USE, so `fadd t, t` is decremented twice
                    succs.entry(def).or_default().push(inst);
                    *indeg.entry(inst).or_insert(0) += 1;
                }
            }
        }
    }
    let mut ready: Vec<Inst> =
        insts.iter().copied().filter(|inst| indeg[inst] == 0).collect();
    let mut out = Vec::with_capacity(insts.len());
    let mut emitted = BitSet::new_empty(func.dfg.num_insts());
    while let Some(inst) = ready.pop() {
        out.push(inst);
        emitted.insert(inst);
        if let Some(succs) = succs.get(&inst) {
            for &succ in succs {
                let deg = indeg.get_mut(&succ).unwrap();
                *deg -= 1;
                if *deg == 0 {
                    ready.push(succ);
                }
            }
        }
    }
    if out.len() != insts.len() {
        for &inst in insts {
            if !emitted.contains(inst) {
                out.push(inst);
            }
        }
    }
    out
}

pub(super) struct Builder<'a> {
    pub(super) topology: &'a mut Topology,
    pub(super) db: &'a CompilationDB,
    pub(super) func: &'a mut Function,
    pub(super) cfg: &'a mut ControlFlowGraph,
    pub(super) output_values: &'a BitSet<Value>,
    pub(super) scratch_buf: BitSet<Inst>,
    pub(super) postorder: Vec<Inst>,
    pub(super) val_map: AHashMap<Value, Value>,
    /// Enhancement-54: parallel replay map for the j*omega component a noise
    /// wave picks up by passing through ddt(); populated only when
    /// `create_dimension` runs with callback information (noise chains).
    pub(super) val_map_react: AHashMap<Value, Value>,
    pub(super) edges: Vec<(Block, Value)>,
    pub(super) phis: Vec<Inst>,
    pub(super) op_dependent_insts: &'a BitSet<Inst>,
    pub(super) op_dependent_vals: &'a [Value],
}

impl<'a> Builder<'a> {
    /// Turns one (or multiple) linear contributions into a separate dimension.
    /// That means that `val` gets replaced with 0 (although not handled in this function yet)
    /// and all dependent calculations will use `dim_val` multiplied with the same value
    /// as `val`.
    ///
    /// Enhancement-54: when `callbacks` is provided (noise chains), a
    /// `ddt()` call in the chain moves the replayed value into a parallel
    /// "react" dimension (`val_map_react`) -- the factor becomes
    /// `val_map[x] + j*omega * val_map_react[x]`. `determine_evaluation`
    /// guarantees at most one ddt per path and no post-ddt phis, so the react
    /// side never needs phi construction.
    pub(super) fn create_dimension(
        &mut self,
        dim_val: Value,
        val: Value,
        callbacks: Option<&TiSet<FuncRef, CallBackKind>>,
    ) {
        self.val_map.clear();
        self.val_map_react.clear();
        self.val_map.insert(val, dim_val);
        // The replay below assumes an instruction is visited only AFTER every
        // operand it depends on, because the `(None, Some(x)) => Some(x)` arms
        // read "the unmapped operand does not depend on the dimension". That is
        // only sound in a topological order.
        //
        // `postorder` does NOT guarantee one: `Postorder::populate` pushes every
        // use of the operator's result onto its stack up front and marks each
        // visited on PUSH, so when one such use feeds another the earlier-pushed
        // one is popped (and emitted) first. For `ddt(V)+ddt(V)+ddt(V)` the
        // instruction `t+t` was emitted before `(t+t)+t`, so replaying the latter
        // found its `t+t` operand still unmapped, took it for dimension-
        // independent, and DROPPED it -- silently yielding C = 1 F instead of 3 F.
        //
        // Sort into a real topological order first. Instructions in a dependency
        // cycle (phi back edges) cannot be ordered and keep their previous
        // relative order; the phi arm below already defers those deliberately.
        let order = dfg_topo_order(self.func, &self.postorder);
        for &inst in &order {
            macro_rules! ins {
                () => {
                    FuncCursor::new(self.func).after_inst(inst).ins()
                };
            }
            // per-component (resist, react) replay; `None` = the component does
            // not depend on the dimension through this instruction
            let mut res: Option<Value> = None;
            let mut res_react: Option<Value> = None;
            match self.func.dfg.insts[inst] {
                InstructionData::Binary { opcode: Opcode::Fadd, args } => {
                    for (map, out) in [
                        (&self.val_map, &mut res),
                        (&self.val_map_react, &mut res_react),
                    ] {
                        *out = match (map.get(&args[0]), map.get(&args[1])) {
                            (None, None) => None,
                            (None, Some(&arg)) | (Some(&arg), None) => Some(arg),
                            (Some(&lhs), Some(&rhs)) => Some(ins!().fadd(lhs, rhs)),
                        };
                    }
                }
                InstructionData::Binary { opcode: Opcode::Fsub, args } => {
                    for (map, out) in [
                        (&self.val_map, &mut res),
                        (&self.val_map_react, &mut res_react),
                    ] {
                        *out = match (map.get(&args[0]), map.get(&args[1])) {
                            (None, None) => None,
                            (None, Some(&arg)) => Some(ins!().fneg(arg)),
                            (Some(&arg), None) => Some(arg),
                            (Some(&lhs), Some(&rhs)) => Some(ins!().fsub(lhs, rhs)),
                        };
                    }
                }
                InstructionData::Unary { opcode: Opcode::Fneg, arg } => {
                    if let Some(&arg) = self.val_map.get(&arg) {
                        res = Some(ins!().fneg(arg));
                    }
                    if let Some(&arg) = self.val_map_react.get(&arg) {
                        res_react = Some(ins!().fneg(arg));
                    }
                }
                InstructionData::Binary { opcode: Opcode::Fmul, args: [lhs, rhs] } => {
                    let lhs_mapped =
                        self.val_map.contains_key(&lhs) || self.val_map_react.contains_key(&lhs);
                    let rhs_mapped =
                        self.val_map.contains_key(&rhs) || self.val_map_react.contains_key(&rhs);
                    match (lhs_mapped, rhs_mapped) {
                        (false, false) | (true, true) => (),
                        (false, true) => {
                            if let Some(&arg) = self.val_map.get(&rhs) {
                                res = Some(ins!().fmul(lhs, arg));
                            }
                            if let Some(&arg) = self.val_map_react.get(&rhs) {
                                res_react = Some(ins!().fmul(lhs, arg));
                            }
                        }
                        (true, false) => {
                            if let Some(&arg) = self.val_map.get(&lhs) {
                                res = Some(ins!().fmul(arg, rhs));
                            }
                            if let Some(&arg) = self.val_map_react.get(&lhs) {
                                res_react = Some(ins!().fmul(arg, rhs));
                            }
                        }
                    }
                }
                InstructionData::Binary { opcode: Opcode::Fdiv, args: [num, denom] } => {
                    if let Some(&num) = self.val_map.get(&num) {
                        res = Some(ins!().fdiv(num, denom));
                    }
                    if let Some(&num) = self.val_map_react.get(&num) {
                        res_react = Some(ins!().fdiv(num, denom));
                    }
                }
                InstructionData::PhiNode(_) => {
                    self.phis.push(inst);
                    // delay phi construction as there could be loops in the DFG
                    res = Some(self.func.dfg.make_invalid_value());
                }
                InstructionData::Unary { opcode: Opcode::OptBarrier, arg } => {
                    res = self.val_map.get(&arg).copied();
                    res_react = self.val_map_react.get(&arg).copied();
                }
                InstructionData::Call { func_ref, .. }
                    if callbacks
                        .map_or(false, |cbs| cbs[func_ref] == CallBackKind::TimeDerivative) =>
                {
                    // Enhancement-54: ddt(x) multiplies the wave's transfer by
                    // j*omega -- the replayed resist component of the argument
                    // becomes the react component of the result. A react
                    // component on the argument (nested ddt) was rejected by
                    // `determine_evaluation`.
                    let arg = self.func.dfg.instr_args(inst)[0];
                    debug_assert!(!self.val_map_react.contains_key(&arg));
                    res_react = self.val_map.get(&arg).copied();
                }
                _ => (),
            };
            if res.is_none() && res_react.is_none() {
                continue;
            }
            let result = self.func.dfg.first_result(inst);
            if let Some(res) = res {
                self.val_map.insert(result, res);
            }
            if let Some(res_react) = res_react {
                self.val_map_react.insert(result, res_react);
            }
        }
        // now that all values have been built we can popluate the phis
        for inst in self.phis.drain(..) {
            let res = self.val_map[&self.func.dfg.first_result(inst)];
            let phi = self.func.dfg.insts[inst].unwrap_phi();
            self.edges.clear();
            for (bb, mut val) in
                phi.edges(&self.func.dfg.insts.value_lists, &self.func.dfg.phi_forest)
            {
                val = self.val_map.get(&val).copied().unwrap_or(F_ZERO);
                self.edges.push((bb, val));
            }
            FuncCursor::new(self.func).after_inst(inst).ins().with_result(res).phi(&self.edges);
        }
        self.func.dfg.replace_uses(val, F_ZERO);
    }
}
