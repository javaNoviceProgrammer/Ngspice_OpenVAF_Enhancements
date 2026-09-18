//! Enhancement-400: diagnostics raised while building the DAE system.
//!
//! Everything above `sim_back` reports through a [`hir::diagnostics::ConsoleSink`], and
//! `sim_back` already owns one such reporter for module collection (see
//! [`crate::module_info`]). The DAE builder works on MIR, where source positions are
//! gone, so a diagnostic raised there carries the spans it needs -- recovered from the
//! HIR by [`hir::Module::contribution_sites`] at the moment of detection -- and is rendered
//! later by the same sink.

use hir::diagnostics::{BaseDB, Diagnostic, FileId, Label, LabelStyle, Report};
use hir::lints::{
    builtin::discarded_contribution, builtin::dollar_in_exported_name,
    builtin::exported_name_collision, builtin::probe_only_branch_short, Lint, LintSrc,
};
use hir::{ContributionSite, FlowProbeSite};
use syntax::sourcemap::FileSpan;
use syntax::TextRange;

/// How many source lines a single report is willing to point at per label style.
const MAX_LABELS: usize = 4;

/// A branch that received both a potential and a flow contribution with no runtime
/// condition between them, so one of the two was silently dropped.
///
/// The backend decides a branch's type from `BranchInfo::is_voltage_src`. When that value
/// is a *constant* the branch is a plain potential or flow source, and any contribution of
/// the other kind has been overwritten -- the model computed a value that reaches neither
/// the residual nor the Jacobian. When it is a runtime value the branch is a genuine
/// switch branch, both kinds are live, and nothing is reported.
pub(crate) struct DiscardedContribution {
    /// The branch as it is spelled in the source: `br`, `(a,b)` or `(a)`.
    pub branch: String,
    /// The module the branch belongs to; used when no source span could be recovered.
    pub module: String,
    /// The kind the branch ended up being: `true` = potential (voltage) source.
    pub kept_potential: bool,
    /// Every contribution to this branch, in source order.
    pub sites: Vec<ContributionSite>,
}

impl DiscardedContribution {
    /// Contributions of the losing kind that actually carry a value. A literal-zero
    /// contribution is excluded: `V(a,b) <+ 0` is a collapse request delivered by a
    /// `CollapseHint` and not by the residual, so it loses nothing by being overwritten,
    /// and the standard CMC idiom pairs exactly that with an unconditional flow
    /// contribution (BSIM4's `rdsMod`). There is no discarded value to report.
    fn discarded(&self) -> impl Iterator<Item = &ContributionSite> {
        let kept = self.kept_potential;
        self.sites.iter().filter(move |site| site.potential != kept && !site.zero)
    }

    fn kept(&self) -> impl Iterator<Item = &ContributionSite> {
        let kept = self.kept_potential;
        self.sites.iter().filter(move |site| site.potential == kept)
    }

    fn kind(potential: bool) -> &'static str {
        if potential {
            "potential"
        } else {
            "flow"
        }
    }
}

impl Diagnostic for DiscardedContribution {
    fn lint(&self, _root_file: FileId, _db: &dyn BaseDB) -> Option<(Lint, LintSrc)> {
        // Anchor the lint at the statement the primary label points at, so
        // `(* openvaf_allow="discarded_contribution" *)` on that statement (or on any
        // enclosing scope) turns it off. Without a recovered span only the CLI can.
        let src = self.discarded().next().map_or(LintSrc::GLOBAL, |site| site.lint_src);
        Some((discarded_contribution, src))
    }

