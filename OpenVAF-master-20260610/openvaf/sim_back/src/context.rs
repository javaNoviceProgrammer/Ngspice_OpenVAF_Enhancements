use std::collections::HashSet;

use bitset::{BitSet, SparseBitMatrix};
use hir::{CompilationDB, Variable};
use hir_lower::{CallBackKind, HirInterner, MirBuilder, ParamKind, PlaceKind};
use lasso::Rodeo;
use mir::{Block, ControlFlowGraph, DominatorTree, Function, Inst, Value};
use mir_opt::{
    aggressive_dead_code_elimination, dead_code_elimination, inst_combine, propagate_direct_taint,
    propagate_taint, simplify_cfg, simplify_cfg_no_phi_merge,
    sparse_conditional_constant_propagation, GVN,
};
use stdx::packed_option::PackedOption;

use crate::ModuleInfo;

pub(crate) struct Context<'a> {
    pub(crate) func: Function,
    pub(crate) cfg: ControlFlowGraph,
    pub(crate) dom_tree: DominatorTree,
    pub(crate) intern: HirInterner,
    pub(crate) db: &'a CompilationDB,
    pub(crate) module: &'a ModuleInfo,
    pub(crate) output_values: BitSet<Value>,
    pub(crate) op_dependent_insts: BitSet<Inst>,
    pub(crate) op_dependent_vals: Vec<Value>,
}

#[derive(PartialEq, Eq, Debug)]
pub enum OptimiziationStage {
    Initial,
    PostDerivative,
    Final,
}

impl<'a> Context<'a> {
    pub fn new(db: &'a CompilationDB, literals: &mut Rodeo, module: &'a ModuleInfo) -> Self {
        let base_keep = |module: &ModuleInfo, kind: &PlaceKind| match *kind {
            PlaceKind::Contribute { .. }
            | PlaceKind::ImplicitResidual { .. }
            | PlaceKind::CollapseImplicitEquation(_)
            | PlaceKind::IsVoltageSrc(_)
            | PlaceKind::BoundStep
            | PlaceKind::AbsDelayTime(_)
            | PlaceKind::LastCrossingDirection(_)
            | PlaceKind::EventState(_) => true,
            PlaceKind::Var(var) => module.op_vars.contains_key(&var),
            _ => false,
        };

        // Enhancement-7: a first, throwaway build (with the baseline predicate above,
        // matching pre-Enhancement-7 behavior) to discover which `Variable`s are
        // genuinely self-referentially read (i.e. their `ParamKind::HiddenState`
        // parameter is actually live, not eliminated as dead) -- this can only be
        // known after the whole body has been lowered once, so it can't be decided
        // by a predicate closure run *during* construction. Rebuilding below with an
        // expanded predicate that also keeps exactly these variables' outputs alive
        // (not *every* variable unconditionally -- that broke
        // `aggressive_dead_code_elimination`'s assumptions for genuinely-dead ones,
        // caught by the existing dae/topology/init test suites) gives real
        // cross-evaluation persistence without regressing anything else.
        let needs_hidden_state: HashSet<Variable> = {
            let (probe_func, probe_intern) =
                MirBuilder::new(db, module.module, &|kind| base_keep(module, &kind), &mut module.op_vars.keys().copied())
                    .with_equations()
                    .with_tagged_writes()
                    .build(literals);
            probe_intern
                .params
                .iter()
                .filter_map(|(kind, val)| match *kind {
                    ParamKind::HiddenState(var) if !probe_func.dfg.value_dead(*val) => Some(var),
                    _ => None,
                })
                .collect()
        };

        let (mut func, mut intern) = MirBuilder::new(
            db,
            module.module,
            &|kind| match kind {
                PlaceKind::Var(var) => {
                    module.op_vars.contains_key(&var) || needs_hidden_state.contains(&var)
                }
                _ => base_keep(module, &kind),
            },
            &mut module.op_vars.keys().copied(),
        )
        .with_equations()
        .with_tagged_writes()
        .build(literals);
        intern.insert_var_init(db, &mut func, literals);

        Context {
            output_values: BitSet::new_empty(func.dfg.num_values()),
            func,
            cfg: ControlFlowGraph::new(),
            dom_tree: DominatorTree::default(),
            intern,
            db,
            module,
            op_dependent_insts: BitSet::new_empty(0),
            op_dependent_vals: Vec::new(),
        }
    }

