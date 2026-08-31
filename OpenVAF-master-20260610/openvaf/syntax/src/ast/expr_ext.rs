//! Various extension methods to ast Expr Nodes, which are hard to code-generate.

use stdx::impl_display;

use super::Stmt;
use crate::ast::{self, support, AstChildren, AstNode, AstToken};
use crate::{SyntaxToken, T};
use ast::ConstExprValue;

use std::borrow::Cow;

impl ast::ConstExprValue {
    pub fn as_real(&self) -> Option<f64> {
        match self {
            &ConstExprValue::Int(v) => return Some(v.into()),
            &ConstExprValue::Float(v) => return Some(v.into()),
            _ => return None,
        }
    }
}

impl ast::Expr {
    pub fn as_literal(&self) -> Option<LiteralKind> {
        if let ast::Expr::Literal(lit) = self {
            Some(lit.kind())
        } else {
            None
        }
    }
    pub fn as_str_literal(&self) -> Option<String> {
        if let Some(LiteralKind::String(lit)) = self.as_literal() {
            Some(lit.unescaped_value())
        } else {
            None
        }
    }

    // Returns constant expression value (for computing attribute values)
    // Takes into account unary +/-, handles scalar real/integer/string
    // This evaluation is performed at AST level, not HIR level
    pub fn as_constexprval(&self) -> Option<ConstExprValue> {
        // Must use Cow because .expr() returns Option<Expr> while
        // self is &Expr and cannot be converted into Option<Expr>
        let (val, negate) = if let ast::Expr::PrefixExpr(pfxe) = self {
            match pfxe.op_kind() {
                // -, skip to argument
                Some(UnaryOp::Neg) => (pfxe.expr().map(Cow::Owned), true),
                // +, skip to argument
                Some(UnaryOp::Identity) => (pfxe.expr().map(Cow::Owned), false),
                // Everything else cannot be evaluated
                _ => return None,
            }
        } else {
            // Not unary Op
            (Some(Cow::Borrowed(self)), false)
        };

        // If we have no expression, give up
        if val.is_none() {
            return None;
        }

        // Get value, negate if required
        match &*val.unwrap() {
            ast::Expr::Literal(lit) => match lit.kind() {
                LiteralKind::String(lit) => Some(ConstExprValue::String(lit.unescaped_value())), // Some(lit.unescaped_value()),
                LiteralKind::StdRealNumber(f) => Some(ConstExprValue::Float(if negate {
                    (-f.value()).into()
                } else {
                    f.value().into()
                })),
                LiteralKind::SiRealNumber(f) => Some(ConstExprValue::Float(if negate {
                    (-f.value()).into()
                } else {
                    f.value().into()
                })),
                LiteralKind::IntNumber(i) => Some(match i.value() {
                    Some(int) => ConstExprValue::Int(if negate { -int } else { int }),
                    // Enhancement-392: `-2147483648` is INT_MIN, an ordinary `integer`
                    // value -- but it can only be SPELLED as unary minus applied to
                    // 2147483648, whose magnitude does not itself fit. Recover it by
                    // checking against the NEGATED range before giving up.
                    //
                    // It used to fall straight through to the real branch below, and the
                    // whole enclosing expression then acquired REAL semantics:
                    // `(-2147483648)/3` floored to -715827883 where integer division
                    // truncates toward zero to -715827882, and `(-2147483648)-1`
                    // saturated instead of wrapping. The runtime path never goes through
                    // here, so the same expression gave two different answers depending
                    // on whether it was constant-folded.
                    None if negate => match i.value_negated() {
                        Some(int) => ConstExprValue::Int(int),
                        None => ConstExprValue::Float((-i.value_as_f64()).into()),
                    },
                    // doesn't fit in i32 (Verilog-A `integer`'s width) -- still a valid real
                    // constant, e.g. a laplace_nd coefficient too large to be a bit-select
                    // index/bus width anyway (those consumers already reject a non-Int here).
                    None => ConstExprValue::Float(i.value_as_f64().into()),
                }),
                _ => None,
            },
            _ => None,
        }
    }
}

