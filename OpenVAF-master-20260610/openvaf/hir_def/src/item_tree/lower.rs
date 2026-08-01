use ordered_float::OrderedFloat;
use std::mem;
use std::sync::Arc;

use arena::IdxRange;
use basedb::{AstId, AstIdMap, ErasedAstId, FileId};
use syntax::ast::{self, ParamRef, PathSegmentKind};
use syntax::name::{kw, AsIdent, AsName, Name};
use syntax::{match_ast, AstNode, ConstExprValue, WalkEvent};
use typed_index_collections::TiVec;

use super::{
    Block, Branch, BranchKind, BusDecl, Discipline, DisciplineAttr, DisciplineAttrKind, Domain,
    Function, FunctionArg, FunctionItem, Instantiation, ItemTree, ItemTreeDiagnostic, ItemTreeId,
    Module, ModuleItem, Nature, NatureAttr, NatureRef, NatureRefKind, Net, Node, Param, Port,
    RootItem, Var,
};
// use tracing::trace;
use crate::db::HirDefDB;
use crate::item_tree::AliasParam;
use crate::types::AsType;
use crate::{LocalFunctionArgId, LocalNodeId, Path, Type};

/// Tries to constant-fold a `[msb:lsb]` width clause into two integers.
/// Only literal integers (optionally unary-negated) are supported, matching
/// `ast::Expr::as_constexprval`. Returns `None` if either bound is missing or
/// not a constant integer.
/// Enhancement-148: cap on how many scalar elements an array / bus / instance-array
/// declaration may expand to. Each element becomes its own scalar net/var/instance, so
/// an unbounded range (`real x[0:100000000]`) would exhaust memory; past this it is
/// reported and degraded to a single scalar. Real declared arrays are far smaller.
const MAX_ARRAY_ELEMS: i64 = 1 << 20; // ~1.05M

/// Number of scalar elements a set of `[msb:lsb]` dimensions expands to, or `None` if
/// that exceeds `MAX_ARRAY_ELEMS` (or overflows).
fn array_elem_count(dims: &[(i32, i32)]) -> Option<i64> {
    let n = dims.iter().try_fold(1i64, |acc, (msb, lsb)| {
        acc.checked_mul((*msb as i64 - *lsb as i64).abs() + 1)
    })?;
    (n <= MAX_ARRAY_ELEMS).then_some(n)
}

fn fold_width_range(range: &ast::Range) -> Option<(i32, i32)> {
    let msb = range.start()?.as_constexprval()?;
    let lsb = range.end()?.as_constexprval()?;
    match (msb, lsb) {
        (ConstExprValue::Int(msb), ConstExprValue::Int(lsb)) => Some((msb, lsb)),
        _ => None,
    }
}

/// Folds every `[msb:lsb]` width clause of an array declaration into a per-dimension
/// `(msb, lsb)` list (outermost dimension first). `None` if any bound isn't a constant integer.
/// Counts the leaf elements of a (possibly nested) `'{...}` array literal; any
/// non-aggregate expression counts as one leaf. Used to check an array
/// variable/parameter initializer against the declared element count
/// (Enhancement-43) before the per-element bodies index into it.
fn count_literal_leaves(expr: &ast::Expr) -> u32 {
    match expr {
        ast::Expr::ArrayExpr(arr) => arr.exprs().map(|e| count_literal_leaves(&e)).sum(),
        _ => 1,
    }
}

fn fold_width_ranges<'a>(widths: impl Iterator<Item = ast::Range>) -> Option<Vec<(i32, i32)>> {
    widths.map(|r| fold_width_range(&r)).collect()
}

/// Parses a synthesized bus-bit name like `"bus[3]"` back into `("bus", 3)`.
/// Used only for diagnosing out-of-range branch-endpoint bit-selects after the
/// fact (the index was already validated to be a constant integer at the
/// point the name was synthesized).
fn parse_synthesized_bit_name(name: &Name) -> Option<(Name, i32)> {
    let s: &str = name;
    let open = s.rfind('[')?;
    if !s.ends_with(']') {
        return None;
    }
    let idx_str = &s[open + 1..s.len() - 1];
    let idx: i32 = idx_str.parse().ok()?;
    Some((Name::resolve(&s[..open]), idx))
}

fn is_input(direction: &Option<ast::Direction>) -> bool {
    direction.as_ref().map_or(false, |it| it.input_token().is_some() || it.inout_token().is_some())
}

fn is_output(direction: &Option<ast::Direction>) -> bool {
    direction.as_ref().map_or(false, |it| it.output_token().is_some() || it.inout_token().is_some())
}

pub(super) struct Ctx {
    tree: ItemTree,
    source_ast_id_map: Arc<AstIdMap>,
}

impl Ctx {
    pub(super) fn new(db: &dyn HirDefDB, file: FileId) -> Self {
        Self { tree: ItemTree::default(), source_ast_id_map: db.ast_id_map(file) }
    }

    pub(super) fn lower_root_items(mut self, file: &ast::SourceFile) -> ItemTree {
        self.tree.top_level = file.items().filter_map(|it| self.lower_root_item(it)).collect();
        self.tree
    }

    fn lower_root_item(&mut self, item: ast::Item) -> Option<RootItem> {
        let item = match item {
            ast::Item::DisciplineDecl(discipline) => self.lower_discipline(discipline)?.into(),
            ast::Item::NatureDecl(nature) => self.lower_nature(nature)?.into(),
            ast::Item::ModuleDecl(module) => self.lower_module(module)?.into(),
            ast::Item::ParamsetDecl(paramset) => self.lower_paramset(paramset)?.into(),
        };
        Some(item)
    }

