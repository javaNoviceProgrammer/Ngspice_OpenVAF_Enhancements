use super::*;
use crate::grammar::call::{call, sys_fun_call};
use crate::grammar::paths::path;

pub(super) const EXPR_EXPECTED: &[SyntaxKind] =
    &[T!['('], T!["'{"], T!['{'], SYSFUN, NAME, LITERAL, T![~], T![!], T![+], T![-]];

pub(super) fn expr(p: &mut Parser) -> Option<CompletedMarker> {
    expr_bp(p, 1)
}

/// Binding powers of operators for a Pratt parser.
///
/// See <https://www.oilshell.org/blog/2016/11/03.html>
#[rustfmt::skip]
fn current_op(p: &Parser) -> (u8, SyntaxKind) {
    const NOT_AN_OP: (u8, SyntaxKind) = (0, T![@]);
    match p.current() {
        T![?]  => (1,   T![?]),
        T![||]  => (2,   T![||]),
        
        T![&&]  => (3,   T![&&]),
        
        T![|]   => (4,   T![|]),
        
        // Enhancement-38: `^`, `~^` and `^~` share ONE precedence level per the LRM
        // (Table 4-2). `~^`/`^~` previously bound tighter than `^` — provably
        // unobservable for xor/xnor chains (each xnor contributes one global
        // inversion regardless of grouping), but fixed for LRM exactness.
        T![^]   => (5,   T![^]),
        T![~^]  => (5,   T![~^]),
        T![^~]  => (5,   T![^~]),
        
        T![&]   => (7,   T![&]),
        
        T![==]  => (8,   T![==]),
        T![!=]  => (8,   T![!=]),
        // case (in)equality: same level as ==/!= per LRM Table 4-2
        T![===] => (8,   T![===]),
        T![!==] => (8,   T![!==]),

        T![>=]  => (9,   T![>=]),
        T![>]   => (9,   T![>]),
        T![<=]  => (9,   T![<=]),
        T![<]   => (9,   T![<]),
        
        T![<<]   => (10,  T![<<]),
        T![>>]   => (10,  T![>>]),
        T![<<<]  => (10,  T![<<<]),
        T![>>>]  => (10,  T![>>>]),

        T![+]    => (11,  T![+]),
        T![-]    => (11,  T![-]),
        
        // Enhancement-38: `*`, `/` and `%` share ONE precedence level per the LRM
        // (Table 4-2), associating left to right. `%` previously bound tighter,
        // which mis-parsed `a * b % c` as `a * (b % c)` — e.g. `6*7%4` evaluated
        // to 18 instead of the LRM's `(6*7)%4 = 2`.
        T![*]    => (12,  T![*]),
        T![/]    => (12,  T![/]),
        T![%]    => (12,  T![%]),

        T![**]   => (14, T![**]),

        _        => NOT_AN_OP
    }
}

/// Enhancement-148: bound expression-tree depth (recursive nesting *and*
/// operator-chain length) so a pathologically deep expression is reported cleanly
/// instead of overflowing the recursive-descent parser -- or a later recursive
/// traversal of the resulting (deep, left-leaning) syntax tree. Real device models
/// nest expressions only a few dozen deep; 1000 leaves generous headroom.
const MAX_EXPR_DEPTH: u32 = 1000;

/// Report an over-deep expression and recover to the next expression boundary.
///
/// Enhancement-387: this used to hand the generic `unexpected_tokens_msg` to
/// `err_recover`, so hitting the depth limit printed
/// "unexpected token identifier; expected '(', '{', ..." -- a complaint about a
/// token that is perfectly valid, with no hint that a depth limit exists. It now
/// reports `ExprTooDeep`, keeping the same recovery.
fn expr_too_deep(p: &mut Parser) {
    p.err_recover(crate::SyntaxError::ExprTooDeep, EXPR_RECOVERY_SET);
}

// Parses expression with binding power of at least bp.
fn expr_bp(p: &mut Parser, bp: u8) -> Option<CompletedMarker> {
    // `atom_expr` brackets recursive nesting; the loop below adds one depth unit per
    // operator (the left-leaning chain it builds is exactly that deep). Restore the
    // entry depth on the way out so sibling expressions start fresh.
    let start = p.expr_depth.get();
    let res = expr_bp_inner(p, bp);
    p.expr_depth.set(start);
    res
}

