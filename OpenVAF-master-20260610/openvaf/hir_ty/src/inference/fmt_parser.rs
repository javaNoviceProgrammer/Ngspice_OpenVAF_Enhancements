use std::str::CharIndices;

use hir_def::ExprId;
use syntax::{TextRange, TextSize};

use crate::inference::InferenceDiagnostic;

#[derive(PartialEq, Eq, PartialOrd, Ord, Copy, Clone)]
enum ParserState {
    Flags,
    FixedFmtLit,
    DynamicFmtLit,
    AnyPrecision,
    FixedPrecision,
    DynamicPrecsion,
}

impl ParserState {
    fn start_precision(self) -> bool {
        self < Self::AnyPrecision
    }

    fn eat_number(self) -> bool {
        matches!(self, Self::FixedPrecision | Self::FixedFmtLit)
    }
    fn candidates(self) -> &'static [char] {
        match self {
            ParserState::Flags => &[
                '-', '+', ' ', '#', '0', '1', '2', '3', '4', '5', '6', '7', '8', '9', '*', '.',
                'e', 'E', 'f', 'F', 'g', 'G', 'r', 'R', '%', 'm', 'M', 'l', 'L', 'd', 'D', 'h',
                'H', 'o', 'O', 'b', 'B', 'c', 'C', 's', 'S',
            ],
            ParserState::FixedFmtLit => &[
                '0', '1', '2', '3', '4', '5', '6', '7', '8', '9', '.', 'e', 'E', 'f', 'F', 'g',
                'G', 'r', 'R', 'd', 'D', 'h', 'H', 'o', 'O', 'b', 'B', 'c', 'C', 's', 'S',
            ],
            ParserState::DynamicFmtLit => &[
                '.', 'e', 'E', 'f', 'F', 'g', 'G', 'r', 'R', 'd', 'D', 'h', 'H', 'o', 'O', 'b',
                'B', 'c', 'C', 's', 'S',
            ],
            ParserState::AnyPrecision => &['0', '1', '2', '3', '4', '5', '6', '7', '8', '9', '*'],
            ParserState::FixedPrecision => &[
                '0', '1', '2', '3', '4', '5', '6', '7', '8', '9', 'e', 'E', 'f', 'F', 'g', 'G',
                'r', 'R', 'd', 'D', 'h', 'H', 'o', 'O', 'b', 'B', 'c', 'C', 's', 'S',
            ],
            ParserState::DynamicPrecsion => &[
                'e', 'E', 'f', 'F', 'g', 'G', 'r', 'R', 'd', 'D', 'h', 'H', 'o', 'O', 'b', 'B',
                'c', 'C', 's', 'S',
            ],
        }
    }
}

pub struct ParseResult {
    pub dynamic_args: Vec<TextSize>,
    pub err: Option<InferenceDiagnostic>,
    pub end: TextSize,
    /// Enhancement-71: the conversion character that terminated the
    /// specifier (`d`, `s`, `g`, ...) -- flags/width/precision are legal
    /// for EVERY conversion, not just the real ones, so the caller maps
    /// this to the expected argument type. `\0` when `err` is set.
    pub conversion: char,
}

pub fn parse_fmt_spec(
    start: u32,
    fmt_expr: ExprId,
    mut pos: Option<(usize, char)>,
    chars: &mut CharIndices,
) -> ParseResult {
    let mut state = ParserState::Flags;
    let mut end = start + 1;
    let mut dynamic_args = Vec::new();
    let mut err = None;
    let mut conversion = '\0';
    loop {
        if let Some((off, c)) = pos {
            end = (off + c.len_utf8()) as u32;
            match c {
                // flags
                '-' | '+' | ' ' | '#' if state == ParserState::Flags => {}
                '0'..='9' if state == ParserState::Flags => {
                    state = ParserState::FixedFmtLit;
                }
                '*' if state == ParserState::Flags => {
                    dynamic_args.push(off.try_into().unwrap());
                    state = ParserState::DynamicFmtLit;
                }
                '.' if state.start_precision() => {
                    state = ParserState::AnyPrecision;
                }

                '*' if state == ParserState::AnyPrecision => {
                    dynamic_args.push(off.try_into().unwrap());
                    state = ParserState::DynamicPrecsion
                }
                '0'..='9' if state == ParserState::AnyPrecision => {
                    state = ParserState::FixedPrecision
                }
                '0'..='9' if state.eat_number() => (),
                // Enhancement-71: every conversion terminates a specifier
                // (integer d/h/o/b/c, string s, real e/f/g/r) -- flags,
                // width and precision are legal for all of them.
                'e'..='g' | 'E'..='G' | 'r' | 'R' | 'd' | 'D' | 'h' | 'H' | 'o' | 'O' | 'b'
                | 'B' | 'c' | 'C' | 's' | 'S'
                    if state != ParserState::AnyPrecision =>
                {
                    conversion = c;
                    break;
                }
                _ => {
                    err = Some(InferenceDiagnostic::InvalidFmtSpecifierChar {
                        fmt_lit: fmt_expr,
                        lit_range: TextRange::new(off.try_into().unwrap(), end.try_into().unwrap()),
                        err_char: c,
                        candidates: state.candidates(),
                    });
                    break;
                }
            }

            pos = chars.next();
        } else {
            err = Some(InferenceDiagnostic::InvalidFmtSpecifierEnd {
                fmt_lit: fmt_expr,
                lit_range: TextRange::new(start.try_into().unwrap(), end.try_into().unwrap()),
            });
            break;
        }
    }

    ParseResult { dynamic_args, err, end: end.into(), conversion }
}
