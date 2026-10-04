use std::fmt::Display;
use std::sync::Arc;

use codespan_reporting::diagnostic::Severity;
use codespan_reporting::files::{Files, Location};
pub use codespan_reporting::term::termcolor::{Ansi, Buffer, ColorChoice, NoColor};
use codespan_reporting::term::termcolor::{StandardStream, WriteColor};
use codespan_reporting::term::{emit, Chars, Config};
use vfs::VfsPath;

use crate::diagnostics::{Diagnostic, Report};
use crate::{BaseDB, FileId};

pub trait DiagnosticSink {
    fn add_report(&mut self, report: Report);
    fn add_diagnostic(&mut self, diagnostic: &dyn Diagnostic, root_file: FileId, db: &dyn BaseDB) {
        if let Some(report) = diagnostic.to_report(root_file, db) {
            self.add_report(report)
        }
    }
    fn add_diagnostics<'a>(
        &mut self,
        diagnostics: impl IntoIterator<Item = &'a (impl Diagnostic + 'a)>,
        root_file: FileId,
        db: &dyn BaseDB,
    ) {
        diagnostics
            .into_iter()
            .for_each(|diagnostic| self.add_diagnostic(diagnostic, root_file, db))
    }
}

struct FileSrc<'a> {
    db: &'a dyn BaseDB,
    anon_paths: bool,
}

impl<'a> Files<'_> for FileSrc<'a> {
    type FileId = FileId;

    type Name = VfsPath;

    type Source = Arc<str>;

    fn name(&self, id: FileId) -> Result<Self::Name, codespan_reporting::files::Error> {
        let mut path = self.db.file_path(id);
        if self.anon_paths {
            path = VfsPath::new_virtual_path(format!("/{}", path.name().unwrap()))
        }

        Ok(path)
    }

    fn source(&self, id: Self::FileId) -> Result<Self::Source, codespan_reporting::files::Error> {
        match self.db.file_text(id) {
            Ok(src) => Ok(src),
            Err(_) => {
                let vfs = self.db.vfs().read();
                let contents = Arc::from(vfs.file_contents_unchecked(id));
                Ok(contents)
            }
        }
    }

    fn line_index(
        &self,
        file: Self::FileId,
        byte_index: usize,
    ) -> Result<usize, codespan_reporting::files::Error> {
        Ok(self.db.line(byte_index.try_into().unwrap(), file).into())
    }

    fn line_range(
        &self,
        file: Self::FileId,
        line_index: usize,
    ) -> Result<std::ops::Range<usize>, codespan_reporting::files::Error> {
        Ok(self.db.line_range(line_index.into(), file).into())
    }
}

pub struct ConsoleSink<'a> {
    warning_cnt: usize,
    error_cnt: usize,
    config: Config,
    db: &'a dyn BaseDB,
    dst: Box<dyn WriteColor + 'a>,
    anon_paths: bool,
    /// Enhancement-414: set when a diagnostic was reported against one of the
    /// synthesised elaboration buffers, so the summary can explain the position.
    saw_elaborated_buffer: bool,
    /// Enhancement-791: per file, whether it has a line longer than
    /// `MAX_QUOTED_LINE` (checked once, on the first report against it).
    long_lines: Vec<(FileId, bool)>,
}


/// Enhancement-574: colour only when the stream IS a terminal. termcolor's
/// `ColorChoice::Auto` consults `TERM` and `NO_COLOR` alone and never the
/// stream, so from any colour terminal every diagnostic written into a pipe --
/// a build log, a harness, ngspice's own `pre_osdi -va` capture -- carried
/// escape codes, and the line that starts with "error:" on the screen started
/// with `\x1b[0m\x1b[1m\x1b[38;5;9m` in the file. `Auto` still decides the
/// terminal case, so `NO_COLOR` and a dumb `TERM` keep their meaning there.
pub fn stderr_color_choice() -> ColorChoice {
    use std::io::IsTerminal;
    if std::io::stderr().is_terminal() { ColorChoice::Auto } else { ColorChoice::Never }
}

