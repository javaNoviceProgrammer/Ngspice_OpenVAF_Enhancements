use std::io;

use stdx::impl_display;
use vfs::{InvalidTextFormatErr, VfsPath};

use crate::sourcemap::CtxSpan;

#[derive(Debug, PartialEq, Clone, Eq)]
pub enum PreprocessorDiagnostic {
    MacroArgumentCountMismatch { expected: usize, found: usize, span: CtxSpan },
    MacroNotFound { name: String, span: CtxSpan },
    MacroNotDefined { name: String, span: CtxSpan },
    MacroRecursion { name: String, span: CtxSpan },
    /// Enhancement-148: a `` `include `` nesting deeper than the limit (a file that
    /// includes itself, directly or transitively) -- reported instead of overflowing
    /// the compiler stack, mirroring the `MacroRecursion` guard.
    IncludeRecursionLimit { file: String, span: CtxSpan },
    UnsupportedCompDir { name: String, span: CtxSpan },
    FileNotFound { file: String, error: io::ErrorKind, span: Option<CtxSpan> },
    InvalidTextFormat { span: Option<CtxSpan>, file: VfsPath, err: InvalidTextFormatErr },
    UnexpectedEof { expected: &'static str, span: CtxSpan },
    MissingOrUnexpectedToken { expected: &'static str, expected_at: CtxSpan, span: CtxSpan },
    UnexpectedToken(CtxSpan),
    MacroOverwritten { old: CtxSpan, new: CtxSpan, name: String },
}

use PreprocessorDiagnostic::*;
impl_display! {
    match PreprocessorDiagnostic{
        MacroArgumentCountMismatch { expected, found, ..} => "argument mismatch expected {} but found {}!", expected, found;
        MacroNotFound{name,..} =>  "macro '`{}' has not been declared", name;
        MacroNotDefined{name,..} =>  "cannot undefine macro '`{}'", name;
        MacroRecursion { name,..} => "macro '`{}' was called recursively",name;
        IncludeRecursionLimit { file,..} => "'`include \"{}\"' nests too deeply (a file that includes itself?)", file;
        UnsupportedCompDir { name,.. } => "unsupported compiler directive {}",name;
        FileNotFound { file, error, .. } => "failed to read '{}': {}", file, std::io::Error::from(*error);
        InvalidTextFormat {  file, ..} => "failed to read {}: file contents are not valid text", file;
        UnexpectedEof { expected ,..} => "unexpected EOF, expected {}",expected;
        MissingOrUnexpectedToken { expected, ..} => "unexpected token, expected '{}'", expected;
        UnexpectedToken(_) => "encountered unexpected token!";
        MacroOverwritten { name, .. } => "macro '`{}' was overwritten", name;
    }
}
