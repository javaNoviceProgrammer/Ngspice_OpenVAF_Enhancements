use std::hash::BuildHasherDefault;

use ahash::AHashSet;
use hir::diagnostics::{BaseDB, ConsoleSink, Diagnostic, FileId, Label, LabelStyle, Report};
use hir::{
    CompilationDB, CompilationUnit, DiagnosticSink, Module, ParamSysFun, Parameter,
    ResolvedAliasParameter, ScopeDef, Type, Variable,
};
use indexmap::IndexMap;
use rustc_hash::FxHasher;
use smol_str::SmolStr;
use syntax::ast::{self, Expr};
use syntax::sourcemap::FileSpan;
use syntax::AstNode;

use crate::diagnostics::ProbeOnlyBranchShort;

#[cfg(test)]
mod tests;

pub fn collect_modules(
    db: &CompilationDB,
    all_vars_opvars: bool,
    sink: &mut ConsoleSink,
) -> Option<Vec<ModuleInfo>> {
    let cu = db.compilation_unit();
    let name = cu.name(db);

    cu.diagnostics(db, sink);

    if sink.summary(&name) {
        return None;
    }

    let res = cu
        .modules(db)
        .into_iter()
        .map(|module| ModuleInfo::collect(db, cu, module, sink, all_vars_opvars))
        .collect();

    if sink.summary(&name) {
        return None;
    }

    Some(res)
}

pub struct ModuleInfo {
    pub module: Module,
    pub params: IndexMap<Parameter, ParamInfo, BuildHasherDefault<FxHasher>>,
    pub sys_fun_alias: IndexMap<ParamSysFun, Vec<SmolStr>, BuildHasherDefault<FxHasher>>,
    pub op_vars: IndexMap<Variable, OpVar, BuildHasherDefault<FxHasher>>,
}

