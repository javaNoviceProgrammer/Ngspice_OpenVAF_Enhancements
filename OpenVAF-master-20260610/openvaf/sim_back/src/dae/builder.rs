use bitset::BitSet;
use hir::lints::builtin::discarded_contribution;
use hir::{BranchKind, BranchWrite, CompilationDB, ContributionMap, Node, ParamSysFun};
use hir_lower::{CurrentKind, HirInterner, ImplicitEquation, ParamKind};
use indexmap::IndexSet;
use mir::builder::InstBuilder;
use mir::cursor::{Cursor, FuncCursor};
use mir::{
    strip_optbarrier, Block, ControlFlowGraph, DominatorTree, Inst, KnownDerivatives, Unknown,
    Value, FALSE, F_ONE, F_ZERO, TRUE,
};
use mir_autodiff::auto_diff;
use rustc_hash::FxHasher;
use std::collections::{HashMap, HashSet};
use std::hash::BuildHasherDefault;
use std::mem::replace;
use std::vec;
use typed_index_collections::TiVec;

use crate::context::Context;
use crate::dae::{
    DaeSystem, MatrixEntry, Residual, ResidualNatureKind, SimUnknown,
};
use crate::diagnostics::DiscardedContribution;
use crate::noise::{NoiseSource, NoiseSourceKind};
use crate::topology::{BranchInfo, Contribution};
use crate::util::{add, is_op_dependent, update_optbarrier};
use crate::{ModuleInfo, SimUnknownKind};

impl Residual {
    fn add(&mut self, cursor: &mut FuncCursor, negate: bool, mut val: Value) {
        // Cursor points at MIR function
        // Go back and skip all optbarriers to get the first actual instruction producing val
        val = strip_optbarrier(&cursor, val);
        // Add or subtract val to resistive residual value, replace resistive value by result
        add(cursor, &mut self.resist, val, negate);
    }

    fn add_contribution(&mut self, contrib: &Contribution, cursor: &mut FuncCursor, negate: bool) {
        let mut add = |residual: &mut Value, contrib| {
            // Cursor points at MIR function
            // Go back and skip all optbarriers to get the first actual instruction producing contrib
            let contrib = strip_optbarrier(&mut *cursor, contrib);
            // Add/subtract contrib to/from residual, replace residual with result
            add(cursor, residual, contrib, negate)
        };
        add(&mut self.resist, contrib.resist);
        add(&mut self.react, contrib.react);
        add(&mut self.resist_small_signal, contrib.resist_small_signal);
        add(&mut self.react_small_signal, contrib.react_small_signal);
    }
}

macro_rules! get_residual {
    ($self: ident, $unknown: expr) => {{
        let unknown = $self.ensure_unknown($unknown);
        &mut $self.system.residual[unknown]
    }};
}

pub(super) struct Builder<'a> {
    pub(super) system: DaeSystem,
    pub(super) cursor: FuncCursor<'a>,
    pub(super) db: &'a CompilationDB,
    pub(super) module: &'a ModuleInfo,
    pub(super) intern: &'a mut HirInterner,
    pub(super) cfg: &'a mut ControlFlowGraph,
    pub(super) dom_tree: &'a mut DominatorTree,
    pub(super) op_dependent_insts: &'a BitSet<Inst>,
    pub(super) output_values: &'a mut BitSet<Value>,
    /// Enhancement-400: see [`Context::unconditional_branch_kind`].
    pub(super) unconditional_branch_kind: &'a HashSet<BranchWrite>,
    /// Enhancement-400: this module's contribution statements bucketed by branch, built
    /// from the HIR on first use (every module has branches, but a module with no analog
    /// block at all should not pay for the walk).
    pub(super) contribution_sites: Option<ContributionMap>,
    /// Enhancement-400: branches written as both a potential and a flow source, collected
    /// here and reported by [`DaeSystem::new`] once the whole system is built.
    pub(super) discarded_contributions: Vec<DiscardedContribution>,
    /// Enhancement-401: branches that carry a 0 V source ONLY because their collapse hint
    /// cannot be honoured. If the netlist ties their terminals to one circuit node the
    /// equation is redundant and the system singular, so the simulator is told about them
    /// and drops the branch current then. Recorded only where the model does not read the
    /// branch current, which is what makes dropping it safe.
    pub(super) terminal_shorts: Vec<BranchWrite>,
}

impl<'a> Builder<'a> {
    pub(super) fn new(ctx: &'a mut Context) -> Self {
        ctx.compute_outputs(false);
        let mut builder = Self {
            system: DaeSystem::default(),
            cursor: FuncCursor::new(&mut ctx.func).at_exit(),
            db: ctx.db,
            module: ctx.module,
            intern: &mut ctx.intern,
            cfg: &mut ctx.cfg,
            dom_tree: &mut ctx.dom_tree,
            op_dependent_insts: &ctx.op_dependent_insts,
            output_values: &mut ctx.output_values,
            unconditional_branch_kind: &ctx.unconditional_branch_kind,
            contribution_sites: None,
            discarded_contributions: Vec::new(),
            terminal_shorts: Vec::new(),
        };

        // ensure ports are the first unknowns and always have an unknown
        for port in ctx.module.module.ports(builder.db) {
            builder.build_node(port)
        }

        for node in ctx.module.module.internal_nodes(builder.db) {
            builder.build_node(node)
        }

        builder
    }

