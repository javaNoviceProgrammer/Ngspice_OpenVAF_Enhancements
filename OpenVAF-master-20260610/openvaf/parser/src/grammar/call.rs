use super::*;
use crate::grammar::expressions::expr;

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
        // A LEADING, INTERIOR or TRAILING slot is a null argument -- see the
        // trailing case at the bottom of the loop.
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
        // A TRAILING empty slot is a null argument too. LRM Syntax 4-3 writes the
        // Laplace filters as
        //
        //     laplace_filter_name ( expr , [ arg ] , [ arg ] [ , constant ] )
        //
        // so the SECOND filter argument may be null with nothing after it:
        // `laplace_np(x, n, )` and `laplace_zp(x, , )` are both spellings the BNF
        // allows, and both were rejected while the interior null already worked.
        //
        // Enhancement-423 raised a dedicated error here instead, for `max(1, 2,)`.
        // That case is still rejected -- as an empty array where a real is
        // expected, the same TYPE error an interior null gets outside a filter --
        // because the parser sees token kinds only and cannot tell the two apart.
        // Deciding it in inference, where the builtin is known, is what makes the
        // legal spelling work without letting the typo through.
        if p.at(T![')']) {
            let null_arg = p.start();
            null_arg.complete(p, ARRAY_EXPR);
            break;
        }
    }
    p.eat(T![')']);
    m.complete(p, ARG_LIST);
}
