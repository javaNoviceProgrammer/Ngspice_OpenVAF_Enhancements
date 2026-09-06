use super::*;
use crate::grammar::paths::path;
mod module;
pub(super) use module::module;
use module::MODULE_ITEM_OR_ATTR_RECOVERY;

pub(super) const ITEM_RECOVERY_SET: TokenSet =
    TokenSet::new(&[DISCIPLINE_KW, NATURE_KW, MODULE_KW, PARAMSET_KW, EOF]);

const DISCIPLINE_RECOVERY_SET: TokenSet =
    ITEM_RECOVERY_SET.union(TokenSet::unique(ENDDISCIPLINE_KW));

pub(super) fn discipline(p: &mut Parser, m: Marker) {
    p.bump(T![discipline]);
    name_r(p, TokenSet::new(&[T![;]]));
    p.eat(T![;]);
    while !p.at_ts(DISCIPLINE_RECOVERY_SET) {
        let m = p.start();
        path(p);
        p.eat(T![=]);
        expr(p);
        if !p.eat(T![;]) {
            let err = p.unexpected_token_msg(T![;]);
            p.err_recover(err, DISCIPLINE_RECOVERY_SET.union(TokenSet::unique(IDENT)));
        }
        m.complete(p, DISCIPLINE_ATTR);
    }
    p.expect(ENDDISCIPLINE_KW);
    m.complete(p, DISCIPLINE_DECL);
}

const PARAMSET_RECOVERY_SET: TokenSet = ITEM_RECOVERY_SET.union(TokenSet::unique(ENDPARAMSET_KW));
/// Book audit (paramsets): what a paramset item may start with -- a
/// declaration keyword, an override's `.`, or a statement.
const PARAMSET_ITEM_TS: TokenSet = TokenSet::new(&[
    PARAMETER_KW, LOCALPARAM_KW, ALIASPARAM_KW, INTEGER_KW, REAL_KW, STRING_KW, T![.],
])
.union(crate::grammar::stmts::STMT_TS);

/// Parses a Verilog-AMS `paramset` (Enhancement-21):
///
/// ```verilog
/// paramset <name> <target_module>;
///     parameter real <p> = <default>;      // paramset's own (card) parameters
///     .<target_param> = <expr>;            // bind a target-module parameter
/// endparamset
/// ```
///
/// A paramset defines an instantiable model `<name>` that behaves like
/// `<target_module>` with the listed target parameters bound to the given
/// expressions (which may reference the paramset's own parameters).
///
/// Book audit (paramsets), LRM 6.4 Syntax 6-4: the body may also declare
/// `aliasparam`s and `integer`/`real` variables -- with `(* desc *)` an
/// output variable of the paramset (6.4.3) -- and carry statements (6.4.1:
/// the statements of an analog function), which compute those variables
/// from the module's own through `.name` references.
pub(super) fn paramset(p: &mut Parser, m: Marker) {
    p.bump(T![paramset]);
    // paramset name
    name_r(p, TokenSet::new(&[T![;], IDENT]));
    // target module name
    name_ref_r(p, TokenSet::new(&[T![;]]));
    p.eat(T![;]);
    while !p.at_ts(PARAMSET_RECOVERY_SET) {
        let m = p.start();
        // (the recovery set must not hold IDENT: an attribute's own name is one)
        attrs(
            p,
            PARAMSET_RECOVERY_SET.union(TokenSet::new(&[
                PARAMETER_KW, LOCALPARAM_KW, ALIASPARAM_KW, INTEGER_KW, REAL_KW, STRING_KW, T![.],
            ])),
        );
        match p.current() {
            PARAMETER_KW | LOCALPARAM_KW => parameter_decl(p, m),
            ALIASPARAM_KW => module::alias_parameter_decl(p, m),
            INTEGER_KW | REAL_KW | STRING_KW => var_decl(p, m),
            T![.] => paramset_override(p, m),
            _ if p.at_ts(crate::grammar::stmts::STMT_TS) => {
                stmt(p, m, crate::grammar::stmts::STMT_TS, PARAMSET_RECOVERY_SET)
            }
            _ => {
                let err = p.unexpected_tokens_msg(vec![
                    PARAMETER_KW,
                    LOCALPARAM_KW,
                    ALIASPARAM_KW,
                    REAL_KW,
                    INTEGER_KW,
                    T![.],
                ]);
                m.abandon(p);
                p.err_recover(err, PARAMSET_RECOVERY_SET.union(PARAMSET_ITEM_TS));
            }
        }
    }
    p.expect(ENDPARAMSET_KW);
    m.complete(p, PARAMSET_DECL);
}