    pub(super) fn finish(mut self) -> DaeSystem {
        // Give every probed port flow `I(<p>)` a defining equation + unknown before we
        // compute derivatives/jacobian, so it participates like any branch current.
        self.build_port_flow_equations();
        // ... and every PROBE-ONLY branch its 0V-source (ideal ammeter) equation
        // (Enhancement-36), for the same reason.
        self.build_probe_only_branches();

        let sim_unknown_reads = self.sim_unknown_reads();
        let derivative_info = self.intern.unknowns(&self.cursor, true);
        let extra_derivatives = self
            .jacobian_derivatives(sim_unknown_reads.iter().map(|&(_, val)| val), &derivative_info);
        // TODO(pref): incrementially update dom_tree (for switch branches) instead
        self.dom_tree.compute(self.cursor.func, self.cfg, true, false, true);
        let derivatives =
            auto_diff(&mut *self.cursor.func, self.dom_tree, &derivative_info, &extra_derivatives);
        drop(extra_derivatives);
        // auto_diff may in an unlikely case add extra bb at the end, ensure we are building everything at the end
        self.cursor.goto_exit();

        self.build_jacobian(&sim_unknown_reads, &derivative_info, &derivatives);
        self.build_lim_rhs(&derivative_info, derivatives);
        self.ensure_optbarriers();

        self.build_input_unknown_pairs();

        let (nres, nreact) = self.count_jacobian_entries();
        self.system.num_resistive = nres;
        self.system.num_reactive = nreact;

        self.system
    }

    pub(super) fn build_node(&mut self, node: Node) {
        self.ensure_unknown(SimUnknownKind::KirchoffLaw(node));
    }

    pub(super) fn with_small_signal_network(
        mut self,
        small_signal_parameters: IndexSet<Value, BuildHasherDefault<FxHasher>>,
    ) -> Self {
        self.system.small_signal_parameters = small_signal_parameters;
        self
    }

    /// Return a list of all parameters that read from one of the simulation
    /// unknowns and therefore need to be considered during matrix construction.
    /// These need to be constructed from the list of parameters instead of the list
    /// of sim unknowns because voltage probes access two node voltages at the same time:
    ///
    /// V(x, y) = V(x) - V(y)
    ///
    /// We derive by these voltage differences to reduce the number of generated derivatives.
    fn sim_unknown_reads(&self) -> Vec<(ParamKind, Value)> {
        self.intern
            .live_params(&self.cursor.func.dfg)
            .filter_map(move |(_, &kind, param)| {
                if matches!(
                    kind,
                    ParamKind::Voltage { .. }
                        | ParamKind::Current(_)
                        | ParamKind::ImplicitUnknown(_)
                ) {
                    Some((kind, param))
                } else {
                    None
                }
            })
            .collect()
    }

    // Create a list of input node pairs corresponding to all model inputs
    fn build_input_unknown_pairs(&mut self) {
        self.system.model_inputs.clear();
        for (_, &kind, _) in self.intern.live_params(&self.cursor.func.dfg) {
            match kind {
                ParamKind::Voltage { hi, lo } => {
                    let mut ih = std::u32::MAX;
                    let mut il = std::u32::MAX;
                    let uh = SimUnknownKind::KirchoffLaw(hi);
                    if let Some(uh) = self.system.unknowns.index(&uh) {
                        ih = u32::from(uh);
                    }
                    if let Some(lo) = lo {
                        let ul = SimUnknownKind::KirchoffLaw(lo);
                        if let Some(ul) = self.system.unknowns.index(&ul) {
                            il = u32::from(ul);
                        }
                    }
                    if ih != std::u32::MAX && il != std::u32::MAX {
                        self.system.model_inputs.push((ih, il));
                    }
                }
                ParamKind::Current(cur_kind) => {
                    // Port flows I(<p>) are wired just like branch/unnamed currents:
                    // build_port_flow_equations() gives each one a defining equation and a
                    // Current unknown, so they participate as ordinary model inputs.
                    let u = SimUnknownKind::Current(cur_kind);
                    if let Some(u) = self.system.unknowns.index(&u) {
                        self.system.model_inputs.push((u32::from(u), std::u32::MAX));
                    }
                }
                ParamKind::ImplicitUnknown(ieq_kind) => {
                    let u = SimUnknownKind::Implicit(ieq_kind);
                    if let Some(u) = self.system.unknowns.index(&u) {
                        self.system.model_inputs.push((u32::from(u), std::u32::MAX));
                    }
                }
                _ => {}
            }
        }
    }

    fn count_jacobian_entries(&mut self) -> (u32, u32) {
        // Count resistive and reactive Jacobian entries
        let mut nres: u32 = 0;
        let mut nreact: u32 = 0;
        for key in self.system.jacobian.keys() {
            if self.system.jacobian[key].resist != F_ZERO {
                nres = nres + 1;
            }

            if self.system.jacobian[key].react != F_ZERO {
                nreact = nreact + 1;
            }
        }
        (nres, nreact)
    }

    fn build_lim_rhs(
        &mut self,
        derivative_info: &KnownDerivatives,
        derivatives: HashMap<(Value, Unknown), Value, BuildHasherDefault<FxHasher>>,
    ) {
        for residual in &mut self.system.residual {
            for (state, (unchanged, lim_vals)) in self.intern.lim_state.iter_enumerated() {
                for &(val, neg) in lim_vals {
                    let unknown = if let Some(unknown) = derivative_info.unknowns.index(&val) {
                        unknown
                    } else {
                        continue;
                    };
                    let changed = HirInterner::ensure_param_(
                        &mut self.intern.params,
                        &mut self.cursor,
                        ParamKind::NewState(state),
                    );

                    let delta = if neg {
                        self.cursor.ins().fadd(changed, *unchanged)
                    } else {
                        self.cursor.ins().fsub(changed, *unchanged)
                    };
                    let mut add_lim_rhs = |dst, residual, residual_small_signal| {
                        let mut ddx =
                            derivatives.get(&(residual, unknown)).copied().unwrap_or(F_ZERO);
                        let ddx_small_signal = derivatives
                            .get(&(residual_small_signal, unknown))
                            .copied()
                            .unwrap_or(F_ZERO);
                        add(&mut self.cursor, &mut ddx, ddx_small_signal, false);
                        if ddx != F_ZERO && delta != F_ZERO {
                            let rhs = self.cursor.ins().fmul(ddx, delta);
                            add(&mut self.cursor, dst, rhs, false);
                        }
                    };
                    add_lim_rhs(
                        &mut residual.resist_lim_rhs,
                        residual.resist,
                        residual.resist_small_signal,
                    );
                    add_lim_rhs(
                        &mut residual.react_lim_rhs,
                        residual.react,
                        residual.react_small_signal,
                    );
                }
            }
        }
    }