    /// Lowers a Verilog-AMS `paramset` (Enhancement-21) into a synthetic "twin" module.
    ///
    /// A `paramset <name> <target>;` defines an instantiable model `<name>` that behaves exactly
    /// like `<target>` (same terminals, same analog behaviour) but with the listed target
    /// parameters bound to the paramset's `.<param> = <expr>;` expressions. The twin module reuses
    /// the target's ports/body/branches/functions verbatim by *sharing the target's `ast_id`*,
    /// under the paramset's name; the paramset's own parameters are added as the twin's (card)
    /// parameters, and each bound target parameter is replaced by a fresh `localparam` whose value
    /// is the override expression (so it is no longer settable from the model card). Everything
    /// downstream (name resolution, body lowering, OSDI descriptor emission) then treats the twin
    /// as an ordinary module.
    fn lower_paramset(&mut self, decl: ast::ParamsetDecl) -> Option<ItemTreeId<Module>> {
        let name = decl.name()?.as_name();
        let ast_id = self.source_ast_id_map.ast_id(&decl);
        let target_name = decl.target()?.as_name();

        // The target module must already be lowered (declared earlier in the file).
        let target_id = self
            .tree
            .data
            .modules
            .iter_enumerated()
            .find(|(_, m)| m.name == target_name)
            .map(|(id, _)| id);
        let Some(target_id) = target_id else {
            self.tree.diagnostics.push(ItemTreeDiagnostic::UnknownParamsetTarget {
                ast_id: ast_id.into(),
                target: target_name,
            });
            return None;
        };

        // Collect the override map: target-parameter name -> `.<param> = <expr>;` node.
        // A `.$mfactor = <expr>;` (hierarchical system parameter, Enhancement-44) is kept
        // separately: it binds no target parameter, but becomes a hidden localparam whose
        // value composes with the instance-level system parameter in `sim_back`.
        let mut overrides: Vec<(Name, AstId<ast::ParamsetOverride>)> = Vec::new();
        let mut hsp_overrides: Vec<(crate::builtin::ParamSysFun, AstId<ast::ParamsetOverride>)> =
            Vec::new();
        for ov in decl.overrides() {
            let Some(name_ref) = ov.name() else { continue };
            let ov_id = self.source_ast_id_map.ast_id(&ov);
            if let Some(tok) = name_ref.sysfun_token() {
                match crate::builtin::ParamSysFun::from_sysfun_text(tok.text()) {
                    Some(sys) => hsp_overrides.push((sys, ov_id)),
                    None => self.tree.diagnostics.push(
                        ItemTreeDiagnostic::InvalidParamsetSysParam {
                            ast_id: ov_id.into(),
                            name: tok.text().to_owned(),
                        },
                    ),
                }
                continue;
            }
            overrides.push((name_ref.as_name(), ov_id));
        }

        // Lower the paramset's own parameters (the twin's card parameters) first, so their item-
        // tree ids precede the target's items -- a bound target parameter (now a localparam) may
        // reference them in its override expression.
        let mut items: Vec<ModuleItem> = Vec::new();
        let mut param_arrays: Vec<BusDecl> = Vec::new();
        for pd in decl.param_decls() {
            self.lower_param(pd, &mut items, Some(&mut param_arrays));
        }

        // Each hierarchical system parameter override becomes a hidden real localparam named
        // `$paramset$<name>` (Enhancement-44). The `$`-spelling can collide with no user
        // identifier, deliberately differs from the OSDI built-in instance parameter
        // `$mfactor` (so ngspice's `m=` alias keeps pointing at the instance value), and is
        // recognised by name in `sim_back`, which composes it with the instance-level value
        // (multiplicatively for $mfactor/$hflip/$vflip, additively for positions/$angle).
        // Its value is the override expression, lowered through the ordinary E-21
        // localparam-with-override machinery, so it may reference the card parameters above.
        // The `ast_id` is a placeholder (there is no `ast::Param` node behind it); the
        // override-expression branch of `param_body_with_sourcemap` never dereferences it.
        for &(sys, ov) in &hsp_overrides {
            let param = Param {
                name: Name::resolve(&format!("$paramset${sys:?}")),
                ty: Some(Type::Real),
                is_local: true,
                ast_id: AstId::<ast::Param>::from_erased(ov.erased()),
                array_index: None,
                override_expr: Some(ov),
            };
            let id = self.tree.data.parameters.push_and_get_key(param);
            items.push(ModuleItem::Parameter(id));
        }

        // Append the target's items, rebinding any overridden parameter to a fresh localparam.
        let target = self.tree.data.modules[target_id].clone();
        for &item in &target.items {
            match item {
                ModuleItem::Parameter(pid) => {
                    let param_name = self.tree.data.parameters[pid].name.clone();
                    if let Some(&(_, ov)) = overrides.iter().find(|(n, _)| *n == param_name) {
                        let mut bound = self.tree.data.parameters[pid].clone();
                        bound.is_local = true;
                        bound.override_expr = Some(ov);
                        let new_id = self.tree.data.parameters.push_and_get_key(bound);
                        items.push(ModuleItem::Parameter(new_id));
                    } else {
                        items.push(ModuleItem::Parameter(pid));
                    }
                }
                other => items.push(other),
            }
        }

        param_arrays.extend(target.param_arrays.iter().cloned());

        let twin = Module {
            name,
            nodes: target.nodes.clone(),
            num_ports: target.num_ports,
            items,
            // Share the target's declaration AST: the twin's ports and analog body are the
            // target's, resolved through the twin's own scope.
            ast_id: target.ast_id,
            buses: target.buses.clone(),
            var_arrays: target.var_arrays.clone(),
            param_arrays,
        };
        Some(self.tree.data.modules.push_and_get_key(twin))
    }

    fn lower_discipline(&mut self, decl: ast::DisciplineDecl) -> Option<ItemTreeId<Discipline>> {
        use kw::raw as kw;
        let name = decl.name()?.as_name();
        let ast_id = self.source_ast_id_map.ast_id(&decl);

        let mut potential = None;
        let mut flow = None;
        let mut domain = None;
        let attr_start = self.tree.data.discipline_attrs.next_key();
        for (id, attr) in decl.discipline_attrs().enumerate() {
            if let Some(name) = attr.name() {
                let kind = if let Some(qual) = name.qualifier() {
                    let qual = qual.segment_token();
                    match qual.as_ref().map(|t| t.text()) {
                        Some(kw::potential) => DisciplineAttrKind::PotentialOverwrite,
                        Some(kw::flow) => DisciplineAttrKind::FlowOverwrite,
                        _ => continue,
                    }
                } else {
                    DisciplineAttrKind::UserDefined
                };

                if let Some(name) = name.segment_token().map(|t| t.as_name()) {
                    let ast_id = self.source_ast_id_map.ast_id(&attr);

                    let mut evaluated: Option<ConstExprValue> = None;
                    match &*name {
                        kw::potential if potential.is_none() => {
                            if let Some(name) = attr.val().and_then(Self::lower_nature_expr) {
                                evaluated = Some(ConstExprValue::String(name.name.to_string()));
                                potential = Some((name, id.into()));
                            }
                        }
                        kw::flow if flow.is_none() => {
                            if let Some(name) = attr.val().and_then(Self::lower_nature_expr) {
                                evaluated = Some(ConstExprValue::String(name.name.to_string()));
                                flow = Some((name, id.into()))
                            }
                        }
                        kw::domain if domain.is_none() => {
                            match attr.val().and_then(|e| e.as_ident()).as_deref() {
                                Some(kw::continuous) => {
                                    evaluated =
                                        Some(ConstExprValue::String(kw::continuous.to_string()));
                                    domain = Some((Domain::Continuous, id.into()));
                                }
                                Some(kw::discrete) => {
                                    evaluated =
                                        Some(ConstExprValue::String(kw::discrete.to_string()));
                                    domain = Some((Domain::Discrete, id.into()));
                                }
                                _ => {
                                    // All other attributes - evaluate ast expression
                                    evaluated = attr.val().and_then(|v| v.as_constexprval());
                                }
                            }
                        }

                        _ => (),
                    };

                    self.tree.data.discipline_attrs.push(DisciplineAttr {
                        name: name.clone(),
                        kind,
                        ast_id,
                        value: evaluated,
                    });
                }
            }
        }
        let attr_end = self.tree.data.discipline_attrs.next_key();
        let res = Discipline {
            ast_id,
            name,
            potential,
            flow,
            extra_attrs: IdxRange::new(attr_start..attr_end),
            domain,
        };
        Some(self.tree.data.disciplines.push_and_get_key(res))
    }

    fn lower_nature_path(decl: &ast::Path) -> Option<NatureRef> {
        let mut name = decl.segment_token()?.as_name();

        let kind = match &*name {
            kw::raw::potential => NatureRefKind::DisciplinePotential,
            kw::raw::flow => NatureRefKind::DisciplineFlow,
            _ if decl.qualifier().is_none() && decl.segment_kind()? == PathSegmentKind::Name => {
                NatureRefKind::Nature
            }
            _ => return None,
        };

        if matches!(kind, NatureRefKind::DisciplineFlow | NatureRefKind::DisciplinePotential) {
            let qual = decl.qualifier()?;
            let segment = qual.segment()?;
            if segment.kind == PathSegmentKind::Root || qual.qualifier().is_some() {
                return None;
            }
            name = segment.syntax.as_name();
        }

        Some(NatureRef { name, kind })
    }

    fn lower_nature_expr(decl: ast::Expr) -> Option<NatureRef> {
        if let ast::Expr::PathExpr(path) = decl {
            Self::lower_nature_path(&path.path()?)
        } else {
            None
        }
    }