pub fn stdout_color_choice() -> ColorChoice {
    use std::io::IsTerminal;
    if std::io::stdout().is_terminal() { ColorChoice::Auto } else { ColorChoice::Never }
}

impl<'a> ConsoleSink<'a> {
    pub fn new(db: &'a dyn BaseDB) -> ConsoleSink<'a> {
        ConsoleSink::new_with(db, Box::new(StandardStream::stderr(stderr_color_choice())))
    }

    pub fn buffer(db: &'a dyn BaseDB, buffer: &'a mut Buffer) -> ConsoleSink<'a> {
        ConsoleSink::new_with(db, Box::new(buffer))
    }

    pub fn summary(&mut self, target_name: &impl Display) -> bool {
        // Enhancement-414: see `add_report`. A `…__generated.va` / `…__paramwidth.va`
        // position is a location in an internally elaborated copy of the source, not in
        // any file on disk; say so once rather than leaving the reader to discover it.
        if self.saw_elaborated_buffer {
            self.saw_elaborated_buffer = false;
            self.print_simple_message(
                Severity::Note,
                "some positions above are in an elaborated copy of the source (a name \
                 ending `__generated.va`, `__paramwidth.va`, ...): the compiler rewrote \
                 the file to expand a generate/genvar construct or a parameter-shaped \
                 width. Those line numbers are the copy's own -- match the quoted code, \
                 not the line number, against your source"
                    .to_owned(),
            );
        }
        if self.error_cnt != 0 {
            let warn = if self.warning_cnt != 0 {
                format!("; {} warning emitted", self.warning_cnt)
            } else {
                String::new()
            };
            // Enhancement-665 (hunt F11): the summary named the elaborated copy
            // (`x.va__namerange.va`) when the last pass ran on one; the file
            // that could not be compiled is the author's
            let mut shown = target_name.to_string();
            for suffix in ELABORATION_BUFFER_SUFFIXES {
                if let Some(base) = shown.strip_suffix(suffix) {
                    shown = base.trim_start_matches('/').to_owned();
                    break;
                }
            }
            let message = format!(
                "could not compile `{}` due to {} previous errors{}",
                shown, self.error_cnt, warn
            );

            self.print_simple_message(Severity::Error, message);
            return true;
        }

        if self.warning_cnt != 0 {
            let message = format!("`{}` generated {} warning", target_name, self.warning_cnt);
            self.print_simple_message(Severity::Warning, message);
            self.warning_cnt = 0;
        }

        false
    }

    pub fn print_simple_message(&mut self, severity: Severity, msg: String) {
        emit(
            &mut self.dst,
            &self.config,
            &FileSrc { db: self.db, anon_paths: self.anon_paths },
            &Report::new(severity).with_message(msg),
        )
        .expect("Span emitting should never fail");
    }

    pub fn new_with(db: &'a dyn BaseDB, dst: Box<dyn WriteColor + 'a>) -> ConsoleSink<'a> {
        let mut config = Config { chars: Chars::ascii(), ..Config::default() };
        config.styles.header_error.set_intense(false);
        config.styles.header_warning.set_intense(false);
        config.styles.header_help.set_intense(false);
        config.styles.header_bug.set_intense(false);
        config.styles.header_note.set_intense(false);

        config.styles.note_bullet.set_bold(true).set_intense(true);
        config.styles.line_number.set_bold(true).set_intense(true);
        config.styles.source_border.set_bold(true).set_intense(true);
        config.styles.primary_label_bug.set_bold(true);
        config.styles.primary_label_note.set_bold(true);
        config.styles.primary_label_help.set_bold(true);
        config.styles.primary_label_error.set_bold(true);
        config.styles.primary_label_warning.set_bold(true);
        config.styles.secondary_label.set_bold(true);

        ConsoleSink { warning_cnt: 0, error_cnt: 0, config, db, dst, anon_paths: false, saw_elaborated_buffer: false, long_lines: Vec::new() }
    }

    /// only print the filename instead of the full path, this is useful for UI tests where we do not want to expose the full path
    pub fn annonymize_paths(&mut self) {
        self.anon_paths = true;
    }
}