    fn build_jacobian(
        &mut self,
        sim_unknown_reads: &[(ParamKind, Value)],
        derivative_info: &KnownDerivatives,
        derivatives: &HashMap<(Value, Unknown), Value, BuildHasherDefault<FxHasher>>,
    ) {
        // Enhancement-404: the jacobian is sparse, so reserving `unknowns^2` entries here
        // asked for a dense matrix that is never built -- 4.3e9 entries for a module with
        // a `[65535:0]` bus. The diagonal is a sane lower bound to start from.
        self.system.jacobian = TiVec::with_capacity(self.system.unknowns.len());

        //  construct the matrix by creating a dense row and then sparsifying
        let mut dense_row = TiVec::from(vec![(F_ZERO, F_ZERO); self.system.unknowns.len()]);
        // Enhancement-404: columns `add_residual` reached in the current row. Scanning the
        // whole dense row per row was O(unknowns^2); a row only ever touches the columns
        // listed here. Sorted before use, so entries still come out in ascending column
        // order and the emitted matrix is byte-identical to the full scan.
        let mut touched: Vec<SimUnknown> = Vec::new();
        let mut add = |matrix_entry: &mut Value, residual, unknown, negate| {
            if let Some(ddx) = derivatives.get(&(residual, unknown)).copied() {
                add(&mut self.cursor, matrix_entry, ddx, negate)
            }
        };

        for (row, residual) in self.system.residual.iter_enumerated() {
            // construct the dense row
            let mut add_residual = |sim_unknown: SimUnknownKind, unknown, negate| {
                let sim_unknown = if let Some(unknown) = self.system.unknowns.index(&sim_unknown) {
                    unknown
                } else {
                    return;
                };
                touched.push(sim_unknown);
                let (resist, react) = &mut dense_row[sim_unknown];
                if let Some(lim_vals) = self.intern.lim_state.raw.get(&unknown) {
                    for (val, negate_lim) in lim_vals {
                        let lim_unknown = if let Some(it) = derivative_info.unknowns.index(val) {
                            it
                        } else {
                            continue;
                        };
                        add(resist, residual.resist, lim_unknown, negate != *negate_lim);
                        add(
                            resist,
                            residual.resist_small_signal,
                            lim_unknown,
                            negate != *negate_lim,
                        );
                        add(react, residual.react, lim_unknown, negate != *negate_lim);
                        add(react, residual.react_small_signal, lim_unknown, negate != *negate_lim);
                    }
                }

                if let Some(unknown) = derivative_info.unknowns.index(&unknown) {
                    add(resist, residual.resist, unknown, negate);
                    add(resist, residual.resist_small_signal, unknown, negate);
                    add(react, residual.react, unknown, negate);
                    add(react, residual.react_small_signal, unknown, negate);
                }
            };
            for &(kind, val) in sim_unknown_reads {
                let unknown = match kind {
                    ParamKind::Voltage { hi, lo } => {
                        if let Some(lo) = lo {
                            add_residual(SimUnknownKind::KirchoffLaw(lo), val, true);
                        }
                        SimUnknownKind::KirchoffLaw(hi)
                    }
                    ParamKind::ImplicitUnknown(equation) => SimUnknownKind::Implicit(equation),
                    ParamKind::Current(kind) => SimUnknownKind::Current(kind),
                    _ => continue,
                };
                add_residual(unknown, val, false);
            }

            // sparsify the row
            touched.sort_unstable();
            touched.dedup();
            for col in touched.drain(..) {
                let (resist, react) = &mut dense_row[col];
                if *resist == F_ZERO && *react == F_ZERO {
                    continue;
                }
                self.system.jacobian.push(MatrixEntry {
                    row,
                    col,
                    resist: replace(resist, F_ZERO),
                    react: replace(react, F_ZERO),
                });
            }
        }
    }




    pub fn jacobian_derivatives(
        &self,
        simulation_unknown: impl Iterator<Item = Value>,
        derivatives: &KnownDerivatives,
    ) -> Vec<(Value, Unknown)> {
        let mut params: Vec<_> =
            simulation_unknown.filter_map(|param| derivatives.unknowns.index(&param)).collect();
        let lim_derivatives = self.intern.lim_state.raw.values().flat_map(|vals| {
            vals.iter().filter_map(|(val, _)| {
                if self.cursor.func.dfg.value_dead(*val) {
                    return None;
                }
                derivatives.unknowns.index(val)
            })
        });
        params.extend(lim_derivatives);

        let small_signal_params = self
            .system
            .small_signal_parameters
            .iter()
            .filter_map(|&param| derivatives.unknowns.index(&param));

        let num_unknowns = params.len() * self.system.residual.len() * 2;
        let mut res = Vec::with_capacity(num_unknowns);
        for residual in &self.system.residual {
            if self.cursor.func.dfg.value_def(residual.resist).as_const().is_none() {
                res.extend(params.iter().map(|unknown| (residual.resist, *unknown)))
            }
            if self.cursor.func.dfg.value_def(residual.react).as_const().is_none() {
                res.extend(params.iter().map(|unknown| (residual.react, *unknown)))
            }
            if self.cursor.func.dfg.value_def(residual.resist_small_signal).as_const().is_none() {
                res.extend(
                    small_signal_params
                        .clone()
                        .map(|unknown| (residual.resist_small_signal, unknown)),
                )
            }
            if self.cursor.func.dfg.value_def(residual.react_small_signal).as_const().is_none() {
                res.extend(
                    small_signal_params
                        .clone()
                        .map(|unknown| (residual.react_small_signal, unknown)),
                )
            }
        }
        res
    }

