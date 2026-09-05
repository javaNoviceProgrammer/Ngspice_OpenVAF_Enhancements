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

        // Enhancement-546: the parameters the author classified `(* type="model" *)`
        // in so many words -- a promotion of one of those is worth its own wording.
        let mut explicit_model: AHashSet<Parameter> = AHashSet::new();

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
                        Some("model") => {
                            explicit_model.insert(param);
                            false
                        }
                        None => false,
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

        promote_instance_dependent(db, cu, &mut params, &explicit_model, sink);

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