#[derive(Copy, Clone, Debug, PartialEq, Eq, Hash)]
pub enum UnaryOp {
    /// The `~` operator for bit inversion
    BitNegate,
    /// The `!` operator for logical inversion
    Not,
    /// The `-` operator for negation
    Neg,
    /// The `+` operator (does absolutely nothing)
    Identity,
}

impl ast::PrefixExpr {
    pub fn op_kind(&self) -> Option<UnaryOp> {
        match self.op_token()?.kind() {
            T![~] => Some(UnaryOp::BitNegate),
            T![!] => Some(UnaryOp::Not),
            T![-] => Some(UnaryOp::Neg),
            T![+] => Some(UnaryOp::Identity),
            _ => None,
        }
    }

    pub fn op_token(&self) -> Option<SyntaxToken> {
        self.syntax().first_child_or_token()?.into_token()
    }
}

impl_display! {
    match UnaryOp{
        UnaryOp::BitNegate => "~";
        UnaryOp::Not => "!";
        UnaryOp::Neg => "-";
        UnaryOp::Identity => "+";
    }
}

#[derive(Copy, Clone, Debug, PartialEq, Eq, Hash)]
pub enum BinaryOp {
    /// The `||` operator for boolean OR
    BooleanOr,
    /// The `&&` operator for boolean AND
    BooleanAnd,
    /// The `==` operator for equality testing
    EqualityTest,
    /// The `!=` operator for equality testing
    NegatedEqualityTest,
    /// The `<=` operator for lesser-equal testing
    LesserEqualTest,
    /// The `>=` operator for greater-equal testing
    GreaterEqualTest,
    /// The `<` operator for comparison
    LesserTest,
    /// The `>` operator for comparison
    GreaterTest,
    /// The `+` operator for addition
    Addition,
    /// The `*` operator for multiplication
    Multiplication,
    /// The `-` operator for subtraction
    Subtraction,
    /// The `/` operator for division
    Division,
    /// The `%` operator for remainder after division
    Remainder,
    /// The `<<` operator for left shift
    LeftShift,
    /// The `>>` operator for right shift
    RightShift,
    /// The `<<<` operator for arithmetic (sign-extending) left shift
    ArithmeticLeftShift,
    /// The `>>>` operator for arithmetic (sign-extending) right shift
    ArithmeticRightShift,
    /// The `^` operator for bitwise XOR
    BitwiseXor,
    /// The `~^`/`^~` operator for bitwise XOR
    BitwiseEq,
    /// The `|` operator for bitwise OR
    BitwiseOr,
    /// The `&` operator for bitwise AND
    BitwiseAnd,
    /// The `**` operator for exponents
    Power,
}

impl ast::BinExpr {
    pub fn op_details(&self) -> Option<(SyntaxToken, BinaryOp)> {
        self.syntax().children_with_tokens().filter_map(|it| it.into_token()).find_map(|c| {
            let bin_op = match c.kind() {
                T![||] => BinaryOp::BooleanOr,
                T![&&] => BinaryOp::BooleanAnd,
                T![==] => BinaryOp::EqualityTest,
                T![!=] => BinaryOp::NegatedEqualityTest,
                T![<=] => BinaryOp::LesserEqualTest,
                T![>=] => BinaryOp::GreaterEqualTest,
                T![<] => BinaryOp::LesserTest,
                T![>] => BinaryOp::GreaterTest,
                T![+] => BinaryOp::Addition,
                T![*] => BinaryOp::Multiplication,
                T![-] => BinaryOp::Subtraction,
                T![/] => BinaryOp::Division,
                T![%] => BinaryOp::Remainder,
                T![<<] => BinaryOp::LeftShift,
                T![>>] => BinaryOp::RightShift,
                T![<<<] => BinaryOp::ArithmeticLeftShift,
                T![>>>] => BinaryOp::ArithmeticRightShift,
                T![^] => BinaryOp::BitwiseXor,
                T![|] => BinaryOp::BitwiseOr,
                T![&] => BinaryOp::BitwiseAnd,
                T![**] => BinaryOp::Power,
                T![~^] | T![^~] => BinaryOp::BitwiseEq,
                _ => return None,
            };
            Some((c, bin_op))
        })
    }