    /// Enhancement-401: would a `V(a,b) <+ 0` collapse hint for this branch be IGNORED by
    /// the simulator?
    ///
    /// ngspice allocates terminal nodes itself, so `collapse_nodes`
    /// (`ngspice-46/src/osdi/osdisetup.c`) skips any collapse pair whose endpoints are all
    /// simulator-allocated -- terminal-to-terminal and terminal-to-ground. Such a branch
    /// then connects NOTHING: the simulator drops the collapse, and the DAE build, seeing
    /// a trivial potential contribution, builds no equation either, so two nodes the model
    /// shorted are left open (the LRM's own `parares` becomes an open circuit at small r).
    /// Build the real 0 V source for exactly that case.
    ///
    /// A collapse onto an INTERNAL node is honoured and must be left alone -- it is what
    /// every compact model uses for a degenerate series resistance (BSIM4's
    /// `V(s,si) <+ 0`), and turning those into equations would add an unknown per node.
    ///
    /// The 0 V source is only half the fix: if the netlist happens to tie the two
    /// terminals to the SAME circuit node the equation is redundant and the system is
    /// singular, which the simulator resolves using the terminal-short metadata recorded
    /// alongside it (see `Builder::terminal_shorts`).
    fn collapse_is_ignored(&self, branch: BranchWrite) -> bool {
        let db = self.db;
        let (hi, lo) = match branch {
            BranchWrite::Named(branch) => match branch.kind(db) {
                BranchKind::Nodes(hi, lo) => (hi, Some(lo)),
                BranchKind::NodeGnd(hi) => (hi, None),
                // a port-flow branch has no node pair to collapse
                BranchKind::PortFlow(_) => return false,
            },
            BranchWrite::Unnamed { hi, lo } => (hi, lo),
        };
        // ground is simulator-allocated too; `lo == None` already means ground
        [Some(hi), lo]
            .into_iter()
            .flatten()
            .filter(|node| !node.is_gnd(db))
            .all(|node| node.is_port(db))
    }

    /// Enhancement-400: `is_voltage_src` is a CONSTANT here, so on every path the last
    /// contribution to `branch` was of the kind named by `kept_potential`, and the branch
    /// is built as a plain potential or flow source. If the module *also* contributes the
    /// other kind to it, that contribution can never take effect: its value reaches
    /// neither the residual nor the Jacobian, and nothing said so.
    ///
    /// No single stage can answer this. The DAE build knows the branch is not a switch --
    /// a genuine switch branch has a runtime `is_voltage_src` and lands in the `_` arm
    /// below, where both kinds stay live -- but it cannot see the discarded contribution
    /// at all, because `hir_lower::stmt::contribute_value` resets the opposite place to
    /// zero as it writes, so `BranchInfo` reports it as trivially zero exactly like a
    /// contribution that was never written. The HIR still has both statements, so ask it;
    /// and the unoptimized MIR (below) decides whether the model or the optimizer made
    /// the branch single-kind.
    fn check_discarded_contribution(&mut self, branch: BranchWrite, kept_potential: bool) {
        // ... but only if the model itself decided the branch's kind. Optimization can
        // also make `is_voltage_src` constant, by folding an `if` whose condition is a
        // configuration constant -- a `\`ifdef`-driven mode selector, say. The surviving
        // arm of a correctly written switch branch is not a discarded contribution, it is
        // the configuration doing its job, so ask the unoptimized MIR instead.
        if !self.unconditional_branch_kind.contains(&branch) {
            return;
        }
        let db = self.db;
        let sites = self
            .contribution_sites
            .get_or_insert_with(|| {
                self.module.module.contribution_sites(db, discarded_contribution)
            })
            .get(db, branch);
        if !sites.iter().any(|site| site.potential != kept_potential && !site.zero) {
            return;
        }
        let name = match branch {
            BranchWrite::Named(branch) => branch.name(db),
            BranchWrite::Unnamed { hi, lo: Some(lo) } => {
                format!("({},{})", hi.name(db), lo.name(db))
            }
            BranchWrite::Unnamed { hi, lo: None } => format!("({})", hi.name(db)),
        };
        let sites = sites.to_vec();
        self.discarded_contributions.push(DiscardedContribution {
            branch: name,
            module: self.module.module.name(db),
            kept_potential,
            sites,
        });
    }

