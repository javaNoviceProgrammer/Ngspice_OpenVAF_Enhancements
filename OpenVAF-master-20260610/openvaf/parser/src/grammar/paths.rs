use super::*;

pub(crate) const PATH_SEGMENT_TS: TokenSet = TokenSet::new(&[IDENT, ROOT_KW]);

pub(crate) fn path(p: &mut Parser) -> CompletedMarker {
    // Enhancement-213: this used to assert!(p.at_ts(PATH_SEGMENT_TS)). Several
    // callers do not check that precondition and reach here on malformed but
    // entirely plausible input -- `aliasparam x = 5;` (a literal where a
    // parameter name belongs), `I(<>)`, or a discipline member that is not an
    // identifier -- which crashed the compiler instead of reporting the error.
    // expect_ts() below already emits "expected identifier", so report that and
    // complete an (empty) path node rather than panicking.
    let path = p.start();
    p.expect_ts(PATH_SEGMENT_TS);
    let mut qual = path.complete(p, PATH);
    while p.at(T![.]) {
        // Hierarchical branch reference tail (Enhancement-86):
        // `.branch(a, b)` / `.branch(a)` / `.branch(<p>)`. Swallowed into
        // the path node so the enclosing item's CST stays whole -- the
        // elaboration hole scanner rewrites the reference textually, and a
        // leftover (unresolvable chain) fails name resolution on the
        // rewritten file rather than shredding the parse.
        if p.nth_at(1, BRANCH_KW) && p.nth_at(2, T!['(']) {
            let path = qual.precede(p);
            p.bump(T![.]);
            p.bump(BRANCH_KW);
            p.bump(T!['(']);
            let mut depth = 1u32;
            while depth > 0 && !p.at(EOF) {
                if p.at(T!['(']) {
                    depth += 1;
                } else if p.at(T![')']) {
                    depth -= 1;
                }
                p.bump_any();
            }
            qual = path.complete(p, PATH);
            break;
        }
        let path = qual.precede(p);
        p.bump(T![.]);
        p.expect_ts(PATH_SEGMENT_TS);
        let path = path.complete(p, PATH);
        qual = path;
    }
    qual
}