impl ModuleInfo {
    fn collect(
        db: &CompilationDB,
        cu: CompilationUnit,
        module: Module,
        sink: &mut ConsoleSink,
        all_vars_opvars: bool,
    ) -> ModuleInfo {
        let mut params: IndexMap<Parameter, ParamInfo, BuildHasherDefault<FxHasher>> =
            IndexMap::default();
        let mut sys_fun_alias: IndexMap<ParamSysFun, Vec<SmolStr>, BuildHasherDefault<FxHasher>> =
            IndexMap::default();
        let mut op_vars: IndexMap<Variable, OpVar, BuildHasherDefault<FxHasher>> =
            IndexMap::default();

        let ast = cu.ast(db);

        check_probe_only_branch_shorts(db, cu, module, sink);

        let mut resolved_attrs = AHashSet::new();
        let mut declarations = module.rec_declarations(db);
        let mut add_diagnostic = |attr: ast::Attr, diag: &dyn Diagnostic| {
            if resolved_attrs.insert(attr.syntax().text_range()) {
                sink.add_diagnostic(diag, cu.root_file(), db)
            }
        };
        while let Some((name, dec)) = declarations.next() {
            match dec {
                ScopeDef::Variable(var) => {
                    // 3.2.1 Output variables
                    //
                    // operating point variables must fulfill two properties
                    // * have a description or units attribute
                    // * belong to a module (not a block/function) -> no path

                    // Bug-hunt F16: the statistics attributes apply to
                    // PARAMETERS; on a variable they are silently inert, and
                    // the shadow-variable typo (`parameter real r; (* std *)
                    // real r_i;`) then runs a Monte-Carlo that varies
                    // nothing. Name the misplacement instead.
                    for stat_name in ["std", "std_rel", "dist"] {
                        if let Some(attr) = var.get_attr(db, &ast, stat_name) {
                            add_diagnostic(attr.clone(), &StatOnNonParam { attr });
                        }
                    }

                    // check for units or description
                    let units = var.get_attr(db, &ast, "units");
                    let desc = var.get_attr(db, &ast, "desc");
                    if units.is_none() && desc.is_none() && !all_vars_opvars {
                        continue;
                    }

                    // LRM 3.2.1: only MODULE-scope variables become output
                    // variables; "Units and descriptions specified for
                    // block-level variables shall be ignored by the
                    // simulator". The old check compared to_path(name)
                    // against the bare name, but block names are never pushed
                    // onto the iterator's path (block-scoped parameters
                    // depend on keeping short names), so it never fired --
                    // two named blocks declaring `(*desc*) real t` both
                    // exported a colliding instance parameter `t`.
                    if declarations.in_block() {
                        continue;
                    }
                    let path = declarations.to_path(name);
                    let units = units
                        .and_then(|attr| {
                            let lit = attr.val().and_then(|e| e.as_str_literal());
                            if lit.is_none() {
                                add_diagnostic(attr.clone(), &IllegalAttr { attr });
                            }
                            lit
                        })
                        .unwrap_or_default();
                    let desc = desc
                        .and_then(|attr| {
                            let lit = attr.val().and_then(|e| e.as_str_literal());
                            if lit.is_none() {
                                add_diagnostic(attr.clone(), &IllegalAttr { attr });
                            }
                            lit
                        })
                        .unwrap_or_default();
                    op_vars.insert(var, OpVar { unit: units, description: desc });
                }

                ScopeDef::Parameter(param) => {
                    let units = param
                        .get_attr(db, &ast, "units")
                        .and_then(|attr| {
                            let lit = attr.val().and_then(|e| e.as_str_literal());
                            if lit.is_none() {
                                add_diagnostic(attr.clone(), &IllegalAttr { attr });
                            }
                            lit
                        })
                        .unwrap_or_default();

                    let desc = param
                        .get_attr(db, &ast, "desc")
                        .and_then(|attr| {
                            let lit = attr.val().and_then(|e| e.as_str_literal());
                            if lit.is_none() {
                                add_diagnostic(attr.clone(), &IllegalAttr { attr });
                            }
                            lit
                        })
                        .unwrap_or_default();

                    let group = param
                        .get_attr(db, &ast, "group")
                        .and_then(|attr| {
                            let lit = attr.val().and_then(|e| e.as_str_literal());
                            if lit.is_none() {
                                add_diagnostic(attr.clone(), &IllegalAttr { attr });
                            }
                            lit
                        })
                        .unwrap_or_default();

                    let type_attr = param.get_attr(db, &ast, "type");
                    let type_ = param.get_attr(db, &ast, "type").and_then(|attr| {
                        let lit = attr.val().and_then(|e| e.as_str_literal());
                        if lit.is_none() {
                            add_diagnostic(attr.clone(), &IllegalAttr { attr });
                        }
                        lit
                    });
                    let is_instance = match type_.as_deref() {
                        Some("instance") => true,
                        Some("model") | None => false,
                        Some(found) => {
                            let attr = type_attr.unwrap();
                            add_diagnostic(
                                attr.clone(),
                                &UnknownType { expr: attr.val().unwrap(), found },
                            );
                            false
                        }
                    };

                    // Statistical metadata for `.option osdimc` Monte-Carlo (a
                    // project extension; LRM 2.9 attributes are the sanctioned
                    // vehicle): `(* std=<sigma> *)` declares an absolute
                    // standard deviation, `(* std_rel=<fraction> *)` one
                    // relative to the resolved nominal, and
                    // `(* dist="gauss"|"uniform" *)` picks the distribution
                    // (gauss when absent; for "uniform" the value is the
                    // HALF-WIDTH of the interval). The values ride the OSDI
                    // side-table `OSDI_STAT_PARAM_INFOS` to the simulator,
                    // which draws per run -- see ngspice's osdisetup.c.
                    let stat = {
                        let mut read_sigma = |attr_name: &str| {
                            param.get_attr(db, &ast, attr_name).and_then(|attr| {
                                let expr = attr.val();
                                let val = expr
                                    .as_ref()
                                    .and_then(|e| e.as_constexprval())
                                    .and_then(|v| v.as_real())
                                    // Convenience: the QUOTED spelling
                                    // `(* std="25.0" *)` is accepted too --
                                    // parsed strictly as one bare number
                                    // (`"25 ohm"`, `"inf"`, `"nan"` are
                                    // refused; a negative falls to the same
                                    // range check as the numeric form).
                                    .or_else(|| {
                                        expr.as_ref()
                                            .and_then(|e| e.as_str_literal())
                                            .and_then(|lit| {
                                                lit.trim().parse::<f64>().ok()
                                            })
                                            .filter(|v| v.is_finite())
                                    });
                                match val {
                                    Some(v) if v >= 0.0 => Some(v),
                                    _ => {
                                        add_diagnostic(
                                            attr.clone(),
                                            &IllegalSigmaAttr { attr },
                                        );
                                        None
                                    }
                                }
                            })
                        };
                        let std = read_sigma("std");
                        let std_rel = read_sigma("std_rel");
                        if std.is_some() && std_rel.is_some() {
                            let attr = param.get_attr(db, &ast, "std_rel").unwrap();
                            add_diagnostic(attr.clone(), &SigmaConflict { attr });
                        }

                        let dist_attr = param.get_attr(db, &ast, "dist");
                        let uniform = dist_attr.as_ref().map_or(false, |attr| {
                            let lit = attr.val().and_then(|e| e.as_str_literal());
                            match lit.as_deref() {
                                Some("gauss") | Some("gaussian") | Some("normal") => false,
                                Some("uniform") => true,
                                Some(found) => {
                                    add_diagnostic(
                                        attr.clone(),
                                        &UnknownDist {
                                            expr: attr.val().unwrap(),
                                            found: found.to_owned(),
                                        },
                                    );
                                    false
                                }
                                None => {
                                    add_diagnostic(
                                        attr.clone(),
                                        &IllegalAttr { attr: attr.clone() },
                                    );
                                    false
                                }
                            }
                        });

                        let (sigma, rel) = match (std, std_rel) {
                            // both given is diagnosed above; the absolute one wins
                            (Some(s), _) => (Some(s), false),
                            (None, Some(s)) => (Some(s), true),
                            (None, None) => (None, false),
                        };

                        match sigma {
                            // a zero sigma declares statistics with no width;
                            // exporting it would only produce exact-zero draws
                            Some(s) if s > 0.0 => {
                                // Only a scalar real, non-local parameter can be
                                // varied by the simulator: the draw path writes a
                                // double through the ordinary parameter setter,
                                // and a localparam refuses netlist writes by
                                // design (E-93).
                                let reason = if param.ty(db) != Type::Real {
                                    Some("only a scalar real parameter can carry statistics")
                                } else if param.is_local(db) {
                                    Some(
                                        "a localparam cannot be varied by the simulator",
                                    )
                                } else {
                                    None
                                };
                                match reason {
                                    Some(reason) => {
                                        let attr = param
                                            .get_attr(db, &ast, "std")
                                            .or_else(|| param.get_attr(db, &ast, "std_rel"))
                                            .unwrap();
                                        add_diagnostic(
                                            attr.clone(),
                                            &SigmaIgnored { attr, reason },
                                        );
                                        None
                                    }
                                    None => Some(ParamStat { std: s, rel, uniform }),
                                }
                            }
                            _ => {
                                if let (None, Some(attr)) = (sigma, dist_attr) {
                                    add_diagnostic(attr.clone(), &DistWithoutSigma { attr });
                                }
                                None
                            }
                        }
                    };

                    params.insert(
                        param,
                        ParamInfo {
                            name: declarations.to_path(name),
                            alias: Vec::new(),
                            unit: units,
                            description: desc,
                            group,
                            is_instance,
                            stat,
                        },
                    );
                }

                // Enhancement-414: an alias that resolves to NOTHING is a cycle
                // (`aliasparam pp = pp;`), which `hir_def` now reports as a real error.
                // This used to `unwrap()` it, so the compiler aborted with a crash dump
                // and no diagnostic; skip it and let the diagnostic do the talking.
                ScopeDef::AliasParameter(alias) => match alias.resolve(db) {
                    Some(ResolvedAliasParameter::Parameter(param)) => {
                        params.entry(param).or_default().alias.push(declarations.to_path(name))
                    }
                    Some(ResolvedAliasParameter::SystemParameter(sys_fun)) => {
                        sys_fun_alias.entry(sys_fun).or_default().push(declarations.to_path(name))
                    }
                    None => (),
                },

                _ => (),
            }
        }

        ModuleInfo { module, params, op_vars, sys_fun_alias }
    }
}

