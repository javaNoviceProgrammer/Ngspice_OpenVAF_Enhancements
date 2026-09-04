use std::sync::Arc;

use hir_def::item_tree::DisciplineAttrKind;
use hir_def::nameres::diagnostics::PathResolveError;
use hir_def::nameres::DefMap;
use hir_def::nameres::ScopeDefItem;
use hir_def::{
    BranchId, DisciplineAttrId, DisciplineAttrLoc, DisciplineId, Intern, Lookup, NatureAttrLoc,
    NatureId, NatureRef, NatureRefKind, NodeId,
};
use syntax::name::{kw, Name};

use crate::db::HirTyDB;

#[derive(Debug, PartialEq, Eq, Clone)]
pub struct NatureTy {
    pub ddt_nature: NatureId,
    pub idt_nature: NatureId,
    pub parent: Option<NatureId>,
    pub base_nature: NatureId,
    pub units: Option<String>,
}

impl NatureTy {
    pub fn nature_info_query(db: &dyn HirTyDB, nature: NatureId) -> Arc<NatureTy> {
        NatureTy::obtain(db, nature, true)
    }
    pub fn obtain(db: &dyn HirTyDB, nature: NatureId, resolve_parent: bool) -> Arc<NatureTy> {
        let data = db.nature_data(nature);
        let loc = nature.lookup(db.upcast());
        let def_map = db.def_map(loc.root_file);

        let parent =
            data.parent.as_ref().and_then(|parent| lookup_nature(&def_map, parent, db).ok());

        let parent_info = parent.and_then(|parent| resolve_parent.then(|| db.nature_info(parent)));
        let base_nature = parent_info.as_ref().map(|parent| parent.base_nature);

        let ddt_nature = data
            .ddt_nature
            .as_ref()
            .and_then(|ddt_nature| lookup_nature(&def_map, ddt_nature, db).ok())
            .or_else(|| parent_info.as_ref().map(|parent| parent.ddt_nature))
            .unwrap_or(nature);

        let idt_nature = data
            .idt_nature
            .as_ref()
            .and_then(|idt_nature| lookup_nature(&def_map, idt_nature, db).ok())
            .or_else(|| parent_info.as_ref().map(|parent| parent.idt_nature))
            .unwrap_or(nature);

        let units = base_nature
            .and_then(|nature| db.nature_info(nature).units.clone())
            .or_else(|| data.units.clone());

        Arc::new(NatureTy {
            ddt_nature,
            idt_nature,
            parent,
            base_nature: base_nature.unwrap_or(nature),
            units,
        })
    }

    #[allow(clippy::trivially_copy_pass_by_ref)]
    pub(crate) fn nature_info_recover(
        db: &dyn HirTyDB,
        _cycle: &salsa::Cycle,
        nature: &NatureId,
    ) -> Arc<NatureTy> {
        NatureTy::obtain(db, *nature, false)
    }

    /// Enhancement-399: two natures that BOTH omit `units` are not compatible
    /// merely because their units strings are equally absent.
    ///
    /// This compared `Option<String>` directly, and `None == None` is true, so
    /// any two natures that left `units` out matched each other. `units` is an
    /// LRM-required nature attribute but omitting it is accepted here, so the
    /// combination was reachable from ordinary source: two unrelated natures,
    /// neither declaring units, and a branch spanning their two disciplines
    /// compiled silently. Declaring DIFFERENT units was correctly rejected, and
    /// so was one-declares/one-omits -- only the both-omit case fell through.
    ///
    /// An absent units string proves nothing, so it must not be used as
    /// evidence of compatibility. Fall back to the LRM's actual rule in that
    /// case -- same base nature (`related`) -- which keeps a nature compatible
    /// with itself and with anything derived from it, while two unrelated
    /// natures now differ as they should.
    pub fn compatible(db: &dyn HirTyDB, nature1: NatureId, nature2: NatureId) -> bool {
        let nature1_info = db.nature_info(nature1);
        let nature2_info = db.nature_info(nature2);
        match (&nature1_info.units, &nature2_info.units) {
            (Some(units1), Some(units2)) => units1 == units2,
            _ => nature1_info.base_nature == nature2_info.base_nature,
        }
    }