    fn lower_nature(&mut self, decl: ast::NatureDecl) -> Option<ItemTreeId<Nature>> {
        let name = decl.name()?.as_name();

        let parent = decl.parent().and_then(|it| Self::lower_nature_path(&it));
        let attr_start = self.tree.data.nature_attrs.next_key();

        let mut access = None;
        let mut ddt_nature = None;
        let mut idt_nature = None;
        let mut units = None;
        let mut abstol = None;

        for (id, attr) in decl.nature_attrs().enumerate() {
            if let Some(name) = attr.name().map(|name| name.as_name()) {
                use kw::raw as kw;

                let ast_id = self.source_ast_id_map.ast_id(&attr);
                let mut evaluated: Option<ConstExprValue> = None;
                match &*name {
                    kw::access if access.is_none() => {
                        if let Some(name) = attr.val().and_then(|e| e.as_ident()) {
                            evaluated = Some(ConstExprValue::String(name.to_string()));
                            access = Some((name, id.into()));
                        }
                    }
                    kw::ddt_nature if ddt_nature.is_none() => {
                        if let Some(name) = attr.val().and_then(Self::lower_nature_expr) {
                            evaluated = Some(ConstExprValue::String(name.name.to_string()));
                            ddt_nature = Some((name, id.into()));
                        }
                    }
                    kw::idt_nature if idt_nature.is_none() => {
                        if let Some(name) = attr.val().and_then(Self::lower_nature_expr) {
                            evaluated = Some(ConstExprValue::String(name.name.to_string()));
                            idt_nature = Some((name, id.into()));
                        }
                    }

                    kw::units if units.is_none() => {
                        if let Some(ast::LiteralKind::String(lit)) =
                            attr.val().and_then(|e| e.as_literal())
                        {
                            let s = lit.unescaped_value();
                            evaluated = Some(ConstExprValue::String(s.clone()));
                            units = Some((s, id.into()));
                        }
                    }

                    kw::abstol if abstol.is_none() => {
                        let v1 =
                            attr.val().and_then(|v| v.as_constexprval()).and_then(|v| v.as_real());
                        if let Some(v) = v1 {
                            abstol = Some((OrderedFloat(v), id.into()));
                            evaluated = Some(ConstExprValue::Float(v.into()));
                        }
                    }
                    _ => {
                        // All other attributes - evaluate ast expression
                        evaluated = attr.val().and_then(|v| v.as_constexprval());
                    }
                };

                self.tree.data.nature_attrs.push(NatureAttr { name, ast_id, value: evaluated });
            }
        }

        let attr_end = self.tree.data.nature_attrs.next_key();
        let ast_id = self.source_ast_id_map.ast_id(&decl);

        let res = Nature {
            ast_id,
            name,
            parent,
            access,
            ddt_nature,
            idt_nature,
            abstol,
            units,
            attrs: IdxRange::new(attr_start..attr_end),
        };
        Some(self.tree.data.natures.push_and_get_key(res))
    }

    fn lower_module(&mut self, decl: ast::ModuleDecl) -> Option<ItemTreeId<Module>> {
        let name = decl.name()?.as_name();
        let ast_id = self.source_ast_id_map.ast_id(&decl);

        let mut nodes = TiVec::new();
        let mut items = Vec::new();
        let mut buses = Vec::new();
        let mut var_arrays = Vec::new();
        let mut param_arrays = Vec::new();
        // Enhancement-90: for non-ANSI headers (`module m(in, y);` with the
        // width in a body declaration), we need each bus port's width *before*
        // creating its header placeholder so the bits stay contiguous in
        // header-port order. Pre-scan the body port declarations for widths.
        let port_widths = Self::prescan_body_port_widths(decl.module_items());
        if let Some(ports) = decl.module_ports() {
            self.lower_module_ports(ports, &mut nodes, &mut items, &mut buses, &port_widths);
        }

        let num_ports = nodes.len() as u32;
        self.lower_module_items(
            decl.module_items(),
            &mut nodes,
            &mut items,
            &mut buses,
            &mut var_arrays,
            &mut param_arrays,
        );

        // Enhancement-396: a bus port states its range twice -- once on the
        // direction declaration and once on the net declaration -- and the two
        // used to be reconciled by letting the DIRECTION win. `inout [0:2] b;`
        // beside `electrical [0:4] b;` therefore produced a three-bit port and
        // silently dropped the net's other two bits, so the module had fewer
        // terminals than its own source said. (The opposite order was already
        // caught, but only incidentally, as "no discipline for net 'b[3]'".)
        // Each declaration registers its OWN `BusDecl`, so compare every bus
        // carrying the port's name against the range the direction stated.
        for (name, range) in &port_widths {
            let Some((dir_msb, dir_lsb)) = fold_width_range(range) else { continue };
            for bus in buses.iter().filter(|b| b.base_name == *name) {
                if bus.msb != dir_msb || bus.lsb != dir_lsb {
                    self.tree.diagnostics.push(ItemTreeDiagnostic::PortRangeMismatch {
                        ast_id: bus.ast_id,
                        name: name.clone(),
                        dir_msb,
                        dir_lsb,
                        net_msb: bus.msb,
                        net_lsb: bus.lsb,
                    });
                    break;
                }
            }
        }

        self.check_branch_bus_refs(&items, &buses);

        let res =
            Module { name, nodes, items, ast_id, num_ports, buses, var_arrays, param_arrays };
        Some(self.tree.data.modules.push_and_get_key(res))
    }

    fn lower_module_items(
        &mut self,
        items: ast::AstChildren<ast::ModuleItem>,
        nodes: &mut TiVec<LocalNodeId, Node>,
        dst: &mut Vec<ModuleItem>,
        buses: &mut Vec<BusDecl>,
        var_arrays: &mut Vec<BusDecl>,
        param_arrays: &mut Vec<BusDecl>,
    ) {
        for item in items {
            match item {
                ast::ModuleItem::BodyPortDecl(decl) => {
                    if let Some(decl) = decl.port_decl() {
                        self.lower_port_decl(decl, nodes, dst, buses);
                    }
                }
                ast::ModuleItem::NetDecl(decl) => {
                    self.lower_net_decl(decl, nodes, dst, buses);
                }
                ast::ModuleItem::AnalogBehaviour(behaviour) => {
                    if let Some(stmt) = behaviour.stmt() {
                        self.lower_stmt(stmt, dst);
                    }
                }
                ast::ModuleItem::VarDecl(var) => {
                    self.lower_var(var, dst, Some(var_arrays));
                }
                ast::ModuleItem::ParamDecl(param) => {
                    self.lower_param(param, dst, Some(param_arrays));
                }
                ast::ModuleItem::Function(fun) => {
                    self.lower_fun(fun, dst);
                }
                ast::ModuleItem::BranchDecl(branch) => self.lower_branch(branch, dst),
                ast::ModuleItem::AliasParam(alias) => self.lower_alias_param(alias, dst),
                ast::ModuleItem::Instantiation(inst) => self.lower_instantiation(inst, dst),
                // `genvar`/`generate for` are always fully elaborated away
                // (text-level, before this stage runs) by
                // `hir::elaborate::elaborate_generates` -- see that module.
                // Reaching here means elaboration bailed out (e.g. a loop
                // bound that didn't constant-fold); drop the construct and
                // leave a diagnostic rather than silently miscompiling.
                ast::ModuleItem::GenvarDecl(_) => {}
                ast::ModuleItem::GenerateFor(gen) => {
                    let ast_id = self.source_ast_id_map.ast_id(&gen);
                    self.tree
                        .diagnostics
                        .push(ItemTreeDiagnostic::UnelaboratedGenerate { ast_id: ast_id.into() });
                }
                ast::ModuleItem::GenerateIf(gen) => {
                    let ast_id = self.source_ast_id_map.ast_id(&gen);
                    self.tree
                        .diagnostics
                        .push(ItemTreeDiagnostic::UnelaboratedGenerate { ast_id: ast_id.into() });
                }
                ast::ModuleItem::GenerateCase(gen) => {
                    let ast_id = self.source_ast_id_map.ast_id(&gen);
                    self.tree
                        .diagnostics
                        .push(ItemTreeDiagnostic::UnelaboratedGenerate { ast_id: ast_id.into() });
                }
            };
        }
    }

