use super::*;
use crate::grammar::stmts::{STMT_ATTR_RECOVER, STMT_RECOVER, STMT_TS};

const MODULE_ITEM_RECOVERY: TokenSet = DIRECTION_TS.union(TokenSet::new(&[
    NET_TYPE,
    ANALOG_KW,
    INITIAL_KW,
    BRANCH_KW,
    STRING_KW,
    REAL_KW,
    INTEGER_KW,
    PARAMETER_KW,
    LOCALPARAM_KW,
    GENVAR_KW,
    GENERATE_KW,
    ENDMODULE_KW,
    EOF,
]));
pub(super) const MODULE_ITEM_OR_ATTR_RECOVERY: TokenSet =
    MODULE_ITEM_RECOVERY.union(TokenSet::unique(T!["(*"]));

pub(crate) fn module(p: &mut Parser, m: Marker) {
    p.bump(T![module]);
    name_r(p, TokenSet::new(&[T!['('], T![;]]));
    if p.at(T!['(']) {
        let m = p.start();
        p.bump(T!['(']);
        module_ports(p);
        m.complete(p, MODULE_PORTS);
    }
    p.expect(T![;]);
    module_items(p);

    p.expect(ENDMODULE_KW);

    m.complete(p, MODULE_DECL);
}

const MODULE_PORTS_RECOVERY: TokenSet = TokenSet::new(&[T![;], T![')'], ENDMODULE_KW, EOF]);

fn module_ports(p: &mut Parser) {
    while !p.at_ts(MODULE_PORTS_RECOVERY) {
        let m = p.start();
        if !eat_name(p) {
            let m = p.start();
            attrs(p, MODULE_PORTS_RECOVERY.union(DIRECTION_TS));
            port_decl::<true>(p, m)
        }
        m.complete(p, MODULE_PORT);
        if !p.at(T![')']) {
            p.expect_with(T![,], &[T![,], T![')']]);
        }
    }
    p.expect(T![')']);
}

/// Enhancement-58: `defparam <path> = <expr> [, <path> = <expr>]* ;` — a
/// compile-time hierarchical parameter override (legacy Verilog-2001 form,
/// LRM 2.6). Each `<path>` names a parameter, usually inside an instance
/// (`u1.r`, `u1.u2.r`). The DEFPARAM node is consumed entirely by the E-5
/// elaboration pass (it resolves each target to the flattened parameter and
/// rewrites that parameter's default), so it is deliberately NOT a typed
/// `ast::ModuleItem` — later compiler stages never see it.
pub(super) fn defparam_decl(p: &mut Parser, m: Marker) {
    p.bump(DEFPARAM_KW);
    loop {
        if p.at_ts(crate::grammar::paths::PATH_SEGMENT_TS) {
            path(p);
        }
        p.expect(T![=]);
        expr(p);
        if !p.eat(T![,]) {
            break;
        }
    }
    p.eat(T![;]);
    m.complete(p, DEFPARAM);
}

pub(super) fn alias_parameter_decl(p: &mut Parser, m: Marker) {
    p.bump(ALIASPARAM_KW);
    name_r(p, TokenSet::new(&[T![;], T![=]]));
    p.expect(T![=]);
    if p.at(SYSFUN) {
        let m = p.start();
        p.bump_any();
        m.complete(p, SYS_FUN);
    } else {
        path(p);
    }
    p.eat(T![;]);
    m.complete(p, ALIAS_PARAM);
}

const DIRECTION_TS: TokenSet = TokenSet::new(&[T![inout], T![output], T![input]]);
const MODULE_PORT_RECOVERY: TokenSet =
    MODULE_PORTS_RECOVERY.union(DIRECTION_TS).union(TokenSet::unique(T!["(*"]));
const NET_RECOVERY: TokenSet = TokenSet::new(&[EOF, ENDMODULE_KW, T![;]]);