    pub fn related(db: &dyn HirTyDB, nature1: NatureId, nature2: NatureId) -> bool {
        let nature1_info = db.nature_info(nature1);
        let nature2_info = db.nature_info(nature2);
        nature1_info.base_nature == nature2_info.base_nature
    }

    pub fn lookup_attr(
        db: &dyn HirTyDB,
        nature: NatureId,
        name: &Name,
    ) -> Result<ScopeDefItem, PathResolveError> {
        fn lookup_attr_inner(
            db: &dyn HirTyDB,
            mut nature: NatureId,
            name: &Name,
        ) -> Option<ScopeDefItem> {
            loop {
                if let Some((attr, _)) = db
                    .nature_data(nature)
                    .attrs
                    .iter_enumerated()
                    .find(|(_, attr)| &attr.name == name)
                {
                    return Some(NatureAttrLoc { nature, id: attr }.intern(db.upcast()).into());
                }
                // Round-4 audit: LRM 3.6.2.6 -- a nature derived from a
                // DISCIPLINE's flow or potential (`nature n : ttl.flow;`)
                // inherits the attributes of the nature bound there "as
                // modified in" that discipline. So the discipline's override
                // sits on this link, between the derived nature and the nature
                // it names, and has to be consulted before the walk steps past
                // it: the LRM's own example comments the inherited value as
                // "abstol = 10u as modified in ttl", and it read 1u.
                if let Some(attr) =
                    derived_through_discipline(db, nature).and_then(|(disc, potential)| {
                        discipline_attr_override(db, disc, name, potential)
                    })
                {
                    return Some(attr.into());
                }
                let info = db.nature_info(nature);
                if info.base_nature == nature {
                    return None;
                }
                nature = info.parent?;
            }
        }
        lookup_attr_inner(db, nature, name).ok_or_else(|| PathResolveError::NotFoundIn {
            name: name.clone(),
            scope: db.nature_data(nature).name.clone(),
        })
    }
}

/// Round-4 audit: the attribute a DISCIPLINE declares for the nature it binds
/// (LRM 3.6.2.5 -- `flow.abstol = 10u`, "the keyword flow or potential, then
/// the hierarchical separator . and the attribute name"). Such an override
/// takes precedence over the nature's own declaration of the same attribute,
/// which is the whole point of writing one.
pub fn discipline_attr_override(
    db: &dyn HirTyDB,
    discipline: DisciplineId,
    name: &Name,
    potential: bool,
) -> Option<DisciplineAttrId> {
    // ...but only as far as 3.6.1.2 permits. `units` and `access` may not be
    // changed, and the compiler already warns that such an override "has no
    // effect" -- so it must not take effect here either.
    if name == &kw::units || name == &kw::access {
        return None;
    }
    let kind = if potential {
        DisciplineAttrKind::PotentialOverwrite
    } else {
        DisciplineAttrKind::FlowOverwrite
    };
    let data = db.discipline_data(discipline);
    let (id, _) =
        data.attrs.iter_enumerated().find(|(_, attr)| attr.kind == kind && &attr.name == name)?;
    Some(DisciplineAttrLoc { discipline, id }.intern(db.upcast()))
}

/// The discipline a nature was derived THROUGH, if it was written as
/// `nature n : ttl.flow;` rather than `nature n : ttl_curr;` (LRM 3.6.2.6),
/// together with which side of the discipline was named.
fn derived_through_discipline(db: &dyn HirTyDB, nature: NatureId) -> Option<(DisciplineId, bool)> {
    let data = db.nature_data(nature);
    let parent = data.parent.as_ref()?;
    let potential = match parent.kind {
        NatureRefKind::DisciplinePotential => true,
        NatureRefKind::DisciplineFlow => false,
        NatureRefKind::Nature => return None,
    };
    let loc = nature.lookup(db.upcast());
    let def_map = db.def_map(loc.root_file);
    let discipline = def_map.resolve_local_item_in_scope(def_map.root(), &parent.name).ok()?;
    Some((discipline, potential))
}

