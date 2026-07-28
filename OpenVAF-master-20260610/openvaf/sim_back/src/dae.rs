use std::hash::BuildHasherDefault;

use indexmap::IndexSet;
use mir::{strip_optbarrier, Value, F_ZERO};
use rustc_hash::FxHasher;
use stdx::{impl_debug_display, impl_idx_from};
use typed_index_collections::TiVec;
use typed_indexmap::TiSet;

use crate::context::Context;
use crate::dae::builder::Builder;
pub use crate::noise::{NoiseSource, NoiseSourceKind};
use crate::{topology, SimUnknownKind};

mod builder;
#[cfg(test)]
mod tests;

/// An unknown in the system of DAE equations
#[derive(PartialEq, Eq, PartialOrd, Ord, Clone, Copy, Hash)]
pub struct SimUnknown(u32);
impl_idx_from!(SimUnknown(u32));
impl_debug_display! {match SimUnknown{SimUnknown(id) => "sim_node{id}";}}

/// Represents the topology of Verliog-A (top level) module as a set
/// of DAE equations.
///
/// I(x) + ddt(Q(x)) = 0
///
/// This system can be solved using a newton iteration:
///
/// J_I(x) delta_x = I(x) + ddt(Q)
/// x' = x - delta_x
///
#[derive(Default, Debug)]
pub struct DaeSystem {
    /// The unknowns of the DAE system which are solved (x)
    pub unknowns: TiSet<SimUnknown, SimUnknownKind>,
    /// The cost function of the DAE system (resistive: I, reactive: Q).
    /// Additionally contains
    pub residual: TiVec<SimUnknown, Residual>,
    /// The jacobian of the DAE system J_ij = (ddx(I_i, x_j), ddx(Q_i, x_j))
    pub jacobian: TiVec<MatrixEntryId, MatrixEntry>,
    /// list of parameter which are known to be small signal values (always zero during
    /// large signal simulation).
    pub small_signal_parameters: IndexSet<Value, BuildHasherDefault<FxHasher>>,
    /// noise
    pub noise_sources: Vec<NoiseSource>,
    /// model inputs (node pairs)
    pub model_inputs: Vec<(u32, u32)>,
    /// Jacobian entry counts
    pub num_resistive: u32,
    pub num_reactive: u32,
    /// Enhancement-352: 2nd/3rd order Taylor coefficients of the residual,
    /// used by ngspice's Volterra distortion analysis. Empty unless the model
    /// is actually nonlinear -- a linear model has no 2nd derivative and the
    /// sparsification below drops every entry.
    pub taylor2: TiVec<Taylor2EntryId, Taylor2Entry>,
    pub taylor3: TiVec<Taylor3EntryId, Taylor3Entry>,
}

impl DaeSystem {
    pub(crate) fn new(ctx: &mut Context, contributions: topology::Topology) -> DaeSystem {
        // Topology is consumed here.
        let mut builder =
            Builder::new(ctx).with_small_signal_network(contributions.small_signal_vals);

        for (branch, contributions) in contributions.branches.raw {
            builder.build_branch(branch, &contributions)
        }
        for (eq, contributions) in contributions.implicit_equations.iter_enumerated() {
            builder.build_implicit_equation(eq, contributions)
        }
        if std::env::var("OPENVAF_DAE_DEBUG").is_ok() {
            for (eq, contributions) in contributions.implicit_equations.iter_enumerated() {
                eprintln!("DAEDBG implicit {eq:?}: {contributions:?}");
            }
        }
        let sys = builder.finish();
        if std::env::var("OPENVAF_DAE_DEBUG").is_ok() {
            for (u, r) in sys.unknowns.iter_enumerated().zip(&sys.residual).map(|((u, k), r)| ((u, k), r)) {
                eprintln!("DAEDBG unknown {:?} kind {:?} resist {:?} react {:?} resist_ss {:?} react_ss {:?}", u.0, u.1, r.resist, r.react, r.resist_small_signal, r.react_small_signal);
            }
            for e in &sys.jacobian {
                eprintln!("DAEDBG jac ({:?},{:?}) resist {:?} react {:?}", e.row, e.col, e.resist, e.react);
            }
            for n in &sys.noise_sources {
                eprintln!("DAEDBG noise hi={:?} lo={:?} factor={:?} factor_react={:?} kind={:?}", n.hi, n.lo, n.factor, n.factor_react, n.kind);
            }
            // Enhancement-352
            eprintln!("DAEDBG inputs {:?}", sys.model_inputs);
            for e in &sys.taylor2 {
                eprintln!("DAEDBG t2 row={:?} d/d(in{},in{}) resist {:?} react {:?}", e.row, e.col1, e.col2, e.resist, e.react);
            }
            for e in &sys.taylor3 {
                eprintln!("DAEDBG t3 row={:?} d/d(in{},in{},in{}) resist {:?} react {:?}", e.row, e.col1, e.col2, e.col3, e.resist, e.react);
            }
        }
        sys
    }