    /// Lowers a module-instantiation statement. Each comma-separated
    /// `InstanceUnit` becomes one or more `Instantiation` item-tree entries
    /// (one per array element for an arrayed instance, mirroring
    /// `expand_bus_names`'s per-bit expansion) all sharing the statement's
    /// `ast_id`, disambiguated by `unit_idx`/`array_index`. Port/parameter
    /// binding details are intentionally *not* captured here: they're read
    /// straight from the AST (via `ast_id`) by name resolution and by the
    /// elaboration pass, exactly like how `Net`/`Port` only cache their
    /// discipline here and leave the rest to the AST.
    fn lower_instantiation(&mut self, decl: ast::Instantiation, dst: &mut Vec<ModuleItem>) {
        let ast_id = self.source_ast_id_map.ast_id(&decl);
        let Some(module) = decl.module().map(|it| it.as_name()) else { return };

        for (unit_idx, unit) in decl.instance_units().enumerate() {
            let Some(name) = unit.name() else { continue };
            let base_name = name.as_name();

            let range = match unit.width() {
                Some(range) => range,
                None => {
                    let id = self.tree.data.instantiations.push_and_get_key(Instantiation {
                        name: base_name,
                        unit_idx,
                        array_index: None,
                        module: module.clone(),
                        ast_id,
                    });
                    dst.push(id.into());
                    continue;
                }
            };

            match fold_width_range(&range) {
                // Enhancement-148: cap instance-array expansion so `dev r[0:100000000]()`
                // is reported instead of materializing millions of instances.
                Some((msb, lsb)) if array_elem_count(&[(msb, lsb)]).is_none() => {
                    self.tree.diagnostics.push(ItemTreeDiagnostic::ArrayTooLarge {
                        ast_id: ast_id.into(),
                        size: (msb as i64 - lsb as i64).abs() + 1,
                    });
                    let id = self.tree.data.instantiations.push_and_get_key(Instantiation {
                        name: base_name.clone(),
                        unit_idx,
                        array_index: None,
                        module: module.clone(),
                        ast_id,
                    });
                    dst.push(id.into());
                }
                Some((msb, lsb)) => {
                    let (lo, hi) = if msb <= lsb { (msb, lsb) } else { (lsb, msb) };
                    for idx in lo..=hi {
                        let id = self.tree.data.instantiations.push_and_get_key(Instantiation {
                            name: super::bus_bit_name(&base_name, idx),
                            unit_idx,
                            array_index: Some(idx),
                            module: module.clone(),
                            ast_id,
                        });
                        dst.push(id.into());
                    }
                }
                None => {
                    self.tree.diagnostics.push(ItemTreeDiagnostic::NonConstantInstanceArrayWidth {
                        ast_id: ast_id.into(),
                    });
                    let id = self.tree.data.instantiations.push_and_get_key(Instantiation {
                        name: base_name,
                        unit_idx,
                        array_index: None,
                        module: module.clone(),
                        ast_id,
                    });
                    dst.push(id.into());
                }
            }
        }
    }

    fn lower_fun(&mut self, fun: ast::Function, dst: &mut Vec<ModuleItem>) {
        let mut items = Vec::new();
        let mut args: TiVec<LocalFunctionArgId, FunctionArg> = TiVec::new();
        // Array-variable declarations local to this function (Enhancement-18): array locals and
        // array-typed arguments expand into element vars here, exactly like `Module::var_arrays`.
        let mut var_arrays = Vec::new();
        // Enhancement-389: the (direction, type) of the last ANSI header entry that
        // stated one, for entries that omit both.
        let mut ansi_carry: Option<(bool, bool, Option<Type>)> = None;
        for item in fun.function_items() {
            match item {
                ast::FunctionItem::ParamDecl(decl) => self.lower_param(decl, &mut items, None),
                ast::FunctionItem::VarDecl(decl) => {
                    self.lower_var(decl, &mut items, Some(&mut var_arrays))
                }
                ast::FunctionItem::FunctionArg(arg) => {
                    let ast_id = self.source_ast_id_map.ast_id(&arg);
                    let direction = arg.direction();
                    // Enhancement-389: an ANSI header entry may restate neither the
                    // direction nor the type -- `f(input real x, y)` gives `y` both
                    // of `x`'s -- so carry the previous entry forward. Only an entry
                    // with NO direction inherits: the separated form always writes
                    // one (`func_arg` requires it), so its untyped `input x;` can
                    // never pick up a stray type from an earlier argument.
                    let (is_in, is_out, explicit_ty) = if direction.is_some() {
                        let cur = (
                            is_input(&direction),
                            is_output(&direction),
                            arg.ty().map(|ty| ty.as_type()),
                        );
                        ansi_carry = Some(cur.clone());
                        cur
                    } else {
                        match ansi_carry.clone() {
                            Some(prev) => prev,
                            // Enhancement-390: an ANSI entry that states no direction and
                            // has none to inherit -- `f(real x)`, the FIRST argument --
                            // is an INPUT. Verilog defaults a function argument to input,
                            // and the alternative was worse than wrong: the argument was
                            // neither input nor output, so nothing was copied in and the
                            // body read 0 while the call still accepted its value.
                            // `f(3.0)` returned 0 instead of 6, silently. The separated
                            // and combined forms reject a direction-less argument
                            // outright; only this path could produce one.
                            None => (true, false, arg.ty().map(|ty| ty.as_type())),
                        }
                    };
                    for (name_idx, name) in arg.names().enumerate() {
                        let name = name.as_name();
                        if let Some(arg) = args.iter_mut().find(|arg| arg.name == name) {
                            // TODO validation
                            arg.ast_ids.push(ast_id)
                        }
                        let arg = args.push_and_get_key(FunctionArg {
                            name,
                            name_idx,
                            is_input: is_in,
                            is_output: is_out,
                            declarations: Vec::new(),
                            explicit_ty: explicit_ty.clone(),
                            ast_ids: vec![ast_id],
                        });
                        items.push(arg.into());
                    }
                }
                ast::FunctionItem::Stmt(stmt) => self.lower_stmt(stmt, &mut items),
            }
        }

        items.retain(|decl| {
            if let FunctionItem::Variable(var) = decl {
                if let Some(arg) = args.iter_mut().find(|arg| arg.name == self.tree[*var].name) {
                    // TODO validation
                    arg.declarations.push(*var);
                    return false;
                }
            };
            true
        });

        if let Some(name) = fun.name() {
            let base_name = name.as_name();
            let ty = fun.ty().map_or(Type::Real, |ty| ty.as_type());

            // Array return `analog function real[0:n] f;` (Enhancement-23): expand the return into
            // element variables `f[i]` (a var_array named after the function, so its elements
            // resolve exactly like an array argument's), and record the return dimensions.
            let ret_widths: Vec<ast::Range> = fun.widths().collect();
            let ret_dims = if ret_widths.is_empty() {
                None
            } else {
                match fold_width_ranges(ret_widths.iter().cloned()) {
                    // Enhancement-148: cap array-return expansion.
                    Some(dims) if array_elem_count(&dims).is_none() => {
                        let fun_ast_id = self.source_ast_id_map.ast_id(&fun);
                        self.tree.diagnostics.push(ItemTreeDiagnostic::ArrayTooLarge {
                            ast_id: fun_ast_id.into(),
                            size: dims.iter().fold(1i64, |a, (m, l)| {
                                a.saturating_mul((*m as i64 - *l as i64).abs() + 1)
                            }),
                        });
                        None
                    }
                    Some(dims) => {
                        let fun_ast_id = self.source_ast_id_map.ast_id(&fun);
                        let arr = BusDecl {
                            base_name: base_name.clone(),
                            msb: dims[0].0,
                            lsb: dims[0].1,
                            dims: dims.clone(),
                            ast_id: fun_ast_id.into(),
                        };
                        // The return element variables have no `ast::Var` declaration node; they
                        // carry the function's id purely as a placeholder (they are always written
                        // by the body before being read, so their default is never lowered — and
                        // `var_body`/nameres fall back gracefully when the node isn't an `ast::Var`).
                        let var_ast_id = AstId::<ast::Var>::from_erased(fun_ast_id.erased());
                        for indices in arr.index_tuples() {
                            let var = Var {
                                name: arr.elem_name(&indices),
                                ast_id: var_ast_id,
                                ty: ty.clone(),
                                // no `ast::Var` node behind it, so there is no initializer
                                // literal to index into
                                array_index: None,
                            };
                            let id = self.tree.data.variables.push_and_get_key(var);
                            items.push(id.into());
                        }
                        var_arrays.push(arr);
                        Some(dims.into_boxed_slice())
                    }
                    None => {
                        let ast_id = self.source_ast_id_map.ast_id(&fun);
                        self.tree
                            .diagnostics
                            .push(ItemTreeDiagnostic::NonConstantBusWidth { ast_id: ast_id.into() });
                        None
                    }
                }
            };

            let fun = Function {
                name: base_name,
                ty,
                args,
                items,
                ast_id: self.source_ast_id_map.ast_id(&fun),
                var_arrays,
                ret_dims,
            };
            let fun = self.tree.data.functions.push_and_get_key(fun);
            dst.push(fun.into())
        }
    }

