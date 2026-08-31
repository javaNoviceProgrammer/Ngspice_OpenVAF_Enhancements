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
    /// LRM 10.4: `` `undef `` shall have no effect on predefined Verilog-AMS
    /// macros; the simulator may issue a warning for the attempt.
    UndefPredefined { name: String, span: CtxSpan },
    /// Annex C.4: a directive that exists only in full Verilog-AMS
    /// (`` `default_discipline ``) -- recognized, warned about, and ignored.
    AmsOnlyDirective { name: String, span: CtxSpan },
    /// LRM 10.4: a user `` `define `` whose name begins with `__VAMS_` collides
    /// with the reserved predefined-macro namespace.
    ReservedMacroName { name: String, span: CtxSpan },
    /// `` `begin_keywords `` with a version specifier this implementation does
    /// not recognize (LRM 10.6 names VAMS-2023, VAMS-2.3, 1364-2005,
    /// 1364-2001, 1364-1995).
    UnknownKeywordSet { name: String, span: CtxSpan },
    /// `` `begin_keywords `` naming a valid non-VAMS set: recognized, but this
    /// implementation keeps its single (VAMS-2023) keyword table.
    KeywordSetNotSwitched { name: String, span: CtxSpan },
    /// `` `end_keywords `` with no matching `` `begin_keywords ``.
    UnmatchedEndKeywords { span: CtxSpan },
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
        UndefPredefined { name, .. } => "'`undef' has no effect on the predefined macro '`{}'", name;
        AmsOnlyDirective { name, .. } => "'`{}' is an AMS-only directive and is ignored in Verilog-A", name;
        ReservedMacroName { name, .. } => "macro name '{}' lies in the reserved '__VAMS_' namespace", name;
        UnknownKeywordSet { name, .. } => "unknown '`begin_keywords' version specifier \"{}\"", name;
        KeywordSetNotSwitched { name, .. } => "keyword set \"{}\" is treated as \"VAMS-2023\"", name;
        UnmatchedEndKeywords { .. } => "'`end_keywords' without a matching '`begin_keywords'";
    }
}