/// Parses a single paramset override `.<target_param> = <expr>;`.
///
/// Enhancement-44: the overridden name may also be a hierarchical system
/// parameter (`.$mfactor = 8;`, LRM 6.4) — a SYSFUN token, wrapped in the
/// same NAME_REF node so downstream accessors see one shape.
fn paramset_override(p: &mut Parser, m: Marker) {
    p.bump(T![.]);
    if p.at(SYSFUN) {
        let name = p.start();
        p.bump(SYSFUN);
        name.complete(p, NAME_REF);
    } else {
        name_ref_r(p, TokenSet::new(&[T![=], T![;]]));
    }
    p.expect(T![=]);
    expr(p);
    p.eat(T![;]);
    m.complete(p, PARAMSET_OVERRIDE);
}

const NATURE_RECOVERY_SET: TokenSet = ITEM_RECOVERY_SET.union(TokenSet::unique(ENDNATURE_KW));

pub(super) fn nature(p: &mut Parser, m: Marker) {
    p.bump(T![nature]);
    name_r(p, TokenSet::new(&[T![;], T![:]]));
    if p.eat(T![:]) {
        // Enhancement-39: the parent of a derived nature is a PATH — either a plain
        // base nature (`nature X : Current;`) or a discipline's nature
        // (`nature X : electrical.flow;` / `: electrical.potential`). This previously
        // emitted a NAME_REF node, but the AST accessor (`NatureDecl::parent()`) looks
        // for a `Path` child — so the parent was silently always `None`, leaving the
        // fully-implemented inheritance machinery (units/ddt/idt/attribute lookup/
        // access compatibility via `NatureTy`) unreachable, and the
        // discipline-qualified form unparseable ("unexpected token '.'").
        if p.at_ts(crate::grammar::paths::PATH_SEGMENT_TS) {
            path(p);
        } else {
            let err = p.unexpected_token_msg(IDENT);
            p.err_recover(err, TokenSet::unique(T![;]));
        }
    }
    p.eat(T![;]);
    while !p.at_ts(NATURE_RECOVERY_SET) {
        let m = p.start();

        name_r(p, TokenSet::unique(T![=]));
        p.expect(T![=]);
        expr(p);
        if !p.eat(T![;]) {
            let err = p.unexpected_token_msg(T![;]);
            p.err_recover(err, NATURE_RECOVERY_SET.union(TokenSet::unique(IDENT)));
        }
        m.complete(p, NATURE_ATTR);
    }
    p.expect(ENDNATURE_KW);
    m.complete(p, NATURE_DECL);
}

pub(super) fn decl_list(
    p: &mut Parser,
    terminator: SyntaxKind,
    mut parse_entry: impl FnMut(&mut Parser) -> bool,
    recovery: TokenSet,
) {
    let recovery = recovery.union(TokenSet::new(&[terminator]));
    if p.at_ts(recovery) {
        p.error(p.unexpected_token_msg(IDENT));
    } else {
        while !p.at_ts(recovery) && parse_entry(p) {
            if !p.at(terminator) {
                p.expect_with(T![,], &[T![,], terminator]);
            }
        }
    }
}

pub(super) fn decl_name(p: &mut Parser) -> bool {
    name_r(p, TokenSet::new(&[T![,], T![;]]));
    true
}