    pub fn op_kind(&self) -> Option<BinaryOp> {
        self.op_details().map(|t| t.1)
    }

    pub fn op_token(&self) -> Option<SyntaxToken> {
        self.op_details().map(|t| t.0)
    }

    pub fn lhs(&self) -> Option<ast::Expr> {
        support::children(self.syntax()).next()
    }

    pub fn rhs(&self) -> Option<ast::Expr> {
        support::children(self.syntax()).nth(1)
    }

    // pub fn sub_exprs(&self) -> (Option<ast::Expr>, Option<ast::Expr>) {
    //     let mut children = support::children(self.syntax());
    //     let first = children.next();
    //     let second = children.next();
    //     (first, second)
    // }
}

impl_display! {
    match BinaryOp{
        BinaryOp::BooleanOr => "||";
        BinaryOp::BooleanAnd => "&&";
        BinaryOp::EqualityTest => "==";
        BinaryOp::NegatedEqualityTest => "!=";
        BinaryOp::LesserEqualTest => "<=";
        BinaryOp::GreaterEqualTest => ">=";
        BinaryOp::LesserTest => "<";
        BinaryOp::GreaterTest => ">";
        BinaryOp::Addition => "+";
        BinaryOp::Multiplication => "*";
        BinaryOp::Subtraction => "-";
        BinaryOp::Division => "/";
        BinaryOp::Remainder => "%";
        BinaryOp::LeftShift => "<<";
        BinaryOp::RightShift => ">>";
        BinaryOp::ArithmeticLeftShift => "<<<";
        BinaryOp::ArithmeticRightShift => ">>>";
        BinaryOp::BitwiseXor => "^";
        BinaryOp::BitwiseEq => "~^";
        BinaryOp::BitwiseOr => "|";
        BinaryOp::BitwiseAnd => "&";
        BinaryOp::Power => "**";
    }
}

pub enum ArrayExprKind {
    Repeat { initializer: Option<ast::Expr>, repeat: Option<ast::Expr> },
    ElementList(AstChildren<ast::Expr>),
}

impl ast::ArrayExpr {
    pub fn kind(&self) -> ArrayExprKind {
        if self.is_repeat() {
            ArrayExprKind::Repeat {
                initializer: support::children(self.syntax()).next(),
                repeat: support::children(self.syntax()).nth(1),
            }
        } else {
            ArrayExprKind::ElementList(support::children(self.syntax()))
        }
    }

    fn is_repeat(&self) -> bool {
        self.syntax().children_with_tokens().any(|it| it.kind() == T![;])
    }
}

#[derive(Clone, Debug, PartialEq, Eq, Hash)]
pub enum LiteralKind {
    String(ast::StrLit),
    IntNumber(ast::IntNumber),
    SiRealNumber(ast::SiRealNumber),
    StdRealNumber(ast::StdRealNumber),
    Inf,
}

impl ast::Literal {
    pub fn token(&self) -> SyntaxToken {
        self.syntax()
            .children_with_tokens()
            .find(|e| !e.kind().is_trivia())
            .and_then(|e| e.into_token())
            .unwrap()
    }
    pub fn kind(&self) -> LiteralKind {
        let token = self.token();

        if let Some(t) = ast::IntNumber::cast(token.clone()) {
            return LiteralKind::IntNumber(t);
        }
        if let Some(t) = ast::SiRealNumber::cast(token.clone()) {
            return LiteralKind::SiRealNumber(t);
        }
        if let Some(t) = ast::StdRealNumber::cast(token.clone()) {
            return LiteralKind::StdRealNumber(t);
        }

        if let Some(t) = ast::StrLit::cast(token.clone()) {
            return LiteralKind::String(t);
        }

        match token.kind() {
            T![inf] => LiteralKind::Inf,
            // A white-space-separated or macro-substituted based literal
            // (LRM 2.6.1): the LITERAL node holds several tokens
            // ([size] base [digits]); the wrapper evaluates over all of them.
            crate::SyntaxKind::BASED_INT | crate::SyntaxKind::BASE_PREFIX => {
                LiteralKind::IntNumber(ast::IntNumber { syntax: token })
            }
            _ => unreachable!(),
        }
    }
}

