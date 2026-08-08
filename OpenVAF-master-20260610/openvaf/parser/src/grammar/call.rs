use super::*;
use crate::grammar::expressions::{expr, EXPR_EXPECTED};

pub(super) fn call(p: &mut Parser, lhs: CompletedMarker) -> CompletedMarker {
    let m = lhs.precede(p);
    arg_list(p);
    m.complete(p, CALL)
}

pub(super) fn sys_fun_call(p: &mut Parser) -> CompletedMarker {
    let m = p.start();
    let m2 = p.start();
    p.bump(SYSFUN);
    m2.complete(p, SYS_FUN);
    if p.at(T!('(')) {
        arg_list(p);
    }
    m.complete(p, CALL)
}

pub(super) fn arg_list(p: &mut Parser) {
    let m = p.start();
    p.eat(T!['(']);
    while !p.at(T![')']) && !p.at(EOF) {
        if expr(p).is_none() {
            break;
        }
        if p.at(T![')']) {
            break;
        }
        if !p.expect(T![,]) {
            break;
        }
        // Enhancement-423: a comma must be FOLLOWED by an argument. `max(1, 2,)`
        // ended the loop here on the `)` and was accepted as two arguments,
        // while `max(1, )` -- the same trailing comma with a space -- was caught
        // only by the later arity check.
        if p.at(T![')']) {
            p.error(p.unexpected_tokens_msg(EXPR_EXPECTED.to_owned()));
            break;
        }
    }
    p.eat(T![')']);
    m.complete(p, ARG_LIST);
}