pub(super) fn var_decl(p: &mut Parser, m: Marker) {
    ty(p);
    // One or more `[msb:lsb]` clauses: a 1-D array `real [0:n] x;` or a
    // multi-dimensional array `real [0:1][0:2] x;` (Enhancement-15).
    while p.at(T!['[']) {
        width_range(p);
    }
    decl_list(p, T![;], var, MODULE_ITEM_OR_ATTR_RECOVERY);
    p.eat(T![;]);
    m.complete(p, VAR_DECL);
}

fn var(p: &mut Parser) -> bool {
    let m = p.start();
    name_r(p, TokenSet::new(&[T!['['], T![,], T![=], T![;]]));
    // Optional name-then-range array dimensions: `x[0:n]`, or multi-dimensional
    // `m[0:1][0:2]` (Enhancement-18) -- the standard Verilog-AMS unpacked-array
    // form, complementing the range-then-name form (`real [0:n] x;`).
    while p.at(T!['[']) {
        width_range(p);
    }
    if p.eat(T![=]) {
        expr(p);
    }
    m.complete(p, VAR);
    true
}

pub(super) fn parameter_decl(p: &mut Parser, m: Marker) {
    p.bump_any();
    eat_ty(p);
    // Array-valued parameter: `parameter real [msb:lsb] c = '{...};` (Enhancement-14), or a
    // multi-dimensional one `parameter real [0:1][0:2] c = '{...};` (Enhancement-15). The
    // `[msb:lsb]` width clauses after the type mirror array-variable declarations (`var_decl`).
    while p.at(T!['[']) {
        width_range(p);
    }
    decl_list(p, T![;], parameter, MODULE_ITEM_OR_ATTR_RECOVERY);
    p.eat(T![;]);
    m.complete(p, PARAM_DECL);
}

const PARAM_RECOVER: TokenSet = MODULE_ITEM_OR_ATTR_RECOVERY.union(TokenSet::new(&[T![,], T![;]]));
fn parameter(p: &mut Parser) -> bool {
    let m = p.start();
    name_r(p, TokenSet::new(&[T!['['], T![,], T![=], T![;]]));
    // Enhancement-102: name-then-range array-valued parameter, `parameter real
    // c[0:2] = '{...};` (and multi-dimensional `c[0:1][0:2]`), mirroring the
    // array-variable form in `var()`. It complements the type-then-range form
    // `parameter real [0:2] c` (Enhancement-14/15); each name carries its own
    // dimensions, so a multi-name declaration may mix widths.
    while p.at(T!['[']) {
        width_range(p);
    }
    p.expect(T![=]);
    expr(p);
    while !p.at_ts(PARAM_RECOVER) {
        constraint(p)
    }
    m.complete(p, PARAM);
    true
}

fn constraint(p: &mut Parser) {
    let m = p.start();
    if !p.expect_ts_r(TokenSet::new(&[FROM_KW, EXCLUDE_KW]), PARAM_RECOVER) {
        m.abandon(p);
        return;
    }
    if p.eat(T!["'{"]) || p.eat(T!['{']) {
        // array range (for string parameters)
        expr(p);
        while p.eat(T![,]) {
            expr(p);
        }
        p.expect(T!['}']);
    } else {
        range_or_expr(p);
    }
    m.complete(p, CONSTRAINT);
}

/// Parses a `[msb:lsb]` bus-width clause, used by net/port declarations.
pub(super) fn width_range(p: &mut Parser) {
    let m = p.start();
    p.bump(T!['[']);
    expr(p);
    p.expect(T![:]);
    expr(p);
    p.expect(T![']']);
    m.complete(p, RANGE);
}

fn range_or_expr(p: &mut Parser) {
    let m = p.start();

    // while all branches parse an expr they need to eat [/( or nothing first
    #[allow(clippy::branches_sharing_code)]
    if p.eat(T!['(']) {
        expr(p);
        if !p.at(T![:]) {
            p.expect(T![')']);
            m.complete(p, PAREN_EXPR);
            return;
        }
    } else if p.eat(T!['[']) {
        expr(p);
    } else {
        expr(p);
        m.abandon(p);
        return;
    }

    p.expect(T![:]);
    expr(p);
    p.expect_ts(TokenSet::new(&[T![')'], T![']']]));
    m.complete(p, RANGE);
}
