use std::collections::HashSet;

use bitset::{BitSet, SparseBitMatrix};
use hir::{BranchWrite, CompilationDB, Variable};
use hir_lower::{CallBackKind, HirInterner, MirBuilder, ParamKind, PlaceKind};
use lasso::Rodeo;
use mir::{Block, ControlFlowGraph, DominatorTree, Function, Inst, Value};
use mir_opt::{
    aggressive_dead_code_elimination, dead_code_elimination, inst_combine, propagate_direct_taint,
    propagate_taint, simplify_cfg, simplify_cfg_no_phi_merge,
    sparse_conditional_constant_propagation, GVN,
};
use stdx::packed_option::PackedOption;

use crate::util::strip_optbarrier_if_const;
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
    /// Enhancement-400: branches whose potential/flow character is already decided in the
    /// unoptimized MIR -- the model contributes only one kind to them, on every path it
    /// wrote. See [`Context::new`] for why this cannot be asked later.
    pub(crate) unconditional_branch_kind: HashSet<BranchWrite>,
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

        // Enhancement-400: which branches are a single kind of source *as the model
        // writes them*, before any optimization runs. Read here and nowhere later,
        // because the answer changes: constant propagation folds an `if` whose condition
        // is a configuration constant, and a branch the author wrote as a proper switch
        // then looks exactly like one written as a plain source with a stray contribution
        // of the other kind. Lowering has already dropped a phi whose arms agree, so a
        // branch that is the same kind on every path still reads constant here.
        let unconditional_branch_kind = intern
            .outputs
            .iter()
            .filter_map(|(kind, val)| {
                let branch = match *kind {
                    PlaceKind::IsVoltageSrc(branch) => branch,
                    _ => return None,
                };
                match strip_optbarrier_if_const(&func, val.expand()?) {
                    mir::TRUE => Some(branch),
                    mir::FALSE => Some(branch),
                    _ => None,
                }
            })
            .collect();

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
            unconditional_branch_kind,
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
        // Enhancement-505: and mark them in EVERY block, not only the
        // op-controlled ones.
        //
        // Enhancement-55 (above) marked a side-effecting callback op-dependent
        // when an op-dependent branch controlled it. That covered the case it
        // was chasing and left the opposite one open: a callback under NO
        // condition at all is in no op-controlled block, so it stayed
        // op-INdependent -- its arguments are constants and nothing else makes
        // it vary -- and was hoisted into the instance-init split, which runs
        // once at setup instead of on every evaluation.
        //
        // The symptoms did not look related to each other. A bare `$stop;` was
        // silently inert (eval_flags stayed 0 for the whole analysis, while the
        // same `$stop` under a run-time condition set flag 8 immediately), and
        // a bare `$strobe` printed TWICE across a 146-point transient where the
        // conditional form printed 294 times. `$finish` appeared to work only
        // because ngspice checks FATAL|FINISH at setup (osdisetup.c), which is
        // exactly where the hoisted call had gone.
        //
        // A statement under no condition executes on every evaluation by
        // definition, so there is no case in which hoisting one of these out of
        // eval is right. The op_controlled set is still computed above: it is
        // what makes the CONTROLLED case work, and this loop now covers the
        // uncontrolled remainder.
        for bb in self.func.layout.blocks() {
            let controlled = op_controlled.contains(bb);
            let mut cursor = self.func.layout.block_inst_cursor(bb);
            while let Some(inst) = cursor.next(&self.func.layout) {
                if let mir::InstructionData::Call { func_ref, .. } = self.func.dfg.insts[inst] {
                    match self.intern.callbacks[func_ref] {
                        // Enhancement-505: a return-flag callback belongs in eval
                        // whether or not a condition controls it.
                        //
                        // Enhancement-55 marked these only inside an op-controlled
                        // block, which left the UNCONDITIONAL case op-independent --
                        // its arguments are constants and nothing else makes it vary
                        // -- so it was hoisted into the instance-init split, which
                        // runs once at setup instead of on every evaluation. A bare
                        // `$stop;` was therefore inert: eval_flags stayed 0 for the
                        // whole analysis, while the same `$stop` under a run-time
                        // condition set flag 8 at the first point. `$finish` only
                        // appeared to work because ngspice also tests FATAL|FINISH
                        // at setup (osdisetup.c), which is exactly where the hoisted
                        // call had gone.
                        //
                        // A statement under no condition executes on every
                        // evaluation by definition, so hoisting one out of eval is
                        // never right. These take no arguments, so relocating them
                        // cannot strand an operand.
                        CallBackKind::SetRetFlag(_) => {
                            self.op_dependent_insts.insert(inst);
                        }
                        // Enhancement-505: `Print` is deliberately NOT included.
                        // Its arguments are real values, and an unconditional print
                        // whose operands are computed in the init split does not
                        // dominate its new position once the call is moved to eval
                        // -- codegen then reads a `BuilderVal::Undef` and the
                        // compiler aborts (mir_llvm/builder.rs:143). Measured on
                        // examples/concat_examples, whose `$sformat` machinery this
                        // crashed outright. An unconditional `$strobe` consequently
                        // still runs at init rather than per evaluation; moving it
                        // safely means moving its operands too, which is a larger
                        // change than this one and is recorded as an open finding.
                        CallBackKind::Print { .. } if controlled => {
                            self.op_dependent_insts.insert(inst);
                        }
                        _ => {}
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
