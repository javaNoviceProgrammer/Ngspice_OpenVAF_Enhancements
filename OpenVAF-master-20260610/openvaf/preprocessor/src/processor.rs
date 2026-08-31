use std::io;
use std::iter::once;
use std::sync::Arc;

use ahash::AHashMap;
use stdx::{impl_debug_display, impl_idx_from};
use text_size::{TextRange, TextSize};
use tokens::parser::SyntaxKind;
use tokens::SyntaxKind::{L_PAREN, R_PAREN};
// use tracing::{debug, debug_span, trace};
use typed_index_collections::{TiSlice, TiVec};
use vfs::{FileId, VfsPath};

use crate::diagnostics::PreprocessorDiagnostic::{
    self, MacroArgumentCountMismatch, MacroNotFound, UnexpectedToken,
};
use crate::grammar::{parse_condition, parse_define, parse_include, parse_macro_call};
use crate::parser::{CompilerDirective, Parser, PreprocessorToken};
use crate::sourcemap::{CtxSpan, FileSpan, SourceContext, SourceMap};
use crate::{
    Diagnostics, FileReadError, ScopedTextArea, SourceProvider, Token, PREDEFINED_MACROS,
};

/// The `` `begin_keywords `` version specifiers the LRM (10.6) requires an
/// implementation to accept. This compiler keeps a single keyword table (the
/// VAMS-2023 one), so the VAMS specifiers are silently satisfied and the
/// 1364-* ones are accepted with a warning that the set is not narrowed.
const KNOWN_KEYWORD_SETS: [&str; 5] =
    ["VAMS-2023", "VAMS-2.3", "1364-2005", "1364-2001", "1364-1995"];

pub(crate) struct Processor<'a> {
    pub(crate) source_map: SourceMap,
    sources: &'a dyn SourceProvider,
    arena: &'a ScopedTextArea,
    macros: AHashMap<&'a str, Macro<'a>>,
    include_dirs: Arc<[VfsPath]>,
    /// Name given to the most recently seen `` `default_discipline `` directive, if any.
    /// Not currently consumed downstream (net declarations still require an explicit
    /// discipline), but recording it means the directive is at least recognized instead
    /// of being misparsed as an undefined macro call.
    pub(crate) default_discipline: Option<&'a str>,
    /// Enhancement-65: macros currently being expanded, outermost first.
    /// A macro whose expansion (directly or through other macros) reaches
    /// itself again is reported as `MacroRecursion` instead of overflowing
    /// the compiler stack (the diagnostic existed but was never emitted --
    /// `call_macro`'s "TODO track recursion").
    expansion_stack: Vec<&'a str>,
    /// Enhancement-148: current `` `include `` nesting depth. A file that includes
    /// itself (directly or transitively) is reported as `IncludeRecursionLimit`
    /// instead of overflowing the compiler stack.
    include_depth: u32,
    /// Value of the most recently seen `` `default_transition `` directive
    /// (Enhancement-47): the default rise/fall time for `transition()` filters
    /// that omit those arguments. `None` = 0 (instantaneous, the LRM default).
    pub(crate) default_transition: Option<ordered_float::OrderedFloat<f64>>,
    /// True while the virtual `-D` definitions file is processed: the
    /// predefined `__VAMS_*`/`__OPENVAF__` macros are legitimately defined
    /// there, so the reserved-namespace warning must not fire for them.
    in_defines_file: bool,
    /// Nesting depth of `` `begin_keywords `` regions (LRM 10.6).
    keyword_set_depth: u32,
}

impl<'a> Processor<'a> {
    pub fn new(
        storage: &'a ScopedTextArea,
        root_file: FileId,
        sources: &'a dyn SourceProvider,
    ) -> Result<Self, FileReadError> {
        let src = sources.file_text(root_file)?;
        let src = storage.ensure(src);
        // Enhancement-387: the `-D` flags are no longer synthesised into macros
        // here. They are written into a virtual source file (see `defines_src` in
        // hir/src/db.rs) and processed by `run()` below through the ordinary
        // ``define`` path, so `-DK=5.5` actually substitutes 5.5 and a bare `-DK`
        // expands to the documented "1". Synthesising them here could not do
        // that: a macro body is a Vec<ParsedToken> whose text resolves BY SPAN
        // against a real file, and a value from argv has no backing text.
        let macros = AHashMap::default();
        let res = Self {
            source_map: SourceMap::new(root_file, TextSize::of(src)),
            macros,
            arena: storage,
            sources,
            include_dirs: sources.include_dirs(root_file),
            expansion_stack: Vec::new(),
            include_depth: 0,
            default_discipline: None,
            default_transition: None,
            in_defines_file: false,
            keyword_set_depth: 0,
        };
        Ok(res)
    }