pub fn lookup_nature(
    def_map: &DefMap,
    nature_ref: &NatureRef,
    db: &dyn HirTyDB,
) -> Result<NatureId, PathResolveError> {
    let (nature, attr) = match nature_ref.kind {
        NatureRefKind::Nature => {
            return def_map.resolve_local_item_in_scope(def_map.root(), &nature_ref.name)
        }
        NatureRefKind::DisciplinePotential => {
            let discipline =
                def_map.resolve_local_item_in_scope(def_map.root(), &nature_ref.name)?;
            (db.discipline_info(discipline).potential, kw::potential)
        }
        NatureRefKind::DisciplineFlow => {
            let discipline =
                def_map.resolve_local_item_in_scope(def_map.root(), &nature_ref.name)?;
            (db.discipline_info(discipline).flow, kw::flow)
        }
    };

    nature
        .ok_or_else(|| PathResolveError::NotFoundIn { name: attr, scope: nature_ref.name.clone() })
}

#[derive(Debug, PartialEq, Eq, Clone)]
pub struct DisciplineTy {
    pub flow: Option<NatureId>,
    pub potential: Option<NatureId>,
    /// The declared `domain` attribute; `None` when not written. Resolution of
    /// the EFFECTIVE domain (LRM 3.6.2.2/3.6.2.3: natures default it to
    /// continuous, no-natures-no-domain is "domainless") is in
    /// [`Self::resolved_domain`].
    pub domain: Option<hir_def::item_tree::Domain>,
}

#[derive(Debug, PartialEq, Eq, Clone, Copy)]
pub enum DisciplineAccess {
    Potential,
    Flow,
}

impl DisciplineTy {
    pub fn discipline_info_query(db: &dyn HirTyDB, discipline: DisciplineId) -> Arc<DisciplineTy> {
        let data = db.discipline_data(discipline);
        let def_map = db.def_map(discipline.lookup(db.upcast()).root_file);
        Arc::new(DisciplineTy {
            flow: data.flow.as_ref().and_then(|flow| lookup_nature(&def_map, flow, db).ok()),
            potential: data
                .potential
                .as_ref()
                .and_then(|potential| lookup_nature(&def_map, potential, db).ok()),
            domain: data.domain,
        })
    }

    /// Which of this discipline's access functions `nature` names, if any.
    ///
    /// Enhancement-395: this asks whether the natures are RELATED (share a base
    /// nature), not merely whether their UNITS strings match. `NatureTy::compatible`
    /// compares units alone, so any unrelated user-defined nature that happened to
    /// declare `units = "A"` was accepted as `electrical`'s flow access -- writing
    /// `Zi(p,n)` on an electrical branch silently behaved exactly as `I(p,n)`. The
    /// check could tell a potential from a flow but not WHICH discipline the access
    /// function belonged to, so a genuine modelling error compiled clean.
    ///
    /// `related` is the LRM's own rule (natures are compatible when they share a
    /// base nature), and it still admits every legitimate use: a discipline's own
    /// access functions, and any nature DERIVED from them (`nature MyPot : Voltage`
    /// keeps Voltage as its base).
    pub fn access(&self, nature: NatureId, db: &dyn HirTyDB) -> Option<DisciplineAccess> {
        if self.flow.map_or(false, |flow| NatureTy::related(db, flow, nature)) {
            Some(DisciplineAccess::Flow)
        } else if self
            .potential
            .map_or(false, |potential| NatureTy::related(db, potential, nature))
        {
            Some(DisciplineAccess::Potential)
        } else {
            None
        }
    }

    /// The discipline's effective domain (LRM 3.6.2.2/3.6.2.3): the declared
    /// `domain` attribute; else continuous when there is any nature binding;
    /// else `None` -- a "domainless" discipline.
    pub fn resolved_domain(&self) -> Option<hir_def::item_tree::Domain> {
        self.domain.or_else(|| {
            (self.flow.is_some() || self.potential.is_some())
                .then_some(hir_def::item_tree::Domain::Continuous)
        })
    }

