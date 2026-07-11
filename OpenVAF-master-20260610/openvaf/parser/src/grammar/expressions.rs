use super::*;
use crate::grammar::call::{call, sys_fun_call};
use crate::grammar::paths::path;

const EXPR_EXPECTED: &[SyntaxKind] =
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

/// Report an over-deep expression and recover to the next expression boundary --
/// the same recovery the generic "unexpected token" path uses.
fn expr_too_deep(p: &mut Parser) {
    p.err_recover(p.unexpected_tokens_msg(EXPR_EXPECTED.to_owned()), EXPR_RECOVERY_SET);
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
            expr(p);
            p.expect(T![:]);
            expr(p);
            return Some(m.complete(p, SELECT_EXPR));
        }

        let m = lhs.precede(p);
        p.bump(op);

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
            atom_expr(p);
            m.complete(p, PREFIX_EXPR)
        }
        IDENT | ROOT_KW => {
            let m = path(p);
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
        INT_NUMBER | SI_REAL_NUMBER | STD_REAL_NUMBER | STR_LIT | INF_KW => {
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

    while !p.at(EOF) && !p.at(T![')']) {
        // test tuple_attrs
        // const A: (i64, i64) = (1, #[cfg(test)] 2);
        if expr(p).is_none() {
            break;
        }

        if !p.at(T![')']) {
            p.expect(T![,]);
        }
    }
    p.expect(T![')']);
    m.complete(p, PAREN_EXPR)
}

fn array_expr(p: &mut Parser) -> CompletedMarker {
    let m = p.start();
    p.bump(T!["'{"]);
    while !p.at(EOF) && !p.at(T!['}']) {
        if expr(p).is_none() {
            break;
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
