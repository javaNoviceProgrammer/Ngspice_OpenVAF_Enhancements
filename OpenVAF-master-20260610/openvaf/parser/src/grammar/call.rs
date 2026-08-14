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
        // Enhancement-453: the LRM's NULL ARGUMENT -- "two adjacent commas (,,)
        // in the argument list" (LRM 4.5.11 for the Laplace filters, 4.5.12 for
        // the Z-transform filters, both saying "the zeros argument may be
        // represented as a null argument"). The LRM's own worked example
        //
        //     V(out) <+ laplace_zp(white_noise(k), , '{1,0,1,0,-1,0,-1,0});
        //
        // did not compile: `expr` returned None on the empty slot and the loop
        // broke, reporting "unexpected token ','" and then a bogus arity ("at
        // least 3 arguments but found 1").
        //
        // An empty slot becomes an empty ARRAY_EXPR -- the very node `'{}`
        // produces, which the filters already accept and lower to a filter with
        // no zeros. The parser sees token KINDS only, never text, so it cannot
        // tell which function is being called; legality is therefore left to
        // type inference, where the builtin is known. Everywhere a vector is not
        // expected the empty array is a type error, which is what a null
        // argument outside the filters should be (LRM 4.6: "It is illegal to
        // specify a null argument in the argument list of an analog operator,
        // except as specified elsewhere").
        //
        // Only an INTERIOR or LEADING slot is a null argument. A TRAILING comma
        // is still the Enhancement-423 error, handled at the bottom of the loop.
        if p.at(T![,]) {
            let null_arg = p.start();
            null_arg.complete(p, ARRAY_EXPR);
        } else if expr(p).is_none() {
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