fn expr_bp_inner(p: &mut Parser, bp: u8) -> Option<CompletedMarker> {
    let mut lhs = atom_expr(p)?;

    loop {
        let (op_bp, op) = current_op(p);

        if op_bp < bp {
            break;
        }

        p.expr_depth.set(p.expr_depth.get() + 1);
        if p.expr_depth.get() > MAX_EXPR_DEPTH {
            expr_too_deep(p);
            return None;
        }

        if op == T![?] {
            let m = lhs.precede(p);
            p.bump(T![?]);
            // LRM 2.9 / A.8.3: attribute instances may follow the `?`
            attrs(p, EXPR_RECOVERY_SET);
            expr(p);
            p.expect(T![:]);
            expr(p);
            return Some(m.complete(p, SELECT_EXPR));
        }

        let m = lhs.precede(p);
        p.bump(op);
        // LRM 2.9: an attribute instance can appear as a suffix to an operator
        attrs(p, EXPR_RECOVERY_SET);

        expr_bp(p, op_bp + 1);
        lhs = m.complete(p, BIN_EXPR);
    }
    Some(lhs)
}

pub(crate) const EXPR_RECOVERY_SET: TokenSet = TokenSet::new(&[
    T![;],
    T![endmodule],
    T![endfunction],
    T![endnature],
    T![enddiscipline],
    T![endcase],
    T![end],
]);

fn atom_expr(p: &mut Parser) -> Option<CompletedMarker> {
    // Enhancement-148: every level of expression nesting passes through `atom_expr`
    // (prefix operators recurse into it directly; parentheses, calls and ternary
    // branches recurse through `expr` -> `expr_bp` -> `atom_expr`). Counting here
    // bounds the recursion depth; the shared counter is restored by the caller.
    let depth = p.expr_depth.get() + 1;
    p.expr_depth.set(depth);
    let res = if depth > MAX_EXPR_DEPTH {
        expr_too_deep(p);
        None
    } else {
        atom_expr_inner(p)
    };
    p.expr_depth.set(p.expr_depth.get() - 1);
    res
}

fn atom_expr_inner(p: &mut Parser) -> Option<CompletedMarker> {
    // if let Some(m) = literal(p) {
    //     return Some(m);
    // }

    let done = match p.current() {
        T!['('] => paren_expr(p),
        T!["'{"] => array_expr(p),
        T!['{'] => concat_expr(p),
        T![~] | T![!] | T![-] | T![+] => {
            let m = p.start();
            p.bump_ts(TokenSet::new(&[T![~], T![!], T![-], T![+]]));
            // LRM 2.9: an attribute instance can appear as a suffix to an operator
            attrs(p, EXPR_RECOVERY_SET);
            atom_expr(p);
            m.complete(p, PREFIX_EXPR)
        }
        IDENT | ROOT_KW => {
            let m = path(p);
            // LRM 2.9 / A.8.2: attribute instances may follow a function name
            if p.at(T!["(*"]) {
                attrs(p, EXPR_RECOVERY_SET);
            }
            if p.at(T!('(')) {
                call(p, m)
            } else if p.at(T!['[']) {
                // One or more `[index]` clauses: `m[i]`, or a multi-dimensional
                // access `m[i][j]...` (Enhancement-15). All index expressions are
                // collected as children of a single BIT_SELECT_EXPR node.
                let m = m.precede(p);
                while p.at(T!['[']) {
                    p.bump(T!['[']);
                    expr(p);
                    // Optional part-select `[msb:lsb]` (Enhancement-85). The
                    // colon token stays in the CST and distinguishes a range
                    // from E-15's multi-dimensional `[i][j]` indexing; it is
                    // only legal in instance port connections, which body
                    // lowering enforces.
                    if p.eat(T![:]) {
                        expr(p);
                    }
                    p.expect(T![']']);
                }
                m.complete(p, BIT_SELECT_EXPR)
            } else {
                let m = m.precede(p);
                m.complete(p, PATH_EXPR)
            }
        }
        SYSFUN => sys_fun_call(p),
        T![<] => port_flow(p),
        INT_NUMBER => {
            let m = p.start();
            p.bump_any();
            // LRM 2.6.1: the three tokens of a based literal may be separated
            // by white space or produced by macro substitution. Join
            // `5 'D 3` (INT BASE_PREFIX INT), `8'sh FF` (INT BASE_PREFIX
            // IDENT), and `` `SZ'hFF `` (INT BASED_INT) into one LITERAL; the
            // digits after a bare base can lex as INT, IDENT, or INT+IDENT
            // (`'h 837FF` -> `837` + `FF`).
            if p.at(BASE_PREFIX) {
                p.bump_any();
                based_digit_tokens(p);
            } else if p.at(BASED_INT) {
                p.bump_any();
            }
            m.complete(p, LITERAL)
        }
        BASED_INT => {
            let m = p.start();
            p.bump_any();
            m.complete(p, LITERAL)
        }
        BASE_PREFIX => {
            let m = p.start();
            p.bump_any();
            based_digit_tokens(p);
            m.complete(p, LITERAL)
        }
        SI_REAL_NUMBER | STD_REAL_NUMBER | STR_LIT | INF_KW => {
            let m = p.start();
            p.bump_any();
            m.complete(p, LITERAL)
        }
        _ => {
            p.err_recover(p.unexpected_tokens_msg(EXPR_EXPECTED.to_owned()), EXPR_RECOVERY_SET);
            return None;
        }
    };
    Some(done)
}