    pub(super) fn sparsify(&mut self, ctx: &mut Context) {
        let mut sparsify = |val| {
            let stripped = strip_optbarrier(&ctx.func, val);
            if ctx.func.dfg.value_def(stripped).inst().is_some() {
                val
            } else {
                ctx.output_values.remove(val);
                if let Some(inst) = ctx.func.dfg.value_def(val).inst() {
                    if ctx.func.dfg.instr_safe_to_remove(inst) {
                        ctx.func.dfg.zap_inst(inst);
                        ctx.func.layout.remove_inst(inst);
                    }
                }
                stripped
            }
        };
        for residual in &mut self.residual {
            residual.map_vals(&mut sparsify)
        }

        self.noise_sources.retain_mut(|noise_src| {
            noise_src.map_vals(&mut sparsify);
            if noise_src.factor == F_ZERO && noise_src.factor_react == F_ZERO {
                return false;
            }
            match noise_src.kind {
                NoiseSourceKind::WhiteNoise { pwr } | NoiseSourceKind::FlickerNoise { pwr, .. } => {
                    pwr != F_ZERO
                }
                NoiseSourceKind::NoiseTable { .. } => true,
                NoiseSourceKind::AcStim { mag, .. } => mag != F_ZERO,
            }
        });

        self.jacobian.raw.retain_mut(|matrix_entry| {
            matrix_entry.resist = sparsify(matrix_entry.resist);
            matrix_entry.react = sparsify(matrix_entry.react);
            matrix_entry.resist != F_ZERO || matrix_entry.react != F_ZERO
        });

        // Enhancement-352: the same treatment for the distortion tensors. A
        // linear model has no surviving 2nd-order term, so this is what keeps
        // `taylor2`/`taylor3` empty (and the emitted tables absent) rather than
        // full of structural zeros.
        self.taylor2.raw.retain_mut(|e| {
            e.resist = sparsify(e.resist);
            e.react = sparsify(e.react);
            e.resist != F_ZERO || e.react != F_ZERO
        });
        self.taylor3.raw.retain_mut(|e| {
            e.resist = sparsify(e.resist);
            e.react = sparsify(e.react);
            e.resist != F_ZERO || e.react != F_ZERO
        });
    }
}

#[derive(PartialEq, Eq, PartialOrd, Ord, Clone, Copy, Debug)]
pub enum ResidualNatureKind {
    Flow,
    Potential,
    Switch,
}

#[derive(PartialEq, Eq, PartialOrd, Ord, Clone, Copy, Debug)]
pub struct Residual {
    /// The resistive part (I) of the DAE cost function
    pub resist: Value,
    /// The reactive part (Q) of the DAE cost function
    pub react: Value,
    resist_small_signal: Value,
    react_small_signal: Value,
    /// Corrective term that needs to be added during each newton iteration to
    /// correct for limiting. Limiting reduces the maximum change in a variable
    /// for this model. That means that instead of x the system is evaluated
    /// with x_lim. The corresponding newton would be
    ///
    /// J(lim_x) delta_limx = I(lim_x) + ddt(Q)                (1)
    /// x' = lim_x - delta_limx                                (2)
    ///
    /// However the simulator is not aware  of the limiting and will instead
    /// calculate: x' = x - delta_limx. That means x' has an error of
    /// err_x = lim_x - x. Inserting that error back into (2) yields a corrective
    /// term:
    /// x' = lim_x - delta_limx = x + err_x - delta_limx
    /// delta_x = delta_limx - err_x
    /// J(lim_x)  (delta_x + err_x) = I(lim_x) + ddt(Q)
    /// J(lim_x) delta_x  = I(lim_x) + ddt(Q) - J(lim_x) * err_x
    /// lim_rhs = J(lim_x) (lim_x - x)
    ///
    /// note that this term endsup being included automatically in handwritten
    /// models of spice-like simulator:
    /// J(lim_x) (x - x')  =   I(lim_x)  ddt(Q) - J(lim_x) (lim_x - x)
    /// J(lim_x) x'  = J(lim_x) x - I(lim_x) - ddt(Q) + J(lim_x) (lim_x - x)
    /// J(lim_x) x'  = J(lim_x) lim_x - I(lim_x) - ddt(Q)
    ///
    ///
    /// This corrective factor needs to be computed both for the resistive and
    /// reactive residual (the jacobian is madeup of both). The reactive component
    /// is stored in this variable.
    pub resist_lim_rhs: Value,
    /// Corrective term that needs to be added during each newton iteration to
    /// correct for limiting. Limiting reduces the maximum change in a variable
    /// for this model. That means that instead of x the system is evaluated
    /// with x_lim. The corresponding newton would be
    ///
    /// J(lim_x) delta_limx = I(lim_x) + ddt(Q)                (1)
    /// x' = lim_x - delta_limx                                (2)
    ///
    /// However the simulator is not aware  of the limiting and will instead
    /// calculate: x' = x - delta_limx. That means x' has an error of
    /// err_x = lim_x - x. Inserting that error back into (2) yields a corrective
    /// term:
    /// x' = lim_x - delta_limx = x + err_x - delta_limx
    /// delta_x = delta_limx - err_x
    /// J(lim_x)  (delta_x + err_x) = I(lim_x) + ddt(Q)
    /// J(lim_x) delta_x  = I(lim_x) + ddt(Q) - J(lim_x) * err_x
    /// lim_rhs = J(lim_x) (lim_x - x)
    ///
    /// note that this term endsup being included automatically in handwritten
    /// models of spice-like simulator:
    /// J(lim_x) (x - x')  =   I(lim_x)  ddt(Q) - J(lim_x) (lim_x - x)
    /// J(lim_x) x'  = J(lim_x) x - I(lim_x) - ddt(Q) + J(lim_x) (lim_x - x)
    /// J(lim_x) x'  = J(lim_x) lim_x - I(lim_x) - ddt(Q)
    ///
    ///
    /// This corrective factor needs to be computed both for the resistive and
    /// reactive residual (the jacobian is madeup of both). The reactive component
    /// is stored in this variable.
    pub react_lim_rhs: Value,
    /// Residual nature kinde (flow/potential/switch)
    pub nature_kind: ResidualNatureKind,
}

