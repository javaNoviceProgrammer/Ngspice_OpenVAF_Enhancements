mod tree_builder;

use ::preprocessor::sourcemap::SourceContext;
use ::preprocessor::{Preprocess, SourceProvider};
use rowan::{TextRange, TextSize};
use vfs::FileId;

use crate::parsing::tree_builder::SyntaxTreeBuilder;
use crate::syntax_node::GreenNode;
use crate::SyntaxError;

pub(crate) fn parse_text(
    sources: &dyn SourceProvider,
    root_file: FileId,
    Preprocess { ts, sm, .. }: &Preprocess,
) -> (GreenNode, Vec<SyntaxError>, Vec<(TextRange, SourceContext, TextSize)>) {
    // tokens without whitespaces/comments
    let mut parser_tokens: Vec<_> = ts
        .iter()
        .filter_map(|token| {
            if token.kind.is_trivia() {
                return None;
            }
            Some(token.kind)
        })
        .collect();

    // `do` is a legal Verilog-AMS identifier (Annex B does not reserve it);
    // the DO_KW token exists only for the do-while extension. Keep it a
    // keyword exactly where a do-while can start -- the next token begins a
    // statement body -- and let every other `do` (declarations `real do;`,
    // assignments `do = ...`, expression operands) parse as the identifier
    // it legally is.
    use crate::SyntaxKind::{
        ARR_START, AT, BANG, BASED_INT, BEGIN_KW, BREAK_KW, CASEX_KW, CASEZ_KW, CASE_KW,
        CONTINUE_KW, DO_KW, FOR_KW, IDENT, IF_KW, INF_KW, INT_NUMBER, L_CURLY, L_PAREN, MINUS,
        PLUS, REPEAT_KW, RETURN_KW, SEMICOLON, SI_REAL_NUMBER, STD_REAL_NUMBER, STR_LIT, SYSFUN,
        TILDE, WHILE_KW,
    };
    for i in 0..parser_tokens.len() {
        if parser_tokens[i] == DO_KW
            && !matches!(
                parser_tokens.get(i + 1),
                Some(
                    BEGIN_KW
                        | IF_KW
                        | FOR_KW
                        | WHILE_KW
                        | REPEAT_KW
                        | CASE_KW
                        | CASEX_KW
                        | CASEZ_KW
                        | AT
                        | IDENT
                        | SYSFUN
                        | DO_KW
                )
            )
        {
            parser_tokens[i] = IDENT;
        }
        // VAMS-2023 jump statements (LRM 5.11), contextually. A jump keyword
        // must (a) sit where a statement can begin -- the previous token ends
        // a statement or opens a statement position (`;`, begin/end, the `)`
        // of an if/for/while/event header, a case-arm `:`, `else`, `do`, a
        // `(* ... *)` attribute, or a block label's name) -- and (b) be
        // followed by `;` (break/continue) or by `;`/an expression start
        // (return). Every other use -- declarations `real break;`,
        // assignments `return = ...`, expression operands `V(a,b)*break` --
        // stays the identifier it was in pre-2023 source (the older Annex B
        // did not reserve these words), surfaced by the L012 keyword-compat
        // lint like the other VAMS keywords. Two identifiers can never be
        // adjacent in a legal program, so IDENT in the prev-set (a `begin :
        // label` before a leading jump) costs nothing.
        if matches!(parser_tokens[i], BREAK_KW | CONTINUE_KW | RETURN_KW) {
            use crate::SyntaxKind::{
                COLON, DO_KW, ELSE_KW, END_KW, R_ATTR_PAREN, R_PAREN,
            };
            let stmt_position = i == 0
                || matches!(
                    parser_tokens[i - 1],
                    SEMICOLON
                        | BEGIN_KW
                        | END_KW
                        | R_PAREN
                        | COLON
                        | ELSE_KW
                        | DO_KW
                        | R_ATTR_PAREN
                        | IDENT
                );
            let shape_ok = if parser_tokens[i] == RETURN_KW {
                matches!(
                    parser_tokens.get(i + 1),
                    Some(
                        SEMICOLON
                            | IDENT
                            | SYSFUN
                            | INT_NUMBER
                            | BASED_INT
                            | STD_REAL_NUMBER
                            | SI_REAL_NUMBER
                            | STR_LIT
                            | INF_KW
                            | L_PAREN
                            | L_CURLY
                            | ARR_START
                            | MINUS
                            | PLUS
                            | BANG
                            | TILDE
                    )
                )
            } else {
                parser_tokens.get(i + 1) == Some(&SEMICOLON)
            };
            if !(stmt_position && shape_ok) {
                parser_tokens[i] = IDENT;
            }
        }
    }
    let mut builder = SyntaxTreeBuilder::new(sources, root_file, ts, sm);
    for step in parser::parse(&parser_tokens).iter() {
        match step {
            parser::Step::Token { kind } => builder.token(kind),
            parser::Step::Enter { kind } => builder.start_node(kind),
            parser::Step::Exit => builder.finish_node(),
            parser::Step::Error { err } => builder.error(err.clone()),
        }
    }

    let (tree, parser_errors, ctx_map) = builder.finish();

    (tree, parser_errors, ctx_map)
}