/// Strips `_` digit separators (LRM: legal in any number, Enhancement-46).
fn strip_separators(src: &str) -> std::borrow::Cow<'_, str> {
    if src.contains('_') {
        std::borrow::Cow::Owned(src.chars().filter(|&c| c != '_').collect())
    } else {
        std::borrow::Cow::Borrowed(src)
    }
}

/// Parses a based integer literal `[size]'[s]<base><digits>` (LRM A.8.7,
/// Enhancement-46) to its 32-bit `integer` value: the digits are taken in the
/// given radix, masked to `size` bits when a size is given (clamped to 1..=32),
/// and sign-extended from the size's MSB under the `s` qualifier.
fn parse_based_int(text: &str) -> Option<i32> {
    parse_based_int_masked(text).map(|(val, ..)| val)
}

/// Like [`parse_based_int`] but also reports the don't-care digit masks
/// (Enhancement-78, `casex`/`casez`): `x`/`X` digits set their bit positions
/// in `x_mask`, `z`/`Z`/`?` digits set theirs in `z_mask`, and both
/// contribute zero value bits. Returns `(value, x_mask, z_mask)`.
pub fn parse_based_int_masked(text: &str) -> Option<(i32, i32, i32)> {
    let quote = text.find('\'')?;
    let (size_s, rest) = text.split_at(quote);
    let mut rest = &rest[1..];
    let signed = matches!(rest.as_bytes().first(), Some(b's' | b'S'));
    if signed {
        rest = &rest[1..];
    }
    let (radix, bits_per_digit) = match rest.as_bytes().first()? {
        b'd' | b'D' => (10, 0),
        b'h' | b'H' => (16, 4),
        b'o' | b'O' => (8, 3),
        b'b' | b'B' => (2, 1),
        _ => return None,
    };
    let digits = &rest[1..];
    if digits.is_empty() {
        return None;
    }
    let (mut val, mut x_mask, mut z_mask) = (0u128, 0u128, 0u128);
    let mut any_digit = false;
    for c in digits.chars() {
        if c == '_' {
            continue;
        }
        any_digit = true;
        match c {
            'x' | 'X' if bits_per_digit > 0 => {
                val <<= bits_per_digit;
                x_mask = (x_mask << bits_per_digit) | ((1 << bits_per_digit) - 1);
                z_mask <<= bits_per_digit;
            }
            'z' | 'Z' | '?' if bits_per_digit > 0 => {
                val <<= bits_per_digit;
                z_mask = (z_mask << bits_per_digit) | ((1 << bits_per_digit) - 1);
                x_mask <<= bits_per_digit;
            }
            _ => {
                let d = c.to_digit(radix)?;
                if bits_per_digit > 0 {
                    val = (val << bits_per_digit) | d as u128;
                    x_mask <<= bits_per_digit;
                    z_mask <<= bits_per_digit;
                } else {
                    val = val.checked_mul(10)?.checked_add(d as u128)?;
                }
            }
        }
    }
    if !any_digit {
        return None;
    }
    let size: u32 = if size_s.is_empty() {
        32
    } else {
        size_s.parse::<u32>().ok()?.clamp(1, 32)
    };
    if size < 32 {
        let mask = (1u128 << size) - 1;
        val &= mask;
        x_mask &= mask;
        z_mask &= mask;
        if signed && (val >> (size - 1)) & 1 == 1 {
            val |= !mask;
        }
    }
    Some((val as u32 as i32, x_mask as u32 as i32, z_mask as u32 as i32))
}

impl ast::StdRealNumber {
    pub fn value(&self) -> f64 {
        let src = strip_separators(self.syntax.text());
        src.parse().unwrap()
    }
}

