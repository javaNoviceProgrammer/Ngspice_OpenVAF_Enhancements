mod cursor;

#[cfg(test)]
mod tests;

use tokens::lexer::LiteralKind::{self, *};
use tokens::lexer::Token;
use tokens::lexer::TokenKind::{self, *};

use crate::cursor::Cursor;

/// Creates an iterator that produces tokens from the input string.
pub fn tokenize(input: &str) -> Vec<Token> {
    let mut cursor = Cursor::new(input);
    while !cursor.is_eof() {
        cursor.advance_token();
    }
    cursor.finish()
}

/// True if `c` is considered a whitespace according to Rust language definition.
/// See [Rust language reference](https://doc.rust-lang.org/reference/whitespace.html)
/// for definitions of these classes.
///
/// Technically the the VAMS standard only considers ASCII.
/// For better compatibility unicode is also allowed here (same whitespace definition as rust is
/// used)
/// A based-integer-literal base character (LRM A.8.7): d/h/o/b, either case.
fn is_base_char(c: char) -> bool {
    matches!(c, 'd' | 'D' | 'h' | 'H' | 'o' | 'O' | 'b' | 'B')
}

/// Enhancement-213: whether an `e`/`E` actually starts a float exponent, given
/// the two characters that follow it -- the language requires at least one
/// digit (optionally after a sign). Without this check `1e` was lexed as a
/// Float whose text does not parse as an f64, and that panicked in
/// `StdRealNumber::value()`. Leaving a bare `e` unconsumed lexes it as an
/// ordinary identifier so the malformed number surfaces as a parse error --
/// the same approach `based_literal_body` already takes for `8'squark`.
fn starts_float_exponent(after_e: char, after_that: char) -> bool {
    after_e.is_ascii_digit() || (matches!(after_e, '+' | '-') && after_that.is_ascii_digit())
}

/// A character that can start the digit run of a based integer literal --
/// the hex superset; per-base validity is enforced while eating the digits.
fn is_based_digit(c: char) -> bool {
    c.is_ascii_hexdigit() || matches!(c, '_' | 'x' | 'X' | 'z' | 'Z' | '?')
}

pub fn is_whitespace(c: char) -> bool {
    // This is Pattern_White_Space.
    //
    // Note that this set is stable (ie, it doesn't change with different
    // Unicode versions), so it's ok to just hard-code the values.
    matches!(
        c,
        // Usual ASCII suspects
        '\u{0009}'   // \t
        | '\u{000A}' // \n
        | '\u{000B}' // vertical tab
        | '\u{000C}' // form feed
        | '\u{000D}' // \r
        | '\u{0020}' // space

        // NEXT LINE from latin1
        | '\u{0085}'

        // Bidi markers
        | '\u{200E}' // LEFT-TO-RIGHT MARK
        | '\u{200F}' // RIGHT-TO-LEFT MARK

        // Dedicated whitespace characters from Unicode
        | '\u{2028}' // LINE SEPARATOR
        | '\u{2029}' // PARAGRAPH SEPARATOR
    )
}

/// True if 'c' is allowed in an identifier after the first token
pub fn is_ident_char(c: char) -> bool {
    matches!(c,'a'..='z'|'A'..='Z'|'_'|'$'|'0'..='9')
}

/// True if 'c' is allowed in an identifier at the first token (or later)
pub fn is_ident_start_char(c: char) -> bool {
    matches!(c,'a'..='z'|'A'..='Z'|'_')
}