/// Consumes the digits of a white-space-separated based literal after its
/// BASE_PREFIX token. A digit run straight from source is a single INT (the
/// lexer's pending-base mode, LRM 2.6.1 Example 5) or an IDENT (`FF`, `z3`).
/// A run substituted from a macro body was lexed with no base before it, so
/// it can arrive as number/identifier fragments (`1f` as an SI real, `12a` +
/// `b_f001`, `1f` + `2a`): take any run of number tokens, then at most one
/// trailing IDENT (an identifier eats every remaining digit character, so
/// nothing can follow it). The literal's value is computed from the joined
/// token text, which re-validates every digit against the base.
fn based_digit_tokens(p: &mut Parser) {
    let mut any = false;
    while p.at(INT_NUMBER) || p.at(SI_REAL_NUMBER) || p.at(STD_REAL_NUMBER) {
        p.bump_any();
        any = true;
    }
    if p.at(IDENT) {
        p.bump_any();
    } else if !any {
        p.error(p.unexpected_tokens_msg(vec![INT_NUMBER]));
    }
}

fn port_flow(p: &mut Parser) -> CompletedMarker {
    let m = p.start();
    p.bump(T![<]);
    path(p);
    p.expect(T![>]);
    m.complete(p, PORT_FLOW)
}

fn paren_expr(p: &mut Parser) -> CompletedMarker {
    let m = p.start();
    p.bump(T!['(']);

    // Enhancement-387: an EMPTY pair of parentheses is not an expression.
    //
    // The loop below is guarded by `!p.at(T![')'])`, so for `()` it never ran:
    // nothing was parsed and -- worse -- no diagnostic was emitted. The
    // PAREN_EXPR was completed with no child, hir_def lowered it to
    // `Expr::Missing`, and `hir/src/body.rs` has no arm for that variant, so it
    // fell through to `_ => panic!("invalid HIR: {:?}")`. The result was an
    // internal compiler error on a five-line source file:
    //
    //     analog I(p,n) <+ ();
    //     -> "OpenVAF encountered a problem and has crashed!" (exit 101)
    //
    // Every other malformed expression form (`{}`, `{1,}`, `a[]`, `? :`,
    // `sqrt()`, `1+`) was already rejected here in the parser and never reached
    // lowering; `()` was the one hole. Reporting it makes this a clean syntax
    // error like the rest, and no `Expr::Missing` reaches the HIR.
    if p.at(T![')']) {
        p.error(p.unexpected_tokens_msg(EXPR_EXPECTED.to_owned()));
        p.bump(T![')']);
        return m.complete(p, PAREN_EXPR);
    }

    // Enhancement-423: exactly ONE expression, not a tuple.
    //
    // This loop came from rust-analyzer and still carried its Rust test comment
    // (`const A: (i64, i64) = (1, #[cfg(test)] 2);`). Verilog-A has no comma
    // expression, but the loop happily parsed `(a, b, c)`, lowering kept only
    // the first child, and the rest were discarded before the HIR existed -- so
    // an undeclared name, a wrong arity or a type error inside one of them was
    // completely invisible. A `,` written where a `+` was meant, in a
    // parenthesised sum split across lines, silently dropped a whole term.
    if expr(p).is_some() && p.at(T![,]) {
        p.error(crate::SyntaxError::CommaExpr);
        // consume the rest of the list so the caller resynchronises on `)`
        // instead of reporting a cascade of unexpected-token errors
        while p.eat(T![,]) {
            if expr(p).is_none() {
                break;
            }
        }
    }
    p.expect(T![')']);
    m.complete(p, PAREN_EXPR)
}

