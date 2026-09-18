use std::hash::BuildHasherDefault;

use ahash::AHashSet;
use hir::diagnostics::{BaseDB, ConsoleSink, Diagnostic, FileId, Label, LabelStyle, Report};
use hir::lints::{builtin::instance_dependent_parameter, Lint, LintSrc};
use hir::{
    Body, CompilationDB, CompilationUnit, DiagnosticSink, ExprId, Function, Module, ParamSysFun,
    Parameter, ResolvedAliasParameter, ScopeDef, Type, Variable,
};
use indexmap::IndexMap;
use rustc_hash::FxHasher;
use smol_str::SmolStr;
use syntax::ast::{self, Expr};
use syntax::sourcemap::FileSpan;
use syntax::{AstNode, TextRange};

use crate::diagnostics::{
    DollarInExportedName, ExportedName, ExportedNameCollision, ExportedOther, ProbeOnlyBranchShort,
};

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
        // Enhancement-643: the paramset's own parameters are the ones declared
        // inside its `paramset ... endparamset` (LRM 6.4.2)
        let paramset_range = module.paramset_decl_range(db);

        check_probe_only_branch_shorts(db, cu, module, sink);

        // Enhancement-546: the parameters the author classified `(* type="model" *)`
        // in so many words -- a promotion of one of those is worth its own wording.
        let mut explicit_model: AHashSet<Parameter> = AHashSet::new();

        let mut resolved_attrs = AHashSet::new();
        // Enhancement-652 (hunt F8): the alias items themselves, for their spans,
        // and the `$`-named variables that are not exported
        let mut alias_decls: Vec<(SmolStr, hir::AliasParameter, Parameter)> = Vec::new();
        let mut dollar_opvars: Vec<(Variable, String)> = Vec::new();
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
                    for stat_name in ["std", "std_rel", "dist", "corner"] {
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
                    // Book audit (paramsets), LRM 6.4.3: a module output variable a
                    // paramset redeclares lives in the twin as `name$<paramset>`; the
                    // paramset's own is "the value reported for any instance that
                    // uses the paramset", and one without a description makes the
                    // module's unavailable -- so the hidden one is not exported.
                    if name.contains('$') {
                        // Enhancement-652 (hunt F8): a `$` the AUTHOR wrote is a
                        // variable that silently never reaches the simulator;
                        // reported after the loop (`add_diagnostic` holds the sink)
                        if !is_paramset_twin_name(db, cu, &name) {
                            dollar_opvars.push((var, name.to_string()));
                        }
                        continue;
                    }
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
                    // Enhancement-644 (LRM 6.4, IHP hunt C1): a paramset's own
                    // parameter is what an INSTANCE of the paramset sets --
                    // `rsil #(.l(0.5u), .w(0.5u)) r1(...)` in the LRM's world,
                    // `n1 a b rsil l=0.5u w=0.5u` in SPICE's -- so it is an
                    // instance parameter by default (the `.model` card gives
                    // the instances' defaults, as for any instance parameter).
                    // It used to be model-card-only, which no device library
                    // can live with. `(* type="model" *)` keeps one on the card
                    // alone; a pass-through target-module parameter is what
                    // its own declaration says.
                    let paramset_own = paramset_range
                        .is_some_and(|r| r.contains_range(param.text_range(db)));
                    let is_instance = match type_.as_deref() {
                        Some("instance") => true,
                        Some("model") => {
                            explicit_model.insert(param);
                            false
                        }
                        None => paramset_own && !param.is_local(db),
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

                        // Enhancement-554: `dist` names gauss (the default),
                        // uniform, lognormal (alias lnorm: the Gaussian
                        // coordinate is multiplicative, value = nominal *
                        // exp(s z), with `std_rel` the sigma of the logarithm
                        // and an absolute `std` converted at the nominal) or
                        // tgauss (a Gaussian confined to `trunc` sigmas, 3 by
                        // default). `trunc=<sigmas>` composes with gauss and
                        // lognormal; a uniform is bounded already.
                        let dist_attr = param.get_attr(db, &ast, "dist");
                        let (uniform, lognormal, trunc_default) =
                            dist_attr.as_ref().map_or((false, false, 0.0), |attr| {
                                let lit = attr.val().and_then(|e| e.as_str_literal());
                                match lit.as_deref() {
                                    Some("gauss") | Some("gaussian") | Some("normal") => {
                                        (false, false, 0.0)
                                    }
                                    Some("uniform") => (true, false, 0.0),
                                    Some("lognormal") | Some("lnorm") | Some("lognorm") => {
                                        (false, true, 0.0)
                                    }
                                    Some("tgauss") | Some("truncgauss") | Some("truncated") => {
                                        (false, false, 3.0)
                                    }
                                    Some(found) => {
                                        add_diagnostic(
                                            attr.clone(),
                                            &UnknownDist {
                                                expr: attr.val().unwrap(),
                                                found: found.to_owned(),
                                            },
                                        );
                                        (false, false, 0.0)
                                    }
                                    None => {
                                        add_diagnostic(
                                            attr.clone(),
                                            &IllegalAttr { attr: attr.clone() },
                                        );
                                        (false, false, 0.0)
                                    }
                                }
                            });

                        let trunc_attr = param.get_attr(db, &ast, "trunc");
                        let trunc = match &trunc_attr {
                            Some(attr) => {
                                let expr = attr.val();
                                let val = expr
                                    .as_ref()
                                    .and_then(|e| e.as_constexprval())
                                    .and_then(|v| v.as_real())
                                    .or_else(|| {
                                        expr.as_ref()
                                            .and_then(|e| e.as_str_literal())
                                            .and_then(|lit| lit.trim().parse::<f64>().ok())
                                            .filter(|v| v.is_finite())
                                    });
                                match val {
                                    Some(v) if v > 0.0 && v.is_finite() => {
                                        if uniform {
                                            add_diagnostic(
                                                attr.clone(),
                                                &TruncIgnored { attr: attr.clone() },
                                            );
                                            0.0
                                        } else {
                                            v
                                        }
                                    }
                                    _ => {
                                        add_diagnostic(
                                            attr.clone(),
                                            &IllegalTruncAttr { attr: attr.clone() },
                                        );
                                        trunc_default
                                    }
                                }
                            }
                            None => trunc_default,
                        };

                        let (sigma, rel) = match (std, std_rel) {
                            // both given is diagnosed above; the absolute one wins
                            (Some(s), _) => (Some(s), false),
                            (None, Some(s)) => (Some(s), true),
                            (None, None) => (None, false),
                        };

                        // Enhancement-634 (hunt D5): an attribute given more
                        // than once took the first in silence
                        for attr_name in ["std", "std_rel", "dist", "trunc"] {
                            let n = param.attr_count(db, &ast, attr_name);
                            if n > 1 {
                                let attr = param.get_attr(db, &ast, attr_name).unwrap();
                                add_diagnostic(
                                    attr.clone(),
                                    &DuplicateStatAttr { attr, name: attr_name, count: n },
                                );
                            }
                        }
                        // Enhancement-634 (hunt D21): statistics on a parameter
                        // whose `from` is a discrete set -- a draw around a
                        // member is off the set on nearly every trial
                        if sigma.is_some() && param.from_is_discrete_set(db) {
                            let attr = param
                                .get_attr(db, &ast, "std")
                                .or_else(|| param.get_attr(db, &ast, "std_rel"))
                                .unwrap();
                            add_diagnostic(
                                attr.clone(),
                                &StatOnDiscreteSet {
                                    attr,
                                    name: name.to_string(),
                                    range: param.bounds_source(db),
                                },
                            );
                        }

                        // Enhancement-620 (hunt F16): a zero sigma, and a
                        // relative sigma on a default of 0, are said here --
                        // both draw exactly 0 on every trial, in silence
                        if let Some(0.0) = sigma {
                            let attr = param
                                .get_attr(db, &ast, "std")
                                .or_else(|| param.get_attr(db, &ast, "std_rel"))
                                .unwrap();
                            add_diagnostic(attr.clone(), &ZeroSigma { attr });
                        } else if rel && sigma.is_some() && param.default_const(db) == Some(0.0) {
                            let attr = param.get_attr(db, &ast, "std_rel").unwrap();
                            add_diagnostic(
                                attr.clone(),
                                &RelSigmaOnZeroDefault { attr, name: name.to_string() },
                            );
                        }

                        match sigma {
                            // a zero sigma declares statistics with no width;
                            // exporting it would only produce exact-zero draws
                            Some(s) if s > 0.0 => {
                                // Only a scalar real, non-local parameter can be
                                // varied by the simulator: the draw path writes a
                                // double through the ordinary parameter setter,
                                // and a localparam refuses netlist writes by
                                // design (E-93).
                                // Enhancement-640: the wording used to say "only a
                                // scalar real parameter", but an array's elements
                                // are real parameters and each carries its own
                                // statistics; what cannot is a non-real type.
                                let reason = if param.ty(db) != Type::Real {
                                    Some(match param.ty(db) {
                                        Type::Integer => {
                                            "statistics need a real parameter; this one is an integer"
                                        }
                                        Type::String => {
                                            "statistics need a real parameter; this one is a string"
                                        }
                                        _ => "statistics need a real parameter; this one is not real",
                                    })
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
                                    None => Some(ParamStat {
                                        std: s,
                                        rel,
                                        uniform,
                                        lognormal,
                                        trunc,
                                        gated: false,
                                    }),
                                }
                            }
                            _ => {
                                if sigma.is_none() {
                                    if let Some(attr) = dist_attr {
                                        add_diagnostic(
                                            attr.clone(),
                                            &DistWithoutSigma { attr, name: "dist" },
                                        );
                                    }
                                    if let Some(attr) = trunc_attr {
                                        add_diagnostic(
                                            attr.clone(),
                                            &DistWithoutSigma { attr, name: "trunc" },
                                        );
                                    }
                                }
                                None
                            }
                        }
                    };

                    // Enhancement-654: `(* corner="ss=115, ff=-10%, sf=+3sigma" *)`
                    // names the parameter's position at each process corner
                    // (a project extension beside the statistics above). One
                    // string attribute, `name=value` entries separated by
                    // commas and/or whitespace; a value is a real literal with
                    // an optional scale factor (an absolute value), such a
                    // number followed by `%` (a fraction of the nominal) or
                    // by `sigma` (a multiple of the declared standard
                    // deviation, so it needs `std`/`std_rel`). Names are
                    // folded to lower case, as ngspice folds a deck. The
                    // entries ride the OSDI_CORNER_* side-table to the
                    // simulator, whose `.option corner=<name>` applies them
                    // (ngspice's osdisetup.c).
                    let corners: Vec<ParamCorner> = {
                        let n = param.attr_count(db, &ast, "corner");
                        if n > 1 {
                            let attr = param.get_attr(db, &ast, "corner").unwrap();
                            add_diagnostic(
                                attr.clone(),
                                &DuplicateStatAttr { attr, name: "corner", count: n },
                            );
                        }
                        match param.get_attr(db, &ast, "corner") {
                            None => Vec::new(),
                            Some(attr) => {
                                let lit = attr.val().and_then(|e| e.as_str_literal());
                                let reason = if param.ty(db) != Type::Real {
                                    Some(match param.ty(db) {
                                        Type::Integer => {
                                            "a corner needs a real parameter; this one is an integer"
                                        }
                                        Type::String => {
                                            "a corner needs a real parameter; this one is a string"
                                        }
                                        _ => "a corner needs a real parameter; this one is not real",
                                    })
                                } else if param.is_local(db) {
                                    Some("a localparam cannot be set by the simulator")
                                } else {
                                    None
                                };
                                match (lit, reason) {
                                    (None, _) => {
                                        add_diagnostic(attr.clone(), &IllegalCornerAttr { attr });
                                        Vec::new()
                                    }
                                    (Some(_), Some(reason)) => {
                                        add_diagnostic(
                                            attr.clone(),
                                            &CornerIgnored { attr, reason },
                                        );
                                        Vec::new()
                                    }
                                    (Some(lit), None) => {
                                        let mut out: Vec<ParamCorner> = Vec::new();
                                        // (folded name, name as written)
                                        let mut seen: Vec<(String, String)> = Vec::new();
                                        for item in parse_corner_list(&lit) {
                                            match item {
                                                Err((entry, why)) => add_diagnostic(
                                                    attr.clone(),
                                                    &CornerEntryMalformed {
                                                        attr: attr.clone(),
                                                        entry,
                                                        why,
                                                    },
                                                ),
                                                Ok((written, kind, value)) => {
                                                    let folded = written.to_ascii_lowercase();
                                                    // Enhancement-662 (hunt F3): the nominal's
                                                    // spellings can never be selected -- ngspice's
                                                    // `.option corner=tt` (nom, nominal) IS the
                                                    // nominal -- and the loops ran the nominal
                                                    // twice under two names
                                                    if matches!(
                                                        folded.as_str(),
                                                        "tt" | "nom" | "nominal"
                                                    ) {
                                                        add_diagnostic(
                                                            attr.clone(),
                                                            &CornerNameReserved {
                                                                attr: attr.clone(),
                                                                name: written,
                                                            },
                                                        );
                                                        continue;
                                                    }
                                                    if let Some((_, first)) =
                                                        seen.iter().find(|(f, _)| *f == folded)
                                                    {
                                                        add_diagnostic(
                                                            attr.clone(),
                                                            &CornerNameTwice {
                                                                attr: attr.clone(),
                                                                first: first.clone(),
                                                                second: written,
                                                            },
                                                        );
                                                        continue;
                                                    }
                                                    if kind == CornerKind::Sigma && stat.is_none()
                                                    {
                                                        add_diagnostic(
                                                            attr.clone(),
                                                            &CornerSigmaWithoutStd {
                                                                attr: attr.clone(),
                                                                name: written,
                                                            },
                                                        );
                                                        continue;
                                                    }
                                                    if kind == CornerKind::Relative
                                                        && param.default_const(db) == Some(0.0)
                                                    {
                                                        add_diagnostic(
                                                            attr.clone(),
                                                            &RelCornerOnZeroDefault {
                                                                attr: attr.clone(),
                                                                name: written.clone(),
                                                            },
                                                        );
                                                    }
                                                    seen.push((folded.clone(), written));
                                                    out.push(ParamCorner {
                                                        name: folded.into(),
                                                        kind,
                                                        value,
                                                    });
                                                }
                                            }
                                        }
                                        out
                                    }
                                }
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
                            instance_bounds: false,
                            given_tested: false,
                            dynamic_bounds: false,
                            stat,
                            corners,
                            range_text: param.bounds_source(db),
                            default_value: param.default_const(db),
                            paramset_own,
                        },
                    );
                }

                // Enhancement-414: an alias that resolves to NOTHING is a cycle
                // (`aliasparam pp = pp;`), which `hir_def` now reports as a real error.
                // This used to `unwrap()` it, so the compiler aborted with a crash dump
                // and no diagnostic; skip it and let the diagnostic do the talking.
                ScopeDef::AliasParameter(alias) => match alias.resolve(db) {
                    Some(ResolvedAliasParameter::Parameter(param)) => {
                        let path = declarations.to_path(name);
                        alias_decls.push((path.clone(), alias, param));
                        params.entry(param).or_default().alias.push(path)
                    }
                    Some(ResolvedAliasParameter::SystemParameter(sys_fun)) => {
                        sys_fun_alias.entry(sys_fun).or_default().push(declarations.to_path(name))
                    }
                    None => (),
                },

                _ => (),
            }
        }

        promote_instance_dependent(db, cu, &mut params, &explicit_model, sink);

        // Enhancement-652 (hunt F8): after promotion, since it decides which
        // namespace a parameter lands in
        for (var, name) in dollar_opvars {
            sink.add_diagnostic(
                &DollarInExportedName {
                    module: module.name(db),
                    decl: ExportedName {
                        name,
                        kind: "operating-point variable",
                        range: var.text_range(db),
                        lint_src: var.lint_src(db),
                    },
                },
                cu.root_file(),
                db,
            );
        }
        check_exported_names(db, cu, module, &params, &alias_decls, &op_vars, sink);

        // Enhancement-555: which parameters the module tests with $param_given
        let tested = module_given_tests(db, module);
        for (param, info) in params.iter_mut() {
            info.given_tested = tested.contains(param);
            if let Some(stat) = info.stat.as_mut() {
                stat.gated = info.given_tested;
            }
        }

        ModuleInfo { module, params, op_vars, sys_fun_alias }
    }
}

