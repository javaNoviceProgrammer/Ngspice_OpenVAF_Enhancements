use std::sync::Arc;

use diagnostics::PreprocessorDiagnostic;
use sourcemap::{CtxSpan, SourceMap};
use vfs::{FileId, FileReadError, VfsPath};

use crate::processor::Processor;
// use tracing::trace_span;

pub mod diagnostics;
mod grammar;
mod parser;
mod processor;
pub mod sourcemap;

mod scoped_arc_arena;
#[cfg(test)]
#[rustfmt::skip]
mod tests;

type Text = Arc<str>;
type ScopedTextArea = scoped_arc_arena::ScopedArea<Text>;
type Diagnostics = Vec<PreprocessorDiagnostic>;

/// The predefined Verilog-AMS macros (LRM 10.5). `__VAMS_ENABLE__` "shall
/// always be defined during the parsing of Verilog-AMS source text";
/// `__VAMS_COMPACT_MODELING__` is defined because the compact-modeling
/// extensions (`ddx`, ...) are supported; `__OPENVAF__` is the
/// simulator-specific macro the LRM requires every implementation to provide.
/// Per LRM 10.4 `` `undef `` (and `` `undefineall ``) has no effect on these.
/// `basedb::STANDARD_FLAGS` re-exports this list as the default macro flags.
pub const PREDEFINED_MACROS: [&str; 4] =
    ["__OPENVAF__", "__VAMS__", "__VAMS_COMPACT_MODELING__", "__VAMS_ENABLE__"];

#[derive(PartialEq, Eq, Clone, Debug)]
pub struct Preprocess {
    pub ts: Arc<Vec<Token>>,
    pub sm: Arc<SourceMap>,
    pub diagnostics: Arc<Diagnostics>,
    /// `` `default_transition `` value (Enhancement-47), if the compilation
    /// declared one: the default rise/fall time for `transition()` filters
    /// that omit those arguments.
    pub default_transition: Option<ordered_float::OrderedFloat<f64>>,
}

/// # Panics
/// This function panics if called multiple times in the same OpenVAF session
pub fn preprocess(sources: &dyn SourceProvider, file: FileId) -> Preprocess {
    // let span = trace_span!("preprocessor", main_file = display(sources.file_path(file)));
    // let _scope = span.enter();

    let storage = ScopedTextArea::new();
    let (ts, diagnostics, sm, default_transition) =
        match Processor::new(&storage, file, sources) {
            Ok(mut processor) => {
                let (ts, diagnostics) = processor.run(file);
                (ts, diagnostics, processor.source_map, processor.default_transition)
            }
            Err(FileReadError::Io(error)) => (
                vec![],
                vec![PreprocessorDiagnostic::FileNotFound {
                    file: sources.file_path(file).to_string(),
                    error,
                    span: None,
                }],
                SourceMap::new(file, 0.into()),
                None,
            ),
            Err(FileReadError::InvalidTextFormat(err)) => (
                vec![],
                vec![PreprocessorDiagnostic::InvalidTextFormat {
                    file: sources.file_path(file),
                    span: None,
                    err,
                }],
                SourceMap::new(file, 0.into()),
                None,
            ),
        };

    Preprocess {
        ts: Arc::new(ts),
        diagnostics: Arc::new(diagnostics),
        sm: Arc::new(sm),
        default_transition,
    }
}

pub trait SourceProvider {
    fn include_dirs(&self, root_file: FileId) -> Arc<[VfsPath]>;
    fn macro_flags(&self, file_root: FileId) -> Arc<[Arc<str>]>;

    fn file_text(&self, file: FileId) -> Result<Arc<str>, FileReadError>;
    fn file_path(&self, file: FileId) -> VfsPath;
    fn file_id(&self, path: VfsPath) -> FileId;

    /// Round-4 audit (LRM 10.4 -> IEEE 1364-2005 19.3.1): stores the text of
    /// the virtual file that backs preprocessor-synthesized tokens (macro
    /// stringification and token pasting produce text that exists in no
    /// source file). The file id was interned through `file_id` earlier;
    /// after this call `file_text` must serve `text` for it.
    fn set_file_text(&self, file: FileId, text: &str);
}

#[derive(Debug, Copy, Clone, PartialEq, Eq)]
pub struct Token {
    pub span: CtxSpan,
    pub kind: tokens::parser::SyntaxKind,
}