    fn build_report(&self, root_file: FileId, db: &dyn BaseDB) -> Report {
        let parse = db.parse(root_file);
        let sm = db.sourcemap(root_file);
        let span = |site: &ContributionSite| -> FileSpan { parse.to_file_span(site.range, &sm) };

        let mut labels = Vec::new();
        let mut hidden = 0;
        for (i, site) in self.discarded().enumerate() {
            if i >= MAX_LABELS {
                hidden += 1;
                continue;
            }
            let FileSpan { range, file } = span(site);
            labels.push(Label {
                style: LabelStyle::Primary,
                file_id: file,
                range: range.into(),
                message: format!(
                    "this {} contribution is discarded",
                    Self::kind(site.potential)
                ),
            });
        }
        for (i, site) in self.kept().enumerate() {
            if i >= MAX_LABELS {
                hidden += 1;
                continue;
            }
            let FileSpan { range, file } = span(site);
            labels.push(Label {
                style: LabelStyle::Secondary,
                file_id: file,
                range: range.into(),
                message: format!(
                    "info: the branch is a {} source here",
                    Self::kind(site.potential)
                ),
            });
        }

        let mut notes = vec![
            "a branch is either a potential source or a flow source; when both are \
             contributed with no condition between them the last contribution decides, and \
             the other one is dropped -- it reaches neither the residual nor the Jacobian"
                .to_owned(),
            "to switch between the two, contribute them in mutually exclusive conditional \
             paths (a switch branch); that form is unaffected by this check"
                .to_owned(),
        ];
        // Enhancement-532: a noise-only loser deserves its own words. Since
        // Enhancement-531 a noise-only contribution never decides the branch kind
        // (noise is zero in every large-signal analysis, LRM 4.6.4), so "the last
        // contribution decides" above does not apply to it -- the branch keeps the
        // kind of its last VALUE contribution, and the declared noise vanishes with
        // the losing kind.
        if self.discarded().any(|site| site.noise_only) {
            notes.insert(
                1,
                "the discarded contribution is noise-only: it never decides the branch \
                 kind (noise functions are zero in every large-signal analysis, LRM \
                 4.6.4), but its NOISE is dropped with it -- to keep the noise, express \
                 it in the branch's own kind or contribute it on a branch of its own"
                    .to_owned(),
            );
        }
        if labels.is_empty() {
            notes.insert(0, format!("in module '{}'", self.module));
        }
        if hidden != 0 {
            notes.push(format!("and {hidden} further contribution(s) to the same branch"));
        }

        Report::warning()
            .with_message(format!(
                "branch {} is contributed as both a potential and a flow source",
                self.branch
            ))
            .with_labels(labels)
            .with_notes(notes)
    }
}


/// Enhancement-406: a branch whose flow is probed but which nothing contributes to, while
/// a DIFFERENT branch spanning the same two nodes IS contributed to.
///
/// Probing the flow of a branch with no contribution makes it an ideal ammeter -- a 0 V
/// source (E-36, and a documented feature). That is exactly right for a deliberate sense
/// branch, where nothing else drives the node pair. It is a trap when the node pair IS
/// driven, through the other spelling: a declared `branch (a,b) br` and the node pair
/// `(a,b)` are DIFFERENT branches, so the ammeter lands in parallel with the real one and
/// SHORTS it. Measured on two 1 kOhm sections in series, `I(a,mid) <+ ..` contributed and
/// `I(br)` probed doubles the terminal current -- silently, rc=0.
///
/// Deliberately not reported when nothing else drives the pair: that is the ammeter idiom
/// working as documented, and six branches in the shipped corpus rely on it.
pub(crate) struct ProbeOnlyBranchShort {
    /// The probed branch, as spelled: `br` or `(a,b)`.
    pub probed: String,
    /// The branch that carries the contributions, as spelled.
    pub driven: String,
    /// The node pair both span.
    pub nodes: String,
    pub module: String,
    /// Where the flow is probed.
    pub probes: Vec<FlowProbeSite>,
    /// Where the other branch is contributed to.
    pub sites: Vec<ContributionSite>,
}

impl Diagnostic for ProbeOnlyBranchShort {
    fn lint(&self, _root_file: FileId, _db: &dyn BaseDB) -> Option<(Lint, LintSrc)> {
        // anchor on the probe, which is the statement to annotate or change
        let src = self.probes.first().map_or(LintSrc::GLOBAL, |p| p.lint_src);
        Some((probe_only_branch_short, src))
    }

    fn build_report(&self, root_file: FileId, db: &dyn BaseDB) -> Report {
        let parse = db.parse(root_file);
        let sm = db.sourcemap(root_file);

        let mut labels = Vec::new();
        let mut hidden = 0;
        for (i, probe) in self.probes.iter().enumerate() {
            if i >= MAX_LABELS {
                hidden += 1;
                continue;
            }
            let FileSpan { range, file } = parse.to_file_span(probe.range, &sm);
            labels.push(Label {
                style: LabelStyle::Primary,
                file_id: file,
                range: range.into(),
                message: format!("`{}` is probed here, but never contributed to", self.probed),
            });
        }
        for (i, site) in self.sites.iter().enumerate() {
            if i >= MAX_LABELS {
                hidden += 1;
                continue;
            }
            let FileSpan { range, file } = parse.to_file_span(site.range, &sm);
            labels.push(Label {
                style: LabelStyle::Secondary,
                file_id: file,
                range: range.into(),
                message: format!("`{}` spans the same nodes and is driven here", self.driven),
            });
        }

        let mut notes = vec![
            format!(
                "probing the flow of a branch nothing contributes to makes it an ideal \
                 ammeter -- a 0 V source -- so `{}` is a SHORT across {}, in parallel with \
                 `{}`",
                self.probed, self.nodes, self.driven
            ),
            format!(
                "a declared branch and the node pair it spans are DIFFERENT branches, so \
                 `{}` and `{}` do not refer to the same thing",
                self.probed, self.driven
            ),
            format!(
                "help: probe the branch that is driven -- write the flow probe with the same \
                 spelling used to contribute -- or contribute to `{}` as well if the short \
                 is intended",
                self.probed
            ),
        ];
        if hidden != 0 {
            notes.push(format!("... and {hidden} further site(s) not shown"));
        }

        Report::warning()
            .with_message(format!(
                "in module `{}`: branch `{}` is probe-only and shorts `{}`",
                self.module, self.probed, self.driven
            ))
            .with_labels(labels)
            .with_notes(notes)
    }
}

