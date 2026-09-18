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
    // Enhancement-665 (hunt F11): `1e3n`, `0.5e`, `1meg` -- the lexer ends the
    // number before letters it cannot take into it and the parser then
    // complained about the leftover identifier in the range-clause vocabulary
    // ("expected 'exclude' or 'from'"). A number immediately followed by an
    // identifier (no white space, one source context) is a malformed literal:
    // the letters become trivia here, so the rest parses, and the literal is
    // reported as a whole with its text.
    let mut ts_fixed: Vec<::preprocessor::Token> = (**ts).clone();
    let mut suffix_errors: Vec<(usize, String)> = Vec::new();
    for i in 0..ts_fixed.len().saturating_sub(1) {
        let (a, b) = (ts_fixed[i], ts_fixed[i + 1]);
        let is_num = matches!(
            a.kind,
            crate::SyntaxKind::INT_NUMBER
                | crate::SyntaxKind::STD_REAL_NUMBER
                | crate::SyntaxKind::SI_REAL_NUMBER
        );
        if is_num
            && b.kind == crate::SyntaxKind::IDENT
            && a.span.ctx == b.span.ctx
            && a.span.range.end() == b.span.range.start()
        {
            let decl = sm.ctx_data(a.span.ctx).decl;
            let text = sources.file_text(decl.file).ok();
            let (fa, fb) = (a.span.to_file_span(sm).range, b.span.to_file_span(sm).range);
            let combined = text.map(|t| format!("{}{}", &t[fa], &t[fb])).unwrap_or_default();
            suffix_errors.push((i, combined));
            ts_fixed[i + 1].kind = crate::SyntaxKind::COMMENT;
        }
    }
    let ts = &ts_fixed;
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

    let (tree, mut parser_errors, ctx_map) = builder.finish();
    // Enhancement-665: the malformed literals, in the tree's text coordinates
    for (i, text) in suffix_errors {
        let mut start = TextSize::from(0);
        for t in &ts[..i] {
            start += t.span.range.len();
        }
        let len = ts[i].span.range.len() + ts[i + 1].span.range.len();
        parser_errors.push(SyntaxError::NumberSuffix { span: TextRange::at(start, len), text });
    }

    (tree, parser_errors, ctx_map)
}
