pub use sink::{
    is_elaboration_buffer_name, print_all, stderr_color_choice, stdout_color_choice, ConsoleSink,
    DiagnosticSink,
};

use crate::lints::{Lint, LintData, LintLevel, LintSrc};
use crate::{BaseDB, FileId};

mod preprocessor_error;
pub mod sink;
mod syntax_error;

pub type Report = codespan_reporting::diagnostic::Diagnostic<FileId>;
pub type Label = codespan_reporting::diagnostic::Label<FileId>;

pub use codespan_reporting::diagnostic::{LabelStyle, Severity};
use syntax::sourcemap::{CtxSpan, FileSpan, SourceMap};
use syntax::{Parse, SourceFile, TextRange};

pub trait Diagnostic {
    fn lint(&self, _root_file: FileId, _db: &dyn BaseDB) -> Option<(Lint, LintSrc)> {
        None
    }

    fn build_report(&self, root_file: FileId, db: &dyn BaseDB) -> Report;

    fn to_report(&self, root_file: FileId, db: &dyn BaseDB) -> Option<Report> {
        if let Some((lint, lint_src)) = self.lint(root_file, db) {
            let (lvl, is_default) = lint_src.lvl(lint, root_file, db);
            let LintData { name, documentation_id, .. } = db.lint_data(lint);

            let seververity = match lvl {
                LintLevel::Deny => Severity::Error,
                LintLevel::Warn => Severity::Warning,
                LintLevel::Allow => return None,
            };

            let mut report = self.build_report(root_file, db);

            if is_default {
                let hint = format!(
                    "{} is set to {} by default\nuse a CLI argument or an attribute to overwrite",
                    name, lvl
                );
                report.notes.push(hint)
            }

            report.severity = seververity;
            Some(note_command_line_define(report.with_code(format!("L{:03}", documentation_id)), db))
        } else {
            Some(note_command_line_define(self.build_report(root_file, db), db))
        }
    }
}

/// Enhancement-650 (hunt F6): a diagnostic whose primary label sits in the
/// virtual `-D` definitions file (`/std/__openvaf_defines__.va`, see
/// `hir::db::defines_src`) points at a file the user never wrote. Name the
/// command-line argument the offending line was synthesized from.
fn note_command_line_define(mut report: Report, db: &dyn BaseDB) -> Report {
    const DEFINES_FILE: &str = "/std/__openvaf_defines__.va";
    let Some(label) = report.labels.iter().find(|l| l.style == LabelStyle::Primary) else {
        return report;
    };
    if db.file_path(label.file_id).to_string() != DEFINES_FILE {
        return report;
    }
    let Ok(text) = db.file_text(label.file_id) else { return report };
    let start = label.range.start.min(text.len());
    let line_start = text[..start].rfind('\n').map_or(0, |i| i + 1);
    let line_end = text[start..].find('\n').map_or(text.len(), |i| start + i);
    let line = &text[line_start..line_end];
    let arg = match line.strip_prefix("`define ").and_then(|rest| rest.split_once(' ')) {
        Some((name, value)) => format!("-D {name}={value}"),
        None => line.to_owned(),
    };
    report.notes.push(format!(
        "note: this line was synthesized from the command-line argument `{arg}`; the \
         argument is what needs fixing"
    ));
    report
}

pub const HINT_UNSUPPORTED: &str = "this is allowed by VerilogAMS language spec but was purposefully excluded from the supported language subset\nmore details can be found in the OpenVAF documentation";

// TODO support expansion backtrace

pub fn to_unified_spans<const N: usize>(
    sm: &SourceMap,
    mut spans: [CtxSpan; N],
) -> (FileId, [TextRange; N]) {
    assert!(N >= 2);
    let (file, ranges) = sm.to_file_spans(&mut spans);
    (file, ranges.try_into().unwrap())
}

pub fn to_unified_span_list(sm: &SourceMap, spans: &mut [CtxSpan]) -> (FileId, Vec<TextRange>) {
    match spans {
        // Enhancement-220: a diagnostic built from an empty node list (reachable
        // from malformed input -- e.g. a mixed module head with no ports, or an
        // empty illegal-node list) used to hit `unimplemented!()` and crash the
        // compiler. Render it with no labels, anchored to the root file.
        [] => (sm.root_file(), Vec::new()),
        [span] => {
            let FileSpan { range, file } = span.to_file_span(sm);
            (file, vec![range])
        }
        spans => sm.to_file_spans(spans),
    }
}

pub fn text_ranges_to_unified_spans<const N: usize>(
    sm: &SourceMap,
    parse: &Parse<SourceFile>,
    ranges: [TextRange; N],
) -> (FileId, [TextRange; N]) {
    let spans = ranges.map(|range| parse.to_ctx_span(range, sm));
    to_unified_spans(sm, spans)
}

pub fn text_range_list_to_unified_spans(
    sm: &SourceMap,
    parse: &Parse<SourceFile>,
    ranges: &[TextRange],
) -> (FileId, Vec<TextRange>) {
    let mut spans: Vec<_> = ranges.iter().map(|range| parse.to_ctx_span(*range, sm)).collect();
    to_unified_span_list(sm, &mut spans)
}
