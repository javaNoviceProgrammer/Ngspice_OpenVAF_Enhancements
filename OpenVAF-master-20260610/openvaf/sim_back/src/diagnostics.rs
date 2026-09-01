//! Enhancement-400: diagnostics raised while building the DAE system.
//!
//! Everything above `sim_back` reports through a [`hir::diagnostics::ConsoleSink`], and
//! `sim_back` already owns one such reporter for module collection (see
//! [`crate::module_info`]). The DAE builder works on MIR, where source positions are
//! gone, so a diagnostic raised there carries the spans it needs -- recovered from the
//! HIR by [`hir::Module::contribution_sites`] at the moment of detection -- and is rendered
//! later by the same sink.

use hir::diagnostics::{BaseDB, Diagnostic, FileId, Label, LabelStyle, Report};
use hir::lints::{builtin::discarded_contribution, builtin::probe_only_branch_short, Lint, LintSrc};
use hir::{ContributionSite, FlowProbeSite};
use syntax::sourcemap::FileSpan;

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