    /// Resolves a branch endpoint to a `Path`: a plain endpoint resolves its `ast::Path`
    /// normally (a bare reference to a bus base name is detected and diagnosed by the
    /// `finalize_branch_buses` post-pass once all of the module's buses are known); a
    /// bit-select endpoint (`bus[2]`) constant-folds the index and synthesizes the same
    /// `"bus[2]"` path the bus's expanded scalar `Node` was declared under (see
    /// `expand_bus_names`). A non-constant index is diagnosed and fails to resolve (the
    /// branch becomes `BranchKind::Missing`).
    fn resolve_branch_endpoint(
        &mut self,
        endpoint: ast::BranchEndpoint,
        ast_id: ErasedAstId,
    ) -> Option<Path> {
        match endpoint {
            ast::BranchEndpoint::Plain(path) => Path::resolve(path),
            ast::BranchEndpoint::BitSelect(base, index) => {
                let base_name = Path::resolve(base)?.as_ident()?;
                let idx = match index.as_constexprval() {
                    Some(ConstExprValue::Int(i)) => i,
                    _ => {
                        self.tree
                            .diagnostics
                            .push(ItemTreeDiagnostic::NonConstantBranchBitSelect { ast_id });
                        return None;
                    }
                };
                Some(Path::new_ident(super::bus_bit_name(&base_name, idx)))
            }
        }
    }

    fn lower_branch(&mut self, decl: ast::BranchDecl, dst: &mut Vec<ModuleItem>) {
        let ast_id = self.source_ast_id_map.ast_id(&decl);
        let kind = decl
            .branch_kind()
            .and_then(|kind| {
                let res = match kind {
                    ast::BranchKind::PortFlow(flow) => {
                        BranchKind::PortFlow(Path::resolve(flow.port()?)?)
                    }
                    ast::BranchKind::NodeGnd(node) => {
                        BranchKind::NodeGnd(self.resolve_branch_endpoint(node, ast_id.into())?)
                    }
                    ast::BranchKind::Nodes(hi, lo) => BranchKind::Nodes(
                        self.resolve_branch_endpoint(hi, ast_id.into())?,
                        self.resolve_branch_endpoint(lo, ast_id.into())?,
                    ),
                };
                Some(res)
            })
            .unwrap_or(BranchKind::Missing);
        for (name_idx, name) in decl.names().enumerate() {
            let branch = Branch { name: name.as_name(), kind: kind.clone(), ast_id, name_idx };
            let id = self.tree.data.branches.push_and_get_key(branch);
            dst.push(id.into());
        }
    }

    /// Post-pass run once a module's `buses` registry is fully known: diagnoses branch
    /// endpoints that referenced a bus by its bare base name with no bit-select (which
    /// `resolve_branch_endpoint` would otherwise have resolved as an ordinary, and
    /// nonexistent, node path, only to fail name resolution later with a confusing
    /// "not found" error).
    fn check_branch_bus_refs(&mut self, dst: &[ModuleItem], buses: &[BusDecl]) {
        if buses.is_empty() {
            return;
        }
        for item in dst {
            if let ModuleItem::Branch(id) = item {
                let branch = &self.tree.data.branches[*id];
                let ast_id = branch.ast_id.into();
                let endpoints: Vec<&Path> = match &branch.kind {
                    BranchKind::PortFlow(p) | BranchKind::NodeGnd(p) => vec![p],
                    BranchKind::Nodes(p1, p2) => vec![p1, p2],
                    BranchKind::Missing => vec![],
                };
                for path in endpoints {
                    let Some(ident) = path.as_ident() else { continue };
                    if let Some(bus) = buses.iter().find(|b| b.base_name == ident) {
                        // bare reference to a bus base name with no bit-select
                        self.tree.diagnostics.push(ItemTreeDiagnostic::BareBusReferenceInBranch {
                            ast_id,
                            bus_name: bus.base_name.clone(),
                        });
                        continue;
                    }
                    // a synthesized "base[idx]" bit-select path: range-check it against
                    // the bus's declared width, if its base matches a known bus.
                    if let Some((base, idx)) = parse_synthesized_bit_name(&ident) {
                        if let Some(bus) = buses.iter().find(|b| b.base_name == base) {
                            if !bus.contains_bit(idx) {
                                self.tree.diagnostics.push(
                                    ItemTreeDiagnostic::BranchBitSelectOutOfRange {
                                        ast_id,
                                        bus_name: bus.base_name.clone(),
                                        index: idx,
                                        msb: bus.msb,
                                        lsb: bus.lsb,
                                    },
                                );
                            }
                        }
                    }
                }
            }
        }
    }

    /// Pre-scans a module's body port declarations, collecting the declared
    /// width (if any) for each port name. Used by `lower_module_ports` to
    /// expand a non-ANSI header bus port into its bits in header-port order
    /// (Enhancement-90). Only port (direction) declarations carry authoritative
    /// terminal widths; the first width seen for a name wins.
    fn prescan_body_port_widths(
        items: ast::AstChildren<ast::ModuleItem>,
    ) -> Vec<(Name, ast::Range)> {
        let mut res: Vec<(Name, ast::Range)> = Vec::new();
        for item in items {
            let ast::ModuleItem::BodyPortDecl(decl) = item else { continue };
            let Some(decl) = decl.port_decl() else { continue };
            let Some(width) = decl.width() else { continue };
            for name in decl.names() {
                let name = name.as_name();
                if !res.iter().any(|(n, _)| *n == name) {
                    res.push((name, width.clone()));
                }
            }
        }
        res
    }