struct IllegalAttr {
    attr: ast::Attr,
}

impl Diagnostic for IllegalAttr {
    fn build_report(&self, root_file: FileId, db: &dyn BaseDB) -> Report {
        let FileSpan { range, file } = db
            .parse(root_file)
            .to_file_span(self.attr.syntax().text_range(), &db.sourcemap(root_file));
        Report::error()
            .with_message(format!(
                "illegal expression supplied to '{}' attribute; expected a string literal",
                self.attr.name().unwrap(),
            ))
            .with_labels(vec![Label {
                style: LabelStyle::Primary,
                file_id: file,
                range: range.into(),
                message: "expected a string literal".to_owned(),
            }])
    }
}

/// `(* std=... *)` / `(* std_rel=... *)` whose value is not a non-negative
/// real literal. The draw machinery needs one number known at compile time;
/// a negative sigma has no meaning for either distribution.
struct IllegalSigmaAttr {
    attr: ast::Attr,
}

impl Diagnostic for IllegalSigmaAttr {
    fn build_report(&self, root_file: FileId, db: &dyn BaseDB) -> Report {
        let FileSpan { range, file } = db
            .parse(root_file)
            .to_file_span(self.attr.syntax().text_range(), &db.sourcemap(root_file));
        Report::error()
            .with_message(format!(
                "illegal expression supplied to '{}' attribute; expected a non-negative real \
                 literal (a quoted number such as \"25.0\" is also accepted)",
                self.attr.name().unwrap(),
            ))
            .with_labels(vec![Label {
                style: LabelStyle::Primary,
                file_id: file,
                range: range.into(),
                message: "expected a non-negative real literal".to_owned(),
            }])
    }
}

