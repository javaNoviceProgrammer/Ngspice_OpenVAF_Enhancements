use crate::metadata::osdi_0_4::{
    OsdiAttribute, OsdiAttributeValue, OsdiDiscipline, OsdiNature, ATTR_TYPE_INT, ATTR_TYPE_REAL,
    ATTR_TYPE_STR, DOMAIN_CONTINUOUS, DOMAIN_DISCRETE, DOMAIN_NOT_GIVEN, NATREF_DISCIPLINE_FLOW,
    NATREF_DISCIPLINE_POTENTIAL, NATREF_NATURE, NATREF_NONE,
};
use hir::CompilationDB;
use hir_def::db::HirDefDB;
use hir_def::item_tree::{
    Discipline, DisciplineAttr, DisciplineAttrKind, Domain, ItemTreeData, NatureAttr, NatureRef,
    NatureRefKind,
};
use hir_def::ndatable::NDATable;
use lasso::Rodeo;
use std::vec::Vec;
use syntax::ConstExprValue;

impl OsdiAttributeValue {
    pub fn new(v: &ConstExprValue, literals: &mut Rodeo) -> OsdiAttributeValue {
        match v {
            ConstExprValue::Float(f) => OsdiAttributeValue::Real(f.into_inner()),
            ConstExprValue::Int(i) => OsdiAttributeValue::Integer(*i),
            ConstExprValue::String(s) => {
                literals.get_or_intern(s.clone());
                OsdiAttributeValue::String(s.clone())
            }
        }
    }
}

trait IsAttribute {
    fn get_name(&self) -> &str;
    fn get_value(&self) -> Option<&ConstExprValue>;
}

impl IsAttribute for NatureAttr {
    fn get_name(&self) -> &str {
        self.name.as_ref()
    }

    fn get_value(&self) -> Option<&ConstExprValue> {
        self.value.as_ref()
    }
}

impl IsAttribute for DisciplineAttr {
    fn get_name(&self) -> &str {
        self.name.as_ref()
    }

    fn get_value(&self) -> Option<&ConstExprValue> {
        self.value.as_ref()
    }
}

impl OsdiAttribute {
    fn new<T: IsAttribute>(attr: &T, literals: &mut Rodeo) -> Option<OsdiAttribute> {
        if let Some(v) = attr.get_value() {
            literals.get_or_intern(attr.get_name());
            Some(OsdiAttribute {
                name: attr.get_name().to_string(),
                value_type: match v {
                    ConstExprValue::Float(_) => ATTR_TYPE_REAL,
                    ConstExprValue::Int(_) => ATTR_TYPE_INT,
                    ConstExprValue::String(_) => ATTR_TYPE_STR,
                },
                value: OsdiAttributeValue::new(v, literals),
            })
        } else {
            None
        }
    }
}

/// Enhancement-422: the `parent` of a nature, as a (type-tag, index) pair.
///
/// These three lookups used to `.unwrap()`. Nothing validated the name --
/// `hir_ty::lower` resolves it with `lookup_nature(..).ok()`, discarding the
/// error -- so `nature Vd : Vbaze;`, one character wrong, reached here and
/// aborted the compiler with a crash report, whether or not the nature was ever
/// used. Enhancement-422 diagnoses the name in `hir_ty`, so a bad reference no
/// longer arrives; this returns `NATREF_NONE` rather than panicking if one ever
/// does again.
///
/// Note the contrast with `resolve_nature_index` directly below, which
/// Enhancement-39 already wrote as `unwrap_or(u32::MAX)` for the
/// `ddt_nature`/`idt_nature` references. Same reference, same mistake -- one
/// side hardened, the other left to crash.
fn resolve_nature_ref(nature_ref: Option<&NatureRef>, nda_table: &NDATable) -> (u32, u32) {
    let Some(natref) = nature_ref else { return (NATREF_NONE, u32::MAX) };
    let name = natref.name.to_string();
    let idx = match natref.kind {
        NatureRefKind::Nature => nda_table.nature_name_map.get(&name).map(|it| it.into_raw()),
        NatureRefKind::DisciplineFlow | NatureRefKind::DisciplinePotential => {
            nda_table.discipline_name_map.get(&name).map(|it| it.into_raw())
        }
    };
    let Some(idx) = idx else { return (NATREF_NONE, u32::MAX) };
    let kind = match natref.kind {
        NatureRefKind::Nature => NATREF_NATURE,
        NatureRefKind::DisciplineFlow => NATREF_DISCIPLINE_FLOW,
        NatureRefKind::DisciplinePotential => NATREF_DISCIPLINE_POTENTIAL,
    };
    (kind, idx)
}