    pub(super) fn build_branch(&mut self, branch: BranchWrite, contributions: &BranchInfo) {
        let current = branch.into();
        // contributions.is_voltage_src is a Value that is used for choosing the branch type (voltage, current)
        match contributions.is_voltage_src {
            // If it is constant FALSE; this is a current branch
            FALSE => {
                // Enhancement-400: a flow branch the module also contributes a
                // potential to -- that potential value is computed and thrown away.
                self.check_discarded_contribution(branch, false);
                // if the current of the branch is probed we need to create an extra
                // branch
                let requires_unknown =
                    self.intern.is_param_live(&self.cursor, &ParamKind::Current(current));
                let contrib = self.current_branch(contributions);
                if requires_unknown {
                    // A branch with current contributions only, its current must remain an unknown
                    // The residual of the added quation is discipline.flow
                    self.add_source_equation(
                        &contrib,
                        // &contributions.current_src,
                        contributions.current_src.unknown.unwrap(),
                        branch,
                        ResidualNatureKind::Flow,
                    );
                } else {
                    // A branch with current contributions only, current does not rmain an unknown
                    // This is a KCL equation, its residual is discipline.flow
                    self.add_kirchoff_law(&contrib, branch);
                    // self.add_kirchoff_law(&contributions.current_src, branch);
                }
            }
            // If it is constant TRUE; this is a voltage branch
            TRUE => {
                // Enhancement-400: the mirror image -- a potential branch the module
                // also contributes a flow to.
                self.check_discarded_contribution(branch, true);
                // branches only used for node collapsing look like pure current
                // sources, make sure to ignore these branches
                let requires_unknown =
                    self.intern.is_param_live(&self.cursor, &ParamKind::Current(current));
                // Enhancement-401: ... unless the collapse it relies on cannot be
                // honoured, in which case the branch must carry a real 0 V source.
                let only_for_collapse =
                    !requires_unknown && contributions.voltage_src.is_trivial();
                let collapse_ignored = only_for_collapse && self.collapse_is_ignored(branch);
                if collapse_ignored {
                    self.terminal_shorts.push(branch);
                }
                if requires_unknown || !contributions.voltage_src.is_trivial() || collapse_ignored
                {
                    let contrib = self.voltage_branch(contributions);
                    // A branch with voltage contributions only, we need a nextra equation
                    // because its current must be an unknown in the DAE system
                    // The residual of this extra equation is discipline.potential
                    self.add_source_equation(
                        &contrib,
                        contributions.current_src.unknown.unwrap(),
                        branch,
                        ResidualNatureKind::Potential,
                    );
                }
            }

            // Otherwise this is a switch branch
            _ => {
                let requires_current_unknown = !self
                    .cursor
                    .as_ref()
                    .dfg
                    .value_dead(contributions.current_src.unknown.unwrap());
                let op_dependent = is_op_dependent(
                    &self.cursor,
                    contributions.is_voltage_src,
                    self.op_dependent_insts,
                    self.intern,
                );
                // most cases that look like switch branches are just node collapsing
                // so make sure we don't crate switch branches when they aren't needed
                // Enhancement-401: a conditional collapse between two terminals is a real
                // switch branch, not "just node collapsing" -- the simulator ignores the
                // hint, so the 0 V arm has to be an equation. This is the arm the LRM's
                // `parares` takes: its condition is parameter-dependent, so
                // `is_voltage_src` is a runtime value but `op_dependent` is false.
                let only_for_collapse = !op_dependent
                    && !requires_current_unknown
                    && contributions.voltage_src.is_trivial();
                let collapse_ignored = only_for_collapse && self.collapse_is_ignored(branch);
                if collapse_ignored {
                    self.terminal_shorts.push(branch);
                }
                if op_dependent
                    || requires_current_unknown
                    || !contributions.voltage_src.is_trivial()
                    || collapse_ignored
                {
                    // An actual switch branch
                    let start_bb = self.cursor.current_block().unwrap();
                    let voltage_src_bb = self.cursor.layout_mut().append_new_block();
                    let next_block = self.cursor.layout_mut().append_new_block();
                    self.cfg.ensure_bb(next_block);
                    self.cfg.add_edge(start_bb, voltage_src_bb);
                    self.cfg.add_edge(start_bb, next_block);
                    self.cfg.add_edge(voltage_src_bb, next_block);

                    // Debugging
                    // println!("start bb {:?}", start_bb);
                    // println!("voltage src bb {:?}", voltage_src_bb);
                    // println!("next block {:?}", next_block);
                    // println!("cursor at {:?}", self.cursor.position());

                    // Get expression (condition) that determines if branch acts as a voltage source
                    // Skip trailing optbarriers
                    let is_voltage_src =
                        strip_optbarrier(&self.cursor, contributions.is_voltage_src);
                    // Insert branch command (after?) condition
                    // If condition is true, jump to voltage_src_bb block
                    // If false go to next_block
                    self.cursor.ins().br(is_voltage_src, voltage_src_bb, next_block);
                    // Go to the end of voltage_src_bb block
                    self.cursor.goto_bottom(voltage_src_bb);
                    // Insert jump command to next_block
                    self.cursor.ins().jump(next_block);
                    // Go to the end of next_block
                    self.cursor.goto_bottom(next_block);
                    let contrib = self.switch_branch(contributions, voltage_src_bb, start_bb);
                    // The residual switches between discipline.flow and discipline.potential
                    // depending on is_voltage_src
                    //   TRUE  .. discipline.potential
                    //   FALSE .. discipline.flow
                    // Will have to expose is_voltage_src in the OSDI API... TODO
                    self.add_source_equation(
                        &contrib,
                        contributions.current_src.unknown.unwrap(),
                        branch,
                        ResidualNatureKind::Switch,
                    )
                } else {
                    // Not a real switch branch
                    let contrib = self.current_branch(contributions);
                    self.add_kirchoff_law(&contrib, branch);
                }
            }
        };
    }

    /// Give every probed port flow `I(<p>)` a defining equation and DAE unknown.
    ///
    /// A port branch has no `branch(...)` object, so unlike a named/unnamed branch
    /// current it never passes through `build_branch`/`add_source_equation`. Instead we
    /// synthesise its equation here, once all Kirchhoff residuals are populated. By KCL
    /// the current entering the module through port `p` equals the net device current
    /// flowing out of node `p`, which is exactly `residual[KCL(p)]`:
    ///
    ///   `Iport(p) = residual[KCL(p)]`   (resistive + reactive)
    ///
    /// We mirror node `p`'s resistive and reactive residual into the port-current row and
    /// subtract the unknown, so the solved value includes displacement (reactive) current
    /// for free. `Iport` is the very same param the model reads via `I(<p>)`, so
    /// current-controlled sources built on top of it see the correct value.
    fn build_port_flow_equations(&mut self) {
        // Collect the (deduplicated) set of ports whose flow is actually probed.
        let mut ports: Vec<Node> = Vec::new();
        for (_, &kind, _) in self.intern.live_params(&self.cursor.func.dfg) {
            if let ParamKind::Current(CurrentKind::Port(node)) = kind {
                if !ports.contains(&node) {
                    ports.push(node);
                }
            }
        }

        for node in ports {
            // `Iport` — the same input param the model reads as `I(<p>)`.
            let iport = self
                .intern
                .ensure_param(&mut self.cursor, ParamKind::Current(CurrentKind::Port(node)));

            // Snapshot node p's Kirchhoff residual (net device current out of p).
            let kcl = self.ensure_unknown(SimUnknownKind::KirchoffLaw(node));
            let (resist, react) = {
                let r = &self.system.residual[kcl];
                (r.resist, r.react)
            };
            let contrib = Contribution {
                unknown: None,
                resist,
                react,
                resist_small_signal: F_ZERO,
                react_small_signal: F_ZERO,
                noise: Vec::new(),
            };

            // residual[Iport] = residual[KCL(p)] - Iport   =>   Iport = current into p
            let residual = get_residual!(self, SimUnknownKind::Current(CurrentKind::Port(node)));
            residual.add_contribution(&contrib, &mut self.cursor, false);
            residual.add(&mut self.cursor, true, iport);
            residual.nature_kind = ResidualNatureKind::Flow;
        }
    }