impl Default for Residual {
    fn default() -> Self {
        Residual {
            resist: F_ZERO,
            react: F_ZERO,
            resist_small_signal: F_ZERO,
            react_small_signal: F_ZERO,
            resist_lim_rhs: F_ZERO,
            react_lim_rhs: F_ZERO,
            nature_kind: ResidualNatureKind::Flow,
        }
    }
}

impl Residual {
    pub fn is_trivial(&self) -> bool {
        self.is_small_signal()
            && self.resist_small_signal == F_ZERO
            && self.react_small_signal == F_ZERO
    }

    pub fn is_small_signal(&self) -> bool {
        self.resist == F_ZERO && self.react == F_ZERO
    }

    pub fn map_vals(&mut self, mut f: impl FnMut(Value) -> Value) {
        self.resist = f(self.resist);
        self.react = f(self.react);
        self.resist_small_signal = f(self.resist_small_signal);
        self.react_small_signal = f(self.react_small_signal);
        self.resist_lim_rhs = f(self.resist_lim_rhs);
        self.react_lim_rhs = f(self.react_lim_rhs);
    }
}

#[derive(PartialEq, Eq, Clone, Copy, Hash, Debug)]
pub struct MatrixEntry {
    pub row: SimUnknown,
    pub col: SimUnknown,
    pub resist: Value,
    pub react: Value,
}

#[derive(PartialEq, Eq, PartialOrd, Ord, Clone, Copy)]
pub struct MatrixEntryId(u32);
impl_idx_from!(MatrixEntryId(u32));
impl_debug_display! {match MatrixEntryId{MatrixEntryId(id) => "j{id}";}}

/// Enhancement-352: a SECOND-order Taylor coefficient of the DAE system,
/// d2(I_row)/d(x_col1)d(x_col2), stored with the 1/2! already folded in so the
/// value IS the Taylor coefficient rather than the raw derivative. That is the
/// convention ngspice's distortion analysis expects -- `diodset.c` computes
/// `g2 = 0.5*gd/vte`, i.e. (1/2!) d2I/dV2, and the S-primitives it feeds
/// (`S2v2F1(c,Hx,Hy) = Re(c*Hx*Hy)`) carry no factors of their own.
///
/// Only col1 <= col2 is stored: the tensor is symmetric, and the consumer
/// reconstructs the mirrored term. Entries whose value is identically zero are
/// dropped by the same sparsification the jacobian uses.
#[derive(PartialEq, Eq, Clone, Copy, Hash, Debug)]
pub struct Taylor2Entry {
    pub row: SimUnknown,
    /// indices into `DaeSystem::model_inputs` (branch voltages), col1 <= col2
    pub col1: u32,
    pub col2: u32,
    pub resist: Value,
    pub react: Value,
}

#[derive(PartialEq, Eq, PartialOrd, Ord, Clone, Copy)]
pub struct Taylor2EntryId(u32);
impl_idx_from!(Taylor2EntryId(u32));
impl_debug_display! {match Taylor2EntryId{Taylor2EntryId(id) => "t2_{id}";}}

/// Enhancement-352: a THIRD-order Taylor coefficient,
/// (1/3!) d3(I_row)/d(x_col1)d(x_col2)d(x_col3), stored for col1 <= col2 <= col3.
#[derive(PartialEq, Eq, Clone, Copy, Hash, Debug)]
pub struct Taylor3Entry {
    pub row: SimUnknown,
    /// indices into `DaeSystem::model_inputs`, col1 <= col2 <= col3
    pub col1: u32,
    pub col2: u32,
    pub col3: u32,
    pub resist: Value,
    pub react: Value,
}

#[derive(PartialEq, Eq, PartialOrd, Ord, Clone, Copy)]
pub struct Taylor3EntryId(u32);
impl_idx_from!(Taylor3EntryId(u32));
impl_debug_display! {match Taylor3EntryId{Taylor3EntryId(id) => "t3_{id}";}}
