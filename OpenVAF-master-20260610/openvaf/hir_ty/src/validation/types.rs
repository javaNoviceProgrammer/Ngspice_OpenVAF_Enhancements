use std::iter::once;

use basedb::{AstId, ErasedAstId, FileId};
use hir_def::nameres::diagnostics::PathResolveError;
use hir_def::nameres::{DefMap, ScopeDefItem};
use hir_def::{
    AliasParamId, Branch, BranchId, BranchKind, DisciplineId, ItemLoc, ItemTree,
    LocalDisciplineAttrId, LocalNatureAttrId, Lookup, ModuleId, ModuleLoc, NatureId, NodeId,
    NodeTypeDecl, Path, ScopeId,
};
use hir_def::item_tree::DisciplineAttrKind;
use syntax::ast::ArgListOwner;
use syntax::name::{kw, Name};
use syntax::{ast, AstNode, SyntaxNodePtr};
use typed_index_collections::TiSlice;

use crate::db::HirTyDB;
use crate::lower::{lookup_nature, NatureTy};

#[derive(PartialEq, Eq, Clone, Debug)]
pub struct DuplicateItem<Item, Def> {
    pub src: Def,
    pub first: Item,
    pub subsequent: Vec<Item>,
}

#[derive(PartialEq, Eq, Clone, Debug)]
pub enum TypeValidationDiagnostic {
    PathError { err: PathResolveError, src: SyntaxNodePtr },
    DuplicateDisciplineAttr(DuplicateItem<LocalDisciplineAttrId, DisciplineId>),
    DuplicateNatureAttr(DuplicateItem<LocalNatureAttrId, NatureId>),
    MultipleDirections(DuplicateItem<AstId<ast::PortDecl>, NodeId>),
    MultipleDisciplines(DuplicateItem<ErasedAstId, NodeId>),
    MultipleGnds(DuplicateItem<ErasedAstId, NodeId>),
    PortWithoutDirection { decl: ErasedAstId, name: Name },
    NodeWithoutDiscipline { decl: ErasedAstId, name: Name },
    ExpectedPort { node: NodeId, src: ErasedAstId },
    IncompatibleBranch { branch: BranchId, node1: NodeId, node2: NodeId },
    /// Enhancement-414: `branch (a,a)` -- both endpoints are the SAME node.
    /// The potential across it is identically zero and every flow contributed to
    /// it is discarded, so the branch does nothing at all. A one-character slip
    /// (`branch (a,a)` for `branch (a,c)`) therefore produced a device that
    /// contributed nothing, silently.
    DegenerateBranch { branch: BranchId, node: NodeId, src: ErasedAstId },
    /// Enhancement-422: a `nature`/`discipline` reference that does not resolve
    /// to a nature. Nothing checked these: `lookup_nature(..).ok()` threw the
    /// error away, so a mistyped `parent` reached OSDI codegen and hard-panicked
    /// the compiler, while a mistyped `ddt_nature`/`idt_nature` was silently
    /// dropped and a mistyped discipline `potential`/`flow` was reported only
    /// later, against the model body.
    UnresolvedNatureRef {
        owner: Name,
        /// "parent nature", "ddt_nature", "idt_nature", "potential", "flow"
        what: &'static str,
        referenced: Name,
        err: PathResolveError,
        src: ErasedAstId,
    },
    /// LRM 3.6.1.2: "It is illegal for a derived nature to define or change
    /// the units; the derived nature always inherits its parent nature units."
    /// The declared value is DROPPED by `NatureTy::obtain` (units resolve from
    /// the base nature), so accepting it silently can hide a modelling error
    /// -- `nature FunnyV : Voltage; units = "furlong";` stayed 'V'. Warning,
    /// not error, matching this project's permissive derived-nature stance.
    DerivedNatureUnits { nature: NatureId, attr: LocalNatureAttrId },
    /// Round-4 audit / LRM 3.6.1.2: "It is illegal for a derived nature to
    /// change the access attribute". Enhancement-39 supports the fresh access
    /// name ON PURPOSE (`derivednature_demo.va` pins it working), so the
    /// extension keeps working -- this warning makes it audible, the way the
    /// `<<<`/`>>>` extension warns.
    DerivedNatureAccess { nature: NatureId, attr: LocalNatureAttrId },
    /// Round-4 audit / LRM 3.6.2.5: a discipline may override the bound
    /// nature's attributes only "except as restricted by 3.6.1.2" -- and
    /// 3.6.1.2 forbids changing `units` and `access`. `flow.units = "mA"` and
    /// `potential.access = W` compiled without a word (and without effect).
    IllegalDisciplineOverride {
        discipline: DisciplineId,
        attr: LocalDisciplineAttrId,
        what: &'static str,
    },
    /// LRM 3.6.1.2: an `idt_nature`/`ddt_nature` override in a derived nature
    /// "shall be related (share the same base nature) to the nature the parent
    /// uses for its idt_nature/ddt_nature". An unrelated link only mis-selects
    /// idt/ddt tolerance metadata, so this too is a warning.
    UnrelatedIdtDdtOverride {
        nature: NatureId,
        /// "ddt_nature" or "idt_nature"
        what: &'static str,
        own: NatureId,
        parent_link: NatureId,
        src: ErasedAstId,
    },
    /// Enhancement-422: a nature whose parent chain closes on itself. Salsa
    /// recovers from the query cycle by dropping the parent, so the nature
    /// silently becomes its own base nature -- which changes units inheritance
    /// and therefore discipline compatibility.
    NatureCycle { name: Name, chain: Vec<Name>, src: ErasedAstId },
    /// Enhancement-422: an `abstol` that is not a usable absolute tolerance.
    BadAbstol { name: Name, value: Box<str>, src: ErasedAstId },
    /// Enhancement-422: an `abstol` written but SILENTLY DISCARDED because its
    /// value did not fold to a real constant. The lowering only stores `abstol`
    /// when `as_constexprval().as_real()` succeeds, so `abstol = 1.0/0.0`,
    /// `abstol = 1e-6+0.0` and even `abstol = "abc"` left the nature with no
    /// abstol at all, and said nothing.
    NonConstantAbstol { name: Name, src: ErasedAstId },
}