// impl Drop for ConsoleSink<'_>{
//     fn drop(&self){
//         match self.error_cnt{
//             0 => {
//                 match self.warning_cnt{
//                     0 => eprintln!("")
//                     warnings =>
//                 }
//             }
//         }
//         println!("finished with")
//     }
// }

/// Enhancement-219: cap how many diagnostics are *rendered*. Pathological input
/// (e.g. thousands of nested tokens produced by a fuzzer or a corrupted file)
/// can emit thousands of errors; building a source-annotated report for each one
/// (codespan_reporting extracts and lays out the surrounding source per report)
/// turns a clean rejection into a multi-second effective hang. The first
/// `MAX_RENDERED_DIAGNOSTICS` are rendered in full; after that only the counters
/// advance, and `summary()` still reports the true totals. This mirrors the
/// "too many errors" behaviour of rustc/clang.
const MAX_RENDERED_DIAGNOSTICS: usize = 128;

/// Enhancement-414: the names `hir::elaborate` gives the buffers it synthesises, each
/// `<original>.va__<pass>.va`. Matched by suffix rather than by "is this path virtual",
/// because ordinary test fixtures are virtual too and are NOT elaborated copies.
const ELABORATION_BUFFER_SUFFIXES: [&str; 5] = [
    "__generated.va",
    "__paramwidth.va",
    "__namerange.va",
    "__legacygen.va",
    "__elaborated.va",
];

pub fn is_elaboration_buffer_name(name: &str) -> bool {
    ELABORATION_BUFFER_SUFFIXES.iter().any(|s| name.ends_with(s))
}

impl DiagnosticSink for ConsoleSink<'_> {
    fn add_report(&mut self, mut report: Report) {
        match report.severity {
            Severity::Error => self.error_cnt += 1,
            Severity::Warning => self.warning_cnt += 1,
            _ => (),
        }

        let rendered = self.error_cnt + self.warning_cnt;
        if rendered > MAX_RENDERED_DIAGNOSTICS {
            // Announce the suppression exactly once, as we cross the cap.
            if rendered == MAX_RENDERED_DIAGNOSTICS + 1 {
                self.print_simple_message(
                    Severity::Note,
                    format!(
                        "further diagnostics suppressed after {} \
                         (too many errors -- the input is likely malformed)",
                        MAX_RENDERED_DIAGNOSTICS
                    ),
                );
            }
            return;
        }

        // Enhancement-414: a diagnostic can land in one of the ELABORATED buffers the
        // generate/parameter-width passes synthesise, whose name is virtual and whose
        // line numbers are its own -- the buffer is re-rendered after preprocessing, so
        // an expanded `include shifts every line below it. Reporting `foo.va__generated
        // .va:143` for a mistake on line 9 of a twelve-line file sent the reader to a
        // path that does not exist, hunting a line that does not either. The position
        // cannot be mapped back without a real span map, so say what it is instead of
        // presenting it as a location in the user's file.
        if report.labels.iter().any(|l| {
            self.db
                .vfs()
                .read()
                .file_path(l.file_id)
                .name()
                .is_some_and(|n| is_elaboration_buffer_name(&n))
        }) {
            self.saw_elaborated_buffer = true;
        }

        let src = FileSrc { db: self.db, anon_paths: self.anon_paths };
        match self.clip_long_lines(&src, &mut report) {
            Some(clipped) => emit(&mut self.dst, &self.config, &clipped, &report),
            None => emit(&mut self.dst, &self.config, &src, &report),
        }
        .expect("Span emitting should never fail");
    }
}

