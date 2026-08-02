//! Enhancement-400: diagnostics raised while building the DAE system.
//!
//! Everything above `sim_back` reports through a [`hir::diagnostics::ConsoleSink`], and
//! `sim_back` already owns one such reporter for module collection (see
//! [`crate::module_info`]). The DAE builder works on MIR, where source positions are
//! gone, so a diagnostic raised there carries the spans it needs -- recovered from the
//! HIR by [`hir::Module::contribution_sites`] at the moment of detection -- and is rendered
//! later by the same sink.

use hir::diagnostics::{BaseDB, Diagnostic, FileId, Label, LabelStyle, Report};
use hir::lints::{builtin::discarded_contribution, Lint, LintSrc};
use hir::ContributionSite;
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