/// Enhancement-652 (hunt F8): is `name` one of the `name$<paramset>` twins
/// elaboration synthesizes (LRM 6.4.3), rather than a `$` the author wrote?
fn is_paramset_twin_name(db: &CompilationDB, cu: CompilationUnit, name: &str) -> bool {
    let Some((_, suffix)) = name.rsplit_once('$') else { return false };
    cu.modules(db).iter().any(|m| m.name(db) == suffix)
}

/// Enhancement-652 (hunt F8): the names a module exports, judged the way
/// ngspice will look them up.
///
/// Verilog-A is case-sensitive; ngspice folds every name to lower case and
/// keeps two flat tables per device: the instance's parameters, their aliases
/// and the operating-point variables (with the simulator's own `m`/`temp`/
/// `dtemp`/`dt` and the terminal currents Enhancement-394 synthesizes), and
/// the model's parameters and aliases. Two entries that fold to one name are
/// one name to `@inst[name]`, `show` and `alter`, and the first in the table
/// wins: a parameter over a variable, an earlier declaration over a later
/// one, ngspice's own `m` over a variable, a variable over a synthesized
/// terminal current. ngspice warns at load time (E-335/E-396); the author
/// compiling the model never saw it, and L029 (`reserved_parameter_name`)
/// covered parameters only. A parameter and its own aliases are one entry
/// (the simulator routes them to one id). Model parameters and operating-point
/// variables live in different tables and are both reachable, so a case twin
/// across those two is not reported.
///
/// A `$` in an exported name is reported beside it: legal Verilog-A, but
/// ngspice's expression parser reads `$b` in `@inst[a$b]` as a shell
/// variable, so a parameter with one is write-only.
fn check_exported_names(
    db: &CompilationDB,
    cu: CompilationUnit,
    module: Module,
    params: &IndexMap<Parameter, ParamInfo, BuildHasherDefault<FxHasher>>,
    alias_decls: &[(SmolStr, hir::AliasParameter, Parameter)],
    op_vars: &IndexMap<Variable, OpVar, BuildHasherDefault<FxHasher>>,
    sink: &mut ConsoleSink,
) {
    let module_name = module.name(db);
    let root = cu.root_file();
    // (entry, owner): entries of one parameter share an owner and never collide
    let mut instance: Vec<(ExportedName, usize)> = Vec::new();
    let mut model: Vec<(ExportedName, usize)> = Vec::new();
    for (owner, (param, info)) in params.iter().enumerate() {
        let kind = if info.is_instance { "instance parameter" } else { "model parameter" };
        let ns = if info.is_instance { &mut instance } else { &mut model };
        ns.push((
            ExportedName {
                name: info.name.to_string(),
                kind,
                range: param.text_range(db),
                lint_src: param.lint_src(db),
            },
            owner,
        ));
        for (alias_name, alias, _) in alias_decls.iter().filter(|(_, _, target)| target == param) {
            ns.push((
                ExportedName {
                    name: alias_name.to_string(),
                    kind: "alias",
                    range: alias.text_range(db),
                    lint_src: alias.lint_src(db),
                },
                owner,
            ));
        }
    }
    let first_opvar = params.len();
    for (i, (var, _)) in op_vars.iter().enumerate() {
        instance.push((
            ExportedName {
                name: var.name(db).to_string(),
                kind: "operating-point variable",
                range: var.text_range(db),
                lint_src: var.lint_src(db),
            },
            first_opvar + i,
        ));
    }

    // two declared names the simulator cannot tell apart
    for ns in [&instance, &model] {
        for (i, (decl, owner)) in ns.iter().enumerate() {
            let twin = ns[..i]
                .iter()
                .find(|(other, o)| o != owner && other.name.eq_ignore_ascii_case(&decl.name));
            if let Some((other, _)) = twin {
                sink.add_diagnostic(
                    &ExportedNameCollision {
                        module: module_name.clone(),
                        decl: decl.clone(),
                        other: ExportedOther::Declared(other.clone()),
                        decl_wins: false,
                    },
                    root,
                    db,
                );
            }
        }
    }

    // ngspice's own instance names, over an operating-point variable (a
    // parameter of that name is L029's, and `dtemp`/`temp`/`m` on a parameter
    // are routed to it on purpose, E-396)
    const RESERVED: &[&str] = &["m", "temp", "dtemp", "dt"];
    for (decl, _) in instance.iter().filter(|(d, _)| d.kind == "operating-point variable") {
        if let Some(reserved) = RESERVED.iter().find(|r| r.eq_ignore_ascii_case(&decl.name)) {
            sink.add_diagnostic(
                &ExportedNameCollision {
                    module: module_name.clone(),
                    decl: decl.clone(),
                    other: ExportedOther::Builtin {
                        name: (*reserved).to_owned(),
                        what: "ngspice's own instance parameter",
                    },
                    decl_wins: false,
                },
                root,
                db,
            );
        }
    }

    // the terminal currents ngspice synthesizes: `i_<port>`, and `i` for a
    // two-terminal device unless the model owns `i` (routed, E-644)
    let ports = module.ports(db);
    let mut currents: Vec<String> = ports.iter().map(|p| format!("i_{}", p.name(db))).collect();
    if ports.len() == 2 {
        currents.push("i".to_owned());
    }
    for (decl, _) in &instance {
        let Some(current) = currents.iter().find(|c| c.eq_ignore_ascii_case(&decl.name)) else {
            continue;
        };
        if current == "i" && decl.kind != "operating-point variable" {
            continue;
        }
        sink.add_diagnostic(
            &ExportedNameCollision {
                module: module_name.clone(),
                decl: decl.clone(),
                other: ExportedOther::Builtin {
                    name: current.clone(),
                    what: "the terminal current ngspice synthesizes (E-394)",
                },
                decl_wins: true,
            },
            root,
            db,
        );
    }

    // a `$` in a name the simulator is meant to read back
    for (decl, _) in instance.iter().chain(&model) {
        if decl.name.contains('$') && !is_paramset_twin_name(db, cu, &decl.name) {
            sink.add_diagnostic(
                &DollarInExportedName { module: module_name.clone(), decl: decl.clone() },
                root,
                db,
            );
        }
    }
}