impl<'a> ConsoleSink<'a> {
    /// Enhancement-791: when a file a label points into has a line longer than
    /// `MAX_QUOTED_LINE`, quote a copy of it with those lines clipped and move the
    /// labels into the copy. `None` (quote the file as it is) otherwise.
    fn clip_long_lines<'s>(
        &mut self,
        src: &'s FileSrc<'a>,
        report: &mut Report,
    ) -> Option<ClippedSrc<'s, 'a>> {
        let mut files: Vec<FileId> = report.labels.iter().map(|l| l.file_id).collect();
        files.sort_unstable();
        files.dedup();
        let mut clipped = Vec::new();
        for file in files {
            let has_long = match self.long_lines.iter().find(|(f, _)| *f == file) {
                Some(&(_, long)) => long,
                None => {
                    let text = src.source(file).ok()?;
                    let long = text.split('\n').any(|line| line.len() > MAX_QUOTED_LINE);
                    self.long_lines.push((file, long));
                    long
                }
            };
            if !has_long {
                continue;
            }
            let mut points: Vec<usize> = report
                .labels
                .iter()
                .filter(|l| l.file_id == file)
                .flat_map(|l| [l.range.start, l.range.end])
                .collect();
            points.sort_unstable();
            points.dedup();
            let copy = ClippedFile::new(src.source(file).ok()?, &points);
            for label in report.labels.iter_mut().filter(|l| l.file_id == file) {
                label.range = copy.to_copy(label.range.start)..copy.to_copy(label.range.end);
            }
            clipped.push((file, copy));
        }
        if clipped.is_empty() {
            None
        } else {
            Some(ClippedSrc { base: src, clipped })
        }
    }
}

/// Enhancement-791 (hunt D1 of 2026-10-04): the longest line, in bytes, a
/// diagnostic quotes whole. codespan_reporting quotes every line a label
/// touches in full, so the depth error E-718 reports at the 32 768th operator
/// of a generated one-line sum quoted the whole line -- 500 KB for 100 000
/// terms, with 164 KB of spaces under it to place the caret. A longer line is
/// quoted as windows of `QUOTED_CONTEXT` bytes either side of each label's start
/// and end, the cuts marked `...`; the location above the snippet keeps the
/// line's real column.
const MAX_QUOTED_LINE: usize = 240;
const QUOTED_CONTEXT: usize = 60;
const ELISION: &str = "...";

/// A copy of one file in which every line longer than `MAX_QUOTED_LINE` is cut
/// down to the windows around the label positions on it (its first
/// `2 * QUOTED_CONTEXT` bytes when no label is on it: a line quoted as context).
/// Line breaks are kept, so line numbers are the original's.
struct ClippedFile {
    text: Arc<str>,
    line_starts: Vec<usize>,
    /// The kept runs as `(start in the copy, start in the original, length)`,
    /// in order in both.
    runs: Vec<(usize, usize, usize)>,
}

impl ClippedFile {
    fn new(orig: Arc<str>, points: &[usize]) -> ClippedFile {
        let src: &str = &orig;
        let mut text = String::new();
        let mut line_starts = Vec::new();
        let mut runs = Vec::new();
        let mut start = 0;
        loop {
            let end = src[start..].find('\n').map_or(src.len(), |i| start + i);
            let newline = usize::from(end < src.len());
            line_starts.push(text.len());
            if end - start <= MAX_QUOTED_LINE {
                runs.push((text.len(), start, end - start + newline));
                text.push_str(&src[start..end + newline]);
            } else {
                let on_line = &points
                    [points.partition_point(|&p| p < start)..points.partition_point(|&p| p <= end)];
                let mut windows: Vec<(usize, usize)> = Vec::new();
                if on_line.is_empty() {
                    windows.push((start, start + 2 * QUOTED_CONTEXT));
                }
                for &p in on_line {
                    let lo = p.saturating_sub(QUOTED_CONTEXT).max(start);
                    let hi = (p + QUOTED_CONTEXT).min(end);
                    match windows.last_mut() {
                        // windows closer than the marker would be are merged
                        Some(last) if lo <= last.1 + ELISION.len() => last.1 = last.1.max(hi),
                        _ => windows.push((lo, hi)),
                    }
                }
                let mut at = start;
                for (lo, hi) in windows {
                    let lo = floor_char_boundary(src, lo).max(at);
                    let hi = ceil_char_boundary(src, hi.min(end));
                    if lo > at {
                        text.push_str(ELISION);
                    }
                    runs.push((text.len(), lo, hi - lo));
                    text.push_str(&src[lo..hi]);
                    at = hi;
                }
                if at < end {
                    text.push_str(ELISION);
                }
                if newline == 1 {
                    runs.push((text.len(), end, 1));
                    text.push('\n');
                }
            }
            if end == src.len() {
                break;
            }
            start = end + 1;
        }
        ClippedFile { text: Arc::from(text), line_starts, runs }
    }

