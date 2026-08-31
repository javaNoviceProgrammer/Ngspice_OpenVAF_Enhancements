use std::hash::BuildHasherDefault;

use ahash::AHashSet;
use hir::diagnostics::{BaseDB, ConsoleSink, Diagnostic, FileId, Label, LabelStyle, Report};
use hir::{
    CompilationDB, CompilationUnit, DiagnosticSink, Module, ParamSysFun, Parameter,
    ResolvedAliasParameter, ScopeDef, Variable,
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

                    params.insert(
                        param,
                        ParamInfo {
                            name: declarations.to_path(name),
                            alias: Vec::new(),
                            unit: units,
                            description: desc,
                            group,
                            is_instance,
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

#[derive(Debug, Clone, PartialEq, Eq, Default)]
pub struct ParamInfo {
    pub name: SmolStr,
    pub alias: Vec<SmolStr>,
    pub unit: String,
    pub description: String,
    pub group: String,
    pub is_instance: bool,
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