impl ast::SiRealNumber {
    pub fn value(&self) -> f64 {
        let src = strip_separators(self.syntax.text());
        let (src, scale_char) = src.split_at(src.len() - 1);
        let exp = match scale_char {
            "T" => 12,
            "G" => 9,
            "M" => 6,
            "K" | "k" => 3,
            "m" => -3,
            "u" => -6,
            "n" => -9,
            "p" => -12,
            "f" => -15,
            "a" => -18,
            _ => unreachable!(),
        };
        src.parse::<f64>().unwrap() * (10_f64).powi(exp)
    }
}

impl ast::IntNumber {
    /// The literal's full text with `_` separators (and, for a multi-token
    /// based literal, white space between the tokens) stripped. A based
    /// literal may span several sibling tokens of one LITERAL node -- size,
    /// base, digits -- because LRM 2.6.1 allows white space between them and
    /// macro substitution of each; joining the non-trivia tokens rebuilds the
    /// contiguous spelling the parsers below understand.
    pub(crate) fn number_text(&self) -> String {
        let multi = self.syntax.parent().filter(|node| {
            node.children_with_tokens().any(|t| {
                matches!(t.kind(), crate::SyntaxKind::BASED_INT | crate::SyntaxKind::BASE_PREFIX)
            }) && node
                .children_with_tokens()
                .filter(|t| !t.kind().is_trivia())
                .nth(1)
                .is_some()
        });
        match multi {
            Some(node) => {
                let mut joined = String::new();
                for tok in node.children_with_tokens().filter_map(|e| e.into_token()) {
                    if !tok.kind().is_trivia() {
                        joined.extend(tok.text().chars().filter(|&c| c != '_'));
                    }
                }
                joined
            }
            None => strip_separators(self.syntax.text()).into_owned(),
        }
    }

    /// Parses this integer literal's text as an `i32`, or `None` if it doesn't fit (e.g. a
    /// literal like `6134876650875544`, larger than Verilog-A's 32-bit `integer` type can
    /// hold) -- callers should fall back to `value_as_f64` in that case rather than treating
    /// it as an error, since a bare digit-string with no `.`/exponent is still a perfectly
    /// valid (if unusually spelled) real-number literal wherever a `real` is expected.
    pub fn value(&self) -> Option<i32> {
        let src = self.number_text();
        if src.contains('\'') {
            return parse_based_int(&src);
        }
        src.parse().ok()
    }

    /// Enhancement-392: this literal's value NEGATED, when the negation fits in an
    /// `i32` even though the literal itself does not.
    ///
    /// Exists for exactly one value: `2147483648`, whose negation is `i32::MIN`.
    /// Without it, `-2147483648` -- the smallest `integer` -- could not be written
    /// as a constant at all, and silently became a real.
    pub fn value_negated(&self) -> Option<i32> {
        let src = self.number_text();
        if src.contains('\'') {
            return None;
        }
        let magnitude: i64 = src.parse().ok()?;
        let negated = -magnitude;
        if negated >= i32::MIN as i64 && negated <= i32::MAX as i64 {
            Some(negated as i32)
        } else {
            None
        }
    }

    /// The don't-care digit masks of a based literal -- `(x_mask, z_mask)`
    /// bit sets -- or `None` when it has none (Enhancement-78, casex/casez).
    pub fn dontcare_masks(&self) -> Option<(i32, i32)> {
        let src = self.number_text();
        if !src.contains('\'') {
            return None;
        }
        let (_, x_mask, z_mask) = parse_based_int_masked(&src)?;
        if x_mask == 0 && z_mask == 0 {
            None
        } else {
            Some((x_mask, z_mask))
        }
    }

    /// Parses this integer literal's text as an `f64`. Always succeeds for any token the
    /// lexer classified as `IntNumber` (a plain digit string is always valid float syntax,
    /// and never exceeds f64's much larger range) -- the fallback for `value()` returning
    /// `None`.
    pub fn value_as_f64(&self) -> f64 {
        let src = self.number_text();
        if src.contains('\'') {
            // a based literal always fits `i32` after masking; a malformed one
            // (already a parse error elsewhere) degrades to 0 rather than panicking
            return parse_based_int(&src).unwrap_or(0) as f64;
        }
        src.parse().expect("IntNumber token must be valid float syntax too")
    }
}