    pub fn run(&mut self, file: FileId) -> (Vec<Token>, Diagnostics) {
        let working_dir = self.sources.file_path(file).parent().unwrap();

        let mut err = Diagnostics::new();
        let mut dst = Vec::new();

        // Enhancement-387: process the `-D` definitions first, as ordinary source.
        // They contain only ``define`` directives, so nothing reaches `dst`; what
        // they leave behind is `self.macros`, populated with REAL spans -- which
        // is what lets a `-D` value be substituted at all.
        self.process_defines(&mut dst, &mut err);

        let parser =
            Parser::new(self.arena.get(0), SourceContext::ROOT, working_dir, &mut dst, &mut err);
        self.process_file(parser, &mut err);

        (dst, err)
    }

    /// Enhancement-387: run the virtual `-D` definitions file through the normal
    /// preprocessor path. Silently does nothing when it is absent or empty, so a
    /// compilation with no `-D` flags is byte-for-byte what it was before.
    fn process_defines(&mut self, dst: &mut Vec<Token>, errors: &mut Diagnostics) {
        const DEFINES_FILE: &str = "/std/__openvaf_defines__.va";
        let path = VfsPath::new_virtual_path(DEFINES_FILE.to_owned());
        let file = self.sources.file_id(path);
        let src = match self.sources.file_text(file) {
            Ok(src) if !src.is_empty() => src,
            _ => return,
        };
        let src = self.arena.ensure(src);
        let workdir = self.sources.file_path(file).parent().unwrap();
        let ctx = self.source_map.add_ctx(
            FileSpan { file, range: TextRange::up_to(TextSize::of(src)) },
            CtxSpan { range: TextRange::empty(0.into()), ctx: SourceContext::ROOT },
        );
        let parser = Parser::new(src, ctx, workdir, dst, errors);
        self.in_defines_file = true;
        self.process_file(parser, errors);
        self.in_defines_file = false;
    }

    pub(crate) fn is_macro_defined(&mut self, name: &'a str) -> bool {
        self.macros.contains_key(name)
    }

    pub(crate) fn include_file(
        &mut self,
        path: &str,
        span: CtxSpan,
        dst: &mut Vec<Token>,
        errors: &mut Diagnostics,
        workdir: &VfsPath,
    ) -> Result<(), (FileReadError, Option<VfsPath>)> {
        // Enhancement-148: bound `include nesting so a file that includes itself
        // (directly or transitively) is reported cleanly instead of recursing until
        // the compiler stack overflows.
        const MAX_INCLUDE_DEPTH: u32 = 64;
        if self.include_depth >= MAX_INCLUDE_DEPTH {
            errors.push(PreprocessorDiagnostic::IncludeRecursionLimit {
                file: path.to_owned(),
                span,
            });
            return Ok(());
        }
        let mut include_dirs = once(workdir).chain(&*self.include_dirs);
        let found = loop {
            if let Some(dir) = include_dirs.next() {
                if let Some(path) = dir.join(path) {
                    let file = self.sources.file_id(path.clone());
                    match self.sources.file_text(file) {
                        Ok(contents) => break Some((contents, file)),
                        Err(FileReadError::Io(io::ErrorKind::NotFound)) => (),
                        Err(err) => return Err((err, Some(path))),
                    }
                }
            } else {
                break None;
            }
        };
        let (src, file) = found.ok_or((FileReadError::Io(io::ErrorKind::NotFound), None))?;
        let src = self.arena.ensure(src);
        let workdir = self.sources.file_path(file).parent().unwrap();

        let ctx = self
            .source_map
            .add_ctx(FileSpan { file, range: TextRange::up_to(TextSize::of(src)) }, span);

        let parser = Parser::new(src, ctx, workdir, dst, errors);
        self.include_depth += 1;
        self.process_file(parser, errors);
        self.include_depth -= 1;

        Ok(())
    }

    pub(crate) fn define_macro(
        &mut self,
        name: &'a str,
        def: Macro<'a>,
        diagnostics: &mut Diagnostics,
    ) {
        // LRM 10.4: user macro names shall not begin with `__VAMS_` (that
        // namespace belongs to the predefined macros). The virtual `-D`
        // definitions file is where the predefined macros themselves are
        // defined, so it is exempt.
        if !self.in_defines_file && (name.starts_with("__VAMS_") || name == "__OPENVAF__") {
            diagnostics.push(PreprocessorDiagnostic::ReservedMacroName {
                name: name.to_owned(),
                span: def.head_span(),
            });
        }
        let span = def.head_span();
        if let Some(old) = self.macros.insert(name, def) {
            diagnostics.push(PreprocessorDiagnostic::MacroOverwritten {
                old: old.head_span(),
                new: span,
                name: name.to_owned(),
            })
        }
    }

