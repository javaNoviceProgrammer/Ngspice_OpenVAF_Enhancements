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
        AT, BEGIN_KW, CASEX_KW, CASEZ_KW, CASE_KW, DO_KW, FOR_KW, IDENT, IF_KW, REPEAT_KW,
        SYSFUN, WHILE_KW,
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
