use std::fmt::Debug;

use stdx::pretty;

use crate::Token;

#[derive(Debug, Clone)]
pub enum SyntaxError {
    // #[error("{name} was already declared in this Scope!")]
    // AlreadyDeclaredInThisScope { declaration: Span, other_declaration: Span, name: Box<str> },
    //
    // #[error("Unexpected Token!")]
    // MissingOrUnexpectedToken { expected: Token, expected_at: Span, span: Span },
    //
    // #[error("Reached 'endmodule' while still expecting an 'end' delimiter!")]
    // MismatchedDecimeters { start: Span, end: Span },
    //
    // #[error("Unexpected EOF! Expected {expected}")]
    // UnrecognizedEof { expected: ListFormatter<Vec<String>>, span: Span },
    // #[display(fmt = "unexpected token {}; expected {}", "found", "expected")]
    UnexpectedToken { expected: pretty::List<Vec<Token>>, found: Token },
    /// Enhancement-387: the expression-tree depth guard fired.
    ///
    /// Enhancement-148 bounds expression depth so a pathologically deep
    /// expression is rejected instead of overflowing the recursive-descent
    /// parser. It reported that through the ordinary `UnexpectedToken` path, so
    /// a 999-term operator chain came back as
    /// "unexpected token identifier; expected '(', '{', ..." -- which describes
    /// a syntax problem the source does not have. The preprocessor's own
    /// recursion guard has always said what actually happened ("nests too
    /// deeply (a file that includes itself?)"); this gives the parser the same.
    ExprTooDeep,
    // ExtraToken { span: Span, token: Token },
    //
    // #[error("Unexpected Token!")]
    // UnexpectedToken { span: Span, ignored: Option<Span> },
}