impl Cursor<'_> {
    /// Parses a token from the input string.
    fn advance_token(&mut self) {
        let first_char = self.bump().unwrap();
        let token_kind = match first_char {
            // Slash, comment or block comment.
            '/' => match self.first() {
                '/' => self.line_comment(),
                '*' => self.block_comment(),
                _ => Slash,
            },

            '\n' => {
                self.finish_marker();
                self.whitespace()
            }
            // Whitespace sequence.
            c if is_whitespace(c) => self.whitespace(),

            '\\' if self.first() == '\n' => {
                self.bump();
                self.whitespace()
            }
            '`' if is_ident_start_char(self.first()) => self.compiler_directive(),

            // Identifier (this should be checked after other variant that can
            // start as identifier).
            '\\' if !is_whitespace(self.first()) => {
                self.eat_while(|c| !is_whitespace(c));
                EscapedIdent
            }

            // Identifier (this should be checked after other variant that can
            // start as identifier).
            c if is_ident_start_char(c) => {
                self.eat_identifier();
                SimpleIdent
            }

            '$' if is_ident_start_char(self.first()) => {
                self.bump();
                self.eat_identifier();
                SystemCallIdent
            }

            // Numeric literal.
            '0'..='9' => {
                let literal_kind = self.number();
                TokenKind::Literal { kind: literal_kind }
            }

            // Three Symbol tokens
            '<' if self.first() == '<' && self.second() == '<' => {
                self.bump();
                self.bump();
                ShlA
            }

            '>' if self.first() == '>' && self.second() == '>' => {
                self.bump();
                self.bump();
                ShrA
            }

            // Two Symbol tokens
            '(' if self.first() == '*' => {
                self.bump();
                AttrOpenParen
            }
            '*' if self.first() == ')' => {
                self.bump();
                AttrCloseParen
            }

            '\'' if self.first() == '{' => {
                self.bump();
                ArrStart
            }
            // Unsized based integer literal `'d42` / `'sh1F` (LRM A.8.7,
            // Enhancement-46), or a bare base token `'d` / `'sh` whose digits
            // follow after white space -- LRM 2.6.1 allows white space between
            // the base format and the digits (`5 'D 3` is the LRM's own
            // example) and macro substitution of the individual tokens
            // (`` `SZ'hFF ``). The sized contiguous form (`8'hFF`) is handled
            // in `number()`, whose token began with the size digits. A base
            // token with attached digits is a complete literal (BASED_INT);
            // one without is a BASE_PREFIX the parser joins with the size
            // before it and the digits token after it.
            '\'' if is_base_char(self.first())
                || (matches!(self.first(), 's' | 'S') && is_base_char(self.second())) =>
            {
                let has_digits = self.based_literal_body();
                TokenKind::Literal {
                    kind: if has_digits {
                        LiteralKind::BasedInt
                    } else {
                        LiteralKind::BasePrefix
                    },
                }
            }
            '=' if self.first() == '=' => {
                self.bump();
                Eq2
            }

            '!' if self.first() == '=' => {
                self.bump();
                Neq
            }

            '<' if self.first() == '=' => {
                self.bump();
                Leq
            }

            '>' if self.first() == '=' => {
                self.bump();
                Geq
            }

            '|' if self.first() == '|' => {
                self.bump();
                Pipe2
            }

            '&' if self.first() == '&' => {
                self.bump();
                Amp2
            }

            '<' if self.first() == '<' => {
                self.bump();
                Shl
            }

            '>' if self.first() == '>' => {
                self.bump();
                Shr
            }

            '<' if self.first() == '+' => {
                self.bump();
                Contribute
            }

            '*' if self.first() == '*' => {
                self.bump();
                Pow
            }

            '~' if self.first() == '^' => {
                self.bump();
                NXorL
            }

            '^' if self.first() == '~' => {
                self.bump();
                NXorR
            }

            // One-symbol tokens.
            ';' => Semi,
            ',' => Comma,
            '.' => Dot,
            '(' => OpenParen,
            ')' => CloseParen,
            '{' => OpenBrace,
            '}' => CloseBrace,
            '[' => OpenBracket,
            ']' => CloseBracket,
            '@' => At,
            '#' => Pound,
            '~' => Tilde,
            '?' => Question,
            ':' => Colon,
            '$' => Dollar,
            '=' => Eq,
            '!' => Not,
            '<' => Lt,
            '>' => Gt,
            '-' => Minus,
            '&' => And,
            '|' => Or,
            '+' => Plus,
            '*' => Star,
            '^' => Caret,
            '%' => Percent,

            // String literal.
            '"' => {
                let terminated = self.double_quoted_string();
                Literal { kind: Str { terminated } }
            }
            _ => Unknown,
        };
        self.finish_token(token_kind)
    }

    fn compiler_directive(&mut self) -> TokenKind {
        let mut is_define = true;
        for e in ['d', 'e', 'f', 'i', 'n', 'e'] {
            if self.first() != e {
                is_define = false;
                break;
            }
            self.bump();
        }

        if !is_define || is_ident_char(self.first()) {
            self.eat_while(is_ident_char);
            CompilerDirective
        } else {
            self.set_marker()
        }
    }

    fn line_comment(&mut self) -> TokenKind {
        debug_assert!(self.prev() == '/' && self.first() == '/');
        self.bump();

        loop {
            match self.first() {
                '\n' => break,
                '\\' if self.second() == '\n' => break,
                // Enhancement-35: a `//` comment terminated by end-of-file rather than a
                // newline must end the token too. `first()` returns `EOF_CHAR` forever at
                // the end of input while `bump()` no-ops, so without this the loop never
                // exits — a `// comment` as the last line of a file with no trailing
                // newline hung the compiler forever.
                _ if self.is_eof() => break,
                _ => {
                    self.bump();
                }
            };
        }
        debug_assert!(!(self.prev() == '\\' && self.first() == '\n'));
        debug_assert!(self.prev() != '\n');
        LineComment
    }

    fn block_comment(&mut self) -> TokenKind {
        debug_assert!(self.prev() == '/' && self.first() == '*');
        self.bump();

        while let Some(c) = self.bump() {
            match c {
                '*' if self.first() == '/' => {
                    self.bump();
                    return BlockComment { terminated: true };
                }
                _ => (),
            }
        }

        BlockComment { terminated: false }
    }

    fn whitespace(&mut self) -> TokenKind {
        loop {
            match self.first() {
                '\n' if self.finish_marker() => {
                    break;
                }
                '\\' if self.second() == '\n' => {
                    self.bump();
                }
                c if c.is_whitespace() => (),
                _ => break,
            }
            self.bump();
        }
        Whitespace
    }

    fn number(&mut self) -> LiteralKind {
        debug_assert!('0' <= self.prev() && self.prev() <= '9');
        // let mut base = Base::Decimal; TODO decimal with different base
        // if first_digit == '0' {
        //     // Attempt to parse encoding base.
        //     let has_digits = match self.first() {
        //         'b' => {
        //             base = Base::Binary;
        //             self.bump();
        //             self.eat_decimal_digits()
        //         }
        //         'o' => {
        //             base = Base::Octal;
        //             self.bump();
        //             self.eat_decimal_digits()
        //         }
        //         'x' => {
        //             base = Base::Hexadecimal;
        //             self.bump();
        //             self.eat_hexadecimal_digits()
        //         }
        //         // Not a base prefix.
        //         '0'..='9' | '_' | '.' | 'e' | 'E' => {
        //             self.eat_decimal_digits();
        //             true
        //         }
        //         // Just a 0.
        //         _ => return Int { base, empty_int: false },
        //     };
        //     // Base prefix was provided, but there were no digits
        //     // after it, e.g. "0x".
        //     if !has_digits {
        //         return Int { base, empty_int: true };
        //     }
        // } else {
        // No base prefix, parse number in the usual way.
        self.eat_decimal_digits();
        // };

        match self.first() {
            '.' => {
                self.bump();
                let mut has_scale_char = false;
                if self.first().is_ascii_digit() {
                    self.eat_decimal_digits();
                    match self.first() {
                        // Enhancement-213: only an `e` with an actual exponent
                        // after it belongs to the number (`1.5e` -> `1.5` + `e`).
                        'e' | 'E' if starts_float_exponent(self.second(), self.third()) => {
                            self.bump();
                            self.eat_float_exponent();
                        }

                        'T' | 'G' | 'M' | 'K' | 'k' | 'm' | 'u' | 'n' | 'p' | 'f' | 'a' => {
                            self.bump();
                            has_scale_char = true;
                        }
                        _ => (),
                    }
                }
                Float { has_scale_char }
            }

            'T' | 'G' | 'M' | 'K' | 'k' | 'm' | 'u' | 'n' | 'p' | 'f' | 'a' => {
                self.bump();
                Float { has_scale_char: true }
            }
            // Enhancement-213: see starts_float_exponent -- a bare `1e` is not a
            // real number, so leave the `e` to lex as an identifier and let the
            // parser report it, rather than building a Float that cannot parse.
            'e' | 'E' if starts_float_exponent(self.second(), self.third()) => {
                self.bump();
                self.eat_float_exponent();
                Float { has_scale_char: false }
            }
            // Sized based integer literal `8'hFF` (LRM A.8.7, Enhancement-46):
            // the digits eaten so far are the size prefix. A digit is required
            // after the base (see the unsized arm above).
            '\'' if (is_base_char(self.second()) && is_based_digit(self.third()))
                || (matches!(self.second(), 's' | 'S')
                    && is_base_char(self.third())
                    && is_based_digit(self.fourth())) =>
            {
                self.bump();
                let _ = self.based_literal_body();
                Int
            }
            _ => Int,
        }
    }

    /// Eats the `[s]<base><digits>` body of a based integer literal, after the
    /// `'` has been consumed. Only digits valid for the base (plus `_`
    /// separators) are eaten, so an invalid digit ends the token and surfaces
    /// as an ordinary parse error. Returns whether any digit was attached --
    /// `false` means the token is a bare base prefix (`'d`) whose digits
    /// follow after white space (LRM 2.6.1).
    fn based_literal_body(&mut self) -> bool {
        let mut has_digits = false;
        if matches!(self.first(), 's' | 'S') && is_base_char(self.second()) {
            self.bump();
        }
        if !is_base_char(self.first()) {
            // malformed (`8'squark`): stop after the quote; the rest lexes as
            // ordinary tokens and surfaces as a parse error
            return has_digits;
        }
        let base = self.first();
        self.bump();
        loop {
            let ok = match base {
                // x/z/? are don't-care digits (casex/casez items, LRM A.8.7);
                // legal in the power-of-two bases, not in decimal
                'b' | 'B' => {
                    matches!(self.first(), '0' | '1' | '_' | 'x' | 'X' | 'z' | 'Z' | '?')
                }
                'o' | 'O' => {
                    matches!(self.first(), '0'..='7' | '_' | 'x' | 'X' | 'z' | 'Z' | '?')
                }
                'd' | 'D' => matches!(self.first(), '0'..='9' | '_'),
                'h' | 'H' => {
                    matches!(self.first(), '0'..='9' | 'a'..='f' | 'A'..='F' | '_' | 'x' | 'X' | 'z' | 'Z' | '?')
                }
                _ => false,
            };
            if !ok {
                break;
            }
            if self.first() != '_' {
                has_digits = true;
            }
            self.bump();
        }
        has_digits
    }
    /// Eats double-quoted string and returns true
    /// if string is terminated.
    fn double_quoted_string(&mut self) -> bool {
        debug_assert!(self.prev() == '"');
        while let Some(c) = self.bump() {
            match c {
                '"' => {
                    return true;
                }
                '\\' if self.first() == '\\' || self.first() == '"' => {
                    // Bump again to skip escaped character.
                    self.bump();
                }
                _ => (),
            }
        }
        // End of file reached.
        false
    }

    fn eat_decimal_digits(&mut self) -> bool {
        let mut has_digits = false;
        loop {
            match self.first() {
                '_' => {
                    self.bump();
                }
                '0'..='9' => {
                    has_digits = true;
                    self.bump();
                }
                _ => break,
            }
        }
        has_digits
    }

    // fn eat_hexadecimal_digits(&mut self) -> bool {
    //     let mut has_digits = false;
    //     loop {
    //         match self.first() {
    //             '_' => {
    //                 self.bump();
    //             }
    //             '0'..='9' | 'a'..='f' | 'A'..='F' => {
    //                 has_digits = true;
    //                 self.bump();
    //             }
    //             _ => break,
    //         }
    //     }
    //     has_digits
    // }

    /// Eats the float exponent. Returns true if at least one digit was met,
    /// and returns false otherwise.
    fn eat_float_exponent(&mut self) -> bool {
        debug_assert!(self.prev() == 'e' || self.prev() == 'E');
        if self.first() == '-' || self.first() == '+' {
            self.bump();
        }
        self.eat_decimal_digits()
    }

    // Eats the identifier.
    fn eat_identifier(&mut self) {
        // debug_assert!(is_ident_char(self.first()));
        // self.bump();
        self.eat_while(is_ident_char);
    }

    /// Eats symbols while predicate returns true or until the end of file is reached.
    fn eat_while(&mut self, mut predicate: impl FnMut(char) -> bool) {
        while predicate(self.first()) && !self.is_eof() {
            self.bump();
        }
    }
}