impl TypeValidationDiagnostic {
    pub fn collect(db: &dyn HirTyDB, root_file: FileId) -> Vec<TypeValidationDiagnostic> {
        let mut res = Vec::new();

        let def_map = db.def_map(root_file);
        let tree = db.item_tree(root_file);
        TypeValidationCtx { db, dst: &mut res, def_map: &def_map, tree: &tree, root_file }
            .validate();

        res
    }
}

struct TypeValidationCtx<'a> {
    db: &'a dyn HirTyDB,
    dst: &'a mut Vec<TypeValidationDiagnostic>,
    def_map: &'a DefMap,
    tree: &'a ItemTree,
    root_file: FileId,
}

impl TypeValidationCtx<'_> {
    fn validate(&mut self) {
        let root = &self.def_map[self.def_map.root()];
        for def in root.declarations.values() {
            match *def {
                ScopeDefItem::NatureId(nature) => self.verify_nature(nature),
                ScopeDefItem::DisciplineId(discipline) => self.verify_discipline(discipline),
                ScopeDefItem::ModuleId(module) => self.verify_module(module),
                _ => (),
            }
        }
    }

    fn verify_module(&mut self, module: ModuleId) {
        let loc = module.lookup(self.db.upcast());
        let scope = loc.scope.local_scope;
        for item in self.def_map[scope].declarations.values() {
            match item {
                ScopeDefItem::NodeId(node) => self.verify_node(*node, loc),
                ScopeDefItem::BranchId(branch) => self.verify_branch(*branch),
                ScopeDefItem::AliasParamId(alias) => self.verify_alias(*alias),
                _ => (),
            }
        }
    }

    fn resolve_node(
        &mut self,
        node: &Path,
        scope: ScopeId,
        branch: &ItemLoc<Branch>,
    ) -> Option<NodeId> {
        let node = scope.resolve_item_path::<NodeId>(self.db.upcast(), node);
        match node {
            Ok(node) => Some(node),
            Err(err) => {
                let src = SyntaxNodePtr::new(
                    branch
                        .source(self.db.upcast())
                        .arg_list()
                        .unwrap()
                        .args()
                        .next()
                        .unwrap()
                        .syntax(),
                );
                self.report(TypeValidationDiagnostic::PathError { err, src });
                None
            }
        }
    }

    fn verify_alias(&mut self, alias: AliasParamId) {
        if self.db.resolve_alias(alias).is_none() {
            let loc = alias.lookup(self.db.upcast());
            let data = self.db.alias_data(alias);
            if let Some(path) = data.src.as_ref() {
                match loc.scope.resolve_path(self.db.upcast(), path) {
                    // TODO: better errors for cycels
                    Ok(found) => {
                        let src = SyntaxNodePtr::new(
                            loc.source(self.db.upcast()).src().unwrap().syntax(),
                        );
                        self.report(TypeValidationDiagnostic::PathError {
                            err: PathResolveError::ExpectedItemKind {
                                name: path.segments.last().unwrap().clone(),
                                expected: "parameter",
                                found,
                            },
                            src,
                        })
                    }
                    Err(err) => {
                        let src = SyntaxNodePtr::new(
                            loc.source(self.db.upcast()).src().unwrap().syntax(),
                        );
                        self.report(TypeValidationDiagnostic::PathError { err, src })
                    }
                }
            }
        }
    }

    fn report(&mut self, diag: impl Into<TypeValidationDiagnostic>) {
        self.dst.push(diag.into())
    }

    fn verify_branch(&mut self, branch_: BranchId) {
        let branch_data = self.db.branch_data(branch_);
        let kind = &branch_data.kind;
        let branch = branch_.lookup(self.db.upcast());
        let scope = branch.scope;
        match kind {
            BranchKind::PortFlow(port) => {
                if let Some(node) = self.resolve_node(port, scope, &branch) {
                    let node_ = self.db.node_data(node);
                    if !node_.is_input && !node_.is_output {
                        let src = branch.ast_id(self.db.upcast()).into();
                        self.report(TypeValidationDiagnostic::ExpectedPort { node, src });
                    }
                }
            }
            BranchKind::NodeGnd(node) => {
                self.resolve_node(node, scope, &branch);
            }
            BranchKind::Nodes(node1, node2) => {
                let node1 = self.resolve_node(node1, scope, &branch);
                let node2 = self.resolve_node(node2, scope, &branch);
                let (node1, node2) = if let (Some(node1), Some(node2)) = (node1, node2) {
                    (node1, node2)
                } else {
                    return;
                };

                // Enhancement-414: both endpoints the same node -- see DegenerateBranch.
                if node1 == node2 {
                    let src = branch.ast_id(self.db.upcast()).into();
                    self.report(TypeValidationDiagnostic::DegenerateBranch {
                        branch: branch_,
                        node: node1,
                        src,
                    });
                }

                let discipline1 = self.db.node_discipline(node1);
                let discipline2 = self.db.node_discipline(node2);
                // fast path
                if discipline1 == discipline2 {
                    return;
                }

                let (discipline1, discipline2) =
                    if let (Some(d1), Some(d2)) = (discipline1, discipline2) {
                        (d1, d2)
                    } else {
                        return;
                    };

                if !self.db.discipline_info(discipline1).compatible(discipline2, self.db) {
                    self.report(TypeValidationDiagnostic::IncompatibleBranch {
                        branch: branch_,
                        node1,
                        node2,
                    })
                }
            }
            BranchKind::Missing => (),
        };
    }

    fn verify_node(&mut self, node: NodeId, module: ModuleLoc) {
        let loc = node.lookup(self.db.upcast());
        let node_ = &self.tree[module.id].nodes[loc.id];
        if node_.decls.is_empty() {
            self.report(TypeValidationDiagnostic::PortWithoutDirection {
                decl: node_.ast_id,
                name: node_.name.clone(),
            });
            self.report(TypeValidationDiagnostic::NodeWithoutDiscipline {
                decl: node_.ast_id,
                name: node_.name.clone(),
            });
            return; // Do not print other diagnostics here would just lead to duplications
        }
        let mut directions = node_.decls.iter().filter_map(|decl| {
            if let NodeTypeDecl::Port(p) = decl {
                Some(self.tree[*p].ast_id)
            } else {
                None
            }
        });
        if let Some(first) = directions.next() {
            let duplicates: Vec<_> = directions.collect();
            if !duplicates.is_empty() {
                self.report(TypeValidationDiagnostic::MultipleDirections(DuplicateItem {
                    src: node,
                    first,
                    subsequent: duplicates,
                }))
            }
        } else if node_.decls[0].ast_id(self.tree) != node_.ast_id {
            self.report(TypeValidationDiagnostic::PortWithoutDirection {
                decl: node_.ast_id,
                name: node_.name.clone(),
            })
        }

        let mut disciplines = node_
            .decls
            .iter()
            .filter_map(|it| it.discipline(self.tree).as_ref().map(|discipline| (it, discipline)));

        if let Some((decl, discipline)) = disciplines.next() {
            for (decl, discipline) in once((decl, discipline)).chain(disciplines.clone()) {
                if let Err(err) = self
                    .def_map
                    .resolve_local_item_in_scope::<DisciplineId>(self.def_map.root(), discipline)
                {
                    self.report(TypeValidationDiagnostic::PathError {
                        err,
                        src: SyntaxNodePtr::new(
                            decl.discipline_src(self.db.upcast(), self.root_file).unwrap().syntax(),
                        ),
                    })
                }
            }

            let duplicates: Vec<_> = disciplines.map(|(decl, _)| decl.ast_id(self.tree)).collect();
            if !duplicates.is_empty() {
                self.report(TypeValidationDiagnostic::MultipleDisciplines(DuplicateItem {
                    src: node,
                    first: decl.ast_id(self.tree),
                    subsequent: duplicates,
                }))
            }
        } else {
            self.report(TypeValidationDiagnostic::NodeWithoutDiscipline {
                decl: node_.ast_id,
                name: node_.name.clone(),
            });
        }

        let mut gnd_declarations = node_.decls.iter().filter(|it| it.is_gnd(self.tree));

        if let Some(first) = gnd_declarations.next() {
            let duplicates: Vec<_> = gnd_declarations.map(|it| it.ast_id(self.tree)).collect();
            if !duplicates.is_empty() {
                self.report(TypeValidationDiagnostic::MultipleDisciplines(DuplicateItem {
                    src: node,
                    first: first.ast_id(self.tree),
                    subsequent: duplicates,
                }))
            }
        }
    }

    // TODO check natures/discipline (~dspom/OpenVAF#1)
    fn verify_discipline(&mut self, discipline: DisciplineId) {
        // let info = self.db.discipline_info(discipline);
        let data = self.db.discipline_data(discipline);
        self.verify_unique_attributes(
            &data.attrs,
            discipline,
            TypeValidationDiagnostic::DuplicateDisciplineAttr,
        );

        // Enhancement-422: a `potential`/`flow` naming something that is not a
        // nature used to be reported only much later and against the MODEL BODY
        // -- "illegal access of branch '(p, p)'", which names neither the
        // discipline nor the missing nature. Say it at the declaration.
        let loc = discipline.lookup(self.db.upcast());
        let src: ErasedAstId = self.tree[loc.id].ast_id.into();
        let name = data.name.clone();
        for (what, nature_ref) in
            [("potential", &data.potential), ("flow", &data.flow)]
        {
            if let Some(nature_ref) = nature_ref {
                if let Err(err) = lookup_nature(self.def_map, nature_ref, self.db) {
                    self.report(TypeValidationDiagnostic::UnresolvedNatureRef {
                        owner: name.clone(),
                        what,
                        referenced: nature_ref.name.clone(),
                        err,
                        src,
                    })
                }
            }
        }

        // Round-4 audit / LRM 3.6.2.5: an attribute override (`flow.attr = v`)
        // is permitted "except as restricted by 3.6.1.2", which forbids
        // changing `units` and `access`. Both compiled in silence -- and
        // without effect. The legal overrides (abstol, user-defined) are not
        // this check's business.
        for (attr, attr_data) in data.attrs.iter_enumerated() {
            let what = match attr_data.kind {
                DisciplineAttrKind::PotentialOverwrite => "potential",
                DisciplineAttrKind::FlowOverwrite => "flow",
                DisciplineAttrKind::UserDefined => continue,
            };
            let attr_name = attr_data.name.to_string();
            if attr_name == "units" || attr_name == "access" {
                self.report(TypeValidationDiagnostic::IllegalDisciplineOverride {
                    discipline,
                    attr,
                    what,
                });
            }
        }
    }

    fn verify_nature(&mut self, nature: NatureId) {
        // let info = self.db.nature_info(nature);
        let data = self.db.nature_data(nature);

        self.verify_unique_attributes(
            &data.attrs,
            nature,
            TypeValidationDiagnostic::DuplicateNatureAttr,
        );

        let loc = nature.lookup(self.db.upcast());
        let src: ErasedAstId = self.tree[loc.id].ast_id.into();
        let name = data.name.clone();

        // Enhancement-422: THE CRASH. `parent` was resolved with
        // `lookup_nature(..).ok()` in `hir_ty::lower`, which throws the error
        // away, and `osdi::ndatable::resolve_nature_ref` then `.unwrap()`ed the
        // missing name-map entry -- so `nature Vd : Vbaze;`, one character
        // wrong, aborted the compiler with a crash report. It did not even have
        // to be USED: a stray nature declaration in an included header killed
        // every build that included it.
        //
        // `ddt_nature`/`idt_nature` sit right beside it and merely went silent,
        // because Enhancement-39 hardened THEIR codegen path
        // (`unwrap_or(u32::MAX)`) without adding a diagnostic. Same reference,
        // same mistake, three different outcomes; now one.
        // NOT checked, twice over, and both were written and then WITHDRAWN:
        //
        //  * a BASE nature that omits `abstol` or `access`. LRM 3.6.1.2 says of each
        //    "This attribute is required for all base natures", but Enhancement-422
        //    decided the opposite deliberately -- its suite pins "a nature with NO
        //    abstol attribute at all stays legal" -- and neither omission produces a
        //    wrong answer, only a spec-conformance nit. (E-422's stated reason, that
        //    "the LRM makes it optional", does not survive reading 3.6.1.2; the
        //    DECISION still stands, and reversing it is a call for the project, not a
        //    side effect of a bug hunt.)
        //
        //  * a DERIVED nature that declares its own `access`. LRM 3.6.1.2 calls that
        //    illegal, but Enhancement-39 supports it ON PURPOSE: its example
        //    `derivednature_demo.va` derives `Current2` with a fresh access function,
        //    and Enhancement-422's suite builds every derived nature that way.
        //    Round-4 audit: the extension still works, and is now AUDIBLE -- a
        //    warning names the rule (DerivedNatureAccess below), the same
        //    treatment the `<<<`/`>>>` extension gets.
        //
        // Both rules were implemented as ERRORS, and the two suites caught them
        // within one regression sweep. They are recorded here so the next reader
        // finds the decision rather than the idea.

        for (what, nature_ref) in [
            ("parent nature", &data.parent),
            ("ddt_nature", &data.ddt_nature),
            ("idt_nature", &data.idt_nature),
        ] {
            if let Some(nature_ref) = nature_ref {
                if let Err(err) = lookup_nature(self.def_map, nature_ref, self.db) {
                    self.report(TypeValidationDiagnostic::UnresolvedNatureRef {
                        owner: name.clone(),
                        what,
                        referenced: nature_ref.name.clone(),
                        err,
                        src,
                    })
                }
            }
        }

        // LRM audit (disciplines n6/n9): two rules on DERIVED natures.
        if let Some(parent) =
            data.parent.as_ref().and_then(|p| lookup_nature(self.def_map, p, self.db).ok())
        {
            // units on a derived nature: declared value is silently ignored.
            if data.units.is_some() {
                if let Some((attr, _)) = data
                    .attrs
                    .iter_enumerated()
                    .find(|(_, attr)| attr.name.to_string() == "units")
                {
                    self.report(TypeValidationDiagnostic::DerivedNatureUnits { nature, attr });
                }
            }
            // access on a derived nature: LRM 3.6.1.2 makes changing it
            // illegal; the fresh name is a deliberate, working extension (see
            // the note above) -- round-4 audit: now audible.
            if let Some((attr, _)) =
                data.attrs.iter_enumerated().find(|(_, attr)| attr.name.to_string() == "access")
            {
                self.report(TypeValidationDiagnostic::DerivedNatureAccess { nature, attr });
            }
            // idt_nature/ddt_nature override must be RELATED (same base nature)
            // to the nature the parent uses for that link. The parent's link
            // defaulting to the parent itself means nothing was declared up the
            // chain -- no link to be related to, so nothing to check.
            let parent_info = self.db.nature_info(parent);
            for (what, declared, parent_link) in [
                ("ddt_nature", &data.ddt_nature, parent_info.ddt_nature),
                ("idt_nature", &data.idt_nature, parent_info.idt_nature),
            ] {
                if parent_link == parent {
                    continue;
                }
                if let Some(own) =
                    declared.as_ref().and_then(|r| lookup_nature(self.def_map, r, self.db).ok())
                {
                    if !NatureTy::related(self.db, own, parent_link) {
                        self.report(TypeValidationDiagnostic::UnrelatedIdtDdtOverride {
                            nature,
                            what,
                            own,
                            parent_link,
                            src,
                        });
                    }
                }
            }
        }

        // Enhancement-422: an inheritance CYCLE. Salsa recovers from the query
        // cycle by re-running `NatureTy::obtain` with `resolve_parent = false`,
        // so nothing crashes and nothing is said -- the nature just silently
        // becomes its own `base_nature`, losing the units it meant to inherit
        // and therefore changing which disciplines it is compatible with.
        // Parameter cycles, `aliasparam` cycles and analog-function recursion
        // are all rejected by name; this was the one that was not.
        //
        // The walk uses `nature_data` + `lookup_nature` rather than
        // `nature_info`, precisely so it sees the cycle instead of salsa's
        // recovery. Reported only from the member the walk returns to, so an
        // N-cycle produces N reports and not N^2.
        let mut chain = vec![name.clone()];
        let mut cur = nature;
        loop {
            let Some(parent_ref) = self.db.nature_data(cur).parent.clone() else { break };
            let Ok(parent) = lookup_nature(self.def_map, &parent_ref, self.db) else { break };
            chain.push(self.db.nature_data(parent).name.clone());
            if parent == nature {
                self.report(TypeValidationDiagnostic::NatureCycle {
                    name: name.clone(),
                    chain,
                    src,
                });
                break;
            }
            // a cycle that does not pass through `nature` is reported by its own
            // members; stop rather than spin
            if chain.len() > self.def_map[self.def_map.root()].declarations.len() + 2 {
                break;
            }
            cur = parent;
        }

        // Enhancement-422: `abstol` is an ABSOLUTE TOLERANCE -- the size below
        // which the solver stops caring about a difference. Zero, negative,
        // infinite and NaN are all meaningless, all compiled silently, and all
        // reached the OSDI nature descriptor. Same class as the tolerance
        // constants Enhancement-396 hardened on the builtins.
        if data.abstol.is_none()
            && data.attrs.iter().any(|attr| attr.name == kw::abstol)
        {
            self.report(TypeValidationDiagnostic::NonConstantAbstol {
                name: name.clone(),
                src,
            })
        }
        if let Some((abstol, _)) = data.abstol {
            let v = *abstol;
            if !(v > 0.0) || !v.is_finite() {
                // formatted here: the diagnostic enum derives Eq and f64 does not
                self.report(TypeValidationDiagnostic::BadAbstol {
                    name,
                    value: format!("{v}").into_boxed_str(),
                    src,
                })
            }
        }
    }

    fn verify_unique_attributes<Attr: From<usize> + PartialEq, Def: Copy>(
        &mut self,
        attrs: &TiSlice<Attr, impl PartialEq>,
        def: Def,
        wrap_err: impl Fn(DuplicateItem<Attr, Def>) -> TypeValidationDiagnostic,
    ) {
        // This is quadratic (actually its n(n+1)/2). But disciplines and nature usually only have very few (below 5)
        // attributes so this is probably faster than allocating a HashMap. If this ever becomes a
        // problem just use a HashMap instead
        for (id, attr) in attrs.iter_enumerated() {
            let mut duplicates =
                attrs.iter_enumerated().filter_map(
                    |it| {
                        if it.1 == attr {
                            Some(it.0)
                        } else {
                            None
                        }
                    },
                );

            if duplicates.next().unwrap() != id {
                continue;
            }

            let duplicates: Vec<_> = duplicates.collect();

            if !duplicates.is_empty() {
                let err = DuplicateItem { src: def, first: id, subsequent: duplicates };
                self.report(wrap_err(err))
            }
        }
    }
}