    /// Enhancement-36: gives every PROBE-ONLY branch its 0V-source (ideal ammeter)
    /// equation and DAE unknown.
    ///
    /// The topology only materialises branches that are *contributed* to (it is keyed
    /// off the `IsVoltageSrc` outputs, which only exist for contributions), so a branch
    /// that is merely probed — `x = I(p, n);`, or a declared `branch (p,n) sense;` that
    /// only ever appears inside `I(sense)` — never reached the DAE: its current param
    /// fell back to the "always zero" eval path AND the branch conducted nothing (an
    /// open circuit). Per the LRM a flow-probed branch with no contribution behaves as
    /// a **short** (a potential source of 0) whose current is the probed value — the
    /// ideal-ammeter idiom, and the mechanism flow-only (`current` discipline)
    /// signal-flow nets ride on.
    ///
    /// The synthesised system mirrors `add_source_equation` for a voltage branch with
    /// source expression 0:
    ///
    ///   `residual[Current(br)] = -V(hi,lo)`  (nature Potential; equation V(hi,lo) = 0)
    ///   `residual[KCL(hi)] += I(br)` , `residual[KCL(lo)] -= I(br)`
    ///
    /// Port flows are excluded — they get their own defining equation in
    /// `build_port_flow_equations` above. Note that paralleling several probe-only
    /// branches across the *same* node pair is degenerate (parallel ideal 0V sources),
    /// exactly as paralleling ideal voltage sources is.
    fn build_probe_only_branches(&mut self) {
        // Collect the (deduplicated) set of probed branch currents that the
        // contribution-driven `build_branch` pass did not materialise.
        let mut todo: Vec<CurrentKind> = Vec::new();
        for (_, &kind, _) in self.intern.live_params(&self.cursor.func.dfg) {
            if let ParamKind::Current(cur) = kind {
                if matches!(cur, CurrentKind::Port(_)) {
                    continue;
                }
                if self.system.unknowns.index(&SimUnknownKind::Current(cur)).is_none()
                    && !todo.contains(&cur)
                {
                    todo.push(cur);
                }
            }
        }

        for cur in todo {
            let (hi, lo) = BranchWrite::try_from(cur)
                .expect("port flows are filtered above")
                .nodes(self.db);

            // `I(br)` — the same input param the model reads; its value is injected
            // into the Kirchhoff rows of the branch's nodes.
            let i_br = self.intern.ensure_param(&mut self.cursor, ParamKind::Current(cur));
            // V(hi,lo) — the branch voltage the source equation pins to zero.
            let v = self.intern.ensure_param(&mut self.cursor, ParamKind::Voltage { hi, lo });

            // residual[Current(br)] = 0 - V(hi,lo)   (same shape as add_source_equation
            // with a zero source expression)
            let residual = get_residual!(self, SimUnknownKind::Current(cur));
            residual.add(&mut self.cursor, true, v);
            residual.nature_kind = ResidualNatureKind::Potential;

            // Kirchhoff rows: positive branch current flows from `hi` to `lo`.
            get_residual!(self, SimUnknownKind::KirchoffLaw(hi)).add(
                &mut self.cursor,
                false,
                i_br,
            );
            if let Some(lo) = lo {
                get_residual!(self, SimUnknownKind::KirchoffLaw(lo)).add(
                    &mut self.cursor,
                    true,
                    i_br,
                );
            }
        }
    }

    pub(super) fn build_implicit_equation(&mut self, eq: ImplicitEquation, contrib: &Contribution) {
        get_residual!(self, SimUnknownKind::Implicit(eq)).add_contribution(
            contrib,
            &mut self.cursor,
            false,
        );
        // Enhancement-54: noise attached to an implicit-equation contribution (the
        // `Evaluation::Equation` path: NoiseSrc unknowns and ddt correlation
        // networks) was silently dropped here -- every other add_contribution site
        // pairs with add_noise. Without this the source never reaches the OSDI
        // descriptor and the simulator reports no noise for it at all.
        self.add_noise(contrib, SimUnknownKind::Implicit(eq), None);
    }

    fn mfactor_multiply(&mut self, mfactor: Value, srcfactor: Value) -> Value {
        match (mfactor, srcfactor) {
            // Leave srcfactor unchanged if mfactor is 1
            (F_ONE, fac) => fac,
            // mfactor is not 1
            // Note that srcfactor is the signal scaling factor.
            // Because power scales with mfactor the signal scales with
            // sqrt(mfactor).
            (mfactor, srcfactor) => {
                let sqrt_mfactor = self.cursor.ins().sqrt(mfactor);
                if srcfactor == F_ONE {
                    // Old factor is 1, replace it with sqrt(mfactor)
                    sqrt_mfactor
                } else {
                    // Multiply old factor with sqrt(mfactor)
                    self.cursor.ins().fmul(srcfactor, sqrt_mfactor)
                }
            }
        }
    }

