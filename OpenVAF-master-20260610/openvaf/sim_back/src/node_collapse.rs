use bitset::HybridBitSet;
use hir::BranchWrite;
use hir_lower::{CallBackKind, PlaceKind};
use stdx::{impl_debug_display, impl_idx_from};
use typed_index_collections::TiVec;
use typed_indexmap::TiSet;

use crate::context::Context;
use crate::dae::{DaeSystem, SimUnknown};
use crate::init::Initialization;
use crate::SimUnknownKind;

#[derive(PartialEq, Eq, PartialOrd, Ord, Clone, Copy, Hash)]
pub struct CollapsePair(u32);
impl_idx_from!(CollapsePair(u32));
impl_debug_display! {match CollapsePair{CollapsePair(id) => "collapse{id}";}}

pub struct NodeCollapse {
    pairs: TiSet<CollapsePair, (SimUnknown, Option<SimUnknown>)>,
    /// node pairs that are collapsed as a result of another node collapsing
    extra_pairs: TiVec<CollapsePair, HybridBitSet<CollapsePair>>,
}

impl NodeCollapse {
    pub(super) fn new(
        init: &Initialization,
        dae_system: &DaeSystem,
        ctx: &Context,
    ) -> NodeCollapse {
        let mut pairs = TiSet::with_capacity(32);
        for (&kind, _) in &init.intern.outputs {
            if let PlaceKind::CollapseImplicitEquation(eq) = kind {
                let eq = dae_system.unknowns.unwrap_index(&SimUnknownKind::Implicit(eq));
                pairs.insert((eq, None));
            }
        }
        // A collapse hint whose branch current is an actual DAE unknown must
        // not collapse: the model reads I(branch) (e.g. an explicit 0V
        // ammeter, or the port-branch ammeters Enhancement-86 synthesizes),
        // and collapsing the pair eliminates the very unknown the probe
        // reads -- it silently became 0. The hint callback stays in the
        // init MIR but, with no registered pair, marks nothing.
        let mut probed_pairs: Vec<(SimUnknown, Option<SimUnknown>)> = Vec::new();
        for (_, &kind) in dae_system.unknowns.iter_enumerated() {
            if let SimUnknownKind::Current(kind) = kind {
                if let Ok(branch) = BranchWrite::try_from(kind) {
                    let (hi, lo) = branch.nodes(ctx.db);
                    let hi = dae_system.unknowns.unwrap_index(&SimUnknownKind::KirchoffLaw(hi));
                    let lo = lo
                        .map(|lo| dae_system.unknowns.unwrap_index(&SimUnknownKind::KirchoffLaw(lo)));
                    probed_pairs.push((hi, lo));
                }
            }
        }

        for kind in init.intern.callbacks.iter() {
            if let CallBackKind::CollapseHint(hi, lo) = *kind {
                let hi = dae_system.unknowns.unwrap_index(&SimUnknownKind::KirchoffLaw(hi));
                let lo =
                    lo.map(|lo| dae_system.unknowns.unwrap_index(&SimUnknownKind::KirchoffLaw(lo)));
                let probed = probed_pairs.contains(&(hi, lo))
                    || lo.is_some_and(|lo| probed_pairs.contains(&(lo, Some(hi))));
                if probed {
                    continue;
                }
                pairs.insert((hi, lo));
            }
        }
        let mut extra_pairs = TiVec::from(vec![HybridBitSet::default(); pairs.len()]);
        for (unknown, &kind) in dae_system.unknowns.iter_enumerated() {
            if let SimUnknownKind::Current(kind) = kind {
                let (hi, lo) = if let Ok(branch) = BranchWrite::try_from(kind) {
                    branch.nodes(ctx.db)
                } else {
                    continue;
                };
                let lo =
                    lo.map(|lo| dae_system.unknowns.unwrap_index(&SimUnknownKind::KirchoffLaw(lo)));
                let hi = dae_system.unknowns.unwrap_index(&SimUnknownKind::KirchoffLaw(hi));
                let source_pair: Option<CollapsePair> = pairs.index(&(hi, lo)).or_else(|| {
                    let lo = lo?;
                    pairs.index(&(lo, Some(hi)))
                });
                if let Some(source_pair) = source_pair {
                    // careful, if we insert extra derivatives for currents then we need to
                    // check that we are not overwriting that list here
                    let pair = pairs.ensure((unknown, None)).0;
                    extra_pairs[source_pair].insert(pair, pairs.len());
                }
            }
        }
        NodeCollapse { pairs, extra_pairs }
    }

    /// indicates that a collapse hint was provided, `f` is called
    /// for each pair of nodes that should be collapsed together
    pub fn hint(&self, hi: SimUnknown, lo: Option<SimUnknown>, mut f: impl FnMut(CollapsePair)) {
        // A hint whose pair was suppressed (its branch current is a DAE
        // unknown the model reads -- see `new`) marks nothing.
        let Some(pair) = self.pairs.index(&(hi, lo)) else { return };
        f(pair);
        for extra_pair in self.extra_pairs[pair].iter() {
            f(extra_pair)
        }
    }

    /// Returns an iterator that yields all possible combination of
    /// nodes that could be collapsed into a single node. If the second
    /// node is `None` that indicates that the first node is collapsed with
    /// ground/the global reference node.
    pub fn pairs(
        &self,
    ) -> impl Iterator<Item = (CollapsePair, SimUnknown, Option<SimUnknown>)> + '_ {
        self.pairs.iter_enumerated().map(|(i, &(node1, node2))| (i, node1, node2))
    }

    /// Return the number of possible possible combinations of
    /// nodes that can be collapsed into each other (see `pairs`)
    pub fn num_pairs(&self) -> u32 {
        self.pairs.len() as u32
    }
}