    /// An offset of the original that lies in a kept run (every label point
    /// does), as an offset of the copy.
    fn to_copy(&self, pos: usize) -> usize {
        let i = self.runs.partition_point(|&(_, orig, _)| orig <= pos).saturating_sub(1);
        let (copy, orig, len) = self.runs[i];
        copy + (pos - orig).min(len)
    }

    fn to_orig(&self, pos: usize) -> usize {
        let i = self.runs.partition_point(|&(copy, _, _)| copy <= pos).saturating_sub(1);
        let (copy, orig, len) = self.runs[i];
        orig + (pos - copy).min(len)
    }
}

fn floor_char_boundary(s: &str, mut i: usize) -> usize {
    while !s.is_char_boundary(i) {
        i -= 1;
    }
    i
}

fn ceil_char_boundary(s: &str, mut i: usize) -> usize {
    while !s.is_char_boundary(i) {
        i += 1;
    }
    i
}

/// The files a report is rendered from, with the clipped copies standing in for
/// the files that needed them.
struct ClippedSrc<'s, 'a> {
    base: &'s FileSrc<'a>,
    clipped: Vec<(FileId, ClippedFile)>,
}

impl ClippedSrc<'_, '_> {
    fn copy(&self, id: FileId) -> Option<&ClippedFile> {
        self.clipped.iter().find(|(f, _)| *f == id).map(|(_, c)| c)
    }
}

impl Files<'_> for ClippedSrc<'_, '_> {
    type FileId = FileId;
    type Name = VfsPath;
    type Source = Arc<str>;

    fn name(&self, id: FileId) -> Result<VfsPath, codespan_reporting::files::Error> {
        self.base.name(id)
    }

    fn source(&self, id: FileId) -> Result<Arc<str>, codespan_reporting::files::Error> {
        match self.copy(id) {
            Some(copy) => Ok(copy.text.clone()),
            None => self.base.source(id),
        }
    }

    fn line_index(
        &self,
        id: FileId,
        byte_index: usize,
    ) -> Result<usize, codespan_reporting::files::Error> {
        match self.copy(id) {
            Some(copy) => Ok(copy.line_starts.partition_point(|&s| s <= byte_index) - 1),
            None => self.base.line_index(id, byte_index),
        }
    }

    fn line_range(
        &self,
        id: FileId,
        line_index: usize,
    ) -> Result<std::ops::Range<usize>, codespan_reporting::files::Error> {
        match self.copy(id) {
            Some(copy) => {
                let start = copy.line_starts[line_index];
                let end = copy.line_starts.get(line_index + 1).copied().unwrap_or(copy.text.len());
                Ok(start..end)
            }
            None => self.base.line_range(id, line_index),
        }
    }

    /// The location above a snippet is the ORIGINAL line and column.
    fn location(
        &self,
        id: FileId,
        byte_index: usize,
    ) -> Result<Location, codespan_reporting::files::Error> {
        match self.copy(id) {
            Some(copy) => self.base.location(id, copy.to_orig(byte_index)),
            None => self.base.location(id, byte_index),
        }
    }
}

pub fn print_all<'a>(
    diagnostics: impl IntoIterator<Item = &'a (impl Diagnostic + 'a)>,
    db: &dyn BaseDB,
    root_file: FileId,
) {
    ConsoleSink::new(db).add_diagnostics(diagnostics, root_file, db)
}