/// Enhancement-39: resolves a `ddt_nature`/`idt_nature` reference to a concrete
/// nature INDEX. The `OsdiNature` descriptor encodes `ddt`/`idt` as a bare nature
/// index (unlike `parent`, which carries a type tag), so a discipline-qualified
/// reference (`ddt_nature = electrical.potential;`) must be resolved through the
/// discipline to its underlying nature here — previously it hard-panicked
/// ("Nature's ddt must be a nature reference").
fn resolve_nature_index(
    nature_ref: Option<&NatureRef>,
    nda_table: &NDATable,
    it_data: &ItemTreeData,
) -> u32 {
    let Some(natref) = nature_ref else { return u32::MAX };
    let lookup = |name: &str| {
        nda_table.nature_name_map.get(name).map(|it| it.into_raw()).unwrap_or(u32::MAX)
    };
    match natref.kind {
        NatureRefKind::Nature => lookup(&natref.name.to_string()),
        NatureRefKind::DisciplineFlow | NatureRefKind::DisciplinePotential => {
            let disc = it_data.disciplines.iter().find(|disc| disc.name == natref.name);
            let nature = disc.and_then(|disc| {
                let slot = if natref.kind == NatureRefKind::DisciplineFlow {
                    &disc.flow
                } else {
                    &disc.potential
                };
                slot.as_ref().map(|(nature, _)| nature)
            });
            match nature {
                Some(nature) if nature.kind == NatureRefKind::Nature => {
                    lookup(&nature.name.to_string())
                }
                _ => u32::MAX,
            }
        }
    }
}

// Collect disciplie attributes
fn collect_discipline_attrs(
    discipline: &Discipline,
    it_data: &ItemTreeData,
    kind: DisciplineAttrKind,
    attrs: &mut Vec<OsdiAttribute>,
    literals: &mut Rodeo,
) -> (u32, u32) {
    let i1 = attrs.len();
    for idx in discipline.extra_attrs.clone() {
        let attr = &it_data.discipline_attrs[idx];
        if attr.kind != kind {
            continue;
        }
        // LRM 3.6.2.5 permits an override only as far as 3.6.1.2 allows, and
        // 3.6.1.2 forbids changing `units` or `access`. The compiler warns
        // that such an override has no effect; exporting it would invite a
        // consumer of these tables to apply what the diagnostic says is
        // ignored, so it is dropped here too. (Round-4 audit -- the LEGAL
        // overrides, `abstol` and user-defined attributes, reach the tables
        // now that their values are evaluated at all.)
        if kind != DisciplineAttrKind::UserDefined
            && matches!(attr.name.as_ref(), "units" | "access")
        {
            continue;
        }
        literals.get_or_intern(attr.name.to_string());
        if let Some(osdi_attr) = OsdiAttribute::new(attr, literals) {
            attrs.push(osdi_attr);
        }
    }
    let i2 = attrs.len();
    (i1 as u32, i2 as u32)
}