/// Enhancement-652 (hunt F8): a name exported to the simulator -- a
/// parameter, an alias or an operating-point variable -- with its span and
/// lint anchor.
#[derive(Clone)]
pub(crate) struct ExportedName {
    pub name: String,
    /// "instance parameter", "model parameter", "alias", "operating-point variable"
    pub kind: &'static str,
    pub range: TextRange,
    pub lint_src: LintSrc,
}

/// What the reported declaration collides with.
pub(crate) enum ExportedOther {
    Declared(ExportedName),
    /// One of ngspice's own names: its instance parameter (`m`, `temp`, ...)
    /// or a terminal current it synthesizes (`i_<port>`, `i`).
    Builtin { name: String, what: &'static str },
}

/// Enhancement-652 (hunt F8): two names ngspice cannot tell apart.
///
/// Verilog-A is case-sensitive; ngspice folds every name to lower case, so an
/// instance's parameters, aliases and operating-point variables share ONE flat
/// namespace with the simulator's own `m`/`temp`/`dtemp`/`dt` and the terminal
/// currents Enhancement-394 synthesizes, and a model's parameters and aliases
/// share another. Two entries that fold to the same name are one name to
/// `@inst[name]`, `show` and `alter`: the first in the simulator's table wins
/// (a parameter over a variable, an earlier declaration over a later one,
/// ngspice's own `m` over a variable, a variable over a synthesized current)
/// and the other is unreachable, with two rows of the same name in `show`.
/// ngspice warns at load time (E-335/E-396); the author compiling the model
/// never saw it. This is that warning where the author is.
pub(crate) struct ExportedNameCollision {
    pub module: String,
    pub decl: ExportedName,
    pub other: ExportedOther,
    /// `true`: the reported declaration is what the lookup reaches, and it is
    /// the OTHER name that is shadowed (a variable over a synthesized current)
    pub decl_wins: bool,
}

impl Diagnostic for ExportedNameCollision {
    fn lint(&self, _root_file: FileId, _db: &dyn BaseDB) -> Option<(Lint, LintSrc)> {
        Some((exported_name_collision, self.decl.lint_src))
    }