    fn process_macro_token(
        &mut self,
        token: &ParsedTokenKind<'a>,
        span: CtxSpan,
        args: &TiSlice<MacroArg, Vec<Token>>,
        dst: &mut Vec<Token>,
        errors: &mut Diagnostics,
    ) {
        match *token {
            ParsedTokenKind::ResolvedToken(kind) => dst.push(Token { kind, span }),
            ParsedTokenKind::ArgumentReference(arg) => {
                dst.extend(&args[arg]);
            }
            ParsedTokenKind::MacroCall(ref call) => self.call_macro(call, span, args, dst, errors),
        }
    }

    pub(crate) fn call_macro(
        &mut self,
        call: &MacroCall<'a>,
        span: CtxSpan,
        args: &TiSlice<MacroArg, Vec<Token>>,
        dst: &mut Vec<Token>,
        errors: &mut Diagnostics,
    ) {
        // Enhancement-65: a macro reached again while its BODY is still being
        // expanded (directly or through other macros) is infinite recursion --
        // report it instead of blowing the compiler stack. The name is pushed
        // only around the body expansion below: a nested call of the same
        // macro inside an ARGUMENT (`QUAD(x)` defined as `TWICE(`TWICE(x))`)
        // is finite and legal, and argument tokens belong to the caller's
        // expansion, not to this macro's own.
        if self.expansion_stack.iter().any(|&n| n == call.name) {
            errors.push(PreprocessorDiagnostic::MacroRecursion {
                name: call.name.to_owned(),
                span,
            });
            return;
        }

        let parent_ctx_span = self.source_map.ctx_data(span.ctx).decl.range.start();
        if let Some(def) = self.macros.get(&call.name).cloned() {
            let new_args: TiVec<_, _> = call
                .arg_bindings
                .iter()
                .map(|(arg, _decl)| {
                    let mut dst = Vec::new();
                    for ParsedToken { kind, range } in arg {
                        // trace!(range = debug(range), "Arg token");
                        let span = CtxSpan { range: range - parent_ctx_span, ctx: span.ctx };
                        self.process_macro_token(kind, span, args, &mut dst, errors)
                    }
                    dst
                })
                .collect();

            if new_args.len() == def.arg_cnt || def.arg_cnt == 0 {
                let ctx = self.source_map.add_ctx(def.span.to_file_span(&self.source_map), span);
                self.expansion_stack.push(call.name);
                for ParsedToken { kind, range } in &def.body {
                    let span = CtxSpan { range: range - def.span.range.start(), ctx };
                    self.process_macro_token(kind, span, &new_args, dst, errors)
                }
                self.expansion_stack.pop();
                if new_args.len() > def.arg_cnt {
                    // macro definition has no arguments, but some were parsed as part of the call
                    // so put the arguments back
                    dst.push(Token { kind: L_PAREN, span });
                    for arg in new_args {
                        for tok in arg {
                            dst.push(tok)
                        }
                    }
                    dst.push(Token { kind: R_PAREN, span });
                }
            } else {
                errors.push(MacroArgumentCountMismatch {
                    expected: def.arg_cnt,
                    found: new_args.len(),
                    span,
                })
            }
        } else {
            errors.push(MacroNotFound { name: call.name.to_owned(), span })
        }
    }

    pub(crate) fn process_file(&mut self, mut p: Parser<'a, '_>, err: &mut Diagnostics) {
        while !p.at(PreprocessorToken::Eof) {
            self.process_token(&mut p, err)
        }
    }