    fn lower_module_ports(
        &mut self,
        ports: ast::ModulePorts,
        nodes: &mut TiVec<LocalNodeId, Node>,
        dst: &mut Vec<ModuleItem>,
        buses: &mut Vec<BusDecl>,
        port_widths: &[(Name, ast::Range)],
    ) {
        for port in ports.ports() {
            let ast_id = self.source_ast_id_map.ast_id(&port);
            match port.kind() {
                ast::ModulePortKind::Name(name) => {
                    let name = name.as_name();
                    if nodes.iter().all(|node| node.name != name) {
                        // Enhancement-90: a non-ANSI header port whose width is
                        // declared in the body. Pre-expand the bus here, in
                        // header order, so its bits stay contiguous. Without
                        // this the header creates a single bare placeholder and
                        // the body's expansion appends the remaining bits at the
                        // end of the node list -- scrambling terminal order for
                        // any bus port that is not the last port, which then
                        // mis-wires the netlist terminals. The `BusDecl` itself
                        // is still registered by the body declaration below.
                        let width = port_widths
                            .iter()
                            .find(|(n, _)| *n == name)
                            .and_then(|(_, w)| fold_width_range(w));
                        match width {
                            // Enhancement-148: cap bus-port expansion.
                            Some((msb, lsb))
                                if array_elem_count(&[(msb, lsb)]).is_none() =>
                            {
                                self.tree.diagnostics.push(ItemTreeDiagnostic::ArrayTooLarge {
                                    ast_id: ast_id.into(),
                                    size: (msb as i64 - lsb as i64).abs() + 1,
                                });
                                let node = nodes.push_and_get_key(Node {
                                    name,
                                    is_port: true,
                                    ast_id: ast_id.into(),
                                    decls: Vec::new(),
                                });
                                dst.push(node.into())
                            }
                            Some((msb, lsb)) => {
                                let (lo, hi) =
                                    if msb >= lsb { (lsb, msb) } else { (msb, lsb) };
                                for bit in lo..=hi {
                                    let node = nodes.push_and_get_key(Node {
                                        name: super::bus_bit_name(&name, bit),
                                        is_port: true,
                                        ast_id: ast_id.into(),
                                        decls: Vec::new(),
                                    });
                                    dst.push(node.into())
                                }
                            }
                            None => {
                                let node = nodes.push_and_get_key(Node {
                                    name,
                                    is_port: true,
                                    ast_id: ast_id.into(),
                                    decls: Vec::new(),
                                });
                                dst.push(node.into())
                            }
                        }
                    }
                }
                ast::ModulePortKind::PortDecl(decl) => {
                    self.lower_port_decl(decl, nodes, dst, buses);
                }
            }
        }
    }

    /// Expands a (possibly vectored) declaration's name list into the list of
    /// scalar names to actually declare, registering a `BusDecl` (and
    /// diagnosing non-constant widths) as needed. Each entry is
    /// `(name, name_idx)` where `name_idx` mirrors the original `enumerate()`
    /// index of the *declared* (un-expanded) name, matching existing
    /// multi-declaration semantics.
    /// Like the result of expansion, but additionally marks the *first* synthesized bit of
    /// each bus with the original (un-expanded) base name. This lets callers merge a bus's
    /// first bit into a pre-existing module-head port placeholder declared under the bare
    /// base name (e.g. `module m(in, out); output [3:0] out;` — the header's bare `out`
    /// placeholder has to become `out[0]`, not be left dangling), without disturbing the
    /// stable `LocalNodeId` indices any other declaration may already reference.
    fn expand_bus_names(
        &mut self,
        width: Option<ast::Range>,
        names: ast::AstChildren<ast::Name>,
        ast_id: ErasedAstId,
        buses: &mut Vec<BusDecl>,
    ) -> Vec<(Name, usize, Option<Name>)> {
        let Some(width) = width else {
            return names.enumerate().map(|(idx, name)| (name.as_name(), idx, None)).collect();
        };

        let mut res = Vec::new();
        for (name_idx, name) in names.enumerate() {
            let base_name = name.as_name();
            match fold_width_range(&width) {
                // Enhancement-148: cap net/port bus expansion.
                Some((msb, lsb)) if array_elem_count(&[(msb, lsb)]).is_none() => {
                    self.tree.diagnostics.push(ItemTreeDiagnostic::ArrayTooLarge {
                        ast_id,
                        size: (msb as i64 - lsb as i64).abs() + 1,
                    });
                    res.push((base_name, name_idx, None));
                }
                Some((msb, lsb)) => {
                    buses.push(BusDecl {
                        base_name: base_name.clone(),
                        msb,
                        lsb,
                        dims: vec![(msb, lsb)],
                        ast_id,
                    });
                    let (lo, hi) = if msb >= lsb { (lsb, msb) } else { (msb, lsb) };
                    // declare from lsb to msb (ascending), matching natural bit order;
                    // direction of the original [msb:lsb] only affects range checks
                    for bit in lo..=hi {
                        let merge_base = if bit == lo { Some(base_name.clone()) } else { None };
                        res.push((super::bus_bit_name(&base_name, bit), name_idx, merge_base));
                    }
                }
                None => {
                    self.tree
                        .diagnostics
                        .push(ItemTreeDiagnostic::NonConstantBusWidth { ast_id });
                    // fall back to a scalar declaration so compilation proceeds
                    res.push((base_name, name_idx, None));
                }
            }
        }
        res
    }