impl ast::StrLit {
    pub fn value(&self) -> &str {
        let src = self.syntax.text();
        // Enhancement-230: a malformed / unterminated string literal that the
        // lexer still classified as a StrLit can be as short as a lone `"`
        // (len 1); `src[1..src.len()-1]` would then be the range [1..0] and
        // panic ("byte range starts at 1 but ends at 0"). Strip the surrounding
        // quotes with a saturating range instead -- an unterminated string is
        // already a parse error reported elsewhere.
        src.get(1..src.len().saturating_sub(1)).unwrap_or("")
    }
    /// Processes the string literal's escape sequences in a single left-to-right
    /// pass (Enhancement-48): `\n`, `\t`, `\\`, `\"`, and `\ddd` (one to three
    /// octal digits, LRM 2.7.1). A backslash before a (possibly CRLF) newline
    /// keeps the newline (line continuation, tolerated as an extension); any
    /// other unknown escape is preserved verbatim. The previous implementation
    /// chained sequential `str::replace` calls, which mis-unescaped overlapping
    /// sequences (`a\\nb` -- a literal backslash followed by `n` -- became a
    /// backslash and a real newline) and did not support octal escapes at all.
    pub fn unescaped_value(&self) -> String {
        let src = self.value();
        let mut out = String::with_capacity(src.len());
        let mut chars = src.chars().peekable();
        while let Some(c) = chars.next() {
            if c != '\\' {
                out.push(c);
                continue;
            }
            match chars.peek() {
                Some('n') => {
                    chars.next();
                    out.push('\n');
                }
                Some('t') => {
                    chars.next();
                    out.push('\t');
                }
                Some('\\') => {
                    chars.next();
                    out.push('\\');
                }
                Some('"') => {
                    chars.next();
                    out.push('"');
                }
                Some('\n') => {
                    chars.next();
                    out.push('\n');
                }
                Some('\r') => {
                    chars.next();
                    out.push('\r');
                    if chars.peek() == Some(&'\n') {
                        chars.next();
                        out.push('\n');
                    }
                }
                Some('0'..='7') => {
                    let mut code = 0u32;
                    for _ in 0..3 {
                        match chars.peek() {
                            Some(&d @ '0'..='7') => {
                                chars.next();
                                code = code * 8 + d.to_digit(8).unwrap();
                            }
                            _ => break,
                        }
                    }
                    match char::from_u32(code) {
                        Some(ch) => out.push(ch),
                        // out-of-range octal (e.g. \777 > 0xFF): keep nothing sensible
                        // to emit; degrade to the replacement character
                        None => out.push(char::REPLACEMENT_CHARACTER),
                    }
                }
                // unknown escape (or trailing backslash): preserved verbatim
                _ => out.push('\\'),
            }
        }
        out
    }
}
impl ast::SelectExpr {
    pub fn then_val(&self) -> Option<ast::Expr> {
        support::children(self.syntax()).nth(1)
    }

    pub fn else_val(&self) -> Option<ast::Expr> {
        support::children(self.syntax()).nth(2)
    }
}

pub enum AsssigmentOp {
    /// a variable assignment stmt
    /// lhs must be an identifier (example `I = V(a,c)/R;`)
    Eq,

    /// a contribute (<+) stmt
    /// lhs must be a branch access (example `I(a,c) <+ V(a,c)/R;`)
    Contribute,

    /// an indirect branch assignment stmt
    /// lhs must be a branch access, rhs must be an equality expression
    /// (example `V(out):V(pin,nin) == 0;`)
    IndirectBranch,
}

impl ast::Assign {
    pub fn op_details(&self) -> Option<(SyntaxToken, AsssigmentOp)> {
        self.syntax().children_with_tokens().filter_map(|it| it.into_token()).find_map(|c| {
            let bin_op = match c.kind() {
                T![=] => AsssigmentOp::Eq,
                T![<+] => AsssigmentOp::Contribute,
                T![:] => AsssigmentOp::IndirectBranch,
                _ => return None,
            };
            Some((c, bin_op))
        })
    }
}

impl ast::BlockStmt {
    pub fn body(&self) -> AstChildren<Stmt> {
        support::children(self.syntax())
    }
}