fn port_decl<const MODULE_HEAD: bool>(p: &mut Parser, m: Marker) {
    let direction = p.start();
    // Module-head callers reach here for anything that is not a plain port
    // name, so a missing direction must become a diagnostic (with one token
    // of forced progress), not an assertion failure.
    p.expect_ts_r(DIRECTION_TS, MODULE_PORT_RECOVERY);
    direction.complete(p, DIRECTION);

    //direction and type are both optional since only one is required
    if !p.nth_at_ts(1, MODULE_PORT_RECOVERY.union(TokenSet::unique(T![,]))) {
        eat_name_ref(p);
    }
    p.eat(NET_TYPE);
    if p.at(T!['[']) {
        width_range(p);
    }

    if MODULE_HEAD {
        decl_list(p, T![')'], module_port, MODULE_PORT_RECOVERY);
    } else {
        net_dec_list(p);
    }

    let finished = m.complete(p, PORT_DECL);
    if !MODULE_HEAD {
        let m = finished.precede(p);
        p.eat(T![;]);
        m.complete(p, BODY_PORT_DECL);
    }
}

fn module_port(p: &mut Parser) -> bool {
    name_r(p, MODULE_PORT_RECOVERY.union(TokenSet::unique(T![,])));
    !(p.at(T![,]) && p.nth_at_ts(1, MODULE_PORT_RECOVERY))
}

fn module_items(p: &mut Parser) {
    let mut error_range: Option<CompletedMarker> = None;
    while !p.at_ts(ITEM_RECOVERY_SET.union(TokenSet::unique(ENDMODULE_KW))) {
        let m = p.start();
        attrs(p, MODULE_ITEM_RECOVERY);

        match p.current() {
            ANALOG_KW if p.nth(1) == FUNCTION_KW => func_decl(p, m),
            ANALOG_KW => {
                p.bump(ANALOG_KW);
                p.eat(INITIAL_KW);
                stmt_with_attrs(p);
                m.complete(p, ANALOG_BEHAVIOUR);
            }
            NET_TYPE => {
                net_decl::<true>(p, m);
            }
            IDENT if is_instantiation(p) => {
                instantiation(p, m);
            }
            IDENT => {
                net_decl::<false>(p, m);
            }
            PARAMETER_KW | LOCALPARAM_KW => {
                parameter_decl(p, m);
            }
            ALIASPARAM_KW => {
                alias_parameter_decl(p, m);
            }
            DEFPARAM_KW => {
                defparam_decl(p, m);
            }
            BRANCH_KW => {
                branch_decl(p, m);
            }
            GENVAR_KW => {
                genvar_decl(p, m);
            }
            GENERATE_KW => {
                generate_region(p, m);
            }
            // Enhancement-96: a module-level `generate for`/`if`/`case` whose
            // `generate`/`endgenerate` keywords are omitted (LRM: they are not
            // required). Without these arms a bare `for`/`if`/`case` at module
            // scope fell through to the error recovery below -- "unexpected
            // token 'for'" -- or, when a following `analog` block let recovery
            // resync, silently dropped the construct. Parsed here as the same
            // GENERATE_FOR/IF/CASE nodes the nested form produces (top = false:
            // no `endgenerate` of their own).
            FOR_KW => {
                generate_for_tail(p, m, false);
            }
            IF_KW => {
                generate_if_tail(p, m, false);
            }
            CASE_KW => {
                generate_case_tail(p, m, false);
            }
            INTEGER_KW | REAL_KW | STRING_KW => var_decl(p, m),
            INPUT_KW | OUTPUT_KW | INOUT_KW => port_decl::<false>(p, m),
            _ => {
                error_range = if let Some(error_range) = error_range {
                    m.abandon(p);
                    p.bump_any();
                    while !p.at_ts(MODULE_ITEM_RECOVERY) {
                        p.bump_any();
                    }
                    Some(error_range.undo_completion(p).complete(p, ERROR))
                } else {
                    let err = p.unexpected_tokens_msg(vec![
                        FUNCTION,
                        PORT_DECL,
                        NET_DECL,
                        ANALOG_BEHAVIOUR,
                    ]);
                    p.error(err);
                    p.bump_any();
                    while !p.at_ts(MODULE_ITEM_RECOVERY) {
                        p.bump_any();
                    }
                    Some(m.complete(p, ERROR))
                }
            }
        }
    }
}

