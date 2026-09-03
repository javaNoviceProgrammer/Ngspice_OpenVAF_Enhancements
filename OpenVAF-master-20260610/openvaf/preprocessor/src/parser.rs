use std::cmp::min;
use std::ops::Range;

use stdx::impl_idx_math_from;
use text_size::{TextRange, TextSize};
use tokens::lexer::{LiteralKind, Token, TokenKind};
use tokens::parser::SyntaxKind;
use tokens::LexerErrorKind;
// use tracing::debug;
use typed_index_collections::{TiSlice, TiVec};
use vfs::VfsPath;

use crate::diagnostics::PreprocessorDiagnostic;
use crate::processor::{ParsedToken, ParsedTokenKind};
use crate::sourcemap::{CtxSpan, SourceContext};
use crate::Diagnostics;

#[derive(PartialEq, Eq, PartialOrd, Ord, Clone, Copy, Debug)]
pub struct FullTokenIdx(u32);
impl_idx_math_from!(FullTokenIdx(u32));

#[derive(PartialEq, Eq, PartialOrd, Ord, Clone, Copy, Debug)]
pub struct RelevantTokenIdx(u32);
impl_idx_math_from!(RelevantTokenIdx(u32));

pub(crate) struct Parser<'a, 'd> {
    full_tokens: TiVec<FullTokenIdx, tokens::lexer::Token>,
    relevant_tokens: TiVec<RelevantTokenIdx, (PreprocessorToken, FullTokenIdx)>,
    previous_offset: TextSize,
    offset: TextSize,
    token: PreprocessorToken,
    pos: RelevantTokenIdx,
    full_token_pos: FullTokenIdx,
    src: &'a str,
    pub(crate) ctx: SourceContext,
    pub(crate) dst: &'d mut Vec<crate::Token>,
    pub(crate) working_dir: VfsPath,
}

fn mk_token(
    pos: RelevantTokenIdx,
    relevant_tokens: &TiSlice<RelevantTokenIdx, (PreprocessorToken, FullTokenIdx)>,
    file_end: FullTokenIdx,
) -> (PreprocessorToken, FullTokenIdx) {
    relevant_tokens
        .get(pos)
        .map_or((PreprocessorToken::Eof, file_end), |(token, pos)| (*token, *pos))
}

impl<'a, 'd> Parser<'a, 'd> {
    pub(crate) fn new(
        src: &'a str,
        ctx: SourceContext,
        working_dir: VfsPath,
        dst: &'d mut Vec<crate::Token>,
        err: &mut Vec<PreprocessorDiagnostic>,
    ) -> Self {
        let full_tokens = TiVec::from(lexer::tokenize(src));
        let mut relevant_tokens: TiVec<_, _> = full_tokens
            .iter_enumerated()
            .filter_map(|(pos, token)| {
                let token = match token.kind {
                    TokenKind::Define { end } => {
                        PreprocessorToken::Define { end: FullTokenIdx::from(end) }
                    }
                    TokenKind::SimpleIdent => PreprocessorToken::SimpleIdent,
                    TokenKind::OpenParen => PreprocessorToken::OpenParen,
                    TokenKind::CloseParen => PreprocessorToken::CloseParen,
                    TokenKind::Comma => PreprocessorToken::Comma,
                    TokenKind::CompilerDirective => PreprocessorToken::CompilerDirective,
                    TokenKind::Literal { kind: LiteralKind::Str { .. } } => {
                        PreprocessorToken::StrLit
                    }
                    TokenKind::Whitespace
                    | TokenKind::LineComment
                    | TokenKind::BlockComment { .. } => return None,
                    _ => PreprocessorToken::Other,
                };
                Some((token, pos))
            })
            .collect();

        relevant_tokens.push((PreprocessorToken::Eof, full_tokens.next_key()));
        dst.reserve(full_tokens.len());

        let (token, full_token_pos) =
            mk_token(RelevantTokenIdx(0), &relevant_tokens, full_tokens.next_key());

        let mut res = Self {
            relevant_tokens,
            full_tokens,
            src,
            ctx,
            dst,
            working_dir,
            previous_offset: 0.into(),
            offset: 0.into(),
            token,
            pos: RelevantTokenIdx(0),
            full_token_pos,
        };

        res.advance(true, 0u32.into(), err);
        res
    }