    fn build_report(&self, root_file: FileId, db: &dyn BaseDB) -> Report {
        let parse = db.parse(root_file);
        let sm = db.sourcemap(root_file);
        let folded = self.decl.name.to_ascii_lowercase();
        let FileSpan { range, file } = parse.to_file_span(self.decl.range, &sm);
        // the model's table is read through `@<model>[..]`/`showmod`, the
        // instance's through `@<inst>[..]`/`show`
        let model_level = self.decl.kind == "model parameter";
        let (level, show, alter) = if model_level {
            ("<model>", "showmod", "altermod")
        } else {
            ("<inst>", "show", "alter")
        };
        let mut involves_var = self.decl.kind == "operating-point variable";
        let (title, primary, mut labels, note) = match &self.other {
            ExportedOther::Declared(other) => {
                involves_var |= other.kind == "operating-point variable";
                let FileSpan { range: orange, file: ofile } = parse.to_file_span(other.range, &sm);
                let secondary = Label {
                    style: LabelStyle::Secondary,
                    file_id: ofile,
                    range: orange.into(),
                    message: format!("info: {} '{}' is declared here", other.kind, other.name),
                };
                (
                    format!(
                        "{} '{}' and {} '{}' differ only by case, which ngspice cannot tell apart",
                        self.decl.kind, self.decl.name, other.kind, other.name
                    ),
                    format!(
                        "unreachable from ngspice: `@{level}[{folded}]` reads {} '{}'",
                        other.kind, other.name
                    ),
                    vec![secondary],
                    format!(
                        "ngspice folds every name to lower case, so `@{level}[{folded}]`, `{show}` \
                         and `{alter}` see one name where the model declares two -- {} '{}' comes \
                         first in the simulator's table and wins the lookup, and `{show}` prints \
                         two '{folded}' rows",
                        other.kind, other.name
                    ),
                )
            }
            ExportedOther::Builtin { name, what } if self.decl_wins => (
                format!(
                    "{} '{}' shadows '{name}', {what}",
                    self.decl.kind, self.decl.name
                ),
                format!("`@<inst>[{name}]` reads this {} instead", self.decl.kind),
                Vec::new(),
                format!(
                    "ngspice folds every name to lower case; '{name}' is what \
                     `.options savecurrents` and `print @<inst>[{name}]` expect to be {what}, \
                     and with this name in the way it is unreachable"
                ),
            ),
            ExportedOther::Builtin { name, what } => (
                format!(
                    "{} '{}' has the name of {what} '{name}', which wins the lookup",
                    self.decl.kind, self.decl.name
                ),
                format!("unreachable from ngspice: `@<inst>[{name}]` reads {what}"),
                Vec::new(),
                format!(
                    "ngspice folds every name to lower case and its own '{name}' comes first, \
                     so the model's value can never be read back and `show` prints two \
                     '{name}' rows"
                ),
            ),
        };
        labels.insert(
            0,
            Label { style: LabelStyle::Primary, file_id: file, range: range.into(), message: primary },
        );
        let help = if involves_var {
            format!(
                "help: rename one of them in the Verilog-A source of module '{}' (the \
                 `desc`/`units` attribute is what exports a variable; dropping the attribute \
                 hides the variable from the simulator instead of renaming it)",
                self.module
            )
        } else {
            format!("help: rename one of them in the Verilog-A source of module '{}'", self.module)
        };
        Report::warning().with_message(title).with_labels(labels).with_notes(vec![note, help])
    }
}

/// Enhancement-652 (hunt F8): a `$` in an exported name.
///
/// `a$b` is a legal Verilog-A identifier (LRM 2.7.1) and ngspice sets
/// `a$b=5` on a card, but `print @inst[a$b]` hands the text between the
/// brackets to the expression parser, which reads `$b` as a shell variable:
/// "b: no such variable", then "no such parameter a". The name is write-only;
/// an operating-point variable with a `$` is not exported at all (its shape
/// is reserved for the `name$paramset` twins, LRM 6.4.3).
pub(crate) struct DollarInExportedName {
    pub module: String,
    pub decl: ExportedName,
    /// Enhancement-665 (hunt F13): the offending character -- `$`, or any
    /// other one an escaped identifier smuggled into an exported name
    pub bad: char,
}

impl Diagnostic for DollarInExportedName {
    fn lint(&self, _root_file: FileId, _db: &dyn BaseDB) -> Option<(Lint, LintSrc)> {
        Some((dollar_in_exported_name, self.decl.lint_src))
    }

    fn build_report(&self, root_file: FileId, db: &dyn BaseDB) -> Report {
        let parse = db.parse(root_file);
        let sm = db.sourcemap(root_file);
        let FileSpan { range, file } = parse.to_file_span(self.decl.range, &sm);
        let opvar = self.decl.kind == "operating-point variable";
        let (label, note) = if opvar {
            (
                "not exported to the simulator".to_owned(),
                "a `$` in an operating-point variable's name is the shape of the \
                 `name$paramset` twins (LRM 6.4.3), so it is kept out of the exported \
                 table; and `@<inst>[a$b]` could not read it anyway"
                    .to_owned(),
            )
        } else if self.bad == '$' {
            (
                "write-only from ngspice".to_owned(),
                format!(
                    "ngspice sets `{0}=...` on a card, but `print @<inst>[{0}]` hands the text \
                     to its expression parser, which reads the `$` part as a shell variable \
                     (\"no such variable\"), so the value can never be read back",
                    self.decl.name
                ),
            )
        } else {
            (
                "unreachable from ngspice".to_owned(),
                format!(
                    "an escaped identifier exports its text as it is: `@<inst>[{0}]` and \
                     `{0}=...` on a card are read by ngspice's parsers, which take `{1}` as \
                     an operator or a separator; keep an exported name to letters, digits and `_`",
                    self.decl.name, self.bad
                ),
            )
        };
        Report::warning()
            .with_message(format!(
                "{} '{}' has a `{}` in its name, which ngspice's expression parser cannot read",
                self.decl.kind, self.decl.name, self.bad
            ))
            .with_labels(vec![Label {
                style: LabelStyle::Primary,
                file_id: file,
                range: range.into(),
                message: label,
            }])
            .with_notes(vec![
                note,
                format!("help: rename it in the Verilog-A source of module '{}'", self.module),
            ])
    }
}