/// Both `std` and `std_rel` on one parameter: two different sigmas for one
/// quantity. The absolute one wins so the model still compiles predictably.
struct SigmaConflict {
    attr: ast::Attr,
}

impl Diagnostic for SigmaConflict {
    fn build_report(&self, root_file: FileId, db: &dyn BaseDB) -> Report {
        let FileSpan { range, file } = db
            .parse(root_file)
            .to_file_span(self.attr.syntax().text_range(), &db.sourcemap(root_file));
        Report::error()
            .with_message(
                "'std' and 'std_rel' attributes are mutually exclusive; \
                 the absolute 'std' is used"
                    .to_owned(),
            )
            .with_labels(vec![Label {
                style: LabelStyle::Primary,
                file_id: file,
                range: range.into(),
                message: "conflicts with the 'std' attribute on this parameter".to_owned(),
            }])
    }
}

/// `(* std=... *)` on a parameter the simulator cannot vary (non-real type,
/// array, or localparam) -- named and dropped rather than silently exported.
struct SigmaIgnored {
    attr: ast::Attr,
    reason: &'static str,
}

impl Diagnostic for SigmaIgnored {
    fn build_report(&self, root_file: FileId, db: &dyn BaseDB) -> Report {
        let FileSpan { range, file } = db
            .parse(root_file)
            .to_file_span(self.attr.syntax().text_range(), &db.sourcemap(root_file));
        Report::warning()
            .with_message(format!(
                "'{}' attribute is ignored: {}",
                self.attr.name().unwrap(),
                self.reason,
            ))
            .with_labels(vec![Label {
                style: LabelStyle::Primary,
                file_id: file,
                range: range.into(),
                message: "this parameter will not vary under .option osdimc".to_owned(),
            }])
    }
}

/// `(* dist=... *)` without any sigma: the distribution of nothing.
struct DistWithoutSigma {
    attr: ast::Attr,
}

impl Diagnostic for DistWithoutSigma {
    fn build_report(&self, root_file: FileId, db: &dyn BaseDB) -> Report {
        let FileSpan { range, file } = db
            .parse(root_file)
            .to_file_span(self.attr.syntax().text_range(), &db.sourcemap(root_file));
        Report::warning()
            .with_message(
                "'dist' attribute has no effect without a 'std' or 'std_rel' attribute"
                    .to_owned(),
            )
            .with_labels(vec![Label {
                style: LabelStyle::Primary,
                file_id: file,
                range: range.into(),
                message: "no sigma is declared for this parameter".to_owned(),
            }])
    }
}

/// Bug-hunt F16: `(* std= / std_rel= / dist= *)` on something that is not a
/// parameter -- statistics declared where nothing reads them.
struct StatOnNonParam {
    attr: ast::Attr,
}

impl Diagnostic for StatOnNonParam {
    fn build_report(&self, root_file: FileId, db: &dyn BaseDB) -> Report {
        let FileSpan { range, file } = db
            .parse(root_file)
            .to_file_span(self.attr.syntax().text_range(), &db.sourcemap(root_file));
        Report::warning()
            .with_message(format!(
                "'{}' attribute is ignored here: statistics attributes apply to parameters",
                self.attr.name().unwrap(),
            ))
            .with_labels(vec![Label {
                style: LabelStyle::Primary,
                file_id: file,
                range: range.into(),
                message: "this declaration is not a parameter; nothing will vary under .option osdimc"
                    .to_owned(),
            }])
    }
}

/// `(* dist="..." *)` naming a distribution the draw machinery does not have.
struct UnknownDist {
    expr: Expr,
    found: String,
}