    /// LRM 3.11.1 discipline compatibility, all six rules:
    /// self / natureless (same domain) / domainless (always) / domain
    /// incompatibility / potential incompatibility / flow incompatibility.
    /// The nature-level Non-Existent Binding Rule makes a binding present on
    /// one side and absent on the other COMPATIBLE -- the LRM's own worked
    /// example (printed p.47) declares `electrical` and the signal-flow
    /// discipline `sig_flow_v` compatible, so a branch between an `electrical`
    /// net and a stock `voltage` net is legal. The previous implementation
    /// required both-present or both-absent, rejecting exactly that pairing
    /// (and every natureless connection with it).
    pub fn compatible(&self, other: DisciplineId, db: &dyn HirTyDB) -> bool {
        let other = db.discipline_info(other);

        // Domainless Discipline Rule ("compatible with all disciplines as
        // there is no nature or domain conflict" -- a domainless discipline
        // has no natures either, by definition).
        let (dom1, dom2) = match (self.resolved_domain(), other.resolved_domain()) {
            (None, _) | (_, None) => return true,
            (Some(d1), Some(d2)) => (d1, d2),
        };
        // Domain Incompatibility Rule.
        if dom1 != dom2 {
            return false;
        }
        // Natureless Discipline Rule: compatible with all disciplines of the
        // same domain.
        if (self.flow.is_none() && self.potential.is_none())
            || (other.flow.is_none() && other.potential.is_none())
        {
            return true;
        }
        // Flow/Potential Incompatibility Rules, with the Non-Existent Binding
        // Rule for the one-sided cases.
        if let (Some(flow1), Some(flow2)) = (self.flow, other.flow) {
            if !NatureTy::compatible(db, flow1, flow2) {
                return false;
            }
        }
        if let (Some(pot1), Some(pot2)) = (self.potential, other.potential) {
            if !NatureTy::compatible(db, pot1, pot2) {
                return false;
            }
        }
        true
    }
}

#[derive(Debug, PartialEq, Eq, Clone, Copy)]
pub enum BranchKind {
    PortFlow(NodeId),
    NodeGnd(NodeId),
    Nodes(NodeId, NodeId),
}

impl BranchKind {
    pub fn discipline(&self, db: &dyn HirTyDB) -> Option<DisciplineId> {
        match *self {
            // standard dictates that the disciplines of the two nodes need to be compatible
            BranchKind::PortFlow(node) | BranchKind::NodeGnd(node) => db.node_discipline(node),
            BranchKind::Nodes(node1, node2) => {
                let discipline1 = db.node_discipline(node1);
                let discipline2 = db.node_discipline(node2);
                // fast path
                if discipline1 == discipline2 {
                    return discipline1;
                }

                let (discipline1, discipline2) = match (discipline1, discipline2) {
                    (None, res) | (res, None) => return res,
                    (Some(d1), Some(d2)) => (d1, d2),
                };

                if db.discipline_info(discipline1).compatible(discipline2, db) {
                    // Compatible disciplines used to behave identically during
                    // type checking, so the first one was picked arbitrarily.
                    // With the LRM 3.11.1 Non-Existent Binding Rule they no
                    // longer do: a branch between `electrical` and the
                    // signal-flow `voltage` is legal, and the branch must take
                    // the discipline that actually HAS the natures -- picking
                    // `voltage` would leave `I(br)` with no flow nature.
                    let info1 = db.discipline_info(discipline1);
                    let info2 = db.discipline_info(discipline2);
                    let bindings = |d: &DisciplineTy| {
                        d.flow.is_some() as u8 + d.potential.is_some() as u8
                    };
                    if bindings(&info2) > bindings(&info1) {
                        Some(discipline2)
                    } else {
                        Some(discipline1)
                    }
                } else {
                    None
                }
            }
        }
    }
}