    pub(crate) fn before(&self, end: FullTokenIdx) -> bool {
        self.full_token_pos < end
    }

    pub(crate) fn current(&self) -> PreprocessorToken {
        self.token
    }

    pub(crate) fn current_range(&self) -> TextRange {
        TextRange::at(
            self.offset,
            self.full_tokens.get(self.full_token_pos).map_or(0.into(), |t| t.len),
        )
    }

    pub(crate) fn current_span(&self) -> CtxSpan {
        CtxSpan { range: self.current_range(), ctx: self.ctx }
    }

    pub(crate) fn current_text(&self) -> &'a str {
        &self.src[self.current_range()]
    }

    pub(crate) fn end(&self) -> FullTokenIdx {
        self.full_tokens.next_key() - 1u32
    }

    pub(crate) fn end_pos(&self, end: FullTokenIdx) -> TextSize {
        let pos = self.relevant_tokens[self.pos].1;
        let len: TextSize = self.full_tokens[end..pos].iter().map(|t| t.len).sum();
        self.offset - len
    }

    pub(crate) fn previous_range(&self) -> TextRange {
        let pos =
            self.relevant_tokens.get(self.pos - 1u32).map_or(self.full_token_pos, |(_, pos)| *pos);
        // Enhancement-213: at end of file `pos` can be one past the last token
        // (e.g. a bare "`define" that ends the file). Indexing directly panicked
        // while building the "expected an identifier" diagnostic; fall back to a
        // zero length, exactly as current_range() above already does.
        let len = self.full_tokens.get(pos).map_or(0.into(), |t| t.len);
        TextRange::at(self.previous_offset, len)
    }

    pub(crate) fn followed_by_bracket_without_space(&self) -> bool {
        // Enhancement-213: at end of file there is no next token -- a bare
        // "`define" that ends the file asks for one past the last -- and
        // indexing directly panicked. Nothing follows, so it certainly is not
        // followed by a bracket.
        match self.relevant_tokens.get(self.pos + 1u32) {
            Some(&(token, idx)) => {
                token == PreprocessorToken::OpenParen && idx == (self.full_token_pos + 1u32)
            }
            None => false,
        }
    }

    fn do_bump(&mut self, save: bool, err: &mut Vec<PreprocessorDiagnostic>) {
        // trace!(token = display(self.current()), save = save_token, "bump");

        if self.token == PreprocessorToken::Eof {
            return;
        }

        self.previous_offset = self.offset;
        let start = self.full_token_pos;

        let (token, full_token_pos) =
            mk_token(self.pos + 1u32, &self.relevant_tokens, self.full_tokens.next_key());
        self.token = token;
        self.full_token_pos = full_token_pos;
        self.pos += 1u32;
        self.advance(save, start, err);
    }

    fn advance(&mut self, save: bool, start: FullTokenIdx, err: &mut Vec<PreprocessorDiagnostic>) {
        let range = start..self.full_token_pos;
        if save {
            self.dst.extend(self.full_tokens[range].iter().filter_map(|token| {
                let res = Self::convert_lexer_token(*token, self.offset, self.src, err, self.ctx);
                self.offset += token.len;
                let (kind, range) = res?;
                Some(crate::Token { span: CtxSpan { range, ctx: self.ctx }, kind })
            }))
        } else {
            let len: TextSize = self.full_tokens[range].iter().map(|token| token.len).sum();
            self.offset += len;
        }
    }

    fn convert_lexer_token(
        token: Token,
        offset: TextSize,
        src: &str,
        err: &mut Vec<PreprocessorDiagnostic>,
        ctx: SourceContext,
    ) -> Option<(SyntaxKind, TextRange)> {
        let range = TextRange::at(offset, token.len);
        let (syntax, error) = token.kind.to_syntax(&src[range]);
        if let Some(error) = error {
            let span = CtxSpan { range, ctx };
            match error {
                LexerErrorKind::UnterminatedStr => {
                    err.push(PreprocessorDiagnostic::UnexpectedEof { expected: "\"", span })
                }
                LexerErrorKind::UnexpectedToken => {
                    err.push(PreprocessorDiagnostic::UnexpectedToken(span))
                }
                LexerErrorKind::UnterminatedBlockComment => {
                    err.push(PreprocessorDiagnostic::UnexpectedEof { expected: "*/", span })
                }
            }
        }

        syntax.map(|kind| (kind, range))
    }
    fn save_tokens_to_macro(
        &mut self,
        range: Range<FullTokenIdx>,
        dst: &mut Vec<ParsedToken<'a>>,
        err: &mut Vec<PreprocessorDiagnostic>,
    ) {
        for token in self.full_tokens[range].iter() {
            // The IEEE 1364-2005 19.3.1 macro operators (via LRM 10.4) are
            // only meaningful in macro text. They are stored as markers the
            // expansion interprets -- `to_syntax` would report them as the
            // errors they are everywhere else.
            let marker = match token.kind {
                TokenKind::MacroQuote => Some(ParsedTokenKind::Quote),
                TokenKind::MacroEscQuote => Some(ParsedTokenKind::EscQuote),
                TokenKind::Paste => Some(ParsedTokenKind::Paste),
                _ => None,
            };
            if let Some(kind) = marker {
                let range = TextRange::at(self.offset, token.len);
                self.offset += token.len;
                dst.push(ParsedToken { kind, range });
                continue;
            }
            let res = Self::convert_lexer_token(*token, self.offset, self.src, err, self.ctx);
            self.offset += token.len;
            if let Some((kind, range)) = res {
                dst.push(ParsedToken { kind: kind.into(), range });
            }
        }
    }

    pub(crate) fn bump_to_macro(
        &mut self,
        dst: &mut Vec<ParsedToken<'a>>,
        end: FullTokenIdx,
        err: &mut Vec<PreprocessorDiagnostic>,
    ) {
        if self.token == PreprocessorToken::Eof {
            return;
        }

        self.previous_offset = self.offset;
        let start = self.full_token_pos;

        let (token, full_token_pos) =
            mk_token(self.pos + 1u32, &self.relevant_tokens, self.full_tokens.next_key());
        self.token = token;
        self.full_token_pos = full_token_pos;
        self.pos += 1u32;
        let macro_end = min(end, self.full_token_pos);
        self.save_tokens_to_macro(start..macro_end, dst, err);
        self.advance(true, macro_end, err)
    }

    pub(crate) fn expect(
        &mut self,
        token: PreprocessorToken,
        expected: &'static str,
        errors: &mut Diagnostics,
    ) -> bool {
        if !self.eat(token) {
            // debug!("syntax error: expected {:?} but found {:?}", token, self.current());
            errors.push(PreprocessorDiagnostic::MissingOrUnexpectedToken {
                expected,
                expected_at: CtxSpan { range: self.previous_range(), ctx: self.ctx },
                span: CtxSpan { range: self.current_range(), ctx: self.ctx },
            });
            // self.eat(RawToken::Unexpected); // Only report lexer errors once
            false
        } else {
            true
        }
    }

    pub(crate) fn at(&self, token: PreprocessorToken) -> bool {
        self.current() == token
    }

    pub(crate) fn ctx(&self) -> SourceContext {
        self.ctx
    }

    /// Consume the next token if `kind` matches.
    pub(crate) fn eat(&mut self, token: PreprocessorToken) -> bool {
        if !self.at(token) {
            return false;
        }
        self.do_bump(false, &mut Vec::new());
        true
    }

    /// Consume the next token if `kind` matches.
    pub(crate) fn bump(&mut self) {
        self.do_bump(false, &mut Vec::new())
    }

    // pub(crate) fn bump(&mut self) {
    //     self.do_bump(false);
    // }

    /// Advances the parser by one token
    pub(crate) fn save_token(&mut self, err: &mut Vec<PreprocessorDiagnostic>) {
        self.do_bump(true, err)
    }

    pub(crate) fn compiler_directive(&self) -> CompilerDirective {
        match self.current_text() {
            "`include" => CompilerDirective::Include,
            "`ifdef" => CompilerDirective::IfDef,
            "`ifndef" => CompilerDirective::IfNotDef,
            "`else" => CompilerDirective::Else,
            "`elsif" => CompilerDirective::ElseIf,
            "`endif" => CompilerDirective::EndIf,
            "`undef" => CompilerDirective::Undef,
            "`resetall" => CompilerDirective::ResetAll,
            "`undefineall" => CompilerDirective::UndefineAll,
            "`celldefine" => CompilerDirective::CellDefine,
            "`endcelldefine" => CompilerDirective::EndCellDefine,
            "`default_discipline" => CompilerDirective::DefaultDiscipline,
            "`default_transition" => CompilerDirective::DefaultTransition,
            "`default_nettype" => CompilerDirective::DefaultNetType,
            "`unconnected_drive" => CompilerDirective::UnconnectedDrive,
            "`nounconnected_drive" => CompilerDirective::NoUnconnectedDrive,
            "`timescale" => CompilerDirective::TimeScale,
            "`line" => CompilerDirective::Line,
            "`pragma" => CompilerDirective::Pragma,
            "`begin_keywords" => CompilerDirective::BeginKeywords,
            "`end_keywords" => CompilerDirective::EndKeywords,
            _ => CompilerDirective::Macro,
        }
    }

    /// Skips (without emitting into the output token stream) every token that
    /// starts before the end of the current source line. Used for compiler
    /// directives whose argument grammar we don't need to parse precisely
    /// (`` `timescale ``, `` `line ``, `` `pragma ``, ...): such directives are
    /// always terminated by the end of the line they appear on, per the
    /// Verilog/Verilog-AMS LRM, so this reliably consumes exactly their
    /// arguments without needing a dedicated per-directive grammar.
    pub(crate) fn skip_rest_of_line(&mut self, err: &mut Vec<PreprocessorDiagnostic>) {
        let line_end = self.src[usize::from(self.offset)..]
            .find('\n')
            .map(|i| self.offset + TextSize::from(i as u32))
            .unwrap_or_else(|| TextSize::of(self.src));
        while self.token != PreprocessorToken::Eof && self.offset < line_end {
            self.do_bump(false, err);
        }
    }

    /// Bumps the current (directive) token, then returns the text of the next
    /// token if it is a simple identifier (without consuming the rest of the
    /// line) -- used for directives that take a single identifier argument
    /// (`` `default_discipline foo ``, `` `unconnected_drive pull1 ``, ...).
    pub(crate) fn bump_directive_and_capture_ident(
        &mut self,
        err: &mut Vec<PreprocessorDiagnostic>,
    ) -> Option<&'a str> {
        self.do_bump(false, err);
        if self.token == PreprocessorToken::SimpleIdent {
            Some(self.current_text())
        } else {
            None
        }
    }

    /// Bumps the current (directive) token, then returns the text of the next
    /// token if it looks like a number (a literal classifies as `Other` here) --
    /// used for `` `default_transition 1u `` (Enhancement-47).
    pub(crate) fn bump_directive_and_capture_number(
        &mut self,
        err: &mut Vec<PreprocessorDiagnostic>,
    ) -> Option<&'a str> {
        self.do_bump(false, err);
        if self.token == PreprocessorToken::Other
            && self.current_text().starts_with(|c: char| c.is_ascii_digit() || c == '.')
        {
            Some(self.current_text())
        } else {
            None
        }
    }
}

#[derive(PartialEq, Eq, Clone, Copy, Debug)]
pub enum PreprocessorToken {
    Define { end: FullTokenIdx },
    StrLit,
    SimpleIdent,
    OpenParen,
    CloseParen,
    CompilerDirective,
    Comma,
    Other,
    Eof,
}

#[derive(PartialEq, Eq, Clone, Copy, Debug)]
pub enum CompilerDirective {
    Include,
    IfDef,
    IfNotDef,
    Else,
    ElseIf,
    EndIf,
    Undef,
    ResetAll,
    UndefineAll,
    CellDefine,
    EndCellDefine,
    DefaultDiscipline,
    DefaultTransition,
    DefaultNetType,
    UnconnectedDrive,
    NoUnconnectedDrive,
    TimeScale,
    Line,
    Pragma,
    BeginKeywords,
    EndKeywords,
    Macro,
}