    pub fn optimize(&mut self, stage: OptimiziationStage) -> GVN {
        if stage == OptimiziationStage::Initial {
            dead_code_elimination(&mut self.func, &self.output_values);
        }
        sparse_conditional_constant_propagation(&mut self.func, &self.cfg);
        inst_combine(&mut self.func);
        if stage == OptimiziationStage::Final {
            simplify_cfg(&mut self.func, &mut self.cfg);
        } else {
            simplify_cfg_no_phi_merge(&mut self.func, &mut self.cfg);
        }
        self.compute_domtree(true, true, false);

        let mut gvn = GVN::default();
        gvn.init(&self.func, &self.dom_tree, self.intern.params.len() as u32);
        gvn.solve(&mut self.func);
        gvn.remove_unnecessary_insts(&mut self.func, &self.dom_tree);

        if stage == OptimiziationStage::Final {
            let mut control_dep = SparseBitMatrix::new_square(0);
            self.dom_tree.compute_postdom_frontiers(&self.cfg, &mut control_dep);
            aggressive_dead_code_elimination(
                &mut self.func,
                &mut self.cfg,
                &|val, _| self.output_values.contains(val),
                &control_dep,
            );
            simplify_cfg(&mut self.func, &mut self.cfg);
        }

        gvn
    }

    pub fn compute_cfg(&mut self) {
        self.cfg.compute(&self.func);
    }

    pub fn compute_domtree(&mut self, dom: bool, pdom: bool, postorder: bool) {
        self.dom_tree.compute(&self.func, &self.cfg, dom, pdom, postorder);
    }

    pub fn compute_outputs(&mut self, contributes: bool) {
        self.output_values.clear();
        self.output_values.ensure(self.func.dfg.num_values() + 1);
        if contributes {
            self.output_values
                .extend(self.intern.outputs.values().copied().filter_map(PackedOption::expand));
        } else {
            for (kind, val) in self.intern.outputs.iter() {
                if val.is_none() {
                    continue;
                }
                if matches!(kind, PlaceKind::Var(_))
                    || matches!(
                        kind,
                        PlaceKind::CollapseImplicitEquation(_)
                            | PlaceKind::BoundStep
                            | PlaceKind::AbsDelayTime(_)
                            | PlaceKind::LastCrossingDirection(_)
                            | PlaceKind::EventState(_)
                    )
                {
                    self.output_values.insert(val.unwrap_unchecked());
                }
            }
        }
    }

    pub fn init_op_dependent_insts(&mut self, dom_frontiers: &mut SparseBitMatrix<Block, Block>) {
        self.dom_tree.compute_dom_frontiers(&self.cfg, dom_frontiers);
        let dfg = &mut self.func.dfg;
        self.op_dependent_insts.ensure(dfg.num_insts());

        for (cb, uses) in self.intern.callback_uses.iter_mut_enumerated() {
            if self.intern.callbacks[cb].is_noise() {
                uses.retain(|&inst| {
                    if self.func.layout.inst_block(inst).is_none() {
                        return false;
                    }
                    self.op_dependent_insts.insert(inst);
                    for &result in dfg.inst_results(inst) {
                        self.op_dependent_vals.push(result);
                    }
                    true
                })
            }
        }
        for (param, &val) in self.intern.params.iter() {
            if !dfg.value_dead(val) && param.op_dependent() {
                self.op_dependent_vals.push(val)
            }
        }

        // Propagate taint
        propagate_direct_taint(
            &self.func,
            dom_frontiers,
            self.op_dependent_vals.iter().copied(),
            &mut self.op_dependent_insts,
        );
    }