impl Diagnostic for UnknownDist {
    fn build_report(&self, root_file: FileId, db: &dyn BaseDB) -> Report {
        let FileSpan { range, file } = db.parse(root_file).to_file_span(
            self.expr.syntax().parent().unwrap().text_range(),
            &db.sourcemap(root_file),
        );
        Report::warning()
            .with_message(format!(
                "unknown distribution \"{}\"; expected \"gauss\" or \"uniform\" (\"gauss\" is used)",
                self.found
            ))
            .with_labels(vec![Label {
                style: LabelStyle::Primary,
                file_id: file,
                range: range.into(),
                message: "unknown distribution".to_owned(),
            }])
    }
}

struct UnknownType<'a> {
    expr: Expr,
    found: &'a str,
}

impl Diagnostic for UnknownType<'_> {
    fn build_report(&self, root_file: FileId, db: &dyn BaseDB) -> Report {
        let FileSpan { range, file } = db.parse(root_file).to_file_span(
            self.expr.syntax().parent().unwrap().text_range(),
            &db.sourcemap(root_file),
        );
        Report::warning()
            .with_message(format!(
                "unknown type \"{}\" expected \"model\" or \"instance\"",
                self.found
            ))
            .with_labels(vec![Label {
                style: LabelStyle::Primary,
                file_id: file,
                range: range.into(),
                message: "unknown type".to_owned(),
            }])
    }
}

#[derive(Debug, Clone, PartialEq, Default)]
pub struct ParamInfo {
    pub name: SmolStr,
    pub alias: Vec<SmolStr>,
    pub unit: String,
    pub description: String,
    pub group: String,
    pub is_instance: bool,
    /// `(* std= / std_rel= / dist= *)` statistics for `.option osdimc`
    pub stat: Option<ParamStat>,
}

/// Declared statistics of a parameter, exported through the OSDI
/// `OSDI_STAT_PARAM_INFOS` side-table for the simulator's Monte-Carlo draws.
#[derive(Debug, Clone, Copy, PartialEq)]
pub struct ParamStat {
    /// standard deviation (gauss) or half-width (uniform); a fraction of the
    /// resolved nominal when `rel` is set
    pub std: f64,
    pub rel: bool,
    /// false = gauss (the default)
    pub uniform: bool,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct OpVar {
    pub unit: String,
    pub description: String,
}


/// Enhancement-406: report a branch whose flow is probed, which nothing contributes to,
/// and whose node pair IS driven through a different branch.
///
/// Needs no MIR: the two facts are both in the HIR, and a branch appearing among the flow
/// probes but nowhere in the contribution map is exactly the probe-only case the DAE would
/// later hand an ideal ammeter (E-36). Doing it here also means the report can point at the
/// probe itself rather than at the correct code around it.
fn check_probe_only_branch_shorts(
    db: &CompilationDB,
    cu: CompilationUnit,
    module: Module,
    sink: &mut ConsoleSink,
) {
    let lint = hir::lints::builtin::probe_only_branch_short;
    let probes = module.flow_probe_sites(db, lint);
    if probes.is_empty() {
        return;
    }
    let contributions = module.contribution_sites(db, lint);

    let spell = |branch: hir::BranchWrite| -> String {
        match branch {
            hir::BranchWrite::Named(br) => br.name(db),
            hir::BranchWrite::Unnamed { hi, lo: Some(lo) } => {
                format!("({},{})", hi.name(db), lo.name(db))
            }
            hir::BranchWrite::Unnamed { hi, lo: None } => format!("({})", hi.name(db)),
        }
    };

    let mut reported: Vec<hir::BranchWrite> = Vec::new();
    for probe in &probes {
        // a branch that IS contributed to is not probe-only; nothing is inserted for it
        if !contributions.get(db, probe.branch).is_empty() {
            continue;
        }
        // ... and a probe-only branch nothing else drives is the deliberate ammeter idiom
        let Some((driven, sites)) = contributions.other_branch_over_same_nodes(db, probe.branch)
        else {
            continue;
        };
        if reported.contains(&probe.branch) {
            continue;
        }
        reported.push(probe.branch);

        let (hi, lo) = probe.branch.nodes(db);
        let nodes = match lo {
            Some(lo) => format!("({},{})", hi.name(db), lo.name(db)),
            None => format!("({})", hi.name(db)),
        };
        let diag = ProbeOnlyBranchShort {
            probed: spell(probe.branch),
            driven: spell(driven),
            nodes,
            module: module.name(db),
            probes: probes.iter().filter(|p| p.branch == probe.branch).cloned().collect(),
            sites: sites.to_vec(),
        };
        sink.add_diagnostic(&diag, cu.root_file(), db);
    }
}