fn net_decl<const NET_TYPE_FIRST: bool>(p: &mut Parser, m: Marker) {
    //direction and type ar both optional since only one is required
    if NET_TYPE_FIRST {
        p.bump(NET_TYPE);
        if !p.nth_at_ts(1, TokenSet::new(&[T![,], T![;]])) {
            eat_name_ref(p);
        }
    } else {
        name_ref_r(p, MODULE_ITEM_OR_ATTR_RECOVERY.union(TokenSet::unique(T![;])));
        // Allow an optional net-type after the discipline, e.g.
        // `electrical ground gnd;`, mirroring the `ground electrical gnd;`
        // form (and `port_decl`, which already accepts a net-type here).
        p.eat(NET_TYPE);
    }

    if p.at(T!['[']) {
        width_range(p);
    }

    net_dec_list(p);
    p.eat(T![;]);
    m.complete(p, NET_DECL);
}

fn net_dec_list(p: &mut Parser) {
    decl_list(p, T![;], net_decl_name, NET_RECOVERY);
}

/// A single net declarator: a name with an optional nodeset initializer
/// (`electrical a = 5.0;`, LRM 3.6.3.2, Enhancement-45). The initializer
/// expression becomes a direct NET_DECL child following its NAME node.
fn net_decl_name(p: &mut Parser) -> bool {
    name_r(p, TokenSet::new(&[T![,], T![=], T![;]]));
    if p.eat(T![=]) {
        expr(p);
    }
    true
}

const FUNCTION_RECOVER: TokenSet = TokenSet::new(&[EOF, ENDMODULE_KW, ENDFUNCTION_KW]);
const FUN_ITEM_TS: TokenSet = TokenSet::new(&[PARAMETER_KW, LOCALPARAM_KW])
    .union(TYPE_TS)
    .union(STMT_RECOVER)
    .union(DIRECTION_TS)
    .union(STMT_TS);

fn func_decl(p: &mut Parser, m: Marker) {
    p.bump(T![analog]);
    p.bump(T![function]);
    eat_ty(p);
    // Optional array return dimensions `analog function real[0:n] f;` (Enhancement-23): one
    // `[msb:lsb]` clause per dimension, before the function name, mirroring an array variable's
    // range-then-name form. The function then returns a whole array.
    while p.at(T!['[']) {
        width_range(p);
    }
    name_r(p, TokenSet::new(&[T![;], T!['(']]));
    // Enhancement-389: the ANSI-style header
    // `analog function real f(input real x, output real y);`. The arguments are
    // emitted as ordinary FUNCTION_ARG children of the FUNCTION node, so they
    // reach `lower_fun` through `function_items()` exactly like the separated
    // `input x; real x;` form and need no separate lowering path.
    if p.at(T!['(']) {
        ansi_func_args(p);
    }
    p.expect(T![;]);

    while !p.at_ts(FUNCTION_RECOVER) {
        let m = p.start();
        // Bug-hunt F17: the recovery set handed to `attrs` must not contain
        // bare IDENT (FUN_ITEM_TS pulls it in through STMT_TS) -- inside
        // `(* std=3.0 *)` the attribute NAME is an IDENT, so attr_list bailed
        // out at `std`, the name was re-parsed as an assignment STATEMENT,
        // and the trailing `*)` died as "unexpected token '*)'; expected ';'".
        // Every attribute on a function item -- desc, units, the statistics
        // set -- was unwritable. Recover on the keyword-shaped item starters
        // and the function/statement recovery points instead, exactly the
        // shape stmts.rs's STMT_ATTR_RECOVER uses.
        attrs(
            p,
            TokenSet::new(&[PARAMETER_KW, LOCALPARAM_KW])
                .union(TYPE_TS)
                .union(DIRECTION_TS)
                .union(STMT_ATTR_RECOVER)
                .union(FUNCTION_RECOVER),
        );
        if p.at_ts(TYPE_TS) {
            var_decl(p, m)
        } else if p.at_ts(TokenSet::new(&[PARAMETER_KW, LOCALPARAM_KW])) {
            parameter_decl(p, m)
        } else if p.at_ts(DIRECTION_TS) {
            func_arg(p, m);
        } else {
            stmt(p, m, FUN_ITEM_TS, FUNCTION_RECOVER)
        }
    }
    p.expect(ENDFUNCTION_KW);
    m.complete(p, FUNCTION);
}