/// Enhancement-546 (compiler hunt F2): a parameter whose default reads an
/// instance parameter is itself per instance, and a range that reads one is
/// judged per instance.
///
/// The model/instance split (`(* type="instance" *)`) is an OpenVAF convention
/// the LRM does not have: in the language every parameter belongs to the
/// instance, and a "model" parameter is one the compiler may resolve ONCE per
/// model card because nothing in it varies between the card's instances.
/// `parameter real l = 2*w` with an instance `w` breaks that premise, and the
/// back end did not notice: `setup_model` resolved `l` with the card-level `w`
/// -- the declared default unless the card gave one -- stored the result in the
/// model, and every instance read it; `l/w` came out 2.0 for an instance at
/// `w = 0.5e-6`. A range `from (0:w]` was judged the same way, once, against a
/// `w` no instance need have: an `l` above the instance's `w` ran while a card
/// value above the DEFAULT `w` was refused.
///
/// Two tiers, because the two dependences mean different things:
///
/// * A DEFAULT that reads an instance parameter gives the parameter a value
///   per instance. It is promoted to instance level here, where the whole
///   back end -- instance storage, the per-instance resolution and range check
///   in `setup_instance`, the OSDI parameter table -- follows `is_instance`.
///   The dependency is transitive: through other promoted parameters, through
///   the user functions a default calls (and those call), and through
///   function-local parameters whose defaults are inlined at every use;
///   `$param_given(p)` counts as reading `p`. A promoted parameter stays
///   settable on the `.model` card, like any instance parameter, as the default
///   for the card's instances. The `instance_dependent_parameter` lint names
///   every promotion except that of an untyped `localparam`, where per-instance
///   resolution is the only meaning the declaration could have and nothing
///   settable changes.
///
/// * BOUNDS that read an instance parameter (declared or promoted) do not
///   change what the parameter is: its value is still the card's. The stock
///   CMC models are full of this shape -- BSIM6's `XGL from (-inf:L*LMLT+XL)`,
///   HiSIM2's `LP from [0:L]` -- and promoting them would rewrite the parameter
///   tables of ten industry models for a range check. Such a parameter keeps
///   its level and is marked `instance_bounds`: the model setup skips its
///   given-value range check, and the instance setup judges it with the
///   instance's values -- as part of resolving it, for an instance parameter;
///   as a check alone, for a model parameter (`check_only` in
///   `HirInterner::insert_param_init`). Nothing is said: the classification is
///   unchanged and the judgement lands where the language puts it.
fn promote_instance_dependent(
    db: &CompilationDB,
    cu: CompilationUnit,
    params: &mut IndexMap<Parameter, ParamInfo, BuildHasherDefault<FxHasher>>,
    explicit_model: &AHashSet<Parameter>,
    sink: &mut ConsoleSink,
) {
    // The module-level parameters each parameter's default and bounds read.
    let deps: Vec<(Vec<Parameter>, Vec<Parameter>)> = params
        .keys()
        .map(|&param| {
            let default = module_param_reads(db, param, &[param.default(db)]);
            let bounds = module_param_reads(db, param, &param.bound_exprs(db));
            (default, bounds)
        })
        .collect();

    // Enhancement-555: a bound that reads any module-level parameter may move
    // after the default was declared; the setup judges such a default.
    for i in 0..params.len() {
        params[i].dynamic_bounds = !deps[i].1.is_empty();
    }

    // To a fixpoint: a parameter whose default reads an instance parameter --
    // declared, or promoted by an earlier pass -- is one itself. `via`
    // remembers the read that decided it, for the diagnostic.
    let mut via: Vec<Option<Parameter>> = vec![None; params.len()];
    loop {
        let mut changed = false;
        for i in 0..params.len() {
            if params[i].is_instance {
                continue;
            }
            let hit = deps[i]
                .0
                .iter()
                .find(|dep| params.get(*dep).map_or(false, |info| info.is_instance));
            if let Some(&dep) = hit {
                params[i].is_instance = true;
                via[i] = Some(dep);
                changed = true;
            }
        }
        if !changed {
            break;
        }
    }

    // With the instance set final: the bounds that read one of them.
    for i in 0..params.len() {
        let bounds_read_instance =
            deps[i].1.iter().any(|dep| params.get(dep).map_or(false, |info| info.is_instance));
        params[i].instance_bounds = bounds_read_instance;
    }

    for (i, (param, info)) in params.iter().enumerate() {
        let Some(dep) = via[i] else { continue };
        let explicit = explicit_model.contains(param);
        let is_local = param.is_local(db);
        if is_local && !explicit {
            continue;
        }
        let diag = InstanceDependentParam {
            name: info.name.clone(),
            via: params.get(&dep).map_or_else(|| dep.name(db).into(), |info| info.name.clone()),
            explicit_model: explicit,
            is_local,
            range: param.text_range(db),
            lint_src: param.lint_src(db),
        };
        sink.add_diagnostic(&diag, cu.root_file(), db);
    }
}

