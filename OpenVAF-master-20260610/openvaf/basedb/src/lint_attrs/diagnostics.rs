use stdx::impl_display;
use syntax::sourcemap::FileSpan;
use syntax::TextRange;

use crate::diagnostics::{text_ranges_to_unified_spans, Diagnostic, Label, LabelStyle, Report};
use crate::lints::builtin::{lint_level_overwrite, lint_not_found};
use crate::lints::{Lint, LintSrc};
use crate::{BaseDB, FileId};

#[derive(Debug, Eq, PartialEq, Clone)]
pub enum AttrDiagnostic {
    ExpectedArrayOrLiteral { range: TextRange, attr: &'static str },
    ExpectedLiteral { range: TextRange, attr: &'static str },
    UnknownLint { range: TextRange, lint: String, src: ErasedAstId },
    LintOverwrite { old: TextRange, new: TextRange, name: String, src: ErasedAstId },
}

use AttrDiagnostic::*;

use crate::ErasedAstId;

impl_display! {
    match AttrDiagnostic{
        ExpectedArrayOrLiteral{attr,..} => "'{}' attribute exptects a string literal or and array of literals",attr;
        ExpectedLiteral{attr,..} => "'{}' attribute expects a string literal here", attr;
        UnknownLint{lint,..} => "unknown lint '{}'",lint;
        LintOverwrite{name,..} => "lint level for '{}' was set multiple times",name;
    }
}

impl Diagnostic for AttrDiagnostic {
    fn lint(&self, _root_file: FileId, _db: &dyn BaseDB) -> Option<(Lint, LintSrc)> {
        match *self {
            UnknownLint { src, .. } => Some((lint_not_found, src.into())),
            LintOverwrite { src, .. } => Some((lint_level_overwrite, src.into())),
            _ => None,
        }
    }

    fn build_report(&self, root_file: FileId, db: &dyn BaseDB) -> Report {
        let sm = db.sourcemap(root_file);
        let parse = db.parse(root_file);

        let report = match *self {
            ExpectedArrayOrLiteral { range, attr } => {
                let FileSpan { file: file_id, range } = parse.to_file_span(range, &sm);
                Report::error()
                    .with_labels(vec![Label {
                        style: LabelStyle::Primary,
                        file_id,
                        range: range.into(),
                        message: "expected a literal or an array".to_owned(),
                    }])
                    .with_notes(vec![format!(
                        "help: valid examples are {0}=\"foo\" and {0}='{{\"foo\",\"bar\"}}",
                        attr
                    )])
            }
            ExpectedLiteral { range, .. } => {
                let FileSpan { file: file_id, range } = parse.to_file_span(range, &sm);
                Report::error().with_labels(vec![Label {
                    style: LabelStyle::Primary,
                    file_id,
                    range: range.into(),
                    message: "expected a string literal".to_owned(),
                }])
            }
            LintOverwrite { old, new, .. } => {
                let (file_id, [new, old]) = text_ranges_to_unified_spans(&sm, &parse, [new, old]);
                Report::warning()
                    .with_labels(vec![
                        Label {
                            style: LabelStyle::Secondary,
                            file_id,
                            range: old.into(),
                            message: "lint lvl was first set here".to_owned(),
                        },
                        Label {
                            style: LabelStyle::Primary,
                            file_id,
                            range: new.into(),
                            message: "lint lvl was overwritten her".to_owned(),
                        },
                    ])
                    .with_notes(vec![
                        "help: the second lint lvl is used; the first attribute has no effect"
                            .to_owned(),
                    ])
            }
            UnknownLint { range, ref lint, .. } => {
                let FileSpan { file: file_id, range } = parse.to_file_span(range, &sm);
                // Enhancement-650 (hunt F6): name the nearest known lint. The
                // report itself existed and was never emitted (see
                // `hir::diagnostics::collect`); now that it is, a typo gets its
                // correction with it.
                let registry = db.lint_registry();
                let nearest = registry
                    .names()
                    .filter(|name| !name.contains("::"))
                    .map(|name| (edit_distance(name, lint), name))
                    .min()
                    .filter(|(dist, _)| *dist <= 1 + lint.len() / 4)
                    .map(|(_, name)| name);
                let mut notes = vec!["help: this attribute has no effect".to_owned()];
                if let Some(name) = nearest {
                    notes.push(format!("help: did you mean '{name}'?"));
                }
                Report::error()
                    .with_labels(vec![Label {
                        style: LabelStyle::Primary,
                        file_id,
                        range: range.into(),
                        message: "unknown lint".to_owned(),
                    }])
                    .with_notes(notes)
            }
        };

        report.with_message(self.to_string())
    }
}

/// Enhancement-650: Levenshtein distance, for the "did you mean" hint above.
fn edit_distance(a: &str, b: &str) -> usize {
    let a: Vec<char> = a.chars().collect();
    let b: Vec<char> = b.chars().collect();
    let mut prev: Vec<usize> = (0..=b.len()).collect();
    for (i, ca) in a.iter().enumerate() {
        let mut cur = vec![i + 1];
        for (j, cb) in b.iter().enumerate() {
            let cost = usize::from(ca != cb);
            cur.push((prev[j] + cost).min(prev[j + 1] + 1).min(cur[j] + 1));
        }
        prev = cur;
    }
    prev[b.len()]
}