fn array_expr(p: &mut Parser) -> CompletedMarker {
    let m = p.start();
    p.bump(T!["'{"]);
    while !p.at(EOF) && !p.at(T!['}']) {
        // Enhancement-457: an element of an assignment pattern may itself be a
        // REPLICATION -- `count{ e0, e1, ... }` -- which the LRM uses in its own
        // examples:
        //
        //     real distort[0:2][0:2] = '{ 3{ '{3{0.0}}}};
        //     ("all elements are initialized to 0.0 using an assignment pattern
        //       and replication operator")
        //
        // This loop read a plain comma-separated list, so it parsed the count as
        // an element, expected `,` or `}` next, met `{` and stopped:
        // "unexpected token '{'; expected ','". Note the replication that DOES
        // work, `{4{0}}`, is the CONCATENATION operator (Enhancement-34) -- a
        // different construct one apostrophe away, which LRM 4.2.13 warns is
        // easily confused with this one.
        //
        // The node built here has the same shape `concat_expr` produces for
        // `{n{...}}`: children `[count, elem0, elem1, ...]`, so `ReplicationExpr`
        // reads its `count()` and `elems()` unchanged. Expansion happens at HIR
        // lowering, where the count can be folded.
        let elem = p.start();
        if expr(p).is_none() {
            elem.abandon(p);
            break;
        }
        if p.at(T!['{']) {
            p.bump(T!['{']);
            while !p.at(EOF) && !p.at(T!['}']) {
                if expr(p).is_none() {
                    break;
                }
                if !p.at(T!['}']) && !p.expect(T![,]) {
                    break;
                }
            }
            p.expect(T!['}']);
            elem.complete(p, REPLICATION_EXPR);
        } else {
            elem.abandon(p);
        }

        if !p.at(T!['}']) && !p.expect(T![,]) {
            break;
        }
    }
    p.expect(T!['}']);

    m.complete(p, ARRAY_EXPR)
}

/// Enhancement-34: `{...}` is the Verilog-AMS *concatenation* operator, distinct from the
/// `'{...}` array-aggregate literal (`array_expr` above):
///
///   concatenation          ::= { expression { , expression } }            -> CONCAT_EXPR
///   multiple_concatenation ::= { expression { expression { , ... } } }    -> REPLICATION_EXPR
///
/// In the replication form the first expression is the (constant) repetition count and the
/// inner brace list holds the replicated elements; the node's children are therefore
/// `[count, elem0, elem1, ...]` (the inner braces produce no node of their own).
fn concat_expr(p: &mut Parser) -> CompletedMarker {
    let m = p.start();
    p.bump(T!['{']);
    if expr(p).is_none() {
        p.expect(T!['}']);
        return m.complete(p, CONCAT_EXPR);
    }

    if p.at(T!['{']) {
        // multiple_concatenation: `{ count { e0, e1, ... } }`
        p.bump(T!['{']);
        while !p.at(EOF) && !p.at(T!['}']) {
            if expr(p).is_none() {
                break;
            }
            if !p.at(T!['}']) && !p.expect(T![,]) {
                break;
            }
        }
        p.expect(T!['}']);
        p.expect(T!['}']);
        return m.complete(p, REPLICATION_EXPR);
    }

    while p.at(T![,]) {
        p.bump(T![,]);
        if expr(p).is_none() {
            break;
        }
    }
    p.expect(T!['}']);

    m.complete(p, CONCAT_EXPR)
}