const FUNC_ARG_RECOVER: TokenSet = TokenSet::new(&[EOF, ENDMODULE_KW]);
fn func_arg(p: &mut Parser, m: Marker) {
    let direction = p.start();
    p.expect_ts_r(DIRECTION_TS, FUNC_ARG_RECOVER);
    direction.complete(p, DIRECTION);

    // Enhancement-389: the COMBINED declaration `input real x;`. Verilog-AMS
    // allows the direction and the data type in one statement; openvaf accepted
    // only the separated `input x; real x;`. The type is optional here, so the
    // separated form parses exactly as before -- an argument with no type of its
    // own still takes it from a matching `real x;` (or defaults to real).
    eat_ty(p);

    // LRM 4.7.1 Example 3 (UDF audit): the LRM's own spelling of an array
    // formal puts the range on the DIRECTION line -- `inout [0:1]a; input
    // [0:1]b; real a[0:1], b[0:1];` -- and it was "unexpected token '['".
    // The compiler's own namerange elaboration pass even REWRITES the
    // name-then-range spelling (`output o[0:1];`) into exactly this
    // range-then-name form, generating syntax its own parser then refused.
    // The range is accepted here; the argument's array dimensions come from
    // its mandatory data-type block-item declaration (which Example 3
    // carries), so the clause is informational -- the same dual-declaration
    // redundancy the LRM itself writes.
    while p.at(T!['[']) {
        width_range(p);
    }

    decl_list(p, T![;], decl_name, FUNC_ARG_RECOVER);
    p.eat(T![;]);
    m.complete(p, FUNCTION_ARG);
}

/// Enhancement-389: the argument list of an ANSI-style function header.
///
/// Each entry is `[direction] [type] name`. Per the LRM an entry may restate
/// neither -- `f(input real x, y)` gives `y` the direction and type of `x` --
/// which `lower_fun` resolves by carrying the previous entry forward.
///
/// Array arguments are NOT accepted in this position (nor in the combined form
/// above): an array argument still needs the separated `output w; real w[0:3];`,
/// whose declaration-level range machinery has no counterpart here.
fn ansi_func_args(p: &mut Parser) {
    p.bump(T!['(']);
    if p.eat(T![')']) {
        return;
    }
    let recover = FUNC_ARG_RECOVER.union(TokenSet::new(&[T![')'], T![;]]));
    while !p.at_ts(recover) {
        let m = p.start();
        if p.at_ts(DIRECTION_TS) {
            let direction = p.start();
            p.bump_ts(DIRECTION_TS);
            direction.complete(p, DIRECTION);
        }
        eat_ty(p);
        name_r(p, TokenSet::new(&[T![,], T![')'], T![;]]));
        m.complete(p, FUNCTION_ARG);
        if !p.at(T![,]) {
            break;
        }
        p.bump(T![,]);
    }
    p.expect(T![')']);
}

fn branch_decl(p: &mut Parser, m: Marker) {
    p.bump(BRANCH_KW);
    if !p.at(T!['(']) {
        p.error(p.unexpected_token_msg(T!['(']));
    }
    arg_list(p);
    decl_list(p, T![;], decl_name, MODULE_ITEM_OR_ATTR_RECOVERY);
    p.eat(T![;]);
    m.complete(p, BRANCH_DECL);
}