    /// Multiplies a deterministic small-signal source factor by the full
    /// mfactor (`ac_stim`, Enhancement-51) -- unlike noise, whose SIGNAL
    /// scales with sqrt(mfactor) because its POWER scales with mfactor.
    fn mfactor_multiply_linear(&mut self, mfactor: Value, srcfactor: Value) -> Value {
        match (mfactor, srcfactor) {
            (F_ONE, fac) => fac,
            (mfactor, F_ONE) => mfactor,
            (mfactor, srcfactor) => self.cursor.ins().fmul(srcfactor, mfactor),
        }
    }

    fn mfactor_divide(&mut self, mfactor: Value, srcfactor: Value) -> Value {
        match (mfactor, srcfactor) {
            // Leave srcfactor unchanged if mfactor is 1
            (F_ONE, fac) => fac,
            // mfactor is not 1
            // Note that srcfactor is the signal scaling factor.
            // Because power scales with mfactor the signal scales with
            // sqrt(mfactor).
            (mfactor, srcfactor) => {
                let sqrt_mfactor = self.cursor.ins().sqrt(mfactor);
                self.cursor.ins().fdiv(srcfactor, sqrt_mfactor)
            }
        }
    }

    fn current_branch(&mut self, BranchInfo { current_src, .. }: &BranchInfo) -> Contribution {
        let mfactor = self
            .intern
            .ensure_param(&mut self.cursor, ParamKind::ParamSysFun(ParamSysFun::mfactor));
        let mut noise = Vec::with_capacity(current_src.noise.len());
        let current_noise = current_src.noise.iter().map(|src| {
            let mut src = src.clone();
            // noise powers scale with mfactor (signal by sqrt); an `ac_stim`
            // stimulus is a deterministic signal and scales linearly
            // (m parallel copies sum their currents) -- Enhancement-51
            src.factor = if matches!(src.kind, NoiseSourceKind::AcStim { .. }) {
                self.mfactor_multiply_linear(mfactor, src.factor)
            } else {
                self.mfactor_multiply(mfactor, src.factor)
            };
            // Enhancement-54: the j*omega component scales identically (it
            // multiplies the same wave); ac_stim never carries one
            if src.factor_react != F_ZERO {
                src.factor_react = self.mfactor_multiply(mfactor, src.factor_react);
            }
            src
        });
        noise.extend(current_noise);

        Contribution {
            unknown: current_src.unknown,
            resist: current_src.resist,
            react: current_src.react,
            resist_small_signal: current_src.resist_small_signal,
            react_small_signal: current_src.react_small_signal,
            noise,
        }
    }

    fn voltage_branch(&mut self, BranchInfo { voltage_src, .. }: &BranchInfo) -> Contribution {
        let mfactor = self
            .intern
            .ensure_param(&mut self.cursor, ParamKind::ParamSysFun(ParamSysFun::mfactor));
        let mut noise = Vec::with_capacity(voltage_src.noise.len());
        let voltage_noise = voltage_src.noise.iter().map(|src| {
            let mut src = src.clone();
            // a deterministic `ac_stim` voltage stimulus is mfactor-invariant
            // (m parallel copies of the same source hold the same voltage);
            // voltage NOISE divides by sqrt(mfactor) -- Enhancement-51
            if !matches!(src.kind, NoiseSourceKind::AcStim { .. }) {
                src.factor = self.mfactor_divide(mfactor, src.factor);
                if src.factor_react != F_ZERO {
                    src.factor_react = self.mfactor_divide(mfactor, src.factor_react);
                }
            }
            src
        });
        noise.extend(voltage_noise);

        Contribution {
            unknown: voltage_src.unknown,
            resist: voltage_src.resist,
            react: voltage_src.react,
            resist_small_signal: voltage_src.resist_small_signal,
            react_small_signal: voltage_src.react_small_signal,
            noise,
        }
    }

    fn switch_branch(
        &mut self,
        BranchInfo { voltage_src, current_src, .. }: &BranchInfo,
        voltage_bb: Block,
        current_bb: Block,
    ) -> Contribution {
        let mut select = |voltage_src_val, current_src_val| {
            let voltage_src_val = strip_optbarrier(&self.cursor, voltage_src_val);
            let current_src_val = strip_optbarrier(&self.cursor, current_src_val);
            if voltage_src_val == current_src_val {
                voltage_src_val
            } else {
                self.cursor
                    .ins()
                    .phi(&[(current_bb, current_src_val), (voltage_bb, voltage_src_val)])
            }
        };

        let voltage = voltage_src.unknown.unwrap();
        let current = current_src.unknown.unwrap();
        let unknown = select(voltage, current);
        // Build noise phi commands
        // Voltage noise, for each noise add a phi instruction that joins the values for
        // the case the switch branch behaves as a voltage source (source value) and as a current source (0)
        let mut noise = Vec::with_capacity(voltage_src.noise.len() + current_src.noise.len());
        let voltage_noise = voltage_src.noise.iter().map(|src| {
            let mut src = src.clone();
            src.factor = select(src.factor, F_ZERO);
            if src.factor_react != F_ZERO {
                src.factor_react = select(src.factor_react, F_ZERO);
            }
            src
        });
        noise.extend(voltage_noise);
        // Current noise, for each noise add a phi instruction that joins the values for
        // the case the switch branch behaves as a voltage source (0) and as a current source (source value)
        let current_noise = current_src.noise.iter().map(|src| {
            let mut src = src.clone();
            src.factor = select(F_ZERO, src.factor);
            if src.factor_react != F_ZERO {
                src.factor_react = select(F_ZERO, src.factor_react);
            }
            src
        });
        noise.extend(current_noise);
        // Build remaining phi commands
        let phi_resist = select(voltage_src.resist, current_src.resist);
        let phi_react = select(voltage_src.react, current_src.react);
        let phi_resist_ss =
            select(voltage_src.resist_small_signal, current_src.resist_small_signal);
        let phi_react_ss = select(voltage_src.react_small_signal, current_src.react_small_signal);
        // Scale noise
        // Must do this after all phi commands
        // because all phi commands must be listed at block beginning
        let mfactor = self
            .intern
            .ensure_param(&mut self.cursor, ParamKind::ParamSysFun(ParamSysFun::mfactor));
        for ii in 0..voltage_src.noise.len() + current_src.noise.len() {
            let is_ac_stim = matches!(noise[ii].kind, NoiseSourceKind::AcStim { .. });
            if ii < voltage_src.noise.len() {
                // Voltage noise divides by sqrt(mfactor); a deterministic
                // ac_stim voltage stimulus is mfactor-invariant (Enhancement-51)
                if !is_ac_stim {
                    noise[ii].factor = self.mfactor_divide(mfactor, noise[ii].factor);
                    if noise[ii].factor_react != F_ZERO {
                        noise[ii].factor_react =
                            self.mfactor_divide(mfactor, noise[ii].factor_react);
                    }
                }
            } else if is_ac_stim {
                // deterministic current stimulus: linear in mfactor
                noise[ii].factor = self.mfactor_multiply_linear(mfactor, noise[ii].factor);
            } else {
                // Current noise
                noise[ii].factor = self.mfactor_multiply(mfactor, noise[ii].factor);
                if noise[ii].factor_react != F_ZERO {
                    noise[ii].factor_react =
                        self.mfactor_multiply(mfactor, noise[ii].factor_react);
                }
            }
        }

        Contribution {
            unknown: Some(unknown),
            resist: phi_resist,
            react: phi_react,
            resist_small_signal: phi_resist_ss,
            react_small_signal: phi_react_ss,
            noise,
        }
    }