// Build natures, disciplines, and attributes array
pub fn nda_arrays(
    db: &CompilationDB,
    literals: &mut Rodeo,
) -> (Vec<OsdiNature>, Vec<OsdiDiscipline>, Vec<OsdiAttribute>) {
    // Retrieve NDATable and root items
    let cu = db.compilation_unit();
    let fileid = cu.root_file();
    let nda_table = db.nda_table(fileid);
    let item_tree = db.item_tree(fileid);

    let mut attr_vec: Vec<OsdiAttribute> = Vec::new();
    let mut nature_vec: Vec<OsdiNature> = Vec::new();
    let mut discipline_vec: Vec<OsdiDiscipline> = Vec::new();

    // Go through natures
    for nature in &item_tree.data.natures {
        // Collect attributes
        let i1 = attr_vec.len();
        for idx in nature.attrs.clone() {
            let attr = &item_tree.data.nature_attrs[idx];
            if let Some(osdi_attr) = OsdiAttribute::new(attr, literals) {
                attr_vec.push(osdi_attr);
            }
        }
        // NOT len()+1: the end index is one PAST the last attribute already.
        // The +1 made every nature's num_attr claim one attribute more than it
        // owns, so a consumer walking attrs[attr_start..attr_start+num_attr]
        // read the first attribute of the NEXT nature (and past the region for
        // the last one). The discipline path below computes it correctly.
        let i2 = attr_vec.len();
        let (pt, pi) = resolve_nature_ref(nature.parent.as_ref(), &nda_table);
        // Enhancement-39: `ddt_nature`/`idt_nature` are encoded as bare nature
        // indices, so discipline-qualified references are resolved to their
        // underlying nature instead of panicking.
        let dni = resolve_nature_index(
            nature.ddt_nature.as_ref().map(|(x, _)| x),
            &nda_table,
            &item_tree.data,
        );
        let ini = resolve_nature_index(
            nature.idt_nature.as_ref().map(|(x, _)| x),
            &nda_table,
            &item_tree.data,
        );

        // Intern strings
        literals.get_or_intern(nature.name.to_string());
        // Add to vector
        nature_vec.push(OsdiNature {
            name: nature.name.to_string(),
            parent_type: pt,
            parent: pi,
            ddt: dni,
            idt: ini,
            attr_start: i1 as u32,
            num_attr: (i2 - i1) as u32,
        });
    }

    // Go through disciplines
    for discipline in &item_tree.data.disciplines {
        // Collect flow and potential overrides
        let (fi1, fi2) = collect_discipline_attrs(
            discipline,
            &item_tree.data,
            DisciplineAttrKind::FlowOverwrite,
            &mut attr_vec,
            literals,
        );
        let (pi1, pi2) = collect_discipline_attrs(
            discipline,
            &item_tree.data,
            DisciplineAttrKind::PotentialOverwrite,
            &mut attr_vec,
            literals,
        );
        // Collect user attributes
        let (i1, i2) = collect_discipline_attrs(
            discipline,
            &item_tree.data,
            DisciplineAttrKind::UserDefined,
            &mut attr_vec,
            literals,
        );
        // Flow and potential nature
        let (ft, fni) = resolve_nature_ref(discipline.flow.as_ref().map(|(x, _)| x), &nda_table);
        if ft != NATREF_NATURE && ft != NATREF_NONE {
            panic!("Discipline's flow must be a nature reference.")
        }
        let (pt, pni) =
            resolve_nature_ref(discipline.potential.as_ref().map(|(x, _)| x), &nda_table);
        if pt != NATREF_NATURE && pt != NATREF_NONE {
            panic!("Discipline's potential must be a nature reference.")
        }

        // Intern strings
        literals.get_or_intern(discipline.name.to_string());
        // Add to vector
        discipline_vec.push(OsdiDiscipline {
            name: discipline.name.to_string(),
            flow: fni,
            potential: pni,
            domain: if let Some((domain, _)) = discipline.domain {
                if domain == Domain::Discrete {
                    DOMAIN_DISCRETE
                } else {
                    DOMAIN_CONTINUOUS
                }
            } else {
                DOMAIN_NOT_GIVEN
            },
            attr_start: fi1,
            num_flow_attr: (fi2 - fi1) as u32,
            num_potential_attr: (pi2 - pi1) as u32,
            num_user_attr: (i2 - i1) as u32,
        });
    }
    (nature_vec, discipline_vec, attr_vec)
}