    pub(crate) fn process_token(&mut self, p: &mut Parser<'a, '_>, err: &mut Diagnostics) {
        match p.current() {
            PreprocessorToken::Define { end } => {
                if let Some((name, def)) = parse_define(p, err, &mut self.source_map, end) {
                    self.define_macro(name, def, err)
                }
            }
            PreprocessorToken::CompilerDirective => match p.compiler_directive() {
                CompilerDirective::Include => {
                    if let Some((file_name, range)) = parse_include(p, err) {
                        let span = CtxSpan { range, ctx: p.ctx() };
                        match self.include_file(file_name, span, p.dst, err, &p.working_dir) {
                            Ok(_) => (),
                            Err((FileReadError::InvalidTextFormat(err_msg), file)) => {
                                err.push(PreprocessorDiagnostic::InvalidTextFormat {
                                    file: file.unwrap(),
                                    span: Some(span),
                                    err: err_msg,
                                })
                            }
                            Err((FileReadError::Io(kind), file)) => {
                                err.push(PreprocessorDiagnostic::FileNotFound {
                                    file: file.map_or_else(
                                        || file_name.to_owned(),
                                        |path| path.to_string(),
                                    ),
                                    error: kind,
                                    span: Some(span),
                                })
                            }
                        }
                    }
                }
                CompilerDirective::IfDef => {
                    // let _span = debug_span!("preprocessing `ifdef");
                    // let _tspan = _span.enter();
                    p.bump();
                    parse_condition(p, err, self, false);
                }
                CompilerDirective::IfNotDef => {
                    // let _span = debug_span!("preprocessing `ifndef");
                    // let _tspan = _span.enter();
                    p.bump();
                    parse_condition(p, err, self, true);
                }
                CompilerDirective::Undef => {
                    p.bump();
                    let name = p.current_text();
                    if PREDEFINED_MACROS.contains(&name) {
                        // LRM 10.4: `undef shall have no effect on predefined
                        // Verilog-AMS macros; a warning may be issued.
                        err.push(PreprocessorDiagnostic::UndefPredefined {
                            name: name.to_owned(),
                            span: p.current_span(),
                        })
                    } else if self.macros.contains_key(name) {
                        self.macros.remove(name);
                    } else {
                        err.push(PreprocessorDiagnostic::MacroNotDefined {
                            name: name.to_owned(),
                            span: p.current_span(),
                        })
                    }
                    p.bump();
                }
                CompilerDirective::ResetAll => {
                    // LRM 10 / IEEE 1364 19.6: reset all compiler directives to
                    // their default values. Text macros are not directives and
                    // survive; the directive state this compiler tracks is
                    // `` `default_transition ``/`` `default_discipline ``.
                    self.default_transition = None;
                    self.default_discipline = None;
                    p.bump();
                }
                CompilerDirective::UndefineAll => {
                    p.bump();
                    // LRM 10.4 protects the predefined macros from undefinition.
                    self.macros.retain(|name, _| PREDEFINED_MACROS.contains(name));
                }
                CompilerDirective::BeginKeywords => {
                    // `` `begin_keywords "VAMS-2023" `` (LRM 10.6). This
                    // implementation has exactly one keyword table (VAMS-2023),
                    // so the VAMS specifiers are satisfied as-is and the 1364-*
                    // ones are accepted with a warning that the reserved set is
                    // not narrowed. The directive only selects reserved words;
                    // it never changes semantics (LRM 10.6).
                    p.bump();
                    self.keyword_set_depth += 1;
                    if p.at(PreprocessorToken::StrLit) {
                        let name = p.current_text().trim_matches('"').to_owned();
                        if !KNOWN_KEYWORD_SETS.contains(&name.as_str()) {
                            err.push(PreprocessorDiagnostic::UnknownKeywordSet {
                                name,
                                span: p.current_span(),
                            });
                        } else if !name.starts_with("VAMS") {
                            err.push(PreprocessorDiagnostic::KeywordSetNotSwitched {
                                name,
                                span: p.current_span(),
                            });
                        }
                        p.bump();
                    } else {
                        err.push(PreprocessorDiagnostic::MissingOrUnexpectedToken {
                            expected: "a version specifier string such as \"VAMS-2023\"",
                            expected_at: p.current_span(),
                            span: p.current_span(),
                        });
                    }
                }
                CompilerDirective::EndKeywords => {
                    if self.keyword_set_depth == 0 {
                        err.push(PreprocessorDiagnostic::UnmatchedEndKeywords {
                            span: p.current_span(),
                        });
                    } else {
                        self.keyword_set_depth -= 1;
                    }
                    p.bump();
                }
                CompilerDirective::CellDefine | CompilerDirective::EndCellDefine => {
                    // Purely a documentation boundary marker for external tools; no
                    // semantic effect on Verilog-A compilation.
                    p.bump();
                }
                CompilerDirective::NoUnconnectedDrive => {
                    // No arguments; restores default (error-on-floating-port) behavior.
                    p.bump();
                }
                CompilerDirective::UnconnectedDrive => {
                    // Takes a single `pull0`/`pull1`/`highz` argument. OpenVAF-r has no
                    // unconnected-port drive model to apply this to, so it's parsed and
                    // discarded rather than left to hard-fail as an unknown macro call.
                    p.skip_rest_of_line(err);
                }
                CompilerDirective::DefaultNetType => {
                    // Takes a single net-type argument (`wire`, `tri`, `none`, ...).
                    // OpenVAF-r requires an explicit discipline on every net, so there is
                    // no implicit net type to default; parsed and discarded.
                    p.skip_rest_of_line(err);
                }
                CompilerDirective::DefaultDiscipline => {
                    self.default_discipline = p.bump_directive_and_capture_ident(err);
                    p.skip_rest_of_line(err);
                }
                CompilerDirective::DefaultTransition => {
                    // `` `default_transition <time> `` (Enhancement-47): the default
                    // rise/fall time for `transition()` filters that omit those
                    // arguments. The last directive seen wins (file-level
                    // granularity; real models declare at most one).
                    if let Some(text) =
                        p.bump_directive_and_capture_number(err).and_then(parse_si_number)
                    {
                        self.default_transition = Some(ordered_float::OrderedFloat(text));
                    }
                    p.skip_rest_of_line(err);
                }
                CompilerDirective::TimeScale | CompilerDirective::Line => {
                    p.skip_rest_of_line(err);
                }
                CompilerDirective::Pragma => {
                    // Tool-specific hints (e.g. `protect`/`endprotect` encryption pragmas
                    // in some vendor files) are not implemented; unrecognized pragmas are
                    // ignorable per the LRM.
                    p.skip_rest_of_line(err);
                }
                CompilerDirective::Macro => {
                    let (call, range) =
                        parse_macro_call(p, err, &[], &mut self.source_map, p.end());
                    let span = CtxSpan { range, ctx: p.ctx() };
                    self.call_macro(&call, span, TiSlice::from_ref(&[]), p.dst, err);
                }

                _ => {
                    err.push(UnexpectedToken(p.current_span()));
                    p.bump()
                }
            },

            _ => p.save_token(err),
        }
    }
}