    pub fn refresh_op_dependent_insts(&mut self) {
        let dfg = &mut self.func.dfg;
        self.op_dependent_vals.clear();
        self.op_dependent_insts.clear();
        self.op_dependent_insts.ensure(dfg.num_insts());
        // Go through all callbacks and their uses
        for (cb, uses) in self.intern.callback_uses.iter_mut_enumerated() {
            // Ff callback is op dependent
            if self.intern.callbacks[cb].op_dependent() {
                // Remove uses that appear in instructions that are not inserted into the layout.
                // Add to op dependent instructions.
                // Add the results of these instructions to op dependent values.
                uses.retain(|&inst| {
                    if self.func.layout.inst_block(inst).is_none() {
                        return false;
                    }
                    self.op_dependent_insts.insert(inst);
                    for &result in dfg.inst_results(inst) {
                        self.op_dependent_vals.push(result);
                    }
                    true
                })
            }
        }
        // Go through parameters, if the corresponding value is not dead and is op dependent
        // (i.e. current, voltage, abstime, ...) add it to op dependent values.
        for (param, &val) in self.intern.params.iter() {
            if !dfg.value_dead(val) && param.op_dependent() {
                self.op_dependent_vals.push(val)
            }
        }

        // Propagate taint
        propagate_taint(
            &self.func,
            &self.dom_tree,
            &self.cfg,
            self.op_dependent_vals.iter().copied(),
            &mut self.op_dependent_insts,
        );

        // Enhancement-55: side-effecting callbacks must respect their CONTROL
        // dependence. `propagate_taint`'s branch handling stops at
        // `ipdom(branch_block)`, but with an early-exit sink ($fatal's `exit`)
        // the post-dominator tree roots AT the sink block, so the branch body
        // never gets block-tainted: a $fatal/$finish/$stop (SetRetFlag) or a
        // display under an op-dependent condition looked op-independent (its
        // args are constants), was hoisted into the instance-init split, and
        // there sat in an unreachable block (the op-dependent branch is
        // rewritten to its else edge) -- silently deleted from BOTH functions.
        // Mark such calls op-dependent directly. Control dependence is computed
        // from scratch here because the shared post-dominator machinery roots
        // its tree at a single exit and mis-handles the extra sink the `exit`
        // instruction introduces (ipdom(branch) = the exit arm itself, so the
        // frontier walk inserts nothing for it). For every op-dependent
        // branch, the blocks reachable from exactly ONE of its two arms are
        // controlled by it -- exact for the structured CFGs the lowering
        // emits, and in particular for early-exit arms, which never reconverge.
        let num_blocks = self.func.layout.num_blocks();
        let mut op_controlled = BitSet::new_empty(num_blocks);
        let mut reach_then = BitSet::new_empty(num_blocks);
        let mut reach_else = BitSet::new_empty(num_blocks);
        let mut queue = Vec::new();
        for bb in self.func.layout.blocks() {
            let Some(term) = self.func.layout.block_terminator(bb) else { continue };
            if !self.op_dependent_insts.contains(term) {
                continue;
            }
            let mir::InstructionData::Branch { then_dst, else_dst, .. } =
                self.func.dfg.insts[term]
            else {
                continue;
            };
            for (start, reach) in
                [(then_dst, &mut reach_then), (else_dst, &mut reach_else)]
            {
                reach.clear();
                reach.insert(start);
                queue.push(start);
                while let Some(next) = queue.pop() {
                    for succ in self.cfg.succ_iter(next) {
                        if reach.insert(succ) {
                            queue.push(succ);
                        }
                    }
                }
            }
            for b in reach_then.iter() {
                if !reach_else.contains(b) {
                    op_controlled.insert(b);
                }
            }
            for b in reach_else.iter() {
                if !reach_then.contains(b) {
                    op_controlled.insert(b);
                }
            }
        }
        for bb in self.func.layout.blocks() {
            if !op_controlled.contains(bb) {
                continue;
            }
            let mut cursor = self.func.layout.block_inst_cursor(bb);
            while let Some(inst) = cursor.next(&self.func.layout) {
                if let mir::InstructionData::Call { func_ref, .. } = self.func.dfg.insts[inst] {
                    if matches!(
                        self.intern.callbacks[func_ref],
                        CallBackKind::SetRetFlag(_) | CallBackKind::Print { .. }
                    ) {
                        self.op_dependent_insts.insert(inst);
                    }
                }
            }
        }

        if std::env::var("OPENVAF_TAINT_DEBUG").is_ok() {
            eprintln!(
                "TAINTDBG {} op-dep insts, {} op-dep vals, {} op-controlled blocks",
                self.op_dependent_insts.iter().count(),
                self.op_dependent_vals.len(),
                op_controlled.iter().count()
            );
        }
    }
}