    /// Finds the node a declared name should attach to: an exact match, or (for the first bit
    /// of a bus) a still-unresolved module-head port placeholder declared under the bus's bare
    /// base name.
    fn find_node_for_decl<'n>(
        nodes: &'n mut TiVec<LocalNodeId, Node>,
        name: &Name,
        merge_base: &Option<Name>,
    ) -> Option<&'n mut Node> {
        if nodes.iter().any(|node| &node.name == name) {
            return nodes.iter_mut().find(|node| &node.name == name);
        }
        let base = merge_base.as_ref()?;
        let node = nodes.iter_mut().find(|node| &node.name == base && node.decls.is_empty())?;
        node.name = name.clone();
        Some(node)
    }

    fn lower_port_decl(
        &mut self,
        decl: ast::PortDecl,
        nodes: &mut TiVec<LocalNodeId, Node>,
        dst: &mut Vec<ModuleItem>,
        buses: &mut Vec<BusDecl>,
    ) {
        let discipline = decl.discipline().map(|it| it.as_name());
        let direction = decl.direction();

        let is_gnd = decl.net_type_token().map_or(false, |it| it.text() == kw::raw::ground);
        let ast_id = self.source_ast_id_map.ast_id(&decl);
        let names = self.expand_bus_names(decl.width(), decl.names(), ast_id.into(), buses);
        for (name, name_idx, merge_base) in names {
            let id = self.tree.data.ports.push_and_get_key(Port {
                name: name.clone(),
                discipline: discipline.clone(),
                is_input: is_input(&direction),
                is_output: is_output(&direction),
                ast_id,
                name_idx,
                is_gnd,
            });

            match Self::find_node_for_decl(nodes, &name, &merge_base) {
                Some(node) => node.decls.push(id.into()),
                None => {
                    let node = nodes.push_and_get_key(Node {
                        name,
                        is_port: true,
                        ast_id: ast_id.into(),
                        decls: vec![id.into()],
                    });
                    dst.push(node.into())
                }
            }
        }
    }

    fn lower_net_decl(
        &mut self,
        decl: ast::NetDecl,
        nodes: &mut TiVec<LocalNodeId, Node>,
        dst: &mut Vec<ModuleItem>,
        buses: &mut Vec<BusDecl>,
    ) {
        let discipline = decl.discipline().map(|it| it.as_name());
        let ast_id = self.source_ast_id_map.ast_id(&decl);

        let is_gnd = decl.net_type_token().map_or(false, |it| it.text() == kw::raw::ground);

        // Nodeset initializers (`electrical a = 5.0;` / `electrical [0:4] b =
        // '{...};`, LRM 3.6.3.2, Enhancement-45): fold each declarator's
        // constant initializer; for a bus, flatten the `'{...}` literal into
        // per-bit leaves in ascending bit order (matching the expansion order
        // below). A non-constant initializer is diagnosed and dropped.
        let declarators = decl.declarators();
        let fold_leaf = |this: &mut Self, e: &ast::Expr| -> Option<f64> {
            match e.as_constexprval() {
                Some(ConstExprValue::Int(i)) => Some(f64::from(i)),
                Some(ConstExprValue::Float(f)) => Some(f.into_inner()),
                _ => {
                    this.tree.diagnostics.push(ItemTreeDiagnostic::NonConstantNodeset {
                        ast_id: ast_id.into(),
                    });
                    None
                }
            }
        };
        let mut init_leaves: Vec<Option<Vec<Option<f64>>>> = Vec::new();
        for (_, init) in &declarators {
            let leaves = init.as_ref().map(|init| match init {
                ast::Expr::ArrayExpr(arr) => {
                    arr.exprs().map(|e| fold_leaf(self, &e)).collect()
                }
                other => vec![fold_leaf(self, other)],
            });
            init_leaves.push(leaves);
        }
        let mut bit_pos: Vec<usize> = vec![0; init_leaves.len()];

        let names = self.expand_bus_names(decl.width(), decl.names(), ast_id.into(), buses);
        for (name, name_idx, merge_base) in names {
            let nodeset = init_leaves.get(name_idx).and_then(|leaves| {
                let leaves = leaves.as_ref()?;
                let pos = bit_pos[name_idx];
                bit_pos[name_idx] += 1;
                leaves.get(pos).copied().flatten()
            });
            let id = self.tree.data.nets.push_and_get_key(Net {
                name: name.clone(),
                discipline: discipline.clone(),
                ast_id,
                is_gnd,
                name_idx,
                nodeset: nodeset.map(OrderedFloat),
            });

            match Self::find_node_for_decl(nodes, &name, &merge_base) {
                Some(node) => node.decls.push(id.into()),
                None => {
                    let node = nodes.push_and_get_key(Node {
                        name,
                        is_port: false,
                        ast_id: ast_id.into(),
                        decls: vec![id.into()],
                    });
                    dst.push(node.into());
                }
            }
        }
    }

    fn lower_stmt<
        T: From<ItemTreeId<Param>> + From<ItemTreeId<Var>> + From<AstId<ast::BlockStmt>>,
    >(
        &mut self,
        stmt: ast::Stmt,
        parent_scope: &mut Vec<T>,
    ) {
        let mut block_stack = Vec::new();
        let mut block_scope_stack = Vec::new();
        let mut blocks = mem::take(&mut self.tree.blocks);

        for event in stmt.syntax().preorder() {
            match event {
                WalkEvent::Enter(node) => {
                    match_ast! {
                        match node {
                            ast::BlockStmt(block) => {
                                let ast_id = self.source_ast_id_map.ast_id(&block);
                                let name = block.block_scope().and_then(|it| Some(it.name()?.as_name()));
                                let block_info = Block { name: name.clone(), scope_items: Vec::new()};
                                // Enhancement-230: only treat a block as a named item-tree
                                // scope when it actually has a name. A `begin :` with the
                                // scope colon but a missing/invalid name identifier has
                                // `block_scope().is_some()` yet `name == None`; linking it
                                // in here made name resolution later `.expect()` the absent
                                // name and panic ("Item tree must only contain named
                                // blocks"). Gate on `name.is_some()` (the parser already
                                // reports the missing block name separately).
                                if name.is_some() {
                                    match block_scope_stack.last() {
                                        Some(block) => {
                                            let block = blocks.get_mut(block).unwrap();
                                             block.scope_items.push(ast_id.into());
                                        }
                                        None =>  parent_scope.push(ast_id.into()),
                                    };

                                    block_scope_stack.push(ast_id);
                                }

                                blocks.insert(ast_id, block_info);
                                block_stack.push(ast_id);
                            },
                            ast::VarDecl(var) => {
                              match block_stack.last() {
                                    Some(block) => {
                                        let block = blocks.get_mut(block).unwrap();
                                        self.lower_var(var, &mut block.scope_items, None)
                                    }
                                    None => self.lower_var(var, parent_scope, None),
                                }
                            },
                            ast::ParamDecl(param) => {
                              match block_stack.last() {
                                    Some(block) => {
                                        let block = blocks.get_mut(block).unwrap();
                                        self.lower_param(param, &mut block.scope_items, None)
                                    }
                                 None => self.lower_param(param, parent_scope, None),
                                }
                            },
                            _ => ()
                        }
                    }
                }
                WalkEvent::Leave(node) => {
                    if let Some(block) = ast::BlockStmt::cast(node) {
                        block_stack.pop();
                        // Enhancement-230: mirror the `name.is_some()` gate used on
                        // Enter, so the scope stack stays balanced for a nameless
                        // `begin :` (which is pushed on neither side).
                        let named = block.block_scope().and_then(|it| it.name()).is_some();
                        if named {
                            block_scope_stack.pop();
                        }
                    }
                }
            }
        }

        self.tree.blocks = blocks;
    }

    /// Lowers a `VarDecl`. `var_arrays` is `Some` only when called from module body scope
    /// (the only scope where array-variable bit-select resolution is supported, mirroring
    /// `buses`/`find_bus`'s `DefWithBodyId::ModuleId`-only lookup, see `Enhancement-4.md` §3);
    /// `None` from `analog function` bodies and nested `begin..end` blocks, where a width
    /// clause is diagnosed and dropped (falls back to an ordinary scalar declaration).
    fn lower_var<T: From<ItemTreeId<Var>>>(
        &mut self,
        decl: ast::VarDecl,
        dst: &mut Vec<T>,
        mut var_arrays: Option<&mut Vec<BusDecl>>,
    ) {
        let ty = decl.ty().as_type();
        // Array dimensions may be written *before* the name and shared by the whole declaration
        // (`real [0:n] x, y;`, Enhancement-15) or *after* each name (`real x[0:n], m[0:1][0:2];`,
        // the standard Verilog-AMS form, Enhancement-18). Each `[msb:lsb]` clause is one dimension.
        let decl_widths: Vec<ast::Range> = decl.widths().collect();

        for var in decl.vars() {
            let Some(name) = var.name() else { continue };
            let base_name = name.as_name();
            let ast_id = self.source_ast_id_map.ast_id(&var);

            // per-variable dimensions take precedence; otherwise the shared declaration-level ones
            let var_widths: Vec<ast::Range> = var.widths().collect();
            let widths = if var_widths.is_empty() { &decl_widths } else { &var_widths };

            let mut push_scalar = |this: &mut Self| {
                let var =
                    Var { name: base_name.clone(), ast_id, ty: ty.clone(), array_index: None };
                let id = this.tree.data.variables.push_and_get_key(var);
                dst.push(id.into());
            };

            if widths.is_empty() {
                // ordinary (non-array) variable declaration
                push_scalar(self);
                continue;
            }

            let Some(var_arrays) = var_arrays.as_deref_mut() else {
                // a width clause outside module body scope: diagnose and degrade to scalar
                self.tree
                    .diagnostics
                    .push(ItemTreeDiagnostic::ArrayVarUnsupportedScope { ast_id: ast_id.into() });
                push_scalar(self);
                continue;
            };

            match fold_width_ranges(widths.iter().cloned()) {
                Some(dims) => {
                    // Enhancement-148: refuse to materialize an absurdly large array.
                    if array_elem_count(&dims).is_none() {
                        let size = dims.iter().fold(1i64, |a, (m, l)| {
                            a.saturating_mul((*m as i64 - *l as i64).abs() + 1)
                        });
                        self.tree
                            .diagnostics
                            .push(ItemTreeDiagnostic::ArrayTooLarge { ast_id: ast_id.into(), size });
                        push_scalar(self);
                        continue;
                    }
                    let arr = BusDecl {
                        base_name: base_name.clone(),
                        msb: dims[0].0,
                        lsb: dims[0].1,
                        dims,
                        ast_id: ast_id.into(),
                    };
                    // an initializer must supply exactly one leaf per element -- a mismatch
                    // used to crash the compiler once the missing leaves reached lowering
                    if let Some(default) = var.default() {
                        let expected = arr.index_tuples().len() as u32;
                        let found = count_literal_leaves(&default);
                        if found != expected {
                            self.tree.diagnostics.push(
                                ItemTreeDiagnostic::ArrayInitializerLengthMismatch {
                                    ast_id: ast_id.into(),
                                    name: base_name.clone(),
                                    expected,
                                    found,
                                },
                            );
                        }
                    }
                    // one scalar element per index tuple, named `x[i]` / `x[i][j]` / ...; each
                    // carries its flat position so a shared `'{...}` initializer can be split
                    // into per-element leaves, exactly like array parameters (Enhancement-43)
                    for (pos, indices) in arr.index_tuples().iter().enumerate() {
                        let var = Var {
                            name: arr.elem_name(indices),
                            ast_id,
                            ty: ty.clone(),
                            array_index: Some(pos as u32),
                        };
                        let id = self.tree.data.variables.push_and_get_key(var);
                        dst.push(id.into());
                    }
                    var_arrays.push(arr);
                }
                None => {
                    self.tree
                        .diagnostics
                        .push(ItemTreeDiagnostic::NonConstantBusWidth { ast_id: ast_id.into() });
                    // fall back to a scalar declaration so compilation proceeds
                    push_scalar(self);
                }
            }
        }
    }

    /// Lowers a `ParamDecl`. `param_arrays` is `Some` only at module body scope (like `var_arrays`
    /// for `lower_var`): an array-valued parameter (`parameter real [msb:lsb] c = '{...};`) is
    /// registered there and expanded into one scalar parameter per element (`c[lo]`..`c[hi]`), each
    /// carrying its `array_index` (declaration-order position) so it can pick its per-element
    /// default from the `'{...}` literal. A width clause outside module scope, or a non-constant
    /// width, degrades to an ordinary scalar parameter.
    fn lower_param<T: From<ItemTreeId<Param>>>(
        &mut self,
        decl: ast::ParamDecl,
        dst: &mut Vec<T>,
        param_arrays: Option<&mut Vec<BusDecl>>,
    ) {
        let ty = decl.ty().map(|ty| ty.as_type());
        let is_local = decl.localparam_token().is_some();
        // Type-then-range dims (`parameter real [0:2] c`, Enhancement-14/15) are
        // shared by every name in the declaration. Enhancement-102 also allows
        // the name-then-range form (`parameter real c[0:2]`), where each name
        // carries its own dims -- so the width set is resolved per name below.
        let decl_widths: Vec<ast::Range> = decl.widths().collect();
        let has_param_arrays = param_arrays.is_some();

        for param in decl.paras() {
            let Some(name) = param.name() else { continue };
            let base_name = name.as_name();
            let ast_id = self.source_ast_id_map.ast_id(&param);
            // Enhancement-102: prefer the shared decl-level dims; otherwise fall
            // back to this name's own name-then-range dims (empty for a scalar).
            let widths: Vec<ast::Range> =
                if decl_widths.is_empty() { param.widths().collect() } else { decl_widths.clone() };
            let dims =
                if widths.is_empty() { None } else { fold_width_ranges(widths.iter().cloned()) };

            let push_scalar = |this: &mut Self, dst: &mut Vec<T>| {
                let param = Param {
                    name: base_name.clone(),
                    is_local,
                    ty: ty.clone(),
                    ast_id,
                    array_index: None,
                    override_expr: None,
                };
                let id = this.tree.data.parameters.push_and_get_key(param);
                dst.push(id.into());
            };

            match (widths.is_empty(), has_param_arrays, &dims) {
                // ordinary scalar parameter
                (true, _, _) => push_scalar(self, dst),
                // array-valued parameter at module scope with constant widths
                (false, true, Some(dims)) => {
                    // Enhancement-148: refuse to materialize an absurdly large array param.
                    if array_elem_count(dims).is_none() {
                        let size = dims.iter().fold(1i64, |a, (m, l)| {
                            a.saturating_mul((*m as i64 - *l as i64).abs() + 1)
                        });
                        self.tree
                            .diagnostics
                            .push(ItemTreeDiagnostic::ArrayTooLarge { ast_id: ast_id.into(), size });
                        push_scalar(self, dst);
                        continue;
                    }
                    let arr = BusDecl {
                        base_name: base_name.clone(),
                        msb: dims[0].0,
                        lsb: dims[0].1,
                        dims: dims.clone(),
                        ast_id: ast_id.into(),
                    };
                    // an initializer must supply exactly one leaf per element -- a mismatch
                    // used to crash the compiler once the missing leaves reached lowering
                    // (Enhancement-43; params and vars share the split-literal machinery)
                    if let Some(default) = param.default() {
                        let expected = arr.index_tuples().len() as u32;
                        let found = count_literal_leaves(&default);
                        if found != expected {
                            self.tree.diagnostics.push(
                                ItemTreeDiagnostic::ArrayInitializerLengthMismatch {
                                    ast_id: ast_id.into(),
                                    name: base_name.clone(),
                                    expected,
                                    found,
                                },
                            );
                        }
                    }
                    // one scalar element parameter per index tuple; `array_index` is its flat
                    // declaration-order position, used to pick its default from the (nested) literal
                    for (pos, indices) in arr.index_tuples().iter().enumerate() {
                        let param = Param {
                            name: arr.elem_name(indices),
                            is_local,
                            ty: ty.clone(),
                            ast_id,
                            array_index: Some(pos as u32),
                            override_expr: None,
                        };
                        let id = self.tree.data.parameters.push_and_get_key(param);
                        dst.push(id.into());
                    }
                }
                // width clause but non-constant range or wrong scope: diagnose, degrade to scalar
                (false, _, _) => {
                    self.tree
                        .diagnostics
                        .push(ItemTreeDiagnostic::NonConstantBusWidth { ast_id: ast_id.into() });
                    push_scalar(self, dst);
                }
            }
        }

        // Register the parameter array so `c[i]`/`c[i][j]` bit-selects resolve to
        // the elements. Enhancement-102: the dims are resolved per name (shared
        // decl-level type-then-range, or this name's own name-then-range dims).
        if let Some(param_arrays) = param_arrays {
            for param in decl.paras() {
                let Some(name) = param.name() else { continue };
                let widths: Vec<ast::Range> = if decl_widths.is_empty() {
                    param.widths().collect()
                } else {
                    decl_widths.clone()
                };
                if widths.is_empty() {
                    continue;
                }
                if let Some(dims) = fold_width_ranges(widths.iter().cloned()) {
                    param_arrays.push(BusDecl {
                        base_name: name.as_name(),
                        msb: dims[0].0,
                        lsb: dims[0].1,
                        dims: dims.clone(),
                        ast_id: self.source_ast_id_map.ast_id(&param).into(),
                    });
                }
            }
        }
    }

    fn lower_alias_param<T: From<ItemTreeId<AliasParam>>>(
        &mut self,
        decl: ast::AliasParam,
        dst: &mut Vec<T>,
    ) {
        let name = decl.name();
        let src = decl.src();

        if let (Some(name), Some(src)) = (name, src) {
            let src = match src {
                ParamRef::Path(path) => Path::resolve(path),
                ParamRef::SysFun(fun) => Some(Path::new_ident(fun.as_name())),
            };
            let param = AliasParam {
                name: name.as_name(),
                src,
                ast_id: self.source_ast_id_map.ast_id(&decl),
            };
            let param = self.tree.data.alias_parameters.push_and_get_key(param);
            dst.push(param.into())
        }
    }
}