pub(crate) type MacroArgs<'s> = TiVec<MacroArg, (Vec<ParsedToken<'s>>, TextRange)>;

#[derive(PartialEq, Eq, PartialOrd, Ord, Clone, Copy, Hash)]
pub(crate) struct MacroArg(u8);

impl_idx_from!(MacroArg(u8));
impl_debug_display!(c@MacroArg => "arg{}",c.0);

#[derive(Clone, Debug, Eq, PartialEq)]
pub(crate) struct ParsedToken<'s> {
    pub(crate) range: TextRange,
    pub(crate) kind: ParsedTokenKind<'s>,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub(crate) enum ParsedTokenKind<'s> {
    ResolvedToken(SyntaxKind),
    ArgumentReference(MacroArg),
    MacroCall(MacroCall<'s>),
}

impl From<SyntaxKind> for ParsedTokenKind<'static> {
    fn from(value: SyntaxKind) -> ParsedTokenKind<'static> {
        ParsedTokenKind::ResolvedToken(value)
    }
}
#[derive(Debug, Clone)]
pub(crate) struct Macro<'s> {
    pub head: TextSize,
    pub span: CtxSpan,
    pub body: Vec<ParsedToken<'s>>,
    pub arg_cnt: usize,
}

impl Macro<'_> {
    pub fn head_span(&self) -> CtxSpan {
        self.span.with_len(self.head)
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub(crate) struct MacroCall<'s> {
    pub name: &'s str,
    pub arg_bindings: MacroArgs<'s>,
}

/// Parses a number with an optional SI scale suffix (`1u`, `10n`, `1e-6`,
/// `0.5m`, with `_` separators allowed), as used by `` `default_transition ``.
fn parse_si_number(text: &str) -> Option<f64> {
    let text: String = text.chars().filter(|&c| c != '_').collect();
    let (num, exp) = match text.chars().last()? {
        'T' => (&text[..text.len() - 1], 12),
        'G' => (&text[..text.len() - 1], 9),
        'M' => (&text[..text.len() - 1], 6),
        'K' | 'k' => (&text[..text.len() - 1], 3),
        'm' => (&text[..text.len() - 1], -3),
        'u' => (&text[..text.len() - 1], -6),
        'n' => (&text[..text.len() - 1], -9),
        'p' => (&text[..text.len() - 1], -12),
        'f' => (&text[..text.len() - 1], -15),
        'a' => (&text[..text.len() - 1], -18),
        _ => (text.as_str(), 0),
    };
    num.parse::<f64>().ok().map(|v| v * 10f64.powi(exp))
}