/// Enhancement-546: the module-level parameters that the expression trees
/// `roots` of `param`'s init body read -- directly, through the user functions
/// they call (and those call), and through the function-local parameters (LRM
/// 4.7.1) any of that reads, whose own defaults are inlined at every use.
/// Enhancement-555: every parameter the module's analog blocks, or a user
/// function they call (transitively), test with `$param_given`.
fn module_given_tests(db: &CompilationDB, module: Module) -> Vec<Parameter> {
    let mut tests: Vec<Parameter> = Vec::new();
    let mut seen_funcs: AHashSet<Function> = AHashSet::new();
    let mut work: Vec<Body> = vec![module.analog_block(db), module.analog_initial_block(db)];
    while let Some(body) = work.pop() {
        let bodyref = body.borrow();
        for param in bodyref.param_given_tests() {
            if !tests.contains(&param) {
                tests.push(param);
            }
        }
        let (_, called) = bodyref.param_reads_and_calls(None);
        for func in called {
            if seen_funcs.insert(func) {
                work.push(func.body(db));
            }
        }
    }
    tests
}

fn module_param_reads(db: &CompilationDB, param: Parameter, roots: &[ExprId]) -> Vec<Parameter> {
    let mut reads: Vec<Parameter> = Vec::new();
    let mut seen_funcs: AHashSet<Function> = AHashSet::new();
    let mut seen_local: AHashSet<Parameter> = AHashSet::new();
    let mut work: Vec<(Body, Option<Vec<ExprId>>)> = vec![(param.init(db), Some(roots.to_vec()))];
    while let Some((body, roots)) = work.pop() {
        let (read, called) = body.borrow().param_reads_and_calls(roots.as_deref());
        for read in read {
            if read.is_function_local(db) {
                if seen_local.insert(read) {
                    work.push((read.init(db), Some(vec![read.default(db)])));
                }
            } else if !reads.contains(&read) {
                reads.push(read);
            }
        }
        for func in called {
            if seen_funcs.insert(func) {
                work.push((func.body(db), None));
            }
        }
    }
    reads
}