#[derive(Debug, PartialEq, Eq, Clone)]
pub struct BranchTy {
    pub discipline: DisciplineId,
    pub kind: BranchKind,
}
impl BranchTy {
    pub fn branch_info_query(db: &dyn HirTyDB, branch: BranchId) -> Option<Arc<BranchTy>> {
        let kind = &db.branch_data(branch).kind;
        let scope = branch.lookup(db.upcast()).scope;
        let kind = match kind {
            hir_def::BranchKind::PortFlow(port) => {
                BranchKind::PortFlow(scope.resolve_item_path(db.upcast(), port).ok()?)
            }
            hir_def::BranchKind::NodeGnd(node) => {
                BranchKind::NodeGnd(scope.resolve_item_path(db.upcast(), node).ok()?)
            }
            hir_def::BranchKind::Nodes(node1, node2) => {
                let node1 = scope.resolve_item_path(db.upcast(), node1).ok()?;
                let node2 = scope.resolve_item_path(db.upcast(), node2).ok()?;
                BranchKind::Nodes(node1, node2)
            }
            hir_def::BranchKind::Missing => return None,
        };

        Some(Arc::new(BranchTy { discipline: kind.discipline(db)?, kind }))
    }

    pub fn access(&self, nature: NatureId, db: &dyn HirTyDB) -> Option<DisciplineAccess> {
        db.discipline_info(self.discipline).access(nature, db)
    }

    pub fn flow_attr(
        db: &dyn HirTyDB,
        branch: BranchId,
        name: &Name,
    ) -> Option<Result<ScopeDefItem, PathResolveError>> {
        let discipline = db.branch_info(branch)?.discipline;
        // 3.6.2.5: the discipline's own override of this attribute wins
        if let Some(attr) = discipline_attr_override(db, discipline, name, false) {
            return Some(Ok(attr.into()));
        }
        match db.discipline_info(discipline).flow {
            Some(nature) => Some(NatureTy::lookup_attr(db, nature, name)),
            None => Some(Err(PathResolveError::NotFoundIn {
                name: kw::flow,
                scope: db.discipline_data(discipline).name.clone(),
            })),
        }
    }

    pub fn potential_attr(
        db: &dyn HirTyDB,
        branch: BranchId,
        name: &Name,
    ) -> Option<Result<ScopeDefItem, PathResolveError>> {
        let discipline = db.branch_info(branch)?.discipline;
        if let Some(attr) = discipline_attr_override(db, discipline, name, true) {
            return Some(Ok(attr.into()));
        }
        match db.discipline_info(discipline).potential {
            Some(nature) => Some(NatureTy::lookup_attr(db, nature, name)),
            None => Some(Err(PathResolveError::NotFoundIn {
                name: kw::potential,
                scope: db.discipline_data(discipline).name.clone(),
            })),
        }
    }
}

/// Net attribute access `net.flow.<attr>` / `net.potential.<attr>` (LRM 5.5.3,
/// Enhancement-45): resolves through the net's discipline to the attribute of
/// its flow/potential nature -- the node twin of `BranchTy::{flow,potential}_attr`.
pub fn net_nature_attr(
    db: &dyn HirTyDB,
    node: NodeId,
    name: &Name,
    potential: bool,
) -> Option<Result<ScopeDefItem, PathResolveError>> {
    let discipline = db.node_discipline(node)?;
    // 3.6.2.5: the discipline's own override of this attribute wins
    if let Some(attr) = discipline_attr_override(db, discipline, name, potential) {
        return Some(Ok(attr.into()));
    }
    let info = db.discipline_info(discipline);
    let (nature, kind) =
        if potential { (info.potential, kw::potential) } else { (info.flow, kw::flow) };
    match nature {
        Some(nature) => Some(NatureTy::lookup_attr(db, nature, name)),
        None => Some(Err(PathResolveError::NotFoundIn {
            name: kind,
            scope: db.discipline_data(discipline).name.clone(),
        })),
    }
}