    fn ensure_unknown(&mut self, unknown: SimUnknownKind) -> SimUnknown {
        let (unknown, new) = self.system.unknowns.ensure(unknown);
        if new {
            self.system.residual.push(Residual::default());
        }
        unknown
    }

    fn add_noise(
        &mut self,
        contrib: &Contribution,
        hi: SimUnknownKind,
        lo: Option<SimUnknownKind>,
    ) {
        let hi = self.ensure_unknown(hi);
        let lo = lo.map(|lo| self.ensure_unknown(lo));
        self.system.noise_sources.extend(contrib.noise.iter().map(|src| {
            let factor = src.factor;
            let factor_react = src.factor_react;
            NoiseSource { name: src.name, idx: src.idx, kind: src.kind.clone(), hi, lo, factor, factor_react }
        }))
    }

    fn add_kirchoff_law(&mut self, contrib: &Contribution, dst: BranchWrite) {
        let (hi, lo) = dst.nodes(self.db);
        let hi = SimUnknownKind::KirchoffLaw(hi);
        let lo = lo.map(SimUnknownKind::KirchoffLaw);
        get_residual!(self, hi).add_contribution(contrib, &mut self.cursor, false);
        if let Some(lo) = lo {
            get_residual!(self, lo).add_contribution(contrib, &mut self.cursor, true);
        }
        // self.add_noise(contrib, hi, lo, true);
        self.add_noise(contrib, hi, lo);
    }

    fn add_source_equation(
        &mut self,
        contrib: &Contribution,
        eq_val: Value,
        dst: BranchWrite,
        nature_kind: ResidualNatureKind,
    ) {
        let residual = get_residual!(self, SimUnknownKind::Current(dst.into()));
        residual.add_contribution(contrib, &mut self.cursor, false);
        residual.add(&mut self.cursor, true, contrib.unknown.unwrap());
        residual.nature_kind = nature_kind;
        // self.add_noise(contrib, SimUnknownKind::Current(dst.into()), None, false);
        self.add_noise(contrib, SimUnknownKind::Current(dst.into()), None);

        let (hi, lo) = dst.nodes(self.db);
        let hi = SimUnknownKind::KirchoffLaw(hi);
        let lo = lo.map(SimUnknownKind::KirchoffLaw);
        get_residual!(self, hi).add(&mut self.cursor, false, eq_val);
        if let Some(lo) = lo {
            get_residual!(self, lo).add(&mut self.cursor, true, eq_val);
        }
    }

    /// multiply each residual and matrix entry with mfactor and ensure it has
    /// a optbarrier
    pub(super) fn ensure_optbarriers(&mut self) {
        let mfactor = self
            .intern
            .ensure_param(&mut self.cursor, ParamKind::ParamSysFun(ParamSysFun::mfactor));
        let mut ensure_optbarrier = |mut val, is_kirchoff_law| {
            val = self.cursor.ins().ensure_optbarrier(val);
            if is_kirchoff_law && val != F_ZERO {
                update_optbarrier(self.cursor.func, &mut val, |val, cursor| {
                    cursor.ins().fmul(mfactor, val)
                })
            }
            self.output_values.ensure(self.cursor.func.dfg.num_values());
            self.output_values.insert(val);
            val
        };
        for (unknown, residual) in &mut self.system.residual.iter_mut_enumerated() {
            // we purpusfully ignore small signal values here since they never contribute the residual
            residual.react_small_signal = F_ZERO;
            residual.react_small_signal = F_ZERO;
            let is_kirchoff =
                matches!(self.system.unknowns[unknown], SimUnknownKind::KirchoffLaw(_));
            residual.map_vals(|val| ensure_optbarrier(val, is_kirchoff));
        }
        ensure_optbarrier(mfactor, false);

        for noise_src in &mut self.system.noise_sources {
            noise_src.map_vals(|val| ensure_optbarrier(val, false));
        }

        for entry in &mut self.system.jacobian {
            let is_kirchoff =
                matches!(self.system.unknowns[entry.row], SimUnknownKind::KirchoffLaw(_));
            entry.resist = ensure_optbarrier(entry.resist, is_kirchoff);
            entry.react = ensure_optbarrier(entry.react, is_kirchoff);
        }

    }
}