/// Enhancement-546 (compiler hunt F2): a parameter promoted to instance level
/// because its default reads an instance parameter.
struct InstanceDependentParam {
    name: SmolStr,
    via: SmolStr,
    explicit_model: bool,
    is_local: bool,
    range: TextRange,
    lint_src: LintSrc,
}

impl Diagnostic for InstanceDependentParam {
    fn lint(&self, _root_file: FileId, _db: &dyn BaseDB) -> Option<(Lint, LintSrc)> {
        Some((instance_dependent_parameter, self.lint_src))
    }

    fn build_report(&self, root_file: FileId, db: &dyn BaseDB) -> Report {
        let FileSpan { range, file } =
            db.parse(root_file).to_file_span(self.range, &db.sourcemap(root_file));
        let kind = if self.is_local { "localparam" } else { "parameter" };
        let message = if self.explicit_model {
            format!(
                "{kind} '{}' is declared (* type=\"model\" *) but depends on instance \
                 parameter '{}'; it is treated as an instance parameter",
                self.name, self.via
            )
        } else {
            format!(
                "{kind} '{}' depends on instance parameter '{}' and is treated as an \
                 instance parameter",
                self.name, self.via
            )
        };
        let help = if self.is_local {
            "help: nothing settable changes for a localparam; \
             `(* openvaf_allow=\"instance_dependent_parameter\" *)` on the declaration \
             accepts the promotion silently"
        } else {
            "help: declare it `(* type=\"instance\" *)` to state the intent -- it stays \
             settable on the .model card as the default for the card's instances -- or \
             `(* openvaf_allow=\"instance_dependent_parameter\" *)` to accept the \
             promotion silently"
        };
        Report::warning()
            .with_message(message)
            .with_labels(vec![Label {
                style: LabelStyle::Primary,
                file_id: file,
                range: range.into(),
                message: format!(
                    "its default is resolved per instance, with that instance's '{}'",
                    self.via
                ),
            }])
            .with_notes(vec![
                "a model parameter is resolved once per model card, where no instance's \
                 value exists yet; a default that reads an instance parameter has a value \
                 per instance, so the compiler resolves it in the instance setup, with that \
                 instance's values (a range that reads one is judged per instance either \
                 way, without moving the parameter)"
                    .to_owned(),
                help.to_owned(),
            ])
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
/// quantity, refused. (Enhancement-640: the message used to add "the absolute
/// 'std' is used", which an error cannot mean -- the build stops.)
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
                "'std' and 'std_rel' are both given on this parameter; give one of them -- \
                 an absolute sigma (std) or a relative one (std_rel)"
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
    name: &'static str,
}

impl Diagnostic for DistWithoutSigma {
    fn build_report(&self, root_file: FileId, db: &dyn BaseDB) -> Report {
        let FileSpan { range, file } = db
            .parse(root_file)
            .to_file_span(self.attr.syntax().text_range(), &db.sourcemap(root_file));
        Report::warning()
            .with_message(format!(
                "'{}' attribute has no effect without a 'std' or 'std_rel' attribute",
                self.name
            ))
            .with_labels(vec![Label {
                style: LabelStyle::Primary,
                file_id: file,
                range: range.into(),
                message: "no sigma is declared for this parameter".to_owned(),
            }])
    }
}

/// Enhancement-620 (2026-09-12 hunt F16): `(* std=0 *)` / `(* std_rel=0 *)`
/// -- statistics with no width. The parameter is not exported (a zero sigma
/// would only produce exact-zero draws) and the deck would never learn why
/// it does not vary; say so at compile time.
struct ZeroSigma {
    attr: ast::Attr,
}

impl Diagnostic for ZeroSigma {
    fn build_report(&self, root_file: FileId, db: &dyn BaseDB) -> Report {
        let FileSpan { range, file } = db
            .parse(root_file)
            .to_file_span(self.attr.syntax().text_range(), &db.sourcemap(root_file));
        Report::warning()
            .with_message(format!(
                "'{}' attribute is 0: the parameter declares statistics with no width and \
                 will not vary under .option osdimc; give it a sigma or drop the attribute",
                self.attr.name().unwrap(),
            ))
            .with_labels(vec![Label {
                style: LabelStyle::Primary,
                file_id: file,
                range: range.into(),
                message: "a zero sigma is not exported".to_owned(),
            }])
    }
}

/// Enhancement-634 (2026-09-12 hunt D5): a statistics attribute given more
/// than once on one parameter -- `(* std=25.0, std=30.0 *)` -- took the
/// last in silence.
struct DuplicateStatAttr {
    attr: ast::Attr,
    name: &'static str,
    count: usize,
}

impl Diagnostic for DuplicateStatAttr {
    fn build_report(&self, root_file: FileId, db: &dyn BaseDB) -> Report {
        let FileSpan { range, file } = db
            .parse(root_file)
            .to_file_span(self.attr.syntax().text_range(), &db.sourcemap(root_file));
        Report::warning()
            .with_message(format!(
                "'{}' is given {} times on this parameter; the last is the one used and the earlier ones are ignored",
                self.name, self.count,
            ))
            .with_labels(vec![Label {
                style: LabelStyle::Primary,
                file_id: file,
                range: range.into(),
                message: "the last one, used".to_owned(),
            }])
    }
}

/// Enhancement-634 (2026-09-12 hunt D21): statistics declared on a parameter
/// whose `from` constraint is a discrete set. A Gaussian or uniform draw
/// around a member of `{1.0, 2.0, 3.0}` lands between the members on nearly
/// every trial and fails the range check; the statistics are exported all
/// the same (the deck may give the value), and the author is told.
struct StatOnDiscreteSet {
    attr: ast::Attr,
    name: String,
    range: String,
}

impl Diagnostic for StatOnDiscreteSet {
    fn build_report(&self, root_file: FileId, db: &dyn BaseDB) -> Report {
        let FileSpan { range, file } = db
            .parse(root_file)
            .to_file_span(self.attr.syntax().text_range(), &db.sourcemap(root_file));
        Report::warning()
            .with_message(format!(
                "'{}' declares statistics on '{}', whose range is the discrete set `{}`: a draw around a member lands off the set and fails the range check on nearly every trial; declare a continuous range, or drop the statistics",
                self.attr.name().unwrap(),
                self.name,
                self.range,
            ))
            .with_labels(vec![Label {
                style: LabelStyle::Primary,
                file_id: file,
                range: range.into(),
                message: "statistics on a discrete-valued parameter".to_owned(),
            }])
    }
}

/// Enhancement-620 (2026-09-12 hunt F16): `(* std_rel=<f> *)` on a parameter
/// whose default is the constant 0 -- a mismatch parameter's natural default.
/// The sigma is relative to the nominal, so with the default in force it is
/// 0 and the parameter never varies; the deck can still give a value, so the
/// statistics are exported and the simulator says so once per parameter when
/// it happens (osdisetup.c).
struct RelSigmaOnZeroDefault {
    attr: ast::Attr,
    name: String,
}

impl Diagnostic for RelSigmaOnZeroDefault {
    fn build_report(&self, root_file: FileId, db: &dyn BaseDB) -> Report {
        let FileSpan { range, file } = db
            .parse(root_file)
            .to_file_span(self.attr.syntax().text_range(), &db.sourcemap(root_file));
        Report::warning()
            .with_message(format!(
                "'std_rel' is relative to the nominal and the default of '{}' is 0: with the \
                 default in force the sigma is 0 and the parameter will not vary under \
                 .option osdimc; give '{}' a value on the card or line, or declare an \
                 absolute 'std'",
                self.name, self.name,
            ))
            .with_labels(vec![Label {
                style: LabelStyle::Primary,
                file_id: file,
                range: range.into(),
                message: "relative to a default of 0".to_owned(),
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
                "'{}' attribute is ignored here: statistics and corner attributes apply to parameters",
                self.attr.name().unwrap(),
            ))
            .with_labels(vec![Label {
                style: LabelStyle::Primary,
                file_id: file,
                range: range.into(),
                message: "this declaration is not a parameter; nothing will vary under .option osdimc or .option corner"
                    .to_owned(),
            }])
    }
}

/// Enhancement-654: `(* corner=... *)` whose value is not a string literal.
struct IllegalCornerAttr {
    attr: ast::Attr,
}

impl Diagnostic for IllegalCornerAttr {
    fn build_report(&self, root_file: FileId, db: &dyn BaseDB) -> Report {
        let FileSpan { range, file } = db
            .parse(root_file)
            .to_file_span(self.attr.syntax().text_range(), &db.sourcemap(root_file));
        Report::error()
            .with_message(
                "illegal expression supplied to 'corner' attribute; expected a string of \
                 name=value entries",
            )
            .with_labels(vec![Label {
                style: LabelStyle::Primary,
                file_id: file,
                range: range.into(),
                message: "expected a string literal".to_owned(),
            }])
            .with_notes(vec![
                "help: `(* corner=\"ss=115, ff=88\" *)` -- entries separated by commas and/or \
                 spaces; a value is a number (2.2n), a percentage of the nominal (+10%) or a \
                 multiple of the declared sigma (-3sigma)"
                    .to_owned(),
            ])
    }
}

/// Enhancement-654: one entry of a `corner` string that does not parse.
struct CornerEntryMalformed {
    attr: ast::Attr,
    entry: String,
    why: &'static str,
}

impl Diagnostic for CornerEntryMalformed {
    fn build_report(&self, root_file: FileId, db: &dyn BaseDB) -> Report {
        let FileSpan { range, file } = db
            .parse(root_file)
            .to_file_span(self.attr.syntax().text_range(), &db.sourcemap(root_file));
        Report::error()
            .with_message(format!("corner entry '{}' is malformed: {}", self.entry, self.why))
            .with_labels(vec![Label {
                style: LabelStyle::Primary,
                file_id: file,
                range: range.into(),
                message: "in this attribute".to_owned(),
            }])
            .with_notes(vec![
                "help: `corner=\"ss=115, ff=-10%, sf=+3sigma\"` -- entries separated by commas \
                 and/or spaces; a value is a number with an optional scale factor, a percentage \
                 of the nominal, or a multiple of the declared sigma"
                    .to_owned(),
            ])
    }
}

/// Enhancement-654: a corner named twice on one parameter -- possibly in two
/// spellings that fold to the same name.
struct CornerNameTwice {
    attr: ast::Attr,
    first: String,
    second: String,
}

impl Diagnostic for CornerNameTwice {
    fn build_report(&self, root_file: FileId, db: &dyn BaseDB) -> Report {
        let FileSpan { range, file } = db
            .parse(root_file)
            .to_file_span(self.attr.syntax().text_range(), &db.sourcemap(root_file));
        let message = if self.first == self.second {
            format!("corner '{}' is given twice on this parameter", self.second)
        } else {
            format!(
                "corners '{}' and '{}' are the same corner: names are folded to lower case, as \
                 ngspice folds a deck",
                self.first, self.second
            )
        };
        Report::error()
            .with_message(message)
            .with_labels(vec![Label {
                style: LabelStyle::Primary,
                file_id: file,
                range: range.into(),
                message: "in this attribute".to_owned(),
            }])
            .with_notes(vec!["help: keep one entry per corner".to_owned()])
    }
}

/// Enhancement-662 (hunt F3): a corner named `tt`, `nom` or `nominal` -- the
/// spellings ngspice reads as the nominal (`.option corner=tt`), so the entry
/// could never be selected, and the `corners`/`autocorner` loops, which put
/// `tt` first and then every declared name, ran the nominal twice.
struct CornerNameReserved {
    attr: ast::Attr,
    name: String,
}

impl Diagnostic for CornerNameReserved {
    fn build_report(&self, root_file: FileId, db: &dyn BaseDB) -> Report {
        let FileSpan { range, file } = db
            .parse(root_file)
            .to_file_span(self.attr.syntax().text_range(), &db.sourcemap(root_file));
        Report::error()
            .with_message(format!(
                "corner '{}' names the nominal: ngspice's `.option corner=tt` (`nom`, `nominal`) \
                 selects the nominal and never reaches this entry",
                self.name
            ))
            .with_labels(vec![Label {
                style: LabelStyle::Primary,
                file_id: file,
                range: range.into(),
                message: "in this attribute".to_owned(),
            }])
            .with_notes(vec![
                "help: the nominal needs no entry -- a parameter sits at its default there; give a \
                 process corner another name (ss, ff, sf, fs, ...)"
                    .to_owned(),
            ])
    }
}

/// Enhancement-654: a corner given in sigmas on a parameter without statistics.
struct CornerSigmaWithoutStd {
    attr: ast::Attr,
    name: String,
}

impl Diagnostic for CornerSigmaWithoutStd {
    fn build_report(&self, root_file: FileId, db: &dyn BaseDB) -> Report {
        let FileSpan { range, file } = db
            .parse(root_file)
            .to_file_span(self.attr.syntax().text_range(), &db.sourcemap(root_file));
        Report::error()
            .with_message(format!(
                "corner '{}' is given in sigmas, but this parameter declares no statistics",
                self.name
            ))
            .with_labels(vec![Label {
                style: LabelStyle::Primary,
                file_id: file,
                range: range.into(),
                message: "no `std` or `std_rel` on this parameter".to_owned(),
            }])
            .with_notes(vec![
                "help: declare `(* std=<sigma> *)` or `(* std_rel=<fraction> *)` beside it, or \
                 give the corner as a value (115) or a percentage of the nominal (+10%)"
                    .to_owned(),
            ])
    }
}

/// Enhancement-654: a `corner` attribute on a parameter the simulator cannot
/// set -- an integer, a string, a localparam.
struct CornerIgnored {
    attr: ast::Attr,
    reason: &'static str,
}

impl Diagnostic for CornerIgnored {
    fn build_report(&self, root_file: FileId, db: &dyn BaseDB) -> Report {
        let FileSpan { range, file } = db
            .parse(root_file)
            .to_file_span(self.attr.syntax().text_range(), &db.sourcemap(root_file));
        Report::warning()
            .with_message(format!("'corner' attribute is ignored: {}", self.reason))
            .with_labels(vec![Label {
                style: LabelStyle::Primary,
                file_id: file,
                range: range.into(),
                message: "no corner is exported for this parameter".to_owned(),
            }])
    }
}

/// Enhancement-654: a percentage corner on a default of 0 moves nothing.
struct RelCornerOnZeroDefault {
    attr: ast::Attr,
    name: String,
}

impl Diagnostic for RelCornerOnZeroDefault {
    fn build_report(&self, root_file: FileId, db: &dyn BaseDB) -> Report {
        let FileSpan { range, file } = db
            .parse(root_file)
            .to_file_span(self.attr.syntax().text_range(), &db.sourcemap(root_file));
        Report::warning()
            .with_message(format!(
                "corner '{}' is a percentage of a default of 0: the parameter is 0 at that \
                 corner unless the netlist gives it",
                self.name
            ))
            .with_labels(vec![Label {
                style: LabelStyle::Primary,
                file_id: file,
                range: range.into(),
                message: "a percentage of the nominal, which defaults to 0".to_owned(),
            }])
            .with_notes(vec!["help: give the corner as an absolute value".to_owned()])
    }
}

/// Enhancement-554: `(* trunc=... *)` that is not a positive real literal.
struct IllegalTruncAttr {
    attr: ast::Attr,
}

impl Diagnostic for IllegalTruncAttr {
    fn build_report(&self, root_file: FileId, db: &dyn BaseDB) -> Report {
        let FileSpan { range, file } = db
            .parse(root_file)
            .to_file_span(self.attr.syntax().text_range(), &db.sourcemap(root_file));
        Report::error()
            .with_message(
                "illegal expression supplied to 'trunc' attribute; expected a positive real \
                 literal, the truncation in sigmas (a quoted number such as \"3.0\" is also \
                 accepted)"
                    .to_owned(),
            )
            .with_labels(vec![Label {
                style: LabelStyle::Primary,
                file_id: file,
                range: range.into(),
                message: "expected a positive real literal".to_owned(),
            }])
    }
}

/// Enhancement-554: `(* trunc=... *)` beside `dist="uniform"`.
struct TruncIgnored {
    attr: ast::Attr,
}

impl Diagnostic for TruncIgnored {
    fn build_report(&self, root_file: FileId, db: &dyn BaseDB) -> Report {
        let FileSpan { range, file } = db
            .parse(root_file)
            .to_file_span(self.attr.syntax().text_range(), &db.sourcemap(root_file));
        Report::warning()
            .with_message(
                "'trunc' attribute has no effect on a uniform distribution (a uniform is \
                 bounded already)"
                    .to_owned(),
            )
            .with_labels(vec![Label {
                style: LabelStyle::Primary,
                file_id: file,
                range: range.into(),
                message: "ignored".to_owned(),
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
                "unknown distribution \"{}\"; expected \"gauss\", \"uniform\", \"lognormal\" \
                 or \"tgauss\" (\"gauss\" is used)",
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
    /// Enhancement-546: the `from`/`exclude` bounds read an instance parameter
    /// (declared or promoted). The model setup skips this parameter's
    /// given-value range check and the instance setup judges it with the
    /// instance's values -- while resolving it, for an instance parameter; as
    /// a check alone, for a model parameter, which keeps its level.
    pub instance_bounds: bool,
    /// Enhancement-555: the module tests `$param_given` on this parameter, so
    /// a machine write that marks it given changes the model's behaviour.
    pub given_tested: bool,
    /// Enhancement-555: the `from`/`exclude` bounds read another parameter,
    /// so the declared default must be judged at setup, when they may have
    /// moved (a constant range is judged at compile time, lint L027, and a
    /// constant default outside it is a deliberate "off" state, E-56).
    pub dynamic_bounds: bool,
    /// `(* std= / std_rel= / dist= *)` statistics for `.option osdimc`
    pub stat: Option<ParamStat>,
    /// Enhancement-654: `(* corner="…" *)` -- the parameter's position at
    /// each named process corner, for `.option corner=<name>`
    pub corners: Vec<ParamCorner>,
    /// Book audit (paramsets), LRM 6.4.2: the default's value when it is a
    /// compile-time constant, for the simulator's paramset selection.
    pub default_value: Option<f64>,
    /// Enhancement-558: the declared range as the source spells it, for the
    /// simulator's out-of-bounds message; empty without a range
    pub range_text: String,
    /// Enhancement-643 (LRM 6.4.2): declared inside the `paramset` this
    /// module is the twin of -- one of the paramset's own parameters, which
    /// are the only ones its selection judges and counts; false for a
    /// target-module parameter passed through, and for a plain module
    pub paramset_own: bool,
}

/// Enhancement-654: one entry of a parameter's `(* corner="…" *)` attribute,
/// exported through the OSDI `OSDI_CORNER_INFOS` side-table for the
/// simulator's `.option corner=<name>`.
#[derive(Debug, Clone, PartialEq)]
pub struct ParamCorner {
    /// the corner's name, folded to lower case (ngspice folds the deck)
    pub name: SmolStr,
    pub kind: CornerKind,
    /// the absolute value; the fraction of the nominal (`+10%` is 0.1); or
    /// the multiple of the declared sigma
    pub value: f64,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum CornerKind {
    Absolute,
    Relative,
    Sigma,
}

/// Enhancement-654: the value of one corner entry -- a real literal with an
/// optional LRM 2.5.1 scale factor, or such a number followed by `%` or by
/// `sigma` (case-insensitive). `inf`, `nan` and anything else is refused.
fn parse_corner_value(text: &str) -> Option<(CornerKind, f64)> {
    let (num, kind) = if let Some(n) = text.strip_suffix('%') {
        (n, CornerKind::Relative)
    } else if text.len() > 5 && text[text.len() - 5..].eq_ignore_ascii_case("sigma") {
        (&text[..text.len() - 5], CornerKind::Sigma)
    } else {
        (text, CornerKind::Absolute)
    };
    let (mant, scale) = match num.chars().last()? {
        'T' => (&num[..num.len() - 1], 1e12),
        'G' => (&num[..num.len() - 1], 1e9),
        'M' => (&num[..num.len() - 1], 1e6),
        'K' | 'k' => (&num[..num.len() - 1], 1e3),
        'm' => (&num[..num.len() - 1], 1e-3),
        'u' => (&num[..num.len() - 1], 1e-6),
        'n' => (&num[..num.len() - 1], 1e-9),
        'p' => (&num[..num.len() - 1], 1e-12),
        'f' => (&num[..num.len() - 1], 1e-15),
        'a' => (&num[..num.len() - 1], 1e-18),
        _ => (num, 1.0),
    };
    // strictly a real literal: sign, digits, one dot, one exponent
    if !mant.chars().any(|c| c.is_ascii_digit())
        || !mant.chars().all(|c| c.is_ascii_digit() || matches!(c, '+' | '-' | '.' | 'e' | 'E'))
    {
        return None;
    }
    let v: f64 = mant.parse().ok()?;
    if !v.is_finite() {
        return None;
    }
    let v = v * scale;
    Some((kind, if kind == CornerKind::Relative { v / 100.0 } else { v }))
}

/// Enhancement-654: the `name=value` entries of a `corner` attribute, split
/// on commas and/or whitespace; a bad entry is returned with the reason so
/// each can be reported on its own.
fn parse_corner_list(text: &str) -> Vec<Result<(String, CornerKind, f64), (String, &'static str)>> {
    text.split(|c: char| c == ',' || c.is_whitespace())
        .filter(|e| !e.is_empty())
        .map(|entry| {
            let Some((name, value)) = entry.split_once('=') else {
                return Err((entry.to_owned(), "an entry is <name>=<value>; there is no '='"));
            };
            let mut chars = name.chars();
            let head_ok = chars.next().is_some_and(|c| c.is_ascii_alphabetic() || c == '_');
            if name.is_empty() || !head_ok || !chars.all(|c| c.is_ascii_alphanumeric() || c == '_') {
                return Err((entry.to_owned(), "the corner name is not an identifier"));
            }
            match parse_corner_value(value) {
                Some((kind, v)) => Ok((name.to_owned(), kind, v)),
                None => Err((
                    entry.to_owned(),
                    "the value is not a number (115, 2.2n), a percentage (+10%) or sigmas (-3sigma)",
                )),
            }
        })
        .collect()
}

/// Declared statistics of a parameter, exported through the OSDI
/// `OSDI_STAT_PARAM_INFOS` side-table for the simulator's Monte-Carlo draws.
#[derive(Debug, Clone, Copy, PartialEq)]
pub struct ParamStat {
    /// standard deviation (gauss) or half-width (uniform); a fraction of the
    /// resolved nominal when `rel` is set. For a lognormal, the sigma of the
    /// logarithm when `rel` is set, else an absolute sigma converted at the
    /// nominal (Enhancement-554).
    pub std: f64,
    pub rel: bool,
    /// false = gauss (the default)
    pub uniform: bool,
    /// Enhancement-554: value = nominal * exp(s z)
    pub lognormal: bool,
    /// Enhancement-554: the Gaussian coordinate is confined to |z| <= trunc
    /// sigmas (rejection with a deterministic sub-key); 0 = untruncated
    pub trunc: f64,
    /// Enhancement-555: the model tests `$param_given` on the parameter -- the
    /// simulator draws it only when the deck gives it
    pub gated: bool,
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