/// Disambiguates a module-instantiation statement (`module_name [#(...)]
/// instance_name [range] (ports);`) from an ordinary net declaration
/// (`discipline_name name (',' name)* ;`), both of which start with a bare
/// `IDENT`. A `#` right after the first identifier is an unambiguous
/// instantiation marker; otherwise, a second `IDENT` followed by `(` or `[`
/// (instance ports / an instance-array range) means instantiation, while a
/// second `IDENT` followed by `,`/`;` means an (possibly single-net) net
/// declaration.
fn is_instantiation(p: &Parser) -> bool {
    p.nth_at(1, T![#])
        || (p.nth_at(1, IDENT) && (p.nth_at(2, T!['(']) || p.nth_at(2, T!['['])))
}

fn instantiation(p: &mut Parser, m: Marker) {
    name_ref_r(p, TokenSet::new(&[T![#], IDENT, T!['(']]));

    if p.at(T![#]) {
        let m = p.start();
        p.bump(T![#]);
        p.expect(T!['(']);
        if !p.at(T![')']) {
            param_assign(p);
            while p.eat(T![,]) {
                param_assign(p);
            }
        }
        p.expect(T![')']);
        m.complete(p, PARAM_OVERRIDES);
    }

    instance_unit(p);
    while p.eat(T![,]) {
        instance_unit(p);
    }
    p.eat(T![;]);
    m.complete(p, INSTANTIATION);
}

fn param_assign(p: &mut Parser) {
    let m = p.start();
    if p.eat(T![.]) {
        // A hierarchical system parameter override (`#(.$mfactor(4))`,
        // LRM 6.3.6): a SYSFUN token wrapped in the same NAME node an
        // ordinary parameter name gets, so downstream accessors see one
        // shape (the paramset override grammar does the same with
        // NAME_REF). Used to fall into `name_r`'s error recovery, which
        // swallowed the token into an ERROR node -- and because that
        // parse error is only attached to the pre-elaboration tree, the
        // override was dropped without any diagnostic at all.
        if p.at(SYSFUN) {
            let name = p.start();
            p.bump(SYSFUN);
            name.complete(p, NAME);
            p.expect(T!['(']);
            expr(p);
            p.expect(T![')']);
            m.complete(p, PARAM_ASSIGN);
            return;
        }
        name_r(p, TokenSet::new(&[T!['('], T![.]]));
        // Enhancement-87: a hierarchical override target (`.blk.p(...)`, e.g.
        // an attempt to reach a block-scoped parameter). The LRM only permits
        // a simple parameter name here, so consume any extra `.segment`s to
        // keep the parse clean -- CST validation rejects the multi-segment
        // form with a targeted diagnostic instead of a parser cascade.
        while p.at(T![.]) {
            p.bump(T![.]);
            name_r(p, TokenSet::new(&[T!['('], T![.]]));
        }
        p.expect(T!['(']);
        expr(p);
        p.expect(T![')']);
    } else {
        expr(p);
    }
    m.complete(p, PARAM_ASSIGN);
}

fn instance_unit(p: &mut Parser) {
    let m = p.start();
    name_r(p, TokenSet::new(&[T!['['], T!['(']]));
    if p.at(T!['[']) {
        width_range(p);
    }
    port_conns(p);
    m.complete(p, INSTANCE_UNIT);
}

fn port_conns(p: &mut Parser) {
    let m = p.start();
    p.expect(T!['(']);
    if !p.at(T![')']) {
        port_conn(p);
        while p.eat(T![,]) {
            port_conn(p);
        }
    }
    p.expect(T![')']);
    m.complete(p, PORT_CONNS);
}

/// A single port actual: named (`.p(net)`), positional (`net`), or an empty
/// slot (an open/unconnected port, e.g. the middle of `inst(a, , c)`).
fn port_conn(p: &mut Parser) {
    let m = p.start();
    if p.at(T![,]) || p.at(T![')']) {
        // open port: emit an empty PORT_CONN node, don't consume anything
    } else if p.eat(T![.]) {
        name_r(p, TokenSet::unique(T!['(']));
        p.expect(T!['(']);
        if !p.at(T![')']) {
            expr(p);
        }
        p.expect(T![')']);
    } else {
        expr(p);
    }
    m.complete(p, PORT_CONN);
}

/// `genvar i, j;` -- one or more compile-time-only loop variables, only
/// ever legal as the loop variable of a `generate for`.
fn genvar_decl(p: &mut Parser, m: Marker) {
    p.bump(GENVAR_KW);
    decl_list(p, T![;], decl_name, MODULE_ITEM_OR_ATTR_RECOVERY);
    p.eat(T![;]);
    m.complete(p, GENVAR_DECL);
}

/// `i = 0` / `i = i + 1` -- a bare assignment (no trailing `;` consumed
/// here; the caller controls the separator), reused for the `init`/`incr`
/// clauses of a `generate for` header, mirroring `stmts::assign_or_expr`.
fn generate_assign(p: &mut Parser) {
    let m = p.start();
    expr(p);
    p.expect(T![=]);
    expr(p);
    m.complete(p, ASSIGN);
}

/// `generate <for|if|case> ... endgenerate` -- dispatches on the construct
/// following the `generate` keyword (Enhancement-67; previously only `for`).
fn generate_region(p: &mut Parser, m: Marker) {
    p.bump(GENERATE_KW);
    match p.current() {
        IF_KW => {
            generate_if_tail(p, m, true);
        }
        CASE_KW => {
            generate_case_tail(p, m, true);
        }
        _ => {
            generate_for_tail(p, m, true);
        }
    }
}

/// `for (i = 0; i < N; i = i + 1) begin [: label] ... end` -- the loop part
/// of a generate region. `top` distinguishes a top-level region (whose
/// closing `endgenerate` belongs to this node) from a NESTED loop inside
/// another generate block (Enhancement-67), which has neither `generate`
/// nor `endgenerate` of its own.
fn generate_for_tail(p: &mut Parser, m: Marker, top: bool) {
    p.expect(FOR_KW);
    p.expect(T!['(']);
    generate_assign(p);
    p.expect(T![;]);
    expr(p);
    p.expect(T![;]);
    generate_assign(p);
    p.expect(T![')']);

    generate_block(p);

    if top {
        p.expect(ENDGENERATE_KW);
    }
    m.complete(p, GENERATE_FOR);
}

/// `if (<const-expr>) begin [: label] ... end [else if ... | else begin ...]`
/// (Enhancement-67). Branch bodies must be begin/end generate blocks; an
/// `else if` chain nests a new GENERATE_IF inside the else position.
fn generate_if_tail(p: &mut Parser, m: Marker, top: bool) {
    p.expect(IF_KW);
    p.expect(T!['(']);
    expr(p);
    p.expect(T![')']);
    generate_block(p);
    if p.eat(ELSE_KW) {
        if p.at(IF_KW) {
            let inner = p.start();
            generate_if_tail(p, inner, false);
        } else {
            generate_block(p);
        }
    }
    if top {
        p.expect(ENDGENERATE_KW);
    }
    m.complete(p, GENERATE_IF);
}

/// `case (<const-expr>) v[, v]*: begin ... end ... [default[:] begin ... end]
/// endcase` (Enhancement-67).
fn generate_case_tail(p: &mut Parser, m: Marker, top: bool) {
    p.expect(CASE_KW);
    p.expect(T!['(']);
    expr(p);
    p.expect(T![')']);
    while !p.at(ENDCASE_KW) && !p.at(EOF) && !p.at(ENDGENERATE_KW) && !p.at(ENDMODULE_KW) {
        let arm = p.start();
        if p.eat(DEFAULT_KW) {
            p.eat(T![:]);
        } else {
            expr(p);
            while p.eat(T![,]) {
                expr(p);
            }
            p.expect(T![:]);
        }
        generate_block(p);
        arm.complete(p, GENERATE_CASE_ARM);
    }
    p.expect(ENDCASE_KW);
    if top {
        p.expect(ENDGENERATE_KW);
    }
    m.complete(p, GENERATE_CASE);
}

const GENERATE_BLOCK_RECOVER: TokenSet = TokenSet::new(&[END_KW, EOF, ENDMODULE_KW, ENDGENERATE_KW]);

/// The `begin : label ... end` body of a `generate for` loop. Its items are
/// ordinary `ModuleItem`s -- nets, instances, vars, params, and (since
/// Enhancement-390) `analog` blocks -- not statements.
///
/// Book audit (generate names), LRM 6.6.2 / 1364-2005 A.4.2: a generate
/// block may also be ONE item with no `begin`/`end` -- `if (c) electrical a;
/// else electrical b;`, `for (...) if (1) electrical a;` -- the shape the
/// LRM's own 6.6.3 example is written in. It used to parse as a block missing
/// its `begin`, swallowing every following item up to the next `end`.
fn generate_block(p: &mut Parser) {
    let m = p.start();
    if !p.at(BEGIN_KW) {
        generate_block_item(p);
        m.complete(p, GENERATE_BLOCK);
        return;
    }
    p.bump(BEGIN_KW);
    // the `: label` is optional (Enhancement-67): anonymous generate blocks
    // are legal per 1364-2005; elaboration auto-names them.
    if p.eat(T![:]) {
        name(p);
    }

    while !p.at_ts(GENERATE_BLOCK_RECOVER) {
        generate_block_item(p);
    }
    p.expect(END_KW);
    m.complete(p, GENERATE_BLOCK);
}

/// One item of a generate block.
fn generate_block_item(p: &mut Parser) {
    {
        let m = p.start();
        attrs(p, MODULE_ITEM_RECOVERY);
        match p.current() {
            // nested generate constructs (no `generate`/`endgenerate` of
            // their own -- Enhancement-67)
            FOR_KW => {
                generate_for_tail(p, m, false);
            }
            IF_KW => {
                generate_if_tail(p, m, false);
            }
            CASE_KW => {
                generate_case_tail(p, m, false);
            }
            IDENT if is_instantiation(p) => {
                instantiation(p, m);
            }
            IDENT => {
                net_decl::<false>(p, m);
            }
            NET_TYPE => {
                net_decl::<true>(p, m);
            }
            PARAMETER_KW | LOCALPARAM_KW => {
                parameter_decl(p, m);
            }
            INTEGER_KW | REAL_KW | STRING_KW => var_decl(p, m),
            // Enhancement-390: an `analog` block is a module item, so it is legal
            // inside a generate block -- `generate for (i=0;i<N;i=i+1) begin
            // analog I(p,n) <+ ...; end` is the natural way to build N identical
            // contributions. It used to land in the catch-all below, and the
            // resulting parse error was then SWALLOWED: elaboration re-renders the
            // generate region from its syntax tree, so the error never reached the
            // user and the malformed node rendered to nothing. The block compiled
            // clean, reported no diagnostics, and contributed exactly zero.
            ANALOG_KW if p.nth(1) == FUNCTION_KW => func_decl(p, m),
            ANALOG_KW => {
                p.bump(ANALOG_KW);
                p.eat(INITIAL_KW);
                stmt_with_attrs(p);
                m.complete(p, ANALOG_BEHAVIOUR);
            }
            // `defparam u.g = 2e-3 * i;` targeting an instance declared in
            // this (or an enclosing) generate block is legal (LRM 6.3.1,
            // "defparam statements in the same module ... including
            // generate blocks"). It used to fall into the recovery below --
            // and because elaboration re-renders the generate region from
            // its syntax tree, the parse error was swallowed and the
            // override silently vanished (same failure shape as the
            // Enhancement-390 `analog` arm above).
            DEFPARAM_KW => {
                defparam_decl(p, m);
            }
            BRANCH_KW => {
                branch_decl(p, m);
            }
            ALIASPARAM_KW => {
                alias_parameter_decl(p, m);
            }
            _ => {
                m.abandon(p);
                let err =
                    p.unexpected_tokens_msg(vec![NET_DECL, INSTANTIATION, VAR_DECL, ANALOG_BEHAVIOUR]);
                p.error(err);
                p.bump_any();
                while !p.at_ts(MODULE_ITEM_RECOVERY.union(GENERATE_BLOCK_RECOVER)) {
                    p.bump_any();
                }
            }
        }
    }
}
