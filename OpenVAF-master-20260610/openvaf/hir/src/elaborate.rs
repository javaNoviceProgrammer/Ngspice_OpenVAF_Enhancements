//! Module-instantiation elaboration: a text-level "flattening" pass that
//! turns `resistor #(.r(1e3)) r1(in, out);`-style instantiation statements
//! into an ordinary, hand-written-looking flat module, by textually
//! inlining the referenced module's own declarations (alpha-renamed with a
//! per-instance prefix, with ports/parameters bound to the instantiation's
//! actual arguments) in place of the instantiation statement.
//!
//! This runs once, eagerly, right after a [`CompilationDB`] is constructed
//! (see [`elaborate_instantiations`]), entirely as ordinary Rust code
//! operating on the already-working `db`/`root_file` -- it does not hook
//! into the salsa `parse`/`preprocess` query chain. If elaboration produces
//! new text, it is registered as a new virtual file in the database's
//! `Vfs` and `db.root_file` is redirected to it; every downstream stage
//! (`hir_def`, `hir_ty`, `hir_lower`, `mir*`, `sim_back`, `osdi`) then sees
//! what looks like an ordinary flat file and requires zero changes.
//!
//! Known limitation: diagnostics for code that originated inside an
//! inlined instance point at the synthesized flattened file, not the
//! original module's source location (no cross-file span provenance is
//! tracked, unlike the `` `include``/macro-expansion machinery in
//! `preprocessor::sourcemap`, which this pass deliberately does not hook
//! into -- see `Enhancement-5.md` for the rationale).
//!
//! Bus-typed ports and per-element instance-array port slicing (e.g.
//! `resistor rarr[0:3](p, gnd);` where `p` is itself a matching-width bus,
//! wiring element `i` to `p[i]`) are supported via a single heuristic
//! (`find_matching_caller_bus`): a port actual is sliced only when it is a
//! *bare identifier* naming a bus, in the instantiating module's own
//! scope, whose bit width exactly matches what needs slicing (the target
//! bus port's width, or the instance array's element count); anything else
//! (a non-bus net, a mismatched width, a non-trivial expression) is
//! bound/broadcast verbatim instead, matching ordinary (non-sliced)
//! connection semantics.
//!
//! A bus *port* needs a different substitution mechanism than everything
//! else in this pass: an ordinary rename (`p` -> `prefix__p`) is a single
//! whole-token substitution, but a bus port's bit 0 and bit 1 need to
//! become *different* identities (e.g. `a[0]`/`a[1]`), and the source text
//! only ever contains the bare base identifier (`p`) with the bit-select
//! (`[0]`) as separate tokens right after it -- there is no single token
//! to look up a per-bit answer under. `find_bus_port_holes` handles this
//! by scanning for `ident '[' int_literal ']'` token sequences matching a
//! bus port's base name and replacing the *whole* sequence, turning it
//! into an ordinary hole for `render_with_holes`.

use std::collections::{BTreeMap, BTreeSet, HashMap, HashSet};
use std::ops::Range;
use std::rc::Rc;

use basedb::{AstId, AstIdMap, BaseDB, VfsStorage};
use hir_def::db::HirDefDB;
use hir_def::item_tree::{bus_bit_name, BusDecl, ItemTree, Module as TreeModule, ModuleItem};
use hir_def::nameres::diagnostics::DefDiagnostic;
use hir_def::{ItemTreeId, ParamSysFun};
use syntax::ast::ArgListOwner;
use syntax::name::{AsName, Name};
use syntax::{ast, AstNode, ConstExprValue, Parse, SourceFile, TextRange, TextSize};
use tokens::lexer::TokenKind;

use crate::db::CompilationDB;



/// A lexer token with its byte span in the source.
struct Tok {
    start: usize,
    end: usize,
    kind: TokenKind,
}

fn tok_spans(text: &str) -> Vec<Tok> {
    let mut spans = Vec::new();
    let mut pos = 0usize;
    for t in lexer::tokenize(text) {
        let start = pos;
        let end = pos + usize::from(t.len);
        pos = end;
        spans.push(Tok { start, end, kind: t.kind });
    }
    spans
}

/// Evaluates a constant integer expression over the raw token slice
/// `spans[lo..hi]` of `text` (decimal literals, `+ - * /`, unary `-`,
/// parens). Any identifier or unsupported token makes the whole thing
/// non-constant (`None`) -- e.g. a module parameter, which cannot shape a
/// compile-time unroll. Shared by the legacy-generate bound evaluation and
/// its bit-select index folding (Enhancement-88).
fn eval_const_int_tokens(text: &str, spans: &[Tok], lo: usize, hi: usize) -> Option<i32> {
    eval_const_int_with_params(text, spans, lo, hi, &HashMap::new())
}

/// Like `eval_const_int_tokens` but resolves bare identifiers against `params`
/// (a name -> constant-integer map), used by the Enhancement-91
/// parameter-dependent bus-width fold. With an empty map it is identical to
/// `eval_const_int_tokens` (identifiers make the fold fail), which is what the
/// Enhancement-88 legacy-generate bounds evaluator relies on.
fn eval_const_int_with_params(
    text: &str,
    spans: &[Tok],
    lo: usize,
    hi: usize,
    params: &HashMap<String, i32>,
) -> Option<i32> {
    // Gather the significant (non-trivia) tokens in [lo, hi).
    let toks: Vec<&Tok> = spans[lo..hi].iter().filter(|t| !is_trivia(t.kind)).collect();
    let mut pos = 0usize;
    let res = parse_add(text, &toks, &mut pos, params)?;
    if pos == toks.len() {
        Some(res)
    } else {
        None
    }
}

fn parse_add(text: &str, toks: &[&Tok], pos: &mut usize, params: &HashMap<String, i32>) -> Option<i32> {
    let mut acc = parse_mul(text, toks, pos, params)?;
    while *pos < toks.len() {
        let raw = &text[toks[*pos].start..toks[*pos].end];
        match raw {
            // Enhancement-314: checked, like parse_mul's checked_mul below -- an
            // integer bus-width expression that overflows i32 (2147483647 + 1)
            // otherwise panicked the (overflow-checked) build. On overflow the fold
            // fails to None and the caller (fold_parameter_widths) simply leaves the
            // declaration unchanged, exactly as it does for any un-foldable width.
            "+" => {
                *pos += 1;
                acc = acc.checked_add(parse_mul(text, toks, pos, params)?)?;
            }
            "-" => {
                *pos += 1;
                acc = acc.checked_sub(parse_mul(text, toks, pos, params)?)?;
            }
            _ => break,
        }
    }
    Some(acc)
}

fn parse_mul(text: &str, toks: &[&Tok], pos: &mut usize, params: &HashMap<String, i32>) -> Option<i32> {
    let mut acc = parse_unary(text, toks, pos, params)?;
    while *pos < toks.len() {
        let raw = &text[toks[*pos].start..toks[*pos].end];
        match raw {
            "*" => {
                *pos += 1;
                acc = acc.checked_mul(parse_unary(text, toks, pos, params)?)?;
            }
            "/" => {
                *pos += 1;
                let d = parse_unary(text, toks, pos, params)?;
                if d == 0 {
                    return None;
                }
                acc /= d;
            }
            _ => break,
        }
    }
    Some(acc)
}

fn parse_unary(text: &str, toks: &[&Tok], pos: &mut usize, params: &HashMap<String, i32>) -> Option<i32> {
    let raw = &text[toks.get(*pos)?.start..toks[*pos].end];
    match raw {
        "-" => {
            *pos += 1;
            // Enhancement-314: checked negate -- negating i32::MIN overflowed.
            parse_unary(text, toks, pos, params)?.checked_neg()
        }
        "+" => {
            *pos += 1;
            parse_unary(text, toks, pos, params)
        }
        _ => parse_atom(text, toks, pos, params),
    }
}

fn parse_atom(text: &str, toks: &[&Tok], pos: &mut usize, params: &HashMap<String, i32>) -> Option<i32> {
    let t = toks.get(*pos)?;
    let raw = &text[t.start..t.end];
    if t.kind == TokenKind::OpenParen {
        *pos += 1;
        let v = parse_add(text, toks, pos, params)?;
        if toks.get(*pos)?.kind != TokenKind::CloseParen {
            return None;
        }
        *pos += 1;
        return Some(v);
    }
    if matches!(t.kind, TokenKind::Literal { .. }) {
        *pos += 1;
        return raw.replace('_', "").parse::<i32>().ok();
    }
    // Enhancement-91: a bare identifier resolves to a parameter's
    // elaboration-time value when known (empty map => not resolvable).
    if t.kind == TokenKind::SimpleIdent {
        if let Some(&v) = params.get(raw) {
            *pos += 1;
            return Some(v);
        }
    }
    None
}

/// Collects one `[type] name = <expr>` group of a parameter declaration
/// (Enhancement-91). `lo`/`hi` are significant-token positions bounding the
/// group; the declared name is the last identifier before `=` and the value
/// expression is everything after it. Groups without a default `=` are skipped.
fn collect_param_group(
    text: &str,
    spans: &[Tok],
    sig: &[usize],
    lo: usize,
    hi: usize,
    is_local: bool,
    decls: &mut Vec<(String, usize, usize, bool)>,
) {
    let raw = |i: usize| &text[spans[i].start..spans[i].end];
    let mut eq = None;
    for q in lo..hi {
        if raw(sig[q]) == "=" {
            eq = Some(q);
            break;
        }
    }
    let Some(eq) = eq else { return };
    // The parameter name is the last identifier before `=`.
    let mut name_span = None;
    for q in lo..eq {
        if spans[sig[q]].kind == TokenKind::SimpleIdent {
            name_span = Some(sig[q]);
        }
    }
    let Some(ns) = name_span else { return };
    let name = text[spans[ns].start..spans[ns].end].to_owned();
    let expr_lo = sig[eq] + 1;
    // The value expression ends at the group boundary, or earlier at a
    // `from`/`exclude` range constraint (`parameter integer N = 10 from
    // (0:inf);`) -- the constraint is not part of the value.
    let mut expr_end_sig = hi;
    for q in (eq + 1)..hi {
        if matches!(raw(sig[q]), "from" | "exclude") {
            expr_end_sig = q;
            break;
        }
    }
    let expr_hi = if expr_end_sig < sig.len() { sig[expr_end_sig] } else { spans.len() };
    decls.push((name, expr_lo, expr_hi, is_local));
}

/// Enhancement-92: rewrites the declarations of parameters listed in `frozen`
/// (those that shaped a declaration width) from `parameter` to `localparam`,
/// within the module region `[rs, re)`. A multi-parameter declaration is split
/// so only the structural names freeze; a range constraint (`from [2:24]`) is
/// dropped from a frozen name (a localparam cannot carry one) but preserved on
/// the parameters that stay overridable. Emits declaration-span rewrites into
/// `rewrites` (disjoint from the width-range rewrites, which sit in separate
/// net/port/array declarations).
fn freeze_width_parameters(
    text: &str,
    spans: &[Tok],
    sig: &[usize],
    rs: usize,
    re: usize,
    frozen: &HashSet<String>,
    rewrites: &mut Vec<(usize, usize, String)>,
) {
    if frozen.is_empty() {
        return;
    }
    let raw = |i: usize| &text[spans[i].start..spans[i].end];
    // (name, text) for a parameter group at significant positions [g, stop);
    // the name is the last identifier before `=` (or the last identifier).
    let group = |g: usize, stop: usize| -> Option<(String, String)> {
        if g >= stop {
            return None;
        }
        let mut name_end = stop;
        for q in g..stop {
            if raw(sig[q]) == "=" {
                name_end = q;
                break;
            }
        }
        let mut name = None;
        for q in g..name_end {
            if spans[sig[q]].kind == TokenKind::SimpleIdent {
                name = Some(raw(sig[q]).to_owned());
            }
        }
        let txt = text[spans[sig[g]].start..spans[sig[stop - 1]].end].trim().to_owned();
        Some((name?, txt))
    };

    let mut p = rs;
    while p < re {
        if raw(sig[p]) != "parameter" {
            p += 1;
            continue;
        }
        // optional shared type keyword
        let mut gp = p + 1;
        let type_kw = if gp < re
            && matches!(raw(sig[gp]), "integer" | "real" | "string" | "realtime")
        {
            let t = raw(sig[gp]).to_owned();
            gp += 1;
            Some(t)
        } else {
            None
        };
        let mut froze: Vec<String> = Vec::new();
        let mut kept: Vec<String> = Vec::new();
        let mut any = false;
        let mut depth = 0i32;
        let mut g_start = gp;
        let mut val_stop: Option<usize> = None; // before a `from`/`exclude` constraint
        let mut semi: Option<usize> = None;
        let mut q = gp;
        let close_group = |g_start: usize, boundary: usize, val_stop: Option<usize>,
                               froze: &mut Vec<String>, kept: &mut Vec<String>, any: &mut bool| {
            let vs = val_stop.unwrap_or(boundary);
            if let Some((name, no_constraint)) = group(g_start, vs) {
                if frozen.contains(&name) {
                    froze.push(no_constraint);
                    *any = true;
                } else if let Some((_, full)) = group(g_start, boundary) {
                    kept.push(full);
                }
            }
        };
        while q < re {
            match raw(sig[q]) {
                "(" | "[" | "{" => depth += 1,
                ")" | "]" | "}" => depth -= 1,
                "from" | "exclude" if depth == 0 && val_stop.is_none() => val_stop = Some(q),
                "," if depth == 0 => {
                    close_group(g_start, q, val_stop, &mut froze, &mut kept, &mut any);
                    g_start = q + 1;
                    val_stop = None;
                }
                ";" if depth == 0 => {
                    close_group(g_start, q, val_stop, &mut froze, &mut kept, &mut any);
                    semi = Some(q);
                    break;
                }
                _ => {}
            }
            q += 1;
        }
        let Some(semi) = semi else {
            p += 1;
            continue;
        };
        if any {
            let ty = type_kw.as_deref().map(|t| format!("{t} ")).unwrap_or_default();
            let mut rep = format!("localparam {}{};", ty, froze.join(", "));
            if !kept.is_empty() {
                rep.push_str(&format!(" parameter {}{};", ty, kept.join(", ")));
            }
            rewrites.push((spans[sig[p]].start, spans[sig[semi]].end, rep));
        }
        p = semi + 1;
    }
}

/// Enhancement-91: folds *parameter-dependent* net/port/array declaration
/// widths -- `electrical [0:bits-1] out;`, `integer result[0:bits-1];` -- into
/// literal ranges using each module's parameter defaults, so the range-then-name
/// bus machinery (Enhancement-3) and the array machinery (Enhancement-14/15) see
/// constant bounds. A textual pre-pass, like the sibling declaration normalisers.
///
/// Scope note: the width is fixed at the parameter's *elaboration-time* value
/// (its default, resolved through other parameters). A model card / instance
/// that overrides the parameter does **not** resize the bus -- the OSDI
/// descriptor has a single fixed node count, so a width parameter is structural
/// (the same decision as generate bounds, Enhancement-67/88). Only declaration
/// ranges (`[msb:lsb]`, containing a `:`) are touched; bit-selects (`x[i]`) and
/// literal ranges are left unchanged.
pub(crate) fn fold_parameter_widths(db: &mut CompilationDB) -> anyhow::Result<()> {
    let root_file = db.compilation_unit().root_file();
    let Ok(text) = db.file_text(root_file) else { return Ok(()) };
    if !text.contains('[') {
        return Ok(());
    }
    let spans = tok_spans(&text);
    let sig: Vec<usize> = (0..spans.len()).filter(|&i| !is_trivia(spans[i].kind)).collect();
    let raw = |i: usize| &text[spans[i].start..spans[i].end];

    // Segment into module regions [start, end) of significant-token positions so
    // parameters stay module-scoped (two modules may reuse a parameter name).
    let mut regions: Vec<(usize, usize)> = Vec::new();
    let mut cur_start: Option<usize> = None;
    for (p, &i) in sig.iter().enumerate() {
        match raw(i) {
            "module" => cur_start = Some(p),
            "endmodule" => {
                if let Some(s) = cur_start.take() {
                    regions.push((s, p));
                }
            }
            _ => {}
        }
    }
    if regions.is_empty() {
        regions.push((0, sig.len()));
    }

    let match_bracket = |openj: usize| -> Option<usize> {
        let mut depth = 0i32;
        for j in openj..spans.len() {
            match spans[j].kind {
                TokenKind::OpenBracket => depth += 1,
                TokenKind::CloseBracket => {
                    depth -= 1;
                    if depth == 0 {
                        return Some(j);
                    }
                }
                _ => {}
            }
        }
        None
    };

    // Vectored-net base names per module, in source order, for pass 2b (the
    // LRM 5.5.2 net-bit-select index fold). The textual module regions and
    // the item tree's modules line up 1:1 exactly when both count the same;
    // when they do not (malformed source, unusual nesting), pass 2b simply
    // stays off and the existing literal-only rule applies.
    let item_tree = db.item_tree(root_file);
    let module_buses: Vec<HashSet<String>> = if item_tree.data.modules.len() == regions.len() {
        item_tree
            .data
            .modules
            .iter()
            .map(|m| m.buses.iter().map(|b| b.base_name.to_string()).collect())
            .collect()
    } else {
        Vec::new()
    };

    let mut rewrites: Vec<(usize, usize, String)> = Vec::new();
    for (region_idx, &(rs, re)) in regions.iter().enumerate() {
        // pass 1: collect integer parameter defaults in this module
        let mut decls: Vec<(String, usize, usize, bool)> = Vec::new();
        let mut p = rs;
        while p < re {
            if matches!(raw(sig[p]), "parameter" | "localparam") {
                let is_local = raw(sig[p]) == "localparam";
                let mut q = p + 1;
                let mut group_start = q;
                let mut depth = 0i32;
                let mut end = re;
                while q < re {
                    match raw(sig[q]) {
                        "(" | "[" | "{" => depth += 1,
                        ")" | "]" | "}" => depth -= 1,
                        ";" if depth == 0 => {
                            end = q;
                            break;
                        }
                        "," if depth == 0 => {
                            collect_param_group(
                                &text, &spans, &sig, group_start, q, is_local, &mut decls,
                            );
                            group_start = q + 1;
                        }
                        _ => {}
                    }
                    q += 1;
                }
                collect_param_group(&text, &spans, &sig, group_start, end, is_local, &mut decls);
                p = end;
            }
            p += 1;
        }
        // resolve to a name -> value map (fixpoint: a parameter default may
        // reference an earlier/later parameter of the same module)
        let mut map: HashMap<String, i32> = HashMap::new();
        loop {
            let mut changed = false;
            for (name, lo, hi, _) in &decls {
                if map.contains_key(name) {
                    continue;
                }
                if let Some(v) = eval_const_int_with_params(&text, &spans, *lo, *hi, &map) {
                    map.insert(name.clone(), v);
                    changed = true;
                }
            }
            if !changed {
                break;
            }
        }
        if map.is_empty() {
            continue;
        }

        // pass 2: fold `[e1:e2]` declaration ranges that reference a parameter,
        // recording which parameters actually shaped a width.
        let mut frozen: HashSet<String> = HashSet::new();
        for p in rs..re {
            let bi = sig[p];
            if spans[bi].kind != TokenKind::OpenBracket {
                continue;
            }
            // Enhancement-414: `from [lo:hi]` / `exclude [lo:hi]` bound a parameter's
            // VALUE; they are not declaration widths and must never be folded here.
            // Reading one as a width had two consequences, both silent: the parameter
            // named inside it was marked structural and frozen into a localparam by
            // pass 3 -- so `.model … (aa=5)` did nothing at all, with no diagnostic --
            // and pass 3's rewrite of that declaration then overlapped the one pass 2
            // had already queued for the same text, which panicked the compiler
            // outright when a parameter's range mentioned the parameter itself.
            if is_param_constraint_bracket(&text, &spans, bi) {
                continue;
            }
            let Some(cj) = match_bracket(bi) else { continue };
            // find the range colon at the bracket's own depth, and collect any
            // inner identifiers that are known parameters
            let mut colon = None;
            let mut names_here: Vec<String> = Vec::new();
            let mut depth = 0i32;
            for j in (bi + 1)..cj {
                match spans[j].kind {
                    TokenKind::OpenBracket | TokenKind::OpenParen => depth += 1,
                    TokenKind::CloseBracket | TokenKind::CloseParen => depth -= 1,
                    TokenKind::Colon if depth == 0 && colon.is_none() => colon = Some(j),
                    TokenKind::SimpleIdent
                        if map.contains_key(&text[spans[j].start..spans[j].end]) =>
                    {
                        names_here.push(text[spans[j].start..spans[j].end].to_owned())
                    }
                    _ => {}
                }
            }
            let (Some(cpos), false) = (colon, names_here.is_empty()) else { continue };
            let Some(lhs) = eval_const_int_with_params(&text, &spans, bi + 1, cpos, &map) else {
                continue;
            };
            let Some(rhs) = eval_const_int_with_params(&text, &spans, cpos + 1, cj, &map) else {
                continue;
            };
            rewrites.push((spans[bi].start, spans[cj].end, format!("[{lhs}:{rhs}]")));
            frozen.extend(names_here);
        }

        // pass 2b (behavior audit, LRM 5.5.2): a single-index bit-select on a
        // VECTOR NET is a signal access -- "The index must be a constant
        // expression", and a constant_expression includes parameters, so
        // `V(in[width-2])` is legal Verilog-A. The index selects a NODE of
        // the OSDI descriptor, which makes any parameter it reads structural:
        // fold the index here and freeze the parameter, exactly as a
        // parameter-shaped declaration width is folded and frozen. Only
        // brackets whose base identifier names one of this module's vectored
        // NETS are touched -- an array VARIABLE's `arr[k]` stays a runtime
        // access, and a plain parameter used there is still overridable.
        if let Some(buses) = module_buses.get(region_idx) {
            let plain_params: HashSet<&String> =
                decls.iter().filter(|(_, _, _, is_local)| !is_local).map(|(n, ..)| n).collect();
            for p in (rs + 1)..re {
                let bi = sig[p];
                if spans[bi].kind != TokenKind::OpenBracket {
                    continue;
                }
                let prev = sig[p - 1];
                if spans[prev].kind != TokenKind::SimpleIdent
                    || !buses.contains(&text[spans[prev].start..spans[prev].end])
                {
                    continue;
                }
                let Some(cj) = match_bracket(bi) else { continue };
                let mut has_colon = false;
                let mut names_here: Vec<String> = Vec::new();
                let mut depth = 0i32;
                for j in (bi + 1)..cj {
                    match spans[j].kind {
                        TokenKind::OpenBracket | TokenKind::OpenParen => depth += 1,
                        TokenKind::CloseBracket | TokenKind::CloseParen => depth -= 1,
                        TokenKind::Colon if depth == 0 => has_colon = true,
                        TokenKind::SimpleIdent
                            if map.contains_key(&text[spans[j].start..spans[j].end]) =>
                        {
                            names_here.push(text[spans[j].start..spans[j].end].to_owned())
                        }
                        _ => {}
                    }
                }
                // literal-only indices need no fold, and range/part-selects are
                // pass 2's business
                if has_colon || names_here.is_empty() {
                    continue;
                }
                if rewrites.iter().any(|(s, e, _)| *s <= spans[bi].start && spans[cj].end <= *e)
                {
                    continue;
                }
                let Some(idx) = eval_const_int_with_params(&text, &spans, bi + 1, cj, &map)
                else {
                    continue;
                };
                rewrites.push((spans[bi].start, spans[cj].end, format!("[{idx}]")));
                // Freeze the TRANSITIVE parameter support of the index: a
                // localparam in it may be built from a plain parameter, and
                // baking its value while leaving that parameter overridable
                // would silently ignore the override -- the very trap pass 4's
                // seed rule guards against.
                let mut work = names_here;
                let mut seen: HashSet<String> = HashSet::new();
                while let Some(n) = work.pop() {
                    if !seen.insert(n.clone()) {
                        continue;
                    }
                    if plain_params.contains(&n) {
                        frozen.insert(n.clone());
                    }
                    if let Some((_, lo, hi, _)) =
                        decls.iter().find(|(d, ..)| *d == n)
                    {
                        for j in *lo..*hi {
                            if spans.get(j).map(|s| s.kind) == Some(TokenKind::SimpleIdent) {
                                let t = &text[spans[j].start..spans[j].end];
                                if map.contains_key(t) {
                                    work.push(t.to_owned());
                                }
                            }
                        }
                    }
                }
            }
        }

        // pass 3 (Enhancement-92): a parameter that shaped a declaration width
        // is *structural* -- the OSDI descriptor has one fixed node/array count,
        // so the value must not change at simulation time. Rewrite its
        // declaration to `localparam` (splitting a multi-parameter declaration
        // so only the structural names freeze, and dropping the now-illegal
        // range constraint). Without this an override that grows the parameter
        // would leave the frozen width behind while behavioural code (a runtime
        // loop bound, say) follows the new value -- a silent out-of-bounds.
        freeze_width_parameters(&text, &spans, &sig, rs, re, &frozen, &mut rewrites);

        // pass 4 (Enhancement-393): fold a SINGLE-index bit-select `bus[K]` whose
        // index is elaboration-constant. `Ctx::const_int_index` in `hir_ty` already
        // does this for indices in the analog body, but two consumers resolve their
        // bit-selects EARLIER than name resolution and so cannot ask for a
        // parameter's value at all: a branch endpoint (`branch (n[K], n[0])`, folded
        // in `item_tree::lower::resolve_branch_endpoint`) and a port connection
        // (`kid c(.p(bus[K]))`, which the instantiation elaborator resolves by
        // synthesizing the textual name `bus[K]`). Both fold with `as_constexprval`,
        // which sees literals only.
        //
        // WHICH NAMES MAY BE FOLDED IS THE WHOLE QUESTION. Only names that are fixed
        // before the OSDI descriptor exists:
        //
        //   * a `localparam`, which the LRM forbids overriding externally; and
        //   * a `parameter` that pass 3 just FROZE into one, because it shaped a
        //     declaration width. Indexing the very bus that parameter sized is then
        //     consistent by construction.
        //
        // A plain `parameter` is excluded, and so is a localparam whose value is
        // built from one -- the second fixpoint below can only grow from seeds that
        // are already elaboration-constant, so such a chain never resolves. Baking a
        // parameter's default into a node selection would silently ignore an
        // override from the model card. This mirrors, and must keep mirroring, the
        // rule `hir_ty` applies to body indices. (Vectored-NET indices are wider:
        // pass 2b above folds a plain-parameter index there and FREEZES its
        // transitive parameter support, which preserves the same invariant --
        // the baked selection can never diverge from the card.)
        let mut const_map: HashMap<String, i32> = HashMap::new();
        loop {
            let mut changed = false;
            for (name, lo, hi, is_local) in &decls {
                if const_map.contains_key(name) || !(*is_local || frozen.contains(name)) {
                    continue;
                }
                if let Some(v) = eval_const_int_with_params(&text, &spans, *lo, *hi, &const_map) {
                    const_map.insert(name.clone(), v);
                    changed = true;
                }
            }
            if !changed {
                break;
            }
        }
        if const_map.is_empty() {
            continue;
        }
        for p in rs..re {
            let bi = sig[p];
            if spans[bi].kind != TokenKind::OpenBracket {
                continue;
            }
            let Some(cj) = match_bracket(bi) else { continue };
            // A `:` at the bracket's own depth makes this a range or a part-select,
            // which pass 2 owns; only a single index is folded here.
            let mut has_colon = false;
            let mut mentions_const = false;
            let mut depth = 0i32;
            for j in (bi + 1)..cj {
                match spans[j].kind {
                    TokenKind::OpenBracket | TokenKind::OpenParen => depth += 1,
                    TokenKind::CloseBracket | TokenKind::CloseParen => depth -= 1,
                    TokenKind::Colon if depth == 0 => has_colon = true,
                    TokenKind::SimpleIdent
                        if const_map.contains_key(&text[spans[j].start..spans[j].end]) =>
                    {
                        mentions_const = true
                    }
                    _ => {}
                }
            }
            if has_colon || !mentions_const {
                continue;
            }
            // Never rewrite inside a span another pass already claimed (a parameter
            // declaration that pass 3 rewrote wholesale, say) -- the spans are
            // applied by offset and must stay disjoint.
            if rewrites.iter().any(|(s, e, _)| *s <= spans[bi].start && spans[cj].end <= *e) {
                continue;
            }
            let Some(idx) = eval_const_int_with_params(&text, &spans, bi + 1, cj, &const_map)
            else {
                continue;
            };
            rewrites.push((spans[bi].start, spans[cj].end, format!("[{idx}]")));
        }
    }

    if rewrites.is_empty() {
        return Ok(());
    }
    rewrites.sort_by_key(|(s, _, _)| *s);
    let mut out = String::with_capacity(text.len());
    let mut prev = 0usize;
    for (s, e, rep) in rewrites {
        // Enhancement-414: spans are applied by byte offset, so an overlapping pair
        // used to panic on the slice. Overlap means two passes claimed the same text
        // and the second cannot be applied on top of the first -- drop it rather than
        // abort the compiler.
        if s < prev {
            continue;
        }
        out.push_str(&text[prev..s]);
        out.push_str(&rep);
        prev = e;
    }
    out.push_str(&text[prev..]);

    let root_path = db.vfs().read().file_path(root_file).to_string();
    let base_name =
        root_path.rsplit(['/', '\\']).next().unwrap_or(root_path.as_str()).to_owned();
    let synth_name = format!("/{base_name}__paramwidth.va");
    let file_id = db.vfs().write().add_virt_file(&synth_name, out.into());
    let include_dirs = db.include_dirs(root_file);
    db.set_include_dirs(file_id, include_dirs);
    let macro_flags = db.macro_flags(root_file);
    db.set_macro_flags(file_id, macro_flags);
    let overwrites = db.global_lint_overwrites(root_file);
    db.set_global_lint_overwrites(file_id, overwrites);
    db.set_root_file(file_id);
    Ok(())
}

/// Verilog-A keywords that can precede `<name> [ … ]` and must NOT be treated
/// as a discipline in a name-then-range net declaration (they head variable,
/// parameter, or other declarations that already support the array form, or
/// are not net declarations at all).
const NAME_RANGE_HEAD_EXCLUDE: &[&str] = &[
    "real", "integer", "string", "parameter", "localparam", "aliasparam",
    "genvar", "branch", "defparam", "generate", "analog", "module", "function",
    "nature", "discipline", "paramset", "begin",
];

/// Enhancement-89: normalizes the *name-then-range* form of a net or port
/// declaration -- `electrical in[0:2];`, `input in[0:2];` (LRM 3.6 / 3.7,
/// example page 45) -- to the equivalent *range-then-name* form
/// (`electrical [0:2] in;`, `input [0:2] in;`), which is fully supported
/// (Enhancement-3). Purely syntactic; a textual pre-pass so all of the
/// existing bus/port machinery is reused unchanged.
///
/// Disambiguation from an instance array (`foo a[0:2] (ports)`) is exact: an
/// instantiation always has a `(port list)` after the range, so a
/// `<head> <name> [range]` that is instead followed by `,`/`;` is a
/// declaration.
///
/// Enhancement-91 extends this to *multi-name* declarations
/// (`input a[0:1], b[0:3], c;`): the comma-separated name list is split into
/// one range-then-name declaration per name, each sharing the head (per-name
/// widths, so `input [0:1] a; input [0:3] b; input c;`). The first name must
/// carry the range (the anchor). A *multi-dimensional* name
/// (`in[0:2][0:1]`) is still left untouched -- multi-dimensional vectored
/// ports are unsupported in *both* declaration orders (the range-then-name
/// form does not parse either), so the existing diagnostic fires.
pub(crate) fn normalize_name_range_decls(db: &mut CompilationDB) -> anyhow::Result<()> {
    let root_file = db.compilation_unit().root_file();
    let Ok(text) = db.file_text(root_file) else { return Ok(()) };
    if !text.contains('[') {
        return Ok(());
    }

    let spans = tok_spans(&text);
    let sig: Vec<usize> = (0..spans.len()).filter(|&i| !is_trivia(spans[i].kind)).collect();
    let raw = |i: usize| &text[spans[i].start..spans[i].end];
    // sig index -> position in `sig`, for stepping to previous significant tokens
    let pos_in_sig: HashMap<usize, usize> =
        sig.iter().enumerate().map(|(p, &i)| (i, p)).collect();

    // Finds the matching `]` (span index) for an `[` at span index `openj`.
    let match_bracket = |openj: usize| -> Option<usize> {
        let mut depth = 0i32;
        let mut j = openj;
        while j < spans.len() {
            match spans[j].kind {
                TokenKind::OpenBracket => depth += 1,
                TokenKind::CloseBracket => {
                    depth -= 1;
                    if depth == 0 {
                        return Some(j);
                    }
                }
                _ => {}
            }
            j += 1;
        }
        None
    };

    let mut rewrites: Vec<(usize, usize, String)> = Vec::new();
    for (sp, &bi) in sig.iter().enumerate() {
        if spans[bi].kind != TokenKind::OpenBracket || sp < 2 {
            continue;
        }
        let name_i = sig[sp - 1];
        let head_i = sig[sp - 2];
        if spans[name_i].kind != TokenKind::SimpleIdent
            || spans[head_i].kind != TokenKind::SimpleIdent
        {
            continue;
        }
        let head = raw(head_i);
        let is_dir = matches!(head, "input" | "output" | "inout");
        if !is_dir && NAME_RANGE_HEAD_EXCLUDE.contains(&head) {
            continue;
        }
        // the name itself must not be a keyword/net-type
        if matches!(raw(name_i), "ground" | "wire" | "wreal") {
            continue;
        }
        // declaration boundary: the token before the head is `;`, `)`
        // (module-port list or a preceding statement), a direction keyword
        // (net-type-after-direction case, `input electrical in[0:2]`), or the
        // head is the very first token.
        let hp = pos_in_sig[&head_i];
        let boundary = hp == 0
            || matches!(raw(sig[hp - 1]), ";" | ")" | "input" | "output" | "inout");
        if !boundary {
            continue;
        }
        // The full head prefix is the maximal run of significant identifiers
        // ending at `head_i` (`input`, `electrical`, `input electrical`, ...);
        // it is replicated ahead of every name when a multi-name declaration is
        // split (Enhancement-91). The run cannot cross a boundary token, which
        // is never an identifier.
        let mut hstart_p = hp;
        while hstart_p > 0 && spans[sig[hstart_p - 1]].kind == TokenKind::SimpleIdent {
            hstart_p -= 1;
        }
        let head_prefix = &text[spans[sig[hstart_p]].start..spans[head_i].end];

        // Parse the comma-separated name list, starting at the first name
        // (which carries `[range]`): `name [range]? (, name [range]?)* ;`.
        // Each name may be scalar or a 1-D bus. A multi-dimensional name
        // (`in[0:2][0:1]`) is left untouched -- multi-dim vectored ports are
        // unsupported in *both* spellings, so the existing diagnostic fires.
        let mut names: Vec<(String, Option<String>)> = Vec::new();
        let mut p = sp - 1; // sig position of the first name
        let mut ok = true;
        let mut semi_end = None;
        loop {
            let ni = sig[p];
            if spans[ni].kind != TokenKind::SimpleIdent {
                ok = false;
                break;
            }
            let nm = text[spans[ni].start..spans[ni].end].to_owned();
            p += 1;
            let mut range: Option<String> = None;
            let mut groups = 0;
            while p < sig.len() && spans[sig[p]].kind == TokenKind::OpenBracket {
                let Some(cj) = match_bracket(sig[p]) else {
                    ok = false;
                    break;
                };
                range = Some(text[spans[sig[p]].start..spans[cj].end].to_owned());
                groups += 1;
                p = pos_in_sig[&cj] + 1;
            }
            if !ok || groups > 1 {
                ok = false;
                break;
            }
            names.push((nm, range));
            if p >= sig.len() {
                ok = false;
                break;
            }
            match spans[sig[p]].kind {
                TokenKind::Comma => {
                    p += 1;
                    continue;
                }
                TokenKind::Semi => {
                    semi_end = Some(spans[sig[p]].end);
                    break;
                }
                _ => {
                    ok = false;
                    break;
                }
            }
        }
        let (Some(semi_end), true) = (semi_end, ok) else { continue };
        // Nothing to normalize unless at least one name carried a range.
        if !names.iter().any(|(_, r)| r.is_some()) {
            continue;
        }
        // Emit one range-then-name declaration per name, sharing the head.
        let mut rep = String::new();
        for (k, (nm, rng)) in names.iter().enumerate() {
            if k > 0 {
                rep.push(' ');
            }
            match rng {
                Some(r) => rep.push_str(&format!("{head_prefix} {r} {nm};")),
                None => rep.push_str(&format!("{head_prefix} {nm};")),
            }
        }
        rewrites.push((spans[sig[hstart_p]].start, semi_end, rep));
    }

    if rewrites.is_empty() {
        return Ok(());
    }
    rewrites.sort_by_key(|(s, _, _)| *s);
    let mut out = String::with_capacity(text.len());
    let mut prev = 0usize;
    for (s, e, rep) in rewrites {
        out.push_str(&text[prev..s]);
        out.push_str(&rep);
        prev = e;
    }
    out.push_str(&text[prev..]);

    let root_path = db.vfs().read().file_path(root_file).to_string();
    let base_name =
        root_path.rsplit(['/', '\\']).next().unwrap_or(root_path.as_str()).to_owned();
    let synth_name = format!("/{base_name}__namerange.va");
    let file_id = db.vfs().write().add_virt_file(&synth_name, out.into());
    let include_dirs = db.include_dirs(root_file);
    db.set_include_dirs(file_id, include_dirs);
    let macro_flags = db.macro_flags(root_file);
    db.set_macro_flags(file_id, macro_flags);
    let overwrites = db.global_lint_overwrites(root_file);
    db.set_global_lint_overwrites(file_id, overwrites);
    db.set_root_file(file_id);
    Ok(())
}

/// Enhancement-88: unrolls the obsolete Verilog-A 1.0 `generate` statement
/// (LRM Annex C.4): `generate <id> ( <start>, <end> [, <incr>] ) <body>`.
/// This is an analog-block loop-unroll -- the body is replicated with `<id>`
/// substituted by each successive constant value, so an index expression like
/// `out[i]` becomes a literal bus bit-select. Handled textually, like the
/// module-level `generate for` (Enhancement-8), and run before that pass and
/// before name resolution (the index is not a declared variable).
///
/// Bounds must be elaboration-time constants (literals / constant
/// arithmetic); a parameter bound cannot shape the unrolled structure -- the
/// same scope decision as `generate for`/`generate if` (Enhancement-67).
pub(crate) fn elaborate_legacy_generate(db: &mut CompilationDB) -> anyhow::Result<()> {
    let root_file = db.compilation_unit().root_file();
    let Ok(text0) = db.file_text(root_file) else { return Ok(()) };
    if !text0.contains("generate") {
        return Ok(());
    }

    let mut text = text0.to_string();
    // Fixpoint over nested legacy generates: each unroll can expose a
    // generate that was inside the body.
    for _ in 0..64 {
        let Some(next) = unroll_first_legacy_generate(&text)? else { break };
        text = next;
    }

    if text == *text0 {
        return Ok(());
    }

    let root_path = db.vfs().read().file_path(root_file).to_string();
    let base_name =
        root_path.rsplit(['/', '\\']).next().unwrap_or(root_path.as_str()).to_owned();
    let synth_name = format!("/{base_name}__legacygen.va");
    let file_id = db.vfs().write().add_virt_file(&synth_name, text.into());
    let include_dirs = db.include_dirs(root_file);
    db.set_include_dirs(file_id, include_dirs);
    let macro_flags = db.macro_flags(root_file);
    db.set_macro_flags(file_id, macro_flags);
    let overwrites = db.global_lint_overwrites(root_file);
    db.set_global_lint_overwrites(file_id, overwrites);
    db.set_root_file(file_id);
    Ok(())
}

/// Finds the first legacy `generate <id> (...)` statement in `text`, unrolls
/// it, and returns the rewritten source. Returns `Ok(None)` when there is no
/// legacy generate left.
fn unroll_first_legacy_generate(text: &str) -> anyhow::Result<Option<String>> {
    let spans = tok_spans(text);
    let sig: Vec<usize> = (0..spans.len()).filter(|&i| !is_trivia(spans[i].kind)).collect();
    let raw = |i: usize| &text[spans[i].start..spans[i].end];

    // locate `generate` (a SimpleIdent, since the raw lexer does not classify
    // keywords) immediately followed by an identifier that is not for/if/case
    // (those are the module-level generate regions, left untouched).
    for w in 0..sig.len().saturating_sub(1) {
        let gi = sig[w];
        if spans[gi].kind != TokenKind::SimpleIdent || raw(gi) != "generate" {
            continue;
        }
        let ni = sig[w + 1];
        if spans[ni].kind != TokenKind::SimpleIdent
            || matches!(raw(ni), "for" | "if" | "case" | "begin")
        {
            continue;
        }
        let index_name = raw(ni).to_owned();

        // `( start , end [, incr] )`
        let opi = *sig.get(w + 2).ok_or_else(|| anyhow::anyhow!("legacy generate: expected '('"))?;
        if spans[opi].kind != TokenKind::OpenParen {
            anyhow::bail!(
                "legacy generate '{index_name}': expected '( start, end )' after the index"
            );
        }
        // find matching ')', and the comma positions at paren-depth 1
        let mut depth = 0i32;
        let mut close = None;
        let mut commas: Vec<usize> = Vec::new();
        let mut j = opi;
        while j < spans.len() {
            match spans[j].kind {
                TokenKind::OpenParen => depth += 1,
                TokenKind::CloseParen => {
                    depth -= 1;
                    if depth == 0 {
                        close = Some(j);
                        break;
                    }
                }
                TokenKind::Comma if depth == 1 => commas.push(j),
                _ => {}
            }
            j += 1;
        }
        let cpi = close.ok_or_else(|| {
            anyhow::anyhow!("legacy generate '{index_name}': unterminated argument list")
        })?;
        if commas.is_empty() || commas.len() > 2 {
            anyhow::bail!(
                "legacy generate '{index_name}': expected 'generate {index_name} (start, end [, incr])'"
            );
        }
        let bound_err = || {
            anyhow::anyhow!(
                "legacy generate '{index_name}': the bounds must be elaboration-time constants \
                 (literals / constant arithmetic); a module parameter cannot shape a \
                 compile-time unroll"
            )
        };
        let start = eval_const_int_tokens(text, &spans, opi + 1, commas[0]).ok_or_else(bound_err)?;
        let end_hi = if commas.len() == 2 { commas[1] } else { cpi };
        let end = eval_const_int_tokens(text, &spans, commas[0] + 1, end_hi).ok_or_else(bound_err)?;
        let step = if commas.len() == 2 {
            eval_const_int_tokens(text, &spans, commas[1] + 1, cpi).ok_or_else(bound_err)?
        } else if start <= end {
            1
        } else {
            -1
        };
        if step == 0 {
            anyhow::bail!("legacy generate '{index_name}': increment must be non-zero");
        }

        // body: `begin ... end` (balanced) or a single statement up to ';'
        let mut k = cpi + 1;
        while k < spans.len() && is_trivia(spans[k].kind) {
            k += 1;
        }
        let bstart = k;
        let body_end; // exclusive byte index just past the body
        if k < spans.len() && spans[k].kind == TokenKind::SimpleIdent && raw(k) == "begin" {
            let mut bd = 0i32;
            let mut m = k;
            loop {
                if m >= spans.len() {
                    anyhow::bail!("legacy generate '{index_name}': unterminated 'begin ... end'");
                }
                if spans[m].kind == TokenKind::SimpleIdent {
                    match raw(m) {
                        "begin" => bd += 1,
                        "end" => {
                            bd -= 1;
                            if bd == 0 {
                                break;
                            }
                        }
                        _ => {}
                    }
                }
                m += 1;
            }
            body_end = spans[m].end;
        } else {
            // single statement: to the next top-level ';'
            let mut m = k;
            while m < spans.len() && spans[m].kind != TokenKind::Semi {
                m += 1;
            }
            if m >= spans.len() {
                anyhow::bail!("legacy generate '{index_name}': missing ';' after the body");
            }
            body_end = spans[m].end;
        }
        let body_text = &text[spans[bstart].start..body_end];

        // unroll -- wrapped in a single outer `begin ... end` so the whole
        // expansion is ONE statement, valid whether the legacy generate was
        // inside an `analog begin ... end` (nested block) or the direct body
        // of `analog` (which takes a single statement).
        let mut count = 0u32;
        let mut v = start;
        let mut unrolled = String::from("\nbegin\n");
        loop {
            let done = if step > 0 { v > end } else { v < end };
            if done {
                break;
            }
            unrolled.push_str(&format!("// legacy generate {index_name} = {v}\nbegin\n"));
            unrolled.push_str(&substitute_index(body_text, &index_name, v));
            unrolled.push_str("\nend\n");
            v += step;
            count += 1;
            if count > 1_000_000 {
                anyhow::bail!("legacy generate '{index_name}': more than 1,000,000 iterations");
            }
        }
        unrolled.push_str("end\n");

        let mut new_text = String::with_capacity(text.len());
        new_text.push_str(&text[..spans[gi].start]);
        new_text.push_str(&unrolled);
        new_text.push_str(&text[body_end..]);
        return Ok(Some(new_text));
    }
    Ok(None)
}

/// Substitutes the legacy-generate index `name` with the literal `value`
/// in `body`: every whole-identifier occurrence becomes the literal, and
/// each bit-select `[<expr>]` whose contents then constant-fold is replaced
/// by `[<literal>]` (a bus bit-select requires a literal index, not a
/// constant expression). Non-folding indices (dynamic array access) are left
/// untouched.
/// Enhancement-407: evaluates a genvar loop CONDITION over a token range, as 1 or 0.
///
/// [`eval_const_int_with_params`] is an arithmetic evaluator -- it has no relational
/// operators, because every existing caller folds a width or an index, never a predicate.
/// A loop condition is exactly a predicate (`i >= 0`, `k <= width`), so split it on its
/// single top-level relational operator and fold each side with the existing evaluator.
fn eval_const_cond(
    text: &str,
    spans: &[Tok],
    lo: usize,
    hi: usize,
    env: &HashMap<String, i32>,
) -> Option<i32> {
    let mut depth = 0i32;
    let mut split: Option<(usize, &'static str, usize)> = None;
    let mut j = lo;
    while j < hi {
        match spans[j].kind {
            TokenKind::OpenParen | TokenKind::OpenBracket => depth += 1,
            TokenKind::CloseParen | TokenKind::CloseBracket => depth -= 1,
            _ if depth == 0 => {
                // A two-character operator may arrive either as ONE token (`<=`) or as two
                // adjacent ones (`<` then `=`), depending on how the raw lexer split it.
                // Handle both: matching only the split form silently missed every `<=`
                // and `>=`, which is most real loop conditions.
                let raw = &text[spans[j].start..spans[j].end];
                if let Some(op) = ["<=", ">=", "==", "!="].into_iter().find(|o| *o == raw) {
                    split = Some((j, op, 1));
                    break;
                }
                let next = spans.get(j + 1).map(|t| &text[t.start..t.end]);
                let adjacent = spans.get(j + 1).is_some_and(|t| t.start == spans[j].end);
                let two = match (raw, next, adjacent) {
                    ("<", Some("="), true) => Some("<="),
                    (">", Some("="), true) => Some(">="),
                    ("=", Some("="), true) => Some("=="),
                    ("!", Some("="), true) => Some("!="),
                    _ => None,
                };
                if let Some(op) = two {
                    split = Some((j, op, 2));
                    break;
                }
                if raw == "<" || raw == ">" {
                    split = Some((j, if raw == "<" { "<" } else { ">" }, 1));
                    break;
                }
            }
            _ => {}
        }
        j += 1;
    }
    let (at, op, ntok) = split?;
    let rhs_start = at + ntok;
    let l = eval_const_int_with_params(text, spans, lo, at, env)?;
    let r = eval_const_int_with_params(text, spans, rhs_start, hi, env)?;
    let res = match op {
        "<" => l < r,
        "<=" => l <= r,
        ">" => l > r,
        ">=" => l >= r,
        "==" => l == r,
        "!=" => l != r,
        _ => return None,
    };
    Some(res as i32)
}

/// Enhancement-407: how many statement copies one analog genvar loop may expand to.
///
/// The same reasoning as E-148's array cap: each iteration is a full copy of the body, so
/// an unbounded loop bound would exhaust memory in the elaborator before the compiler ever
/// saw the result. Real uses are small -- the LRM's own DAC allows `width from [2:24]`.
const MAX_ANALOG_UNROLL: i32 = 4096;

/// Enhancement-407: unrolls every `for` loop in one `analog` block whose index is a
/// declared `genvar`.
///
/// A genvar loop in an analog block is not a run-time loop. It exists because a vectored
/// net's bit-select must be a CONSTANT -- each bit is a distinct simulator unknown, so
/// `V(out[i]) <+ ..` over an `integer` is rejected outright -- and unrolling turns the
/// index into a literal. The LRM's page-117 example ships the hand-unrolled `dac8` beside
/// the rolled `dac`, which is the semantics written out.
///
/// Purely textual, like the rest of this module: the body is repeated verbatim with the
/// genvar replaced by each successive literal, reusing [`substitute_index`] so the
/// bit-select brackets fold in the same pass. Loops are unrolled outermost-first and the
/// scan restarts after each rewrite, so a nested genvar loop is handled by the next round
/// once its enclosing loop has been expanded.
///
/// Bounds must fold to integers against `env`, which holds the module's localparams --
/// including any `parameter` that `fold_parameter_widths` (E-92) has already frozen for
/// shaping a declaration width. That is exactly the case the LRM examples need: `bits`
/// sizes `out[0:bits-1]`, so it is structural, frozen, and constant here. A bound that
/// does not fold is an error rather than a silent miscompile.
fn unroll_analog_genvar_loops(
    src: &str,
    genvars: &[String],
    env: &HashMap<String, i32>,
) -> anyhow::Result<String> {
    let mut text = src.to_owned();
    // one rewrite per pass, rescanning afterwards: the replacement changes every offset,
    // and an unrolled body may itself contain a further genvar loop
    for _ in 0..MAX_ANALOG_UNROLL {
        match unroll_first_analog_genvar_loop(&text, genvars, env)? {
            Some(next) => text = next,
            None => return Ok(text),
        }
    }
    anyhow::bail!("analog genvar loops nested deeper than {MAX_ANALOG_UNROLL} levels")
}

/// Expands the first analog genvar `for` in `text`, or `None` when there is none left.
fn unroll_first_analog_genvar_loop(
    text: &str,
    genvars: &[String],
    env: &HashMap<String, i32>,
) -> anyhow::Result<Option<String>> {
    let spans = tok_spans(text);
    let sig: Vec<usize> = (0..spans.len()).filter(|&i| !is_trivia(spans[i].kind)).collect();
    let raw = |i: usize| &text[spans[i].start..spans[i].end];

    for w in 0..sig.len() {
        if raw(sig[w]) != "for" {
            continue;
        }
        // `for` `(` <genvar> `=` ...
        let Some(&open) = sig.get(w + 1) else { continue };
        if spans[open].kind != TokenKind::OpenParen {
            continue;
        }
        let Some(&name_i) = sig.get(w + 2) else { continue };
        let gv = raw(name_i).to_owned();
        if !genvars.iter().any(|g| *g == gv) {
            continue;   // an ordinary run-time `for`, left exactly as written
        }

        let close = {
            let mut depth = 0i32;
            let mut j = open;
            loop {
                if j >= spans.len() {
                    anyhow::bail!("genvar for loop `{gv}`: unbalanced `(` in the loop header")
                }
                match spans[j].kind {
                    TokenKind::OpenParen => depth += 1,
                    TokenKind::CloseParen => {
                        depth -= 1;
                        if depth == 0 {
                            break j;
                        }
                    }
                    _ => {}
                }
                j += 1;
            }
        };
        // split the header on its two top-level `;`
        let mut semis = Vec::new();
        let mut depth = 0i32;
        for j in (open + 1)..close {
            match spans[j].kind {
                TokenKind::OpenParen | TokenKind::OpenBracket => depth += 1,
                TokenKind::CloseParen | TokenKind::CloseBracket => depth -= 1,
                _ if depth == 0 && &text[spans[j].start..spans[j].end] == ";" => semis.push(j),
                _ => {}
            }
        }
        if semis.len() != 2 {
            anyhow::bail!(
                "genvar for loop `{gv}`: expected `for (init; condition; step)`"
            )
        }
        let (s1, s2) = (semis[0], semis[1]);

        // init: `<gv> = <expr>`  -- the `=` is the token after the name
        let eq = (name_i + 1..s1)
            .find(|&j| &text[spans[j].start..spans[j].end] == "=")
            .ok_or_else(|| anyhow::anyhow!("genvar for loop `{gv}`: no `=` in the initializer"))?;
        let mut value = eval_const_int_with_params(text, &spans, eq + 1, s1, env).ok_or_else(
            || anyhow::anyhow!(
                "genvar for loop `{gv}`: the initial value is not a compile-time constant \
                 integer -- a genvar loop is unrolled at elaboration, so its bounds must be \
                 known then (a `parameter` only counts once it has been frozen by shaping a \
                 declaration width)"
            ),
        )?;

        // step: `<gv> = <expr>` between the second `;` and `)`
        let step_eq = (s2 + 1..close)
            .find(|&j| &text[spans[j].start..spans[j].end] == "=")
            .ok_or_else(|| anyhow::anyhow!("genvar for loop `{gv}`: no `=` in the step"))?;

        // body: everything after `)` up to the end of one statement
        let body_start = close + 1;
        let (body_lo, body_hi) = statement_extent(text, &spans, body_start).ok_or_else(|| {
            anyhow::anyhow!("genvar for loop `{gv}`: could not find the loop body")
        })?;
        let body = &text[spans[body_lo].start..spans[body_hi - 1].end];

        // Enhancement-414: the FIRST copy keeps the body's own line breaks, so a
        // diagnostic inside the loop still reports the line the user wrote; the
        // remaining copies are folded onto one line and the whole replacement is
        // padded back to the line count of the text it replaces. Without that the
        // expansion shifted every later line -- an error ten lines below a loop was
        // reported a hundred-odd lines away, in a file that does not exist on disk.
        let mut outp = String::from("begin ");
        let mut iters = 0i32;
        loop {
            let mut it_env = env.clone();
            it_env.insert(gv.clone(), value);
            let cond = eval_const_cond(text, &spans, s1 + 1, s2, &it_env).ok_or_else(
                || anyhow::anyhow!(
                    "genvar for loop `{gv}`: the loop condition is not a compile-time \
                     constant integer"
                ),
            )?;
            if cond == 0 {
                break;
            }
            iters += 1;
            if iters > MAX_ANALOG_UNROLL {
                anyhow::bail!(
                    "genvar for loop `{gv}`: expands to more than {MAX_ANALOG_UNROLL} \
                     statement copies"
                )
            }
            // Enhancement-414: a `begin : name` block inside the body would be copied
            // name and all, and N copies of one name collide -- "'blk' was already
            // declared in this scope" for a loop that is perfectly legal. Each copy
            // gets its own suffix, the way a generate block is indexed.
            let copy = rename_named_blocks(&substitute_index(body, &gv, value), value);
            if iters == 1 {
                outp.push_str(&copy);
            } else {
                outp.push_str(&collapse_newlines(&copy));
            }
            outp.push(' ');
            value = eval_const_int_with_params(text, &spans, step_eq + 1, close, &it_env)
                .ok_or_else(|| {
                    anyhow::anyhow!(
                        "genvar for loop `{gv}`: the step is not a compile-time constant integer"
                    )
                })?;
        }
        outp.push_str("end");

        let lo = spans[sig[w]].start;
        let hi = spans[body_hi - 1].end;
        let replaced_lines = text[lo..hi].matches('\n').count();
        let emitted_lines = outp.matches('\n').count();
        for _ in emitted_lines..replaced_lines {
            outp.push('\n');
        }
        return Ok(Some(format!("{}{}{}", &text[..lo], outp, &text[hi..])));
    }
    Ok(None)
}

/// Index of the next non-trivia token at or after `j`.
fn skip_trivia(spans: &[Tok], mut j: usize) -> usize {
    while j < spans.len() && is_trivia(spans[j].kind) {
        j += 1;
    }
    j
}

/// One past a balanced `(`..`)` group that must start at `j`.
fn skip_paren_group(spans: &[Tok], mut j: usize) -> Option<usize> {
    if j >= spans.len() || spans[j].kind != TokenKind::OpenParen {
        return None;
    }
    let mut depth = 0i32;
    while j < spans.len() {
        match spans[j].kind {
            TokenKind::OpenParen => depth += 1,
            TokenKind::CloseParen => {
                depth -= 1;
                if depth == 0 {
                    return Some(j + 1);
                }
            }
            _ => {}
        }
        j += 1;
    }
    None
}

/// Enhancement-414: is this `[` the opening bracket of a parameter's `from`/`exclude`
/// VALUE constraint, rather than a declaration width? The width-folding passes must
/// leave the former alone -- see the call site for what reading one as a width cost.
fn is_param_constraint_bracket(text: &str, spans: &[Tok], bi: usize) -> bool {
    let mut k = bi;
    while k > 0 {
        k -= 1;
        if is_trivia(spans[k].kind) {
            continue;
        }
        return matches!(&text[spans[k].start..spans[k].end], "from" | "exclude");
    }
    false
}

/// Enhancement-414: folds one unrolled copy onto a single line so it occupies no
/// source lines of its own. Line comments are dropped rather than collapsed -- a `//`
/// would otherwise swallow every copy that follows it -- and newlines inside block
/// comments become spaces, which keeps them terminated.
fn collapse_newlines(src: &str) -> String {
    let mut out = String::with_capacity(src.len());
    for t in tok_spans(src) {
        if t.kind == TokenKind::LineComment {
            out.push(' ');
            continue;
        }
        let piece = &src[t.start..t.end];
        if piece.contains(['\n', '\r']) {
            out.extend(piece.chars().map(|c| if c == '\n' || c == '\r' { ' ' } else { c }));
        } else {
            out.push_str(piece);
        }
    }
    out
}

/// Enhancement-414: suffixes every `begin : label` (and matching `end : label`) in one
/// unrolled copy with the iteration index, the way a generate block is indexed.
///
/// The unroll is textual, so without this the block's NAME is copied verbatim too and
/// the copies collide -- `'blk' was already declared in this scope` for a loop that is
/// perfectly legal Verilog-AMS. A negative index spells itself `n1`, since `blk_-1` is
/// not an identifier.
fn rename_named_blocks(src: &str, index: i32) -> String {
    if !src.contains("begin") {
        return src.to_owned();
    }
    let suffix = if index < 0 {
        format!("_n{}", (index as i64).unsigned_abs())
    } else {
        format!("_{index}")
    };
    let spans = tok_spans(src);
    let mut out = String::with_capacity(src.len() + 8);
    let mut prev = 0usize;
    for k in 0..spans.len() {
        if !matches!(&src[spans[k].start..spans[k].end], "begin" | "end") {
            continue;
        }
        let c = skip_trivia(&spans, k + 1);
        if c >= spans.len() || &src[spans[c].start..spans[c].end] != ":" {
            continue;
        }
        let n = skip_trivia(&spans, c + 1);
        if n >= spans.len() || spans[n].kind != TokenKind::SimpleIdent {
            continue;
        }
        out.push_str(&src[prev..spans[n].end]);
        out.push_str(&suffix);
        prev = spans[n].end;
    }
    out.push_str(&src[prev..]);
    out
}

/// The token range of one statement starting at `from`.
///
/// Enhancement-414: this used to recognise exactly two shapes -- a `begin`..`end` block,
/// and "everything through the next top-level `;`" -- so every *other* statement was cut
/// short at the first `;` that happened to fall inside it. A `case`..`endcase` body kept
/// only its first item; `if (c) begin a; b; end` kept only `a;`. Whatever was left over
/// stayed behind, spliced after the generated block.
///
/// Usually that produced a spurious parse error pointing at `endmodule`, but one shape
/// was worse: for `if (c) x = ..; else y = ..;` the orphaned `else` re-attached to an
/// ENCLOSING `if`, so the loop compiled clean and computed a different program. The body
/// is therefore scanned by statement shape now, recursively, which is the only way to
/// know that an `else` belongs to the body rather than to the statement around it.
fn statement_extent(text: &str, spans: &[Tok], from: usize) -> Option<(usize, usize)> {
    let i = skip_trivia(spans, from);
    if i >= spans.len() {
        return None;
    }
    let tok = |j: usize| &text[spans[j].start..spans[j].end];

    match tok(i) {
        // `begin`..`end`, counting nested block and case openers alike
        "begin" | "case" | "casex" | "casez" => {
            let mut depth = 0i32;
            let mut j = i;
            while j < spans.len() {
                match tok(j) {
                    "begin" | "case" | "casex" | "casez" => depth += 1,
                    "end" | "endcase" => {
                        depth -= 1;
                        if depth == 0 {
                            return Some((i, j + 1));
                        }
                    }
                    _ => {}
                }
                j += 1;
            }
            None
        }
        // `if (cond) <stmt> [else <stmt>]` -- the else clause is PART of this statement
        "if" => {
            let after_cond = skip_paren_group(spans, skip_trivia(spans, i + 1))?;
            let (_, then_hi) = statement_extent(text, spans, after_cond)?;
            let e = skip_trivia(spans, then_hi);
            if e < spans.len() && tok(e) == "else" {
                let (_, else_hi) = statement_extent(text, spans, e + 1)?;
                return Some((i, else_hi));
            }
            Some((i, then_hi))
        }
        // header in parentheses, then one body statement
        "while" | "repeat" | "for" => {
            let after_head = skip_paren_group(spans, skip_trivia(spans, i + 1))?;
            let (_, hi) = statement_extent(text, spans, after_head)?;
            Some((i, hi))
        }
        // `do <stmt> while (cond);`
        "do" => {
            let (_, body_hi) = statement_extent(text, spans, i + 1)?;
            let w = skip_trivia(spans, body_hi);
            if w < spans.len() && tok(w) == "while" {
                let after = skip_paren_group(spans, skip_trivia(spans, w + 1))?;
                let s = skip_trivia(spans, after);
                if s < spans.len() && tok(s) == ";" {
                    return Some((i, s + 1));
                }
                return Some((i, after));
            }
            Some((i, body_hi))
        }
        // event control: `@(event) <stmt>` or `@ident <stmt>`
        "@" => {
            let p = skip_trivia(spans, i + 1);
            let after = if p < spans.len() && spans[p].kind == TokenKind::OpenParen {
                skip_paren_group(spans, p)?
            } else {
                p + 1
            };
            let (_, hi) = statement_extent(text, spans, after)?;
            Some((i, hi))
        }
        // the empty statement
        ";" => Some((i, i + 1)),
        // anything else is a simple statement: run to the next `;` at bracket depth zero
        _ => {
            let mut depth = 0i32;
            let mut j = i;
            while j < spans.len() {
                match spans[j].kind {
                    TokenKind::OpenParen | TokenKind::OpenBracket => depth += 1,
                    TokenKind::CloseParen | TokenKind::CloseBracket => depth -= 1,
                    _ if depth == 0 && tok(j) == ";" => return Some((i, j + 1)),
                    // a block closer before any `;` means the source is malformed --
                    // stop rather than swallowing the rest of the module
                    _ if depth == 0 && matches!(tok(j), "end" | "endcase") => return None,
                    _ => {}
                }
                j += 1;
            }
            None
        }
    }
}

fn substitute_index(body: &str, name: &str, value: i32) -> String {
    // pass 1: whole-identifier substitution of `name` -> value
    let spans = tok_spans(body);
    let mut s1 = String::with_capacity(body.len());
    let mut prev = 0usize;
    for t in &spans {
        if t.kind == TokenKind::SimpleIdent && &body[t.start..t.end] == name {
            s1.push_str(&body[prev..t.start]);
            s1.push_str(&value.to_string());
            prev = t.end;
        }
    }
    s1.push_str(&body[prev..]);

    // pass 2: fold bit-select brackets `[<const-int>]` -> `[<int>]`
    let spans = tok_spans(&s1);
    let mut holes: Vec<(usize, usize, String)> = Vec::new();
    let mut i = 0usize;
    while i < spans.len() {
        if spans[i].kind == TokenKind::OpenBracket {
            let mut depth = 0i32;
            let mut close = None;
            let mut j = i;
            while j < spans.len() {
                match spans[j].kind {
                    TokenKind::OpenBracket => depth += 1,
                    TokenKind::CloseBracket => {
                        depth -= 1;
                        if depth == 0 {
                            close = Some(j);
                            break;
                        }
                    }
                    _ => {}
                }
                j += 1;
            }
            if let Some(cj) = close {
                if let Some(val) = eval_const_int_tokens(&s1, &spans, i + 1, cj) {
                    holes.push((spans[i].end, spans[cj].start, val.to_string()));
                }
                i = cj + 1;
                continue;
            }
        }
        i += 1;
    }
    if holes.is_empty() {
        return s1;
    }
    let mut out = String::with_capacity(s1.len());
    let mut prev = 0usize;
    for (hs, he, rep) in holes {
        out.push_str(&s1[prev..hs]);
        out.push_str(&rep);
        prev = he;
    }
    out.push_str(&s1[prev..]);
    out
}

/// Entry point for `generate for`/`genvar` elaboration, called once from
/// [`CompilationDB::new`] *before* [`elaborate_instantiations`] -- so that
/// any instantiation statements written inside a `generate for` body have
/// already been unrolled into concrete text by the time instantiation
/// elaboration runs its own (separate) pass over the file.
///
/// Unlike instantiation elaboration, this pass needs no semantic
/// information at all (no target-module lookup, no port/parameter
/// resolution) -- a `generate for` loop only ever repeats its own body
/// verbatim, substituting one identifier (the genvar) with a per-iteration
/// integer literal, so it operates purely on `db.parse(root_file)` (parsing
/// has no `hir_def` dependency), without ever touching `item_tree`/
/// `def_map`. This keeps `generate` elaboration independent of -- and
/// strictly prior to -- any name-resolution machinery.
///
/// Scope: `generate` produces module items -- net/instance/variable/parameter
/// declarations and, since Enhancement-390, `analog` blocks. Enhancement-8's
/// original note here said the LRM forbids an `analog` block inside a generate;
/// it does not. The 2023 LRM's own grammar lists `analog_construct` as one
/// alternative of `module_or_generate_item`, so an analog block is exactly as
/// legal there as an instantiation. Until E-390 one was accepted by the
/// elaborator and then silently DROPPED, contributing nothing.
pub(crate) fn elaborate_generates(db: &mut CompilationDB) -> anyhow::Result<()> {
    let root_file = db.compilation_unit().root_file();
    let parse = db.parse(root_file);

    let has_any_generate = parse.tree().items().any(|item| {
        matches!(&item, ast::Item::ModuleDecl(m) if m.module_items().any(|it| {
            matches!(it, ast::ModuleItem::GenerateFor(_) | ast::ModuleItem::GenvarDecl(_)
            | ast::ModuleItem::GenerateIf(_) | ast::ModuleItem::GenerateCase(_))
        }))
    });
    if !has_any_generate {
        return Ok(());
    }

    let mut out = String::new();
    for item in parse.tree().items() {
        match item {
            ast::Item::ModuleDecl(module_ast) => {
                out.push_str(&render_module_with_generates(&module_ast)?);
            }
            other => out.push_str(&other.syntax().text().to_string()),
        }
        out.push('\n');
    }

    // Enhancement-58: name the synthetic file by BASENAME only. The VFS holds
    // the canonicalized absolute root path, and this name is embedded in the
    // compiled .osdi as source-file provenance -- an absolute path would leak
    // the build machine's layout into the artifact (repo examples must stay
    // machine-portable). Diagnostics still render fine against the short name.
    let root_path = db.vfs().read().file_path(root_file).to_string();
    let base_name =
        root_path.rsplit(['/', '\\']).next().unwrap_or(root_path.as_str()).to_owned();
    // virtual paths must start with '/' (VfsPath::new_virtual_path)
    let synth_name = format!("/{}__generated.va", base_name);
    let file_id = db.vfs().write().add_virt_file(&synth_name, out.into());

    let include_dirs = db.include_dirs(root_file);
    db.set_include_dirs(file_id, include_dirs);
    let macro_flags = db.macro_flags(root_file);
    db.set_macro_flags(file_id, macro_flags);
    let overwrites = db.global_lint_overwrites(root_file);
    db.set_global_lint_overwrites(file_id, overwrites);

    db.set_root_file(file_id);
    Ok(())
}

/// Renders one top-level module, expanding any `generate for` bodies (and
/// dropping any `genvar` declarations) it directly contains; a module with
/// neither is returned verbatim, byte-for-byte, keeping this pass a no-op
/// for the overwhelming majority of modules.
/// Enhancement-395: rejects a `genvar` whose name collides with anything else the
/// module declares, and duplicate genvars.
///
/// Generate elaboration ERASES genvars textually before `hir_def` builds the item
/// tree (`ModuleItem::GenvarDecl(_) => {}`), so they never enter a scope and never
/// took part in the "already declared in this scope" check that catches every
/// other duplicate pair. A `genvar` colliding with a `localparam` was therefore
/// accepted, and the localparam then won the bit-select fold (Enhancement-393):
/// every loop iteration indexed the SAME element, so a ladder that should have
/// been three series elements came out disconnected -- i(v1) = 0 instead of
/// -3.33e-4, silently. This is the only place the two names coexist.
fn check_genvar_collisions(module_ast: &ast::ModuleDecl) -> anyhow::Result<()> {
    let mut genvars: Vec<String> = Vec::new();
    let mut others: Vec<String> = Vec::new();
    for item in module_ast.module_items() {
        match item {
            ast::ModuleItem::GenvarDecl(decl) => {
                for name in decl.names() {
                    genvars.push(name.syntax().text().to_string());
                }
            }
            ast::ModuleItem::ParamDecl(decl) => {
                for para in decl.paras() {
                    if let Some(name) = para.name() {
                        others.push(name.syntax().text().to_string());
                    }
                }
            }
            ast::ModuleItem::VarDecl(decl) => {
                for var in decl.vars() {
                    if let Some(name) = var.name() {
                        others.push(name.syntax().text().to_string());
                    }
                }
            }
            ast::ModuleItem::NetDecl(decl) => {
                for name in decl.names() {
                    others.push(name.syntax().text().to_string());
                }
            }
            _ => {}
        }
    }
    for (i, g) in genvars.iter().enumerate() {
        if genvars[..i].contains(g) {
            anyhow::bail!("genvar '{g}' was already declared in this scope");
        }
        if others.contains(g) {
            anyhow::bail!(
                "genvar '{g}' collides with another declaration of '{g}' in the same module"
            );
        }
    }

    Ok(())
}

/// Enhancement-405/407: a genvar still referenced in an analog block AFTER unrolling.
///
/// E-405 added this check because elaboration ERASES genvar declarations textually, so
/// such a reference reached name resolution against a source where the declaration no
/// longer existed and was reported as "'g' was not found in the current scope" -- the
/// message for a name that was never declared, in front of a user looking straight at it.
///
/// E-407 moved it AFTER [`unroll_analog_genvar_loops`]. Driving an analog `for` with a
/// genvar is the LRM's own idiom (pages 91, 117 and 134) and is now unrolled rather than
/// rejected, so the check has to run on the result: a genvar the unroller consumed leaves
/// no trace, and one that survives is a genuine misuse -- reading it as a value, say.
fn check_no_genvar_left_in_analog(rendered: &str, genvars: &[String]) -> anyhow::Result<()> {
    if genvars.is_empty() {
        return Ok(());
    }
    let spans = tok_spans(rendered);
    for tok in &spans {
        if tok.kind != TokenKind::SimpleIdent {
            continue;
        }
        let name = &rendered[tok.start..tok.end];
        if genvars.iter().any(|g| g == name) {
            anyhow::bail!(
                "genvar '{name}' cannot be used inside an analog block except as the index \
                 of a `for` loop that is unrolled at elaboration time: a genvar holds no \
                 value during simulation. Use it as `for ({name} = <const>; ...)`, declare \
                 an `integer` to count at run time, or move the loop into a `generate` block"
            );
        }
    }
    Ok(())
}

fn render_module_with_generates(module_ast: &ast::ModuleDecl) -> anyhow::Result<String> {
    let has_generate = module_ast.module_items().any(|it| {
        matches!(it, ast::ModuleItem::GenerateFor(_) | ast::ModuleItem::GenvarDecl(_)
            | ast::ModuleItem::GenerateIf(_) | ast::ModuleItem::GenerateCase(_))
    });
    if !has_generate {
        return Ok(module_ast.syntax().text().to_string());
    }
    check_genvar_collisions(module_ast)?;

    // Enhancement-392: a `localparam` IS a compile-time constant, so it may size a
    // generated structure. Only `parameter` cannot -- it binds at simulation time
    // under OSDI, which is what the diagnostic has always said. The two were
    // rejected together, even though the compiler already accepts a localparam as
    // a constant in every other position: array bounds, bus port widths, parameter
    // defaults, `repeat` counts.
    let const_env = module_localparam_env(module_ast);
    // Enhancement-407: the genvars this module declares, so an `analog` `for` driven by
    // one can be recognised and unrolled below.
    let genvar_names: Vec<String> = module_ast
        .module_items()
        .filter_map(|it| match it {
            ast::ModuleItem::GenvarDecl(decl) => {
                Some(decl.names().map(|n| n.syntax().text().to_string()).collect::<Vec<_>>())
            }
            _ => None,
        })
        .flatten()
        .collect();
    // Replace ONLY the generate-machinery items in place, keeping every
    // other byte of the module verbatim. The previous item-by-item splice
    // rebuilt the whole item region from the typed `module_items()` list --
    // and `defparam` is deliberately NOT a typed `ast::ModuleItem` (it is
    // consumed by the E-58 machinery in the instantiation pass, which scans
    // raw DEFPARAM nodes), so any module containing a generate construct
    // silently dropped every one of its module-scope `defparam`s before
    // that pass could ever see them (LRM 6.3.1).
    let base = module_ast.syntax().text_range().start();
    let full = module_ast.syntax().text().to_string();
    let mut repls: Vec<(Range<usize>, String)> = Vec::new();
    // Book audit (generate names), LRM 6.6.3 / 6.7: every generate construct of
    // the module is numbered in textual order; a block without a label is
    // `genblk<n>` (leading zeroes added while that name is declared); what the
    // blocks declare is recorded under its hierarchical path (`g1[0].z`,
    // `blk.x`, `genblk1.y`) so references to it can be rewritten below.
    let declared = declared_names_of_items(module_ast.module_items());
    let mut taken: HashSet<String> = declared.clone();
    let mut paths: GenPaths = HashMap::new();
    let mut labels: HashSet<String> = HashSet::new();
    let mut construct = 0usize;
    for item in module_ast.module_items() {
        let range = rel_range(base, item.syntax().text_range());
        match item {
            ast::ModuleItem::GenvarDecl(_) => {
                // Compile-time-only; dropped entirely, never reaches `hir_def`.
                repls.push((range, String::new()));
            }
            ast::ModuleItem::GenerateFor(gen_for) => {
                construct += 1;
                let implicit = implicit_block_label(construct, &declared);
                let mut gen =
                    GenCtx { path: String::new(), implicit, paths: &mut paths, taken: &mut taken };
                repls.push((range, render_generate_for(&gen_for, &const_env, "", &Scope::default(), &mut gen)?));
                labels.extend(gen.top_labels());
            }
            ast::ModuleItem::GenerateIf(gen_if) => {
                construct += 1;
                let implicit = implicit_block_label(construct, &declared);
                let mut gen =
                    GenCtx { path: String::new(), implicit, paths: &mut paths, taken: &mut taken };
                repls.push((range, render_generate_if(&gen_if, &const_env, "", &Scope::default(), &mut gen)?));
                labels.extend(gen.top_labels());
            }
            ast::ModuleItem::GenerateCase(gen_case) => {
                construct += 1;
                let implicit = implicit_block_label(construct, &declared);
                let mut gen =
                    GenCtx { path: String::new(), implicit, paths: &mut paths, taken: &mut taken };
                repls.push((range, render_generate_case(&gen_case, &const_env, "", &Scope::default(), &mut gen)?));
                labels.extend(gen.top_labels());
            }
            // Enhancement-407: an `analog` block may drive a genvar `for` loop. Unlike a
            // module-level `generate for`, which repeats declarations, this one repeats
            // STATEMENTS -- and it exists because a vectored net's bit-select must be a
            // constant (each bit is its own simulator unknown), so `V(out[i]) <+ ..` over
            // a run-time `integer` is rejected. Unrolling here is what makes it legal, and
            // the LRM's own page-117 example ships the unrolled `dac8` beside the rolled
            // `dac` to say exactly that.
            ast::ModuleItem::AnalogBehaviour(_) if !genvar_names.is_empty() => {
                let src = item.syntax().text().to_string();
                let rendered = unroll_analog_genvar_loops(&src, &genvar_names, &const_env)?;
                check_no_genvar_left_in_analog(&rendered, &genvar_names)?;
                repls.push((range, rendered));
            }
            _ => {}
        }
    }
    let mut out = full;
    for (range, text) in repls.into_iter().rev() {
        out.replace_range(range, &text);
    }
    // the hierarchical names into the generate blocks, wherever the module's
    // text spells them (analog blocks, connections, declarations)
    let out = rewrite_generate_paths(&out, &paths, &labels)?;
    Ok(out)
}

/// Book audit (generate names): the flat rendered name of everything a
/// module's generate blocks declare, keyed by its LRM 6.7 hierarchical path
/// relative to the module -- `blk.x` for `if (c) begin : blk electrical x;
/// end`, `g1[0].z` for the first iteration of `for (...) begin : g1
/// electrical z; end`, `genblk1.y` for an unlabelled block, nested paths
/// such as `g1[0].genblk1.z` included.
type GenPaths = HashMap<String, String>;

/// The path bookkeeping threaded through one generate construct's rendering.
struct GenCtx<'a> {
    /// the enclosing blocks' path, `""` at module scope or `"g1[0]."`
    path: String,
    /// the label an unlabelled block of this construct takes (LRM 6.6.3)
    implicit: String,
    paths: &'a mut GenPaths,
    /// the flat names already declared in the enclosing scope -- the module's
    /// own and earlier generate blocks' -- so a second block declaring the same
    /// name (the LRM 6.6.3 example: two unlabelled `if`s each declaring `b`)
    /// renders it as `b_genblk02` instead of redeclaring `b`
    taken: &'a mut HashSet<String>,
}

impl GenCtx<'_> {
    /// The labels this construct's blocks are known by at module scope.
    fn top_labels(&self) -> Vec<String> {
        self.paths
            .keys()
            .filter_map(|k| k.split(['.', '[']).next().map(str::to_owned))
            .collect()
    }
}

/// LRM 6.6.3: `genblk<n>`, "if such a name would conflict with an explicitly
/// declared name, then leading zeroes are added in front of the number until
/// the name does not conflict".
fn implicit_block_label(n: usize, declared: &HashSet<String>) -> String {
    let mut digits = n.to_string();
    while declared.contains(&format!("genblk{digits}")) {
        digits.insert(0, '0');
    }
    format!("genblk{digits}")
}

/// Book audit (generate names): rewrites every hierarchical reference into a
/// generate block -- a path whose first segment is one of the module's generate
/// labels -- to the flat name the block's declaration was rendered under. The
/// longest prefix of the path that names a generated declaration is replaced
/// and the rest kept, so `g1[0].u1.x` (an instance inside a loop) becomes
/// `u1_0.x` for the instantiation pass to resolve. A path that starts with a
/// generate label and reaches nothing is an error, named.
fn rewrite_generate_paths(
    text: &str,
    paths: &GenPaths,
    labels: &HashSet<String>,
) -> anyhow::Result<String> {
    if paths.is_empty() {
        return Ok(text.to_owned());
    }
    let spans = tok_spans(text);
    let mut out = String::with_capacity(text.len());
    let mut prev = 0usize;
    let mut k = 0usize;
    while k < spans.len() {
        let t = &spans[k];
        if t.kind != TokenKind::SimpleIdent || !labels.contains(&text[t.start..t.end]) {
            k += 1;
            continue;
        }
        // a member of another path (`u1.blk.x`) is not a reference into this module's blocks
        let mut p = k;
        let mut after_dot = false;
        while p > 0 {
            p -= 1;
            if is_trivia(spans[p].kind) {
                continue;
            }
            after_dot = &text[spans[p].start..spans[p].end] == ".";
            break;
        }
        if after_dot {
            k += 1;
            continue;
        }
        // parse `label ( [int] )? ( . ident ( [int] )? )*`, remembering the
        // longest prefix that names a generated declaration
        let mut canon = text[t.start..t.end].to_owned();
        let mut j = k + 1;
        let mut best: Option<(usize, String)> = None; // (token index after the match, flat name)
        let mut segments = 0usize;
        loop {
            // an optional constant index
            let n = skip_trivia(&spans, j);
            if n < spans.len() && &text[spans[n].start..spans[n].end] == "[" {
                let i = skip_trivia(&spans, n + 1);
                let c = if i < spans.len() { skip_trivia(&spans, i + 1) } else { spans.len() };
                if i < spans.len()
                    && c < spans.len()
                    && &text[spans[c].start..spans[c].end] == "]"
                {
                    if let Ok(v) = text[spans[i].start..spans[i].end].parse::<i64>() {
                        canon.push_str(&format!("[{v}]"));
                        j = c + 1;
                    }
                }
            }
            if segments > 0 {
                if let Some(flat) = paths.get(&canon) {
                    best = Some((j, flat.clone()));
                }
            }
            // a further `. ident`
            let d = skip_trivia(&spans, j);
            if d < spans.len() && &text[spans[d].start..spans[d].end] == "." {
                let i = skip_trivia(&spans, d + 1);
                if i < spans.len() && spans[i].kind == TokenKind::SimpleIdent {
                    canon.push('.');
                    canon.push_str(&text[spans[i].start..spans[i].end]);
                    segments += 1;
                    j = i + 1;
                    continue;
                }
            }
            break;
        }
        if segments == 0 {
            // the bare label (a `disable` target, say): not a hierarchical reference
            k += 1;
            continue;
        }
        match best {
            Some((end, flat)) => {
                out.push_str(&text[prev..t.start]);
                out.push_str(&flat);
                prev = spans[end - 1].end;
                k = end;
            }
            None => anyhow::bail!(
                "'{canon}' names nothing declared in generate block '{}' -- the block declares: {}",
                canon.split(['.', '[']).next().unwrap_or(""),
                {
                    let head = canon.split(['.', '[']).next().unwrap_or("").to_owned();
                    let mut members: Vec<&str> = paths
                        .keys()
                        .filter(|p| p.split(['.', '[']).next() == Some(head.as_str()))
                        .map(String::as_str)
                        .collect();
                    members.sort();
                    if members.is_empty() { "nothing".to_owned() } else { members.join(", ") }
                }
            ),
        }
    }
    out.push_str(&text[prev..]);
    Ok(out)
}

/// Enhancement-392: a module's `localparam` names bound to their integer values.
///
/// Seeded into the generate elaborator's environment so a localparam can size a
/// generated structure, exactly as a literal can. Only integer-valued localparams
/// whose initialiser folds with the same evaluator are included -- one that
/// depends on a `parameter`, or is not an integer, simply is not in the map and
/// the existing "must be a compile-time-constant integer" error still applies.
///
/// `parameter` is deliberately NOT included: it binds at simulation time under
/// OSDI and cannot shape the generated structure.
fn module_localparam_env(module_ast: &ast::ModuleDecl) -> HashMap<String, i32> {
    let mut env = HashMap::new();
    for item in module_ast.module_items() {
        let ast::ModuleItem::ParamDecl(decl) = item else { continue };
        if decl.localparam_token().is_none() {
            continue;
        }
        for para in decl.paras() {
            let (Some(name), Some(default)) = (para.name(), para.default()) else { continue };
            // fold against what is already known, so one localparam may build on
            // an earlier one
            if let Some(v) = eval_int_expr(&default, &env) {
                env.insert(name.syntax().text().to_string(), v);
            }
        }
    }
    env
}

/// Constant-folds one side of a `generate for` header (loop bound,
/// initializer, or step) via `ast::Expr::as_constexprval`, the same
/// literal-only evaluator `hir_def::item_tree::lower::fold_width_range`
/// uses for `[msb:lsb]` instance-array ranges. Only integer literals (and
/// `+`/`-`-prefixed integer literals) fold; a parameter reference or other
/// non-trivial expression does not, and is reported as a hard compile
/// error by `render_generate_for`'s caller (there is no per-module
/// `hir_def`/`ItemTree` diagnostic channel available yet at this point in
/// the pipeline -- see this module's `elaborate_generates` doc comment).
fn fold_int(expr: &ast::Expr) -> Option<i32> {
    match expr.as_constexprval()? {
        ConstExprValue::Int(i) => Some(i),
        _ => None,
    }
}

/// A tiny integer-only constant-expression evaluator used to fold bit-select
/// indices (`node[i+1]`) once the genvar has a known per-iteration value:
/// integer literals (via `as_constexprval`), `+`/`-`-prefixed literals,
/// `+ - * /` binary combinations thereof, and a single bare identifier
/// looked up in `env` (the current genvar -> value binding). This is
/// intentionally much smaller than a general compile-time interpreter --
/// just enough to fold `i`, `i+1`, `i-1`, `2*i`, etc. inside a bit-select or
/// instance-array-range position.
fn eval_int_expr(expr: &ast::Expr, env: &HashMap<String, i32>) -> Option<i32> {
    if let Some(v) = fold_int(expr) {
        return Some(v);
    }
    match expr {
        ast::Expr::PathExpr(p) => {
            let ident = p.path()?.as_raw_ident()?;
            env.get(ident.text()).copied()
        }
        ast::Expr::ParenExpr(p) => eval_int_expr(&p.expr()?, env),
        ast::Expr::PrefixExpr(p) => {
            let v = eval_int_expr(&p.expr()?, env)?;
            match p.op_kind()? {
                ast::UnaryOp::Neg => Some(-v),
                ast::UnaryOp::Identity => Some(v),
                _ => None,
            }
        }
        ast::Expr::BinExpr(b) => {
            let lhs = eval_int_expr(&b.lhs()?, env)?;
            let rhs = eval_int_expr(&b.rhs()?, env)?;
            match b.op_kind()? {
                ast::BinaryOp::Addition => Some(lhs + rhs),
                ast::BinaryOp::Subtraction => Some(lhs - rhs),
                ast::BinaryOp::Multiplication => Some(lhs * rhs),
                ast::BinaryOp::Division if rhs != 0 => Some(lhs / rhs),
                _ => None,
            }
        }
        _ => None,
    }
}


/// Unrolls one `generate for (init; condition; incr) begin : label ... end`
/// loop into `N` concatenated, genvar-substituted copies of its body.
/// Supports the common ascending-loop shape required by the task scope:
/// `genvar = <const-int>; genvar <op> <const-int>; genvar = genvar + <const-int>`
/// (`<op>` is `<` or `<=`) -- i.e. a compile-time-constant-foldable
/// iteration count, evaluated up front, not a general compile-time
/// interpreter. Anything else is a hard elaboration error.
fn render_generate_for(
    gen_for: &ast::GenerateFor,
    outer_env: &HashMap<String, i32>,
    outer_suffix: &str,
    outer_scope: &Scope,
    gen: &mut GenCtx<'_>,
) -> anyhow::Result<String> {
    let init = gen_for
        .init()
        .ok_or_else(|| anyhow::anyhow!("generate for: missing loop-variable initializer"))?;
    let incr = gen_for
        .incr()
        .ok_or_else(|| anyhow::anyhow!("generate for: missing loop increment"))?;
    let condition = gen_for
        .condition()
        .ok_or_else(|| anyhow::anyhow!("generate for: missing loop condition"))?;
    let body = gen_for
        .body()
        .ok_or_else(|| anyhow::anyhow!("generate for: missing 'begin : label ... end' body"))?;
    // the label is optional since Enhancement-67 (anonymous blocks are legal
    // 1364-2005); an unlabelled block is `genblk<n>` (LRM 6.6.3)
    let label =
        body.label().map(|l| l.syntax().text().to_string()).unwrap_or_else(|| gen.implicit.clone());

    let genvar_name = init.lval().map(|e| e.syntax().text().to_string().trim().to_owned());
    let genvar_name = genvar_name
        .filter(|s| !s.is_empty())
        .ok_or_else(|| anyhow::anyhow!("generate for: loop-variable initializer must assign a plain genvar identifier"))?;

    let start = init
        .rval()
        .as_ref()
        .and_then(|e| eval_int_expr(e, outer_env))
        .ok_or_else(|| anyhow::anyhow!(
            "generate for: loop-variable initial value ('{genvar_name} = ...') must be a compile-time-constant integer -- NonConstantGenerateBound"
        ))?;

    // condition: `genvar < N` or `genvar <= N` (only the genvar-on-the-left
    // shape is supported -- see doc comment).
    let ast::Expr::BinExpr(cond_bin) = &condition else {
        anyhow::bail!("generate for: condition must be a simple 'genvar < N' or 'genvar <= N' comparison");
    };
    let op = cond_bin.op_kind().ok_or_else(|| anyhow::anyhow!("generate for: unsupported condition operator"))?;
    let inclusive = match op {
        ast::BinaryOp::LesserTest => false,
        ast::BinaryOp::LesserEqualTest => true,
        _ => anyhow::bail!("generate for: only '<' and '<=' loop conditions are supported"),
    };
    let bound = cond_bin
        .rhs()
        .as_ref()
        .and_then(|e| eval_int_expr(e, outer_env))
        .ok_or_else(|| anyhow::anyhow!(
            "generate for: loop bound must be a compile-time-constant integer (a literal or an outer genvar) -- module parameters bind at simulation time under OSDI and cannot shape the generated structure -- NonConstantGenerateBound"
        ))?;

    // incr: `genvar = genvar + step` (step constant-folds).
    let incr_rval = incr
        .rval()
        .ok_or_else(|| anyhow::anyhow!("generate for: increment must assign a value to the genvar"))?;
    let ast::Expr::BinExpr(incr_bin) = &incr_rval else {
        anyhow::bail!("generate for: only the 'genvar = genvar + step' increment shape is supported");
    };
    if !matches!(incr_bin.op_kind(), Some(ast::BinaryOp::Addition)) {
        anyhow::bail!("generate for: only an ascending ('+') increment is supported");
    }
    let step = incr_bin
        .rhs()
        .as_ref()
        .and_then(|e| eval_int_expr(e, outer_env))
        .ok_or_else(|| anyhow::anyhow!(
            "generate for: loop step must be a compile-time-constant integer -- NonConstantGenerateBound"
        ))?;
    if step <= 0 {
        anyhow::bail!("generate for: loop step must be a positive integer (only ascending loops are supported)");
    }

    let mut count = 0u32;
    let mut i = start;
    while if inclusive { i <= bound } else { i < bound } {
        i += step;
        count += 1;
        if count > 1_000_000 {
            anyhow::bail!("generate for: loop bound too large (>1,000,000 iterations) -- refusing to unroll");
        }
    }

    let mut out = String::new();
    let mut value = start;
    for _ in 0..count {
        let iter_suffix = format!("{outer_suffix}_{value}");
        let mut env = outer_env.clone();
        env.insert(genvar_name.clone(), value);

        out.push_str(&format!("// generate for {label}[{value}]\n"));
        let iter_path = format!("{}{label}[{value}].", gen.path);
        out.push_str(&render_generate_block(
            &body, &env, &iter_suffix, outer_scope, &iter_path, gen.paths, gen.taken,
        )?);
        out.push('\n');
        value += step;
    }
    Ok(out)
}

/// Renders the items of one generate block under `env` (the values of every
/// genvar currently in scope) with `suffix` (the accumulated per-iteration
/// disambiguator, e.g. `_0_2` two loops deep). Every name declared directly
/// in the block (instance/net/variable/parameter names) is suffixed --
/// exactly the Enhancement-5 flattening convention, `_<value>` per level so
/// the result stays an ordinary identifier. Nested `for`/`if`/`case`
/// generate constructs recurse (Enhancement-67); everything else renders as
/// text with two hole passes: constant-folded bit-select indices (so
/// `n[i+1]` becomes `n[3]`, which the bus machinery requires), then every
/// remaining bare genvar identifier replaced by its literal value (so
/// `1e3*(i+1)` works in any expression position -- routing genvars through
/// the identifier-substitution path instead used to re-escape the numeral
/// into a broken escaped identifier like `\0`).
fn render_generate_block(
    block: &ast::GenerateBlock,
    env: &HashMap<String, i32>,
    suffix: &str,
    outer_scope: &Scope,
    path: &str,
    paths: &mut GenPaths,
    taken: &mut HashSet<String>,
) -> anyhow::Result<String> {
    let mut scope = outer_scope.clone();
    let declared = collect_declared_names(block);
    // the block's label, as a suffix that keeps the name an identifier
    let label: String = path
        .trim_end_matches('.')
        .rsplit('.')
        .next()
        .unwrap_or("")
        .chars()
        .map(|c| if c.is_ascii_alphanumeric() || c == '_' { c } else { '_' })
        .collect();
    for name in &declared {
        let base = format!("{name}{suffix}");
        let mut flat = base.clone();
        // Book audit (generate names): a flat name the module already holds --
        // its own declaration, or an earlier generate block's anywhere in it
        // (two unlabelled `if`s each declaring `b`; two loops whose iteration 0
        // both declare `a`) -- moves aside under the block's label
        let mut k = 1;
        while !taken.insert(flat.clone()) {
            k += 1;
            flat = if k == 2 { format!("{base}_{label}") } else { format!("{base}_{label}_{k}") };
        }
        if flat != *name {
            scope.subst.insert(name.clone(), flat);
        }
    }
    // Book audit (generate names): what this block declares, by hierarchical path
    for name in &declared {
        let flat = scope.subst.get(name).cloned().unwrap_or_else(|| name.clone());
        paths.insert(format!("{path}{name}"), flat);
    }
    let declared_set: HashSet<String> = declared.iter().cloned().collect();
    let mut construct = 0usize;

    let mut out = String::new();
    for child in block.syntax().children() {
        let Some(item) = ast::ModuleItem::cast(child.clone()) else {
            // `defparam` is deliberately not a typed `ast::ModuleItem` (see
            // `render_module_with_generates`), so the typed iteration used
            // to skip it here and a `defparam` written inside a generate
            // block vanished without a diagnostic. Render it like any other
            // plain item: the genvar folds into its value expression and the
            // per-iteration rename rewrites its target instance name, so the
            // E-58 collection in the instantiation pass picks it up.
            if child.kind() == syntax::SyntaxKind::DEFPARAM {
                out.push_str(&render_generate_item(&child, env, &scope));
                out.push('\n');
            }
            continue;
        };
        match item {
            ast::ModuleItem::GenvarDecl(_) => {}
            ast::ModuleItem::GenerateFor(inner) => {
                construct += 1;
                let mut gen = GenCtx {
                    path: path.to_owned(),
                    implicit: implicit_block_label(construct, &declared_set),
                    paths: &mut *paths,
                    taken: &mut *taken,
                };
                out.push_str(&render_generate_for(&inner, env, suffix, &scope, &mut gen)?);
            }
            ast::ModuleItem::GenerateIf(inner) => {
                construct += 1;
                let mut gen = GenCtx {
                    path: path.to_owned(),
                    implicit: implicit_block_label(construct, &declared_set),
                    paths: &mut *paths,
                    taken: &mut *taken,
                };
                out.push_str(&render_generate_if(&inner, env, suffix, &scope, &mut gen)?);
            }
            ast::ModuleItem::GenerateCase(inner) => {
                construct += 1;
                let mut gen = GenCtx {
                    path: path.to_owned(),
                    implicit: implicit_block_label(construct, &declared_set),
                    paths: &mut *paths,
                    taken: &mut *taken,
                };
                out.push_str(&render_generate_case(&inner, env, suffix, &scope, &mut gen)?);
            }
            other => {
                out.push_str(&render_generate_item(other.syntax(), env, &scope));
                out.push('\n');
            }
        }
    }
    Ok(out)
}

/// Text-renders one non-generate item from a generate block: fold
/// bit-select indices under `env`, replace remaining bare genvar
/// identifiers with their values, then apply the name substitutions.
fn render_generate_item(
    item: &syntax::SyntaxNode,
    env: &HashMap<String, i32>,
    scope: &Scope,
) -> String {
    let base = item.text_range().start();
    let text = item.text().to_string();

    let mut holes: Vec<(Range<usize>, String)> = Vec::new();
    for node in item.descendants() {
        if let Some(sel) = ast::BitSelectExpr::cast(node) {
            for index in sel.indices() {
                if let Some(v) = eval_int_expr(&index, env) {
                    holes.push((rel_range(base, index.syntax().text_range()), v.to_string()));
                }
            }
        }
    }
    // Enhancement-392: the name in a NAMED connection -- the `r` of `.r(1e3)` or
    // `.p(node[i])` -- belongs to the INSTANTIATED module's namespace, not to this
    // scope, so the per-iteration renaming must not touch it. Substitution is
    // lexical over the whole token stream, so a generate block holding
    // `resistor #(.r(1e3)) r(...)` (an instance whose name collides with the
    // child's parameter) rewrote the override to `.r_0(1e3)`, which then named no
    // parameter of `resistor` and was silently dropped back to the default. Pin
    // each such name to itself with an identity hole.
    for node in item.descendants() {
        let name = if let Some(conn) = ast::PortConn::cast(node.clone()) {
            conn.name()
        } else if let Some(assign) = ast::ParamAssign::cast(node) {
            assign.name()
        } else {
            None
        };
        if let Some(name) = name {
            let range = name.syntax().text_range();
            holes.push((rel_range(base, range), text[rel_range(base, range)].to_string()));
        }
    }
    // bare genvar identifiers anywhere else (skip ranges already covered)
    for tok in item.descendants_with_tokens().filter_map(|el| el.into_token()) {
        if tok.kind() != syntax::SyntaxKind::IDENT {
            continue;
        }
        let Some(v) = env.get(tok.text()) else { continue };
        let r = rel_range(base, tok.text_range());
        if holes.iter().any(|(h, _)| h.start <= r.start && r.end <= h.end) {
            continue;
        }
        holes.push((r, v.to_string()));
    }
    holes.sort_by_key(|(r, _)| r.start);

    render_with_holes(&text, &holes, scope)
}

/// Renders a constant-folded `generate if` (Enhancement-67): evaluate the
/// condition under `env` and emit only the chosen branch. Conditions must
/// be elaboration-time constants (integer literals and genvars) -- module
/// parameters bind at simulation time under OSDI and cannot shape the
/// generated structure.
fn render_generate_if(
    gen_if: &ast::GenerateIf,
    env: &HashMap<String, i32>,
    suffix: &str,
    scope: &Scope,
    gen: &mut GenCtx<'_>,
) -> anyhow::Result<String> {
    let condition = gen_if
        .condition()
        .ok_or_else(|| anyhow::anyhow!("generate if: missing condition"))?;
    let cond = eval_cond_expr(&condition, env).ok_or_else(|| anyhow::anyhow!(
        "generate if: the condition ('{}') must be an elaboration-time constant \
         (integer literals and genvars); module parameters bind at simulation time \
         under OSDI and cannot shape the generated structure",
        condition.syntax().text()
    ))?;

    let mut blocks = gen_if.blocks();
    let then_block = blocks
        .next()
        .ok_or_else(|| anyhow::anyhow!("generate if: missing 'begin ... end' branch body"))?;
    // LRM 6.6.3: the chosen block's own label, or the construct's `genblk<n>`
    let block_path = |gen: &GenCtx<'_>, block: &ast::GenerateBlock| {
        let label = block
            .label()
            .map(|l| l.syntax().text().to_string())
            .unwrap_or_else(|| gen.implicit.clone());
        format!("{}{label}.", gen.path)
    };
    if cond {
        let path = block_path(gen, &then_block);
        return render_generate_block(&then_block, env, suffix, scope, &path, gen.paths, gen.taken);
    }
    // else side: either a nested `else if` (a GENERATE_IF child) or a block;
    // an `else if` chain is ONE construct and keeps its number
    if let Some(else_if) = support_child_generate_if(gen_if) {
        return render_generate_if(&else_if, env, suffix, scope, gen);
    }
    if let Some(else_block) = blocks.next() {
        let path = block_path(gen, &else_block);
        return render_generate_block(&else_block, env, suffix, scope, &path, gen.paths, gen.taken);
    }
    Ok(String::new())
}

/// The nested `else if` of a `generate if`, if any (a direct GENERATE_IF
/// child node).
fn support_child_generate_if(gen_if: &ast::GenerateIf) -> Option<ast::GenerateIf> {
    gen_if.syntax().children().find_map(ast::GenerateIf::cast)
}

/// Renders a constant-folded `generate case` (Enhancement-67): fold the
/// discriminant under `env`, pick the first arm with a matching folded
/// value (or the `default` arm), and emit only that arm's block.
fn render_generate_case(
    gen_case: &ast::GenerateCase,
    env: &HashMap<String, i32>,
    suffix: &str,
    scope: &Scope,
    gen: &mut GenCtx<'_>,
) -> anyhow::Result<String> {
    let disc_expr = gen_case
        .discriminant()
        .ok_or_else(|| anyhow::anyhow!("generate case: missing case expression"))?;
    let disc = eval_int_expr(&disc_expr, env).ok_or_else(|| anyhow::anyhow!(
        "generate case: the case expression ('{}') must be an elaboration-time constant \
         (integer literals and genvars); module parameters bind at simulation time \
         under OSDI and cannot shape the generated structure",
        disc_expr.syntax().text()
    ))?;

    let mut default_arm = None;
    for arm in gen_case.arms() {
        if arm.default_token().is_some() {
            default_arm = Some(arm);
            continue;
        }
        for val in arm.vals() {
            let v = eval_int_expr(&val, env).ok_or_else(|| anyhow::anyhow!(
                "generate case: arm value ('{}') must be an elaboration-time constant integer",
                val.syntax().text()
            ))?;
            if v == disc {
                let block = arm.block().ok_or_else(|| {
                    anyhow::anyhow!("generate case: arm is missing its 'begin ... end' block")
                })?;
                let path = case_block_path(gen, &block);
                return render_generate_block(&block, env, suffix, scope, &path, gen.paths, gen.taken);
            }
        }
    }
    if let Some(arm) = default_arm {
        let block = arm
            .block()
            .ok_or_else(|| anyhow::anyhow!("generate case: default arm is missing its block"))?;
        let path = case_block_path(gen, &block);
        return render_generate_block(&block, env, suffix, scope, &path, gen.paths, gen.taken);
    }
    Ok(String::new())
}

/// LRM 6.6.3: a case arm's block is known by its own label, or by the
/// construct's `genblk<n>`.
fn case_block_path(gen: &GenCtx<'_>, block: &ast::GenerateBlock) -> String {
    let label =
        block.label().map(|l| l.syntax().text().to_string()).unwrap_or_else(|| gen.implicit.clone());
    format!("{}{label}.", gen.path)
}

/// Evaluates a generate-time boolean condition: comparisons and logical
/// combinations of `eval_int_expr`-foldable operands; a bare integer
/// expression is true when non-zero.
fn eval_cond_expr(expr: &ast::Expr, env: &HashMap<String, i32>) -> Option<bool> {
    match expr {
        ast::Expr::ParenExpr(p) => eval_cond_expr(&p.expr()?, env),
        ast::Expr::PrefixExpr(p) if matches!(p.op_kind(), Some(ast::UnaryOp::Not)) => {
            Some(!eval_cond_expr(&p.expr()?, env)?)
        }
        ast::Expr::BinExpr(b) => {
            let op = b.op_kind()?;
            match op {
                ast::BinaryOp::BooleanAnd => {
                    Some(eval_cond_expr(&b.lhs()?, env)? && eval_cond_expr(&b.rhs()?, env)?)
                }
                ast::BinaryOp::BooleanOr => {
                    Some(eval_cond_expr(&b.lhs()?, env)? || eval_cond_expr(&b.rhs()?, env)?)
                }
                ast::BinaryOp::EqualityTest
                | ast::BinaryOp::NegatedEqualityTest
                | ast::BinaryOp::LesserTest
                | ast::BinaryOp::LesserEqualTest
                | ast::BinaryOp::GreaterTest
                | ast::BinaryOp::GreaterEqualTest => {
                    let lhs = eval_int_expr(&b.lhs()?, env)?;
                    let rhs = eval_int_expr(&b.rhs()?, env)?;
                    Some(match op {
                        ast::BinaryOp::EqualityTest => lhs == rhs,
                        ast::BinaryOp::NegatedEqualityTest => lhs != rhs,
                        ast::BinaryOp::LesserTest => lhs < rhs,
                        ast::BinaryOp::LesserEqualTest => lhs <= rhs,
                        ast::BinaryOp::GreaterTest => lhs > rhs,
                        _ => lhs >= rhs,
                    })
                }
                _ => Some(eval_int_expr(expr, env)? != 0),
            }
        }
        _ => Some(eval_int_expr(expr, env)? != 0),
    }
}

/// Collects the base names of everything declared directly inside a
/// `generate for` body (net/port names, instance names, variable names,
/// parameter names) -- these are exactly the identifiers that need a
/// per-iteration disambiguating suffix (see `render_generate_for`); genvar
/// substitution and references to *outer*-scope names (ordinary module
/// nets/parameters used, but not declared, inside the block) are left
/// alone.
fn collect_declared_names(body: &ast::GenerateBlock) -> Vec<String> {
    declared_names_of_item_list(body.items())
}

/// Book audit (generate names): the names a module's own item list declares,
/// for LRM 6.6.3's `genblk<n>` collision rule -- the declarations plus the
/// explicit labels of its generate blocks.
fn declared_names_of_items(items: ast::AstChildren<ast::ModuleItem>) -> HashSet<String> {
    let list: Vec<ast::ModuleItem> = items.collect();
    let mut names: HashSet<String> = declared_names_of_item_list(list.clone().into_iter()).into_iter().collect();
    for item in list {
        let mut labels = Vec::new();
        match item {
            ast::ModuleItem::GenerateFor(g) => {
                if let Some(l) = g.body().and_then(|b| b.label()) {
                    labels.push(l.syntax().text().to_string());
                }
            }
            ast::ModuleItem::GenerateIf(g) => {
                for node in g.syntax().descendants() {
                    if let Some(b) = ast::GenerateBlock::cast(node) {
                        if let Some(l) = b.label() {
                            labels.push(l.syntax().text().to_string());
                        }
                    }
                }
            }
            ast::ModuleItem::GenerateCase(g) => {
                for arm in g.arms() {
                    if let Some(l) = arm.block().and_then(|b| b.label()) {
                        labels.push(l.syntax().text().to_string());
                    }
                }
            }
            ast::ModuleItem::GenvarDecl(d) => {
                labels.extend(d.names().map(|n| n.syntax().text().to_string()));
            }
            _ => {}
        }
        names.extend(labels);
    }
    names
}

fn declared_names_of_item_list(items: impl Iterator<Item = ast::ModuleItem>) -> Vec<String> {
    let mut names = Vec::new();
    for item in items {
        match item {
            ast::ModuleItem::NetDecl(decl) => {
                names.extend(decl.names().map(|n| n.syntax().text().to_string()))
            }
            ast::ModuleItem::VarDecl(decl) => {
                names.extend(decl.vars().filter_map(|v| v.name()).map(|n| n.syntax().text().to_string()))
            }
            ast::ModuleItem::ParamDecl(decl) => {
                names.extend(decl.paras().filter_map(|p| p.name()).map(|n| n.syntax().text().to_string()))
            }
            ast::ModuleItem::Instantiation(inst) => {
                names.extend(
                    inst.instance_units().filter_map(|u| u.name()).map(|n| n.syntax().text().to_string()),
                )
            }
            ast::ModuleItem::BranchDecl(decl) => {
                names.extend(decl.names().map(|n| n.syntax().text().to_string()))
            }
            ast::ModuleItem::AliasParam(decl) => {
                if let Some(n) = decl.name() {
                    names.push(n.syntax().text().to_string());
                }
            }
            // Enhancement-392: an `analog function` declared in a generate block
            // needs renaming like anything else declared there. It used to fall
            // into the catch-all below, so a second iteration redeclared it and
            // the whole generate failed with "'ff' was already declared in this
            // scope" -- reachable since Enhancement-390 made `analog` legal here.
            ast::ModuleItem::Function(fun) => {
                if let Some(n) = fun.name() {
                    names.push(n.syntax().text().to_string());
                }
            }
            // ... as does a NAMED BLOCK LABEL inside an analog block, which is not
            // a module item at all and so was never even looked at. Renaming the
            // label also renames the `disable <label>` that targets it, because
            // both go through the same textual substitution.
            ast::ModuleItem::AnalogBehaviour(ab) => {
                if let Some(stmt) = ab.stmt() {
                    collect_block_labels(stmt.syntax(), &mut names);
                }
            }
            _ => {}
        }
    }
    names
}

/// Enhancement-392: every `begin : label` label at or below `node`.
///
/// Collected so a generate block's analog statements get their labels renamed
/// per iteration, exactly as its nets and variables already are.
fn collect_block_labels(node: &syntax::SyntaxNode, names: &mut Vec<String>) {
    for child in node.descendants() {
        if let Some(block) = ast::BlockStmt::cast(child.clone()) {
            if let Some(scope) = block.block_scope() {
                if let Some(n) = scope.name() {
                    names.push(n.syntax().text().to_string());
                }
            }
        }
    }
}

/// Book audit (paramsets), LRM 6.4.1: a paramset's expressions may hold
/// "hierarchical out-of-module references to local parameters of a different
/// module" -- the book's "constant module" idiom, `.RSH = fab.rsh_poly *
/// fab.bias;` over a `module fab; localparam real rsh_poly = 120.0; ...`. Such a
/// reference used to type-check (name resolution finds the module and its
/// localparam) and then crash code generation, which has no value for another
/// module's parameter. It is a compile-time constant, so it is substituted
/// textually here, before the item tree is built: the localparam's default in
/// parentheses, its own bare references to sibling localparams substituted in
/// turn. A reference to a non-local `parameter` is refused, as the clause
/// requires; a first segment that is not a module (an instance path, `$root`)
/// is left to name resolution.
///
/// A MODULE's body may hold the same reference (LRM 6.7 -- the page-155
/// `processinfo.rho` example reads a never-instantiated process-information
/// module), and is served the same way, provided the module declares no
/// instance of that name (an instance path is the instantiation pass's).
pub(crate) fn elaborate_paramset_consts(db: &mut CompilationDB) -> anyhow::Result<()> {
    let root_file = db.compilation_unit().root_file();
    let parse = db.parse(root_file);
    let tree = parse.tree();
    let modules: HashMap<String, ast::ModuleDecl> = tree
        .items()
        .filter_map(|it| match it {
            ast::Item::ModuleDecl(m) => Some((m.name()?.syntax().text().to_string(), m)),
            _ => None,
        })
        .collect();
    let mut holes: Vec<(Range<usize>, String)> = Vec::new();
    let mut errors: Vec<String> = Vec::new();
    for item in tree.items() {
        let (node, instances): (syntax::SyntaxNode, HashSet<String>) = match item {
            ast::Item::ParamsetDecl(ps) => (ps.syntax().clone(), HashSet::new()),
            ast::Item::ModuleDecl(m) => {
                let instances = m
                    .module_items()
                    .filter_map(|it| match it {
                        ast::ModuleItem::Instantiation(inst) => Some(inst),
                        _ => None,
                    })
                    .flat_map(|inst| {
                        inst.instance_units()
                            .filter_map(|u| u.name().map(|n| n.syntax().text().to_string()))
                            .collect::<Vec<_>>()
                    })
                    .collect();
                (m.syntax().clone(), instances)
            }
            _ => continue,
        };
        for node in node.descendants() {
            let Some(path) = ast::Path::cast(node) else { continue };
            // only a whole path, not its qualifier
            if path.parent_path().is_some() {
                continue;
            }
            let segs: Vec<String> =
                path.syntax().text().to_string().split('.').map(|s| s.trim().to_owned()).collect();
            if segs.len() != 2 || instances.contains(&segs[0]) {
                continue;
            }
            let Some(module) = modules.get(&segs[0]) else { continue };
            match module_localparam_text(module, &segs[0], &segs[1], 0) {
                Ok(text) => holes.push((
                    rel_range(TextSize::from(0), path.syntax().text_range()),
                    format!("({text})"),
                )),
                Err(msg) => errors.push(msg.to_string()),
            }
        }
    }
    if !errors.is_empty() {
        anyhow::bail!("{}", errors.join("\n"));
    }
    if holes.is_empty() {
        return Ok(());
    }
    holes.sort_by_key(|(r, _)| r.start);
    let text = tree.syntax().text().to_string();
    let mut out = String::with_capacity(text.len());
    let mut pos = 0usize;
    for (r, rep) in holes {
        if r.start < pos {
            continue;
        }
        out.push_str(&text[pos..r.start]);
        out.push_str(&rep);
        pos = r.end;
    }
    out.push_str(&text[pos..]);

    let root_path = db.vfs().read().file_path(root_file).to_string();
    let base_name =
        root_path.rsplit(['/', '\\']).next().unwrap_or(root_path.as_str()).to_owned();
    let synth_name = format!("/{}__paramset.va", base_name);
    let file_id = db.vfs().write().add_virt_file(&synth_name, out.into());
    let include_dirs = db.include_dirs(root_file);
    db.set_include_dirs(file_id, include_dirs);
    let macro_flags = db.macro_flags(root_file);
    db.set_macro_flags(file_id, macro_flags);
    let overwrites = db.global_lint_overwrites(root_file);
    db.set_global_lint_overwrites(file_id, overwrites);
    db.set_root_file(file_id);
    Ok(())
}

/// The text of `module_name.name`, a `localparam` of `module`: its default with
/// every bare reference to a sibling localparam substituted the same way.
fn module_localparam_text(
    module: &ast::ModuleDecl,
    module_name: &str,
    name: &str,
    depth: u32,
) -> anyhow::Result<String> {
    if depth > 16 {
        anyhow::bail!("`{module_name}.{name}`: the localparam chain is deeper than 16 levels");
    }
    for item in module.module_items() {
        let ast::ModuleItem::ParamDecl(pd) = item else { continue };
        for para in pd.paras() {
            if para.name().map(|n| n.syntax().text().to_string()).as_deref() != Some(name) {
                continue;
            }
            if pd.localparam_token().is_none() {
                anyhow::bail!(
                    "`{module_name}.{name}` refers to a parameter of module '{module_name}' that \
                     is not a `localparam`: LRM 6.4.1 allows a paramset hierarchical out-of-module \
                     references to LOCAL parameters only -- an overridable parameter has no value \
                     until the model card is read"
                );
            }
            let default = para
                .default()
                .map(|d| d.syntax().text().to_string())
                .unwrap_or_else(|| "0".to_owned());
            let spans = tok_spans(&default);
            let mut out = String::with_capacity(default.len());
            let mut prev = 0usize;
            for (k, t) in spans.iter().enumerate() {
                if t.kind != TokenKind::SimpleIdent {
                    continue;
                }
                // a member of a hierarchical path is not a sibling
                let mut p = k;
                let mut after_dot = false;
                while p > 0 {
                    p -= 1;
                    if is_trivia(spans[p].kind) {
                        continue;
                    }
                    after_dot = &default[spans[p].start..spans[p].end] == ".";
                    break;
                }
                if after_dot {
                    continue;
                }
                let ident = &default[t.start..t.end];
                if ident == name {
                    continue;
                }
                let declared = module.module_items().any(|it| match it {
                    ast::ModuleItem::ParamDecl(pd) => pd.paras().any(|p| {
                        p.name().map(|n| n.syntax().text().to_string()).as_deref() == Some(ident)
                    }),
                    _ => false,
                });
                if !declared {
                    continue;
                }
                let inner = module_localparam_text(module, module_name, ident, depth + 1)?;
                out.push_str(&default[prev..t.start]);
                out.push_str(&format!("({inner})"));
                prev = t.end;
            }
            out.push_str(&default[prev..]);
            return Ok(out);
        }
    }
    anyhow::bail!(
        "`{module_name}.{name}`: module '{module_name}' declares no parameter '{name}' (referenced \
         from a paramset)"
    )
}

/// Entry point, called once from [`CompilationDB::new`]. No-op (and cheap:
/// one `item_tree` lookup) for the overwhelming majority of files, which
/// contain no instantiations at all.
pub(crate) fn elaborate_instantiations(db: &mut CompilationDB) -> anyhow::Result<()> {
    let root_file = db.compilation_unit().root_file();
    let tree = db.item_tree(root_file);

    let has_any_instantiation = tree
        .data
        .modules
        .iter()
        .any(|m| m.items.iter().any(|it| matches!(it, ModuleItem::Instantiation(_))));
    if !has_any_instantiation {
        return Ok(());
    }

    // A cyclic-instantiation diagnostic means the instantiation graph can't
    // be flattened at all (would recurse forever); skip elaboration and let
    // the normal diagnostic-printing path surface the cycle as a compile
    // error against the original file instead.
    let def_map = db.def_map(root_file);
    if def_map.diagnostics.iter().any(|d| matches!(d, DefDiagnostic::CyclicInstantiation { .. })) {
        return Ok(());
    }

    let ast_id_map = db.ast_id_map(root_file);
    let parse = db.parse(root_file);
    let by_name: HashMap<Name, ItemTreeId<TreeModule>> =
        tree.data.modules.iter_enumerated().map(|(id, m)| (m.name.clone(), id)).collect();

    let mut ctx = ElabCtx {
        tree: &tree,
        ast_id_map: &ast_id_map,
        parse: &parse,
        by_name,
        implicit_nets: HashMap::new(),
        implicit_conflicts: Vec::new(),
        defparam_overrides: HashMap::new(),
        defparam_applied: HashSet::new(),
        defparam_src: HashMap::new(),
        port_conn_errors: Vec::new(),
        unknown_module_errors: Vec::new(),
        hier_param_errors: Vec::new(),
        abs_prefixes: Rc::new(AbsPrefixes::default()),
        port_ammeters: HashMap::new(),
        flow_access: flow_access_names(&tree),
        access_names: tree
            .data
            .natures
            .iter()
            .filter_map(|n| n.access.as_ref().map(|(a, _)| a.to_string()))
            .collect(),
        params_given_in_va: HashSet::new(),
    };

    // Enhancement-86: a module whose body holds ABSOLUTE hierarchical
    // references anchored at another module (`V(top.a1.b)`,
    // `I($root.top.d1.branch(<p>))` -- the LRM's cross-instance monitor
    // idiom) is hierarchy-bound: its inlined copies under that anchor
    // resolve fine, but a standalone flattened copy cannot. Detect these
    // with the anchor's own qualified chain map and omit the standalone
    // copy instead of emitting unresolvable text.
    let anchor_maps: Vec<(Name, HashMap<String, String>)> = tree
        .data
        .modules
        .iter_enumerated()
        .map(|(id, m)| {
            let mut chains = HashMap::new();
            ctx.collect_inst_prefixes(id, "", "", &mut chains);
            let anchor = m.name.to_string();
            let mut map: HashMap<String, String> = chains
                .iter()
                .map(|(k, v)| (format!("{anchor}.{k}"), v.clone()))
                .collect();
            map.insert(anchor, String::new());
            (m.name.clone(), map)
        })
        .collect();

    let mut out = String::new();
    for item in parse.tree().items() {
        match item {
            ast::Item::ModuleDecl(module_ast) => {
                let Some(name) = module_ast.name().map(|n| n.as_name()) else { continue };
                let Some(&module_id) = ctx.by_name.get(&name) else { continue };
                let text = module_ast.syntax().text().to_string();
                let anchor = anchor_maps.iter().find(|(anchor_name, map)| {
                    *anchor_name != name
                        && !find_instance_path_holes(&text, map, &AbsPrefixes::default()).is_empty()
                });
                if let Some((anchor_name, _)) = anchor {
                    out.push_str(&format!(
                        "// module '{name}' omitted from standalone output: it holds hierarchical references anchored at '{anchor_name}' and is elaborated inline where instantiated (Enhancement-86)"
                    ));
                } else {
                    out.push_str(&ctx.flatten_top_level_module(module_id, &module_ast));
                }
            }
            other => out.push_str(&other.syntax().text().to_string()),
        }
        out.push('\n');
    }

    if !ctx.implicit_conflicts.is_empty() {
        anyhow::bail!("{}", ctx.implicit_conflicts.join("\n"));
    }

    if !ctx.port_conn_errors.is_empty() {
        anyhow::bail!("{}", ctx.port_conn_errors.join("\n"));
    }

    if !ctx.unknown_module_errors.is_empty() {
        anyhow::bail!("{}", ctx.unknown_module_errors.join("\n"));
    }

    if !ctx.hier_param_errors.is_empty() {
        anyhow::bail!("{}", ctx.hier_param_errors.join("\n"));
    }

    // Enhancement-58: a `defparam` whose target never matched a flattened
    // parameter is almost always a mistake (typo, or an out-of-scope
    // hierarchical target) -- surface it rather than silently ignoring it.
    let unresolved: Vec<_> = ctx
        .defparam_overrides
        .keys()
        .filter(|k| !ctx.defparam_applied.contains(*k))
        .map(|k| ctx.defparam_src.get(k).cloned().unwrap_or_else(|| k.clone()))
        .collect();
    if !unresolved.is_empty() {
        anyhow::bail!(
            "defparam target(s) did not resolve to any parameter: {}",
            unresolved.join(", ")
        );
    }

    // LRM 6.3.5/9.19: a parameter overridden from inside the hierarchy (an
    // instance `#(...)` value or a `defparam`) IS "given" -- but flattening
    // bakes the override in as the parameter's new default, which OSDI
    // would report as "not given" unless the netlist repeated it. Rewrite
    // `$param_given(<flat>)` for exactly those parameters to a true literal.
    let mut given_in_va = ctx.params_given_in_va.clone();
    given_in_va.extend(ctx.defparam_applied.iter().cloned());
    let out = resolve_param_given(&out, &given_in_va);

    // Enhancement-58: name the synthetic file by BASENAME only. The VFS holds
    // the canonicalized absolute root path, and this name is embedded in the
    // compiled .osdi as source-file provenance -- an absolute path would leak
    // the build machine's layout into the artifact (repo examples must stay
    // machine-portable). Diagnostics still render fine against the short name.
    let root_path = db.vfs().read().file_path(root_file).to_string();
    let base_name =
        root_path.rsplit(['/', '\\']).next().unwrap_or(root_path.as_str()).to_owned();
    // virtual paths must start with '/' (VfsPath::new_virtual_path)
    let synth_name = format!("/{}__elaborated.va", base_name);
    let file_id = db.vfs().write().add_virt_file(&synth_name, out.into());

    let include_dirs = db.include_dirs(root_file);
    db.set_include_dirs(file_id, include_dirs);
    let macro_flags = db.macro_flags(root_file);
    db.set_macro_flags(file_id, macro_flags);
    let overwrites = db.global_lint_overwrites(root_file);
    db.set_global_lint_overwrites(file_id, overwrites);

    db.set_root_file(file_id);
    Ok(())
}

/// Book audit (paramsets), LRM 6.4.2: a literal's value -- a number with its
/// SI suffix, an integer, `inf` -- or `None` for anything that is not one.
fn const_real_of(e: &ast::Expr) -> Option<f64> {
    match e.as_constexprval() {
        Some(ConstExprValue::Float(f)) => Some(f.into_inner()),
        Some(ConstExprValue::Int(i)) => Some(i as f64),
        _ => match e {
            ast::Expr::Literal(l) if matches!(l.kind(), ast::LiteralKind::Inf) => Some(f64::INFINITY),
            ast::Expr::PrefixExpr(p) => {
                let inner = p.expr()?;
                match p.op_kind()? {
                    ast::UnaryOp::Neg => const_real_of(&inner).map(|v| -v),
                    ast::UnaryOp::Identity => const_real_of(&inner),
                    _ => None,
                }
            }
            ast::Expr::ParenExpr(p) => const_real_of(&p.expr()?),
            _ => None,
        },
    }
}

/// Book audit (paramsets), LRM 6.4.2: does `value` violate one of `p`'s
/// literal `from`/`exclude` constraints? Returns the offending constraint's
/// text. A bound that is not a literal is taken as unbounded.
fn constraints_reject(p: &ast::Param, value: f64) -> Option<String> {
    let mut any_from = false;
    let mut in_some_from = false;
    for c in p.constraints() {
        let (Some(kind), Some(cv)) = (c.kind(), c.val()) else { continue };
        let text = || c.syntax().text().to_string().split_whitespace().collect::<Vec<_>>().join(" ");
        match (kind, cv) {
            (ast::ConstraintKind::From, ast::ConstraintValue::Range(r)) => {
                any_from = true;
                let lo = r.start().and_then(|e| const_real_of(&e)).unwrap_or(f64::NEG_INFINITY);
                let hi = r.end().and_then(|e| const_real_of(&e)).unwrap_or(f64::INFINITY);
                let above_lo = if r.start_inclusive() { value >= lo } else { value > lo };
                let below_hi = if r.end_inclusive() { value <= hi } else { value < hi };
                if above_lo && below_hi {
                    in_some_from = true;
                }
            }
            (ast::ConstraintKind::From, ast::ConstraintValue::Val(v)) => {
                any_from = true;
                if const_real_of(&v).map_or(true, |x| x == value) {
                    in_some_from = true;
                }
            }
            (ast::ConstraintKind::Exclude, ast::ConstraintValue::Range(r)) => {
                let lo = r.start().and_then(|e| const_real_of(&e)).unwrap_or(f64::NEG_INFINITY);
                let hi = r.end().and_then(|e| const_real_of(&e)).unwrap_or(f64::INFINITY);
                let above_lo = if r.start_inclusive() { value >= lo } else { value > lo };
                let below_hi = if r.end_inclusive() { value <= hi } else { value < hi };
                if above_lo && below_hi {
                    return Some(text());
                }
            }
            (ast::ConstraintKind::Exclude, ast::ConstraintValue::Val(v)) => {
                if const_real_of(&v) == Some(value) {
                    return Some(text());
                }
            }
        }
    }
    if any_from && !in_some_from {
        let froms: Vec<String> = p
            .constraints()
            .filter(|c| c.kind() == Some(ast::ConstraintKind::From))
            .map(|c| c.syntax().text().to_string().split_whitespace().collect::<Vec<_>>().join(" "))
            .collect();
        return Some(froms.join(" "));
    }
    None
}

/// Book audit (paramsets): one paramset of an instantiated chain, composed.
struct PsLevel {
    decl: ast::ParamsetDecl,
    /// the level's own parameters and localparams, name -> value text
    values: HashMap<String, String>,
    /// the level's own variables, in declaration order
    var_names: Vec<String>,
    /// `.var = e;` on the target's variables: (name, value text)
    var_overrides: Vec<(String, String)>,
}

/// Book audit (paramsets): substitutes a paramset text's identifiers. A bare
/// identifier in `own` is replaced by its text; a `.name` reference (a `.` not
/// following an identifier or a closing bracket -- so a hierarchical path is
/// left alone) is replaced by `dots[name]`, the dot dropped, or by the bare
/// name when `dots` has no entry.
fn substitute_paramset_text(
    text: &str,
    own: &HashMap<String, String>,
    dots: &HashMap<String, String>,
) -> String {
    let spans = tok_spans(text);
    let mut out = String::with_capacity(text.len());
    let mut prev = 0usize;
    let mut k = 0usize;
    while k < spans.len() {
        let t = &spans[k];
        let raw = &text[t.start..t.end];
        if raw == "." {
            let n = skip_trivia(&spans, k + 1);
            let member = n < spans.len() && spans[n].kind == TokenKind::SimpleIdent;
            let mut p = k;
            let after_name = loop {
                if p == 0 {
                    break false;
                }
                p -= 1;
                if is_trivia(spans[p].kind) {
                    continue;
                }
                let s = &text[spans[p].start..spans[p].end];
                break spans[p].kind == TokenKind::SimpleIdent
                    || spans[p].kind == TokenKind::EscapedIdent
                    || s == ")"
                    || s == "]";
            };
            if member && !after_name {
                let name = &text[spans[n].start..spans[n].end];
                out.push_str(&text[prev..t.start]);
                out.push_str(dots.get(name).map(String::as_str).unwrap_or(name));
                prev = spans[n].end;
                k = n + 1;
                continue;
            }
        } else if t.kind == TokenKind::SimpleIdent {
            if let Some(v) = own.get(raw) {
                out.push_str(&text[prev..t.start]);
                out.push_str(v);
                prev = t.end;
            }
        }
        k += 1;
    }
    out.push_str(&text[prev..]);
    out
}

/// Book audit (paramsets): the flattened name of every variable a paramset of
/// the chain declares -- outermost level first, `{prefix}{name}`, an inner
/// level's variable of a name an outer one also declares `{prefix}{name}__ps<k>`.
fn paramset_level_names(levels: &[PsLevel], prefix: &str) -> Vec<HashMap<String, String>> {
    let mut used: HashSet<String> = HashSet::new();
    let mut out = Vec::with_capacity(levels.len());
    for (k, level) in levels.iter().enumerate() {
        let mut names = HashMap::new();
        for v in &level.var_names {
            let flat = if used.insert(v.clone()) {
                format!("{prefix}{v}")
            } else {
                format!("{prefix}{v}__ps{k}")
            };
            names.insert(v.clone(), flat);
        }
        out.push(names);
    }
    out
}

/// Book audit (paramsets): renders the variables and statements of an
/// instantiated paramset chain after the module's flattened body -- innermost
/// level first, as the twin module orders them. Each level's own parameters
/// are their composed values, its own variables their flattened names, and a
/// `.name` reference resolves to the namespace of its target: the module's
/// flattened declarations, extended by each inner level's own variables and
/// parameter values (LRM 6.4.3).
fn render_paramset_levels(
    levels: &[PsLevel],
    names: &[HashMap<String, String>],
    scope: &Scope,
) -> String {
    if levels.is_empty() {
        return String::new();
    }
    let mut out = String::new();
    // the module's declarations, as the innermost level sees them
    let mut dots: HashMap<String, String> = scope.subst.clone();
    for (level, own_names) in levels.iter().zip(names).rev() {
        let mut own: HashMap<String, String> = level.values.clone();
        own.extend(own_names.iter().map(|(k, v)| (k.clone(), v.clone())));
        out.push_str("\n// paramset statements (LRM 6.4.1)\n");
        for vd in level.decl.var_decls() {
            let text = vd.syntax().text().to_string();
            out.push_str(&substitute_paramset_text(&text, own_names, &HashMap::new()));
            out.push('\n');
        }
        let mut stmts = String::new();
        for (var, val) in &level.var_overrides {
            let dst = dots.get(var).cloned().unwrap_or_else(|| var.clone());
            stmts.push_str(&format!("{dst} = {val};\n"));
        }
        for st in level.decl.stmts() {
            stmts.push_str(&substitute_paramset_text(&st.syntax().text().to_string(), &own, &dots));
            stmts.push('\n');
        }
        if !stmts.is_empty() {
            out.push_str("analog begin\n");
            out.push_str(&stmts);
            out.push_str("end\n");
        }
        // this level's namespace is what the next-outer level's `.name` sees
        dots.extend(own);
    }
    out
}

struct ElabCtx<'a> {
    tree: &'a ItemTree,
    ast_id_map: &'a AstIdMap,
    parse: &'a Parse<SourceFile>,
    by_name: HashMap<Name, ItemTreeId<TreeModule>>,
    /// Enhancement-41: implicit nets synthesised so far, keyed by their final
    /// (prefix-qualified) name, holding the discipline each was declared with —
    /// used both to emit each declaration exactly once and to diagnose two
    /// connections implying conflicting disciplines for the same net.
    implicit_nets: HashMap<String, String>,
    implicit_conflicts: Vec<String>,
    /// Enhancement-58: `defparam` overrides collected so far, keyed by the
    /// target parameter's FINAL flattened name (`u1.u2.r` -> `u1__u2__r`,
    /// resolved through the same instance-chain prefixes E-49 uses). The
    /// value is the override expression text (already rename-applied). Read
    /// in `render_items`' `ParamDecl` arm to rewrite that parameter's
    /// default; `defparam` takes precedence over an instance `#(...)` value.
    defparam_overrides: HashMap<String, String>,
    /// Every flattened target name that a `defparam` actually overrode, so
    /// unresolved targets (typos, out-of-scope hierarchy) can be diagnosed.
    defparam_applied: HashSet<String>,
    /// Flattened target name -> the original source path (`u1.typo`), for a
    /// readable unresolved-target diagnostic.
    defparam_src: HashMap<String, String>,
    /// Enhancement-59: errors from concatenated port actuals (`u1({a,c})`)
    /// whose bit count doesn't match the connected port's width. Collected
    /// during rendering (which has no error channel) and bailed afterwards,
    /// like `implicit_conflicts`.
    port_conn_errors: Vec<String>,
    /// Instantiations whose target module does not exist anywhere in the
    /// compilation unit. These used to be silently dropped from the rendered
    /// output — a typo'd module name became an invisible open circuit.
    unknown_module_errors: Vec<String>,
    /// Enhancement-87: instance parameter overrides that name a
    /// hierarchical/block-scoped parameter (`#(.blk.p(4))`), which the LRM
    /// forbids (only a module-level parameter may be named here).
    hier_param_errors: Vec<String>,
    /// Enhancement-86: the ABSOLUTE instance-chain map of the top module
    /// currently being flattened — only the unambiguous spellings (the top
    /// module's own name, and `<top>.<chain>`-qualified keys), so it can be
    /// merged into every inlined child's scope without colliding with the
    /// child's own relative chains. This is what lets a SIBLING's body
    /// resolve `V(top.a1.b)` / `$root.top…` references.
    abs_prefixes: Rc<AbsPrefixes>,
    /// Enhancement-86: instance prefixes whose listed ports need a
    /// synthesized 0V ammeter because some body probes
    /// `<chain>.branch(<port>)` — collected by a pre-scan over every
    /// module's text before the top module renders.
    port_ammeters: HashMap<String, BTreeSet<String>>,
    /// Access-function names of every FLOW nature (`I` for `Current`, plus
    /// any derived nature whose parent chain reaches one), resolved from the
    /// item tree's discipline `flow` bindings. Used by the `#(.$mfactor(n))`
    /// child-instance transform, which must scale exactly the flow
    /// contributions/probes of the scaled instance (LRM 6.3.6).
    flow_access: HashSet<String>,
    /// Access-function names of EVERY nature (`V`, `I`, `Pwr`, ...). Used by
    /// the LRM 5.6.8.1 hierarchical-contribution transform to recognise
    /// probe calls that reference the same hierarchical node pair a
    /// contribution targets.
    access_names: HashSet<String>,
    /// FINAL flattened names of every parameter that received a value from
    /// inside the Verilog-A hierarchy (an instance `#(...)` override; a
    /// `defparam` target lands in `defparam_applied` instead). LRM 6.3.5:
    /// such a parameter IS "given", so `$param_given(<flat>)` calls in the
    /// rendered output are rewritten to a true constant -- compile-time
    /// flattening otherwise bakes the override in as the parameter's new
    /// default and OSDI reports "not given" unless the netlist repeats it.
    params_given_in_va: HashSet<String>,
}

/// Access-function names of every FLOW nature (`I` for `Current`), resolved
/// from the item tree: each discipline's `flow` binding names a root nature
/// (possibly through `<discipline>.flow`/`.potential` indirections), and any
/// nature whose parent chain reaches such a root contributes its `access`
/// name. Used by the `#(.$mfactor(n))` instance transform, which must scale
/// exactly the flow contributions/probes of the scaled child (LRM 6.3.6).
fn flow_access_names(tree: &ItemTree) -> HashSet<String> {
    use hir_def::item_tree::{NatureRef, NatureRefKind};

    fn resolve_root(tree: &ItemTree, mut cur: Option<NatureRef>) -> Option<Name> {
        for _ in 0..8 {
            let r = cur?;
            match r.kind {
                NatureRefKind::Nature => return Some(r.name),
                NatureRefKind::DisciplineFlow => {
                    cur = tree
                        .data
                        .disciplines
                        .iter()
                        .find(|d| d.name == r.name)
                        .and_then(|d| d.flow.as_ref().map(|(r, _)| r.clone()));
                }
                NatureRefKind::DisciplinePotential => {
                    cur = tree
                        .data
                        .disciplines
                        .iter()
                        .find(|d| d.name == r.name)
                        .and_then(|d| d.potential.as_ref().map(|(r, _)| r.clone()));
                }
            }
        }
        None
    }

    let flow_roots: HashSet<Name> = tree
        .data
        .disciplines
        .iter()
        .filter_map(|d| resolve_root(tree, d.flow.as_ref().map(|(r, _)| r.clone())))
        .collect();

    let mut out = HashSet::new();
    for nature in tree.data.natures.iter() {
        let mut cur = Some(nature.name.clone());
        let mut is_flow = false;
        for _ in 0..8 {
            let Some(name) = cur else { break };
            if flow_roots.contains(&name) {
                is_flow = true;
                break;
            }
            cur = tree
                .data
                .natures
                .iter()
                .find(|n| n.name == name)
                .and_then(|n| n.parent.as_ref())
                .and_then(|p| match p.kind {
                    NatureRefKind::Nature => Some(p.name.clone()),
                    _ => resolve_root(tree, Some(p.clone())),
                });
        }
        if is_flow {
            if let Some((access, _)) = &nature.access {
                out.insert(access.to_string());
            }
        }
    }
    out
}

/// Composes the hierarchical system parameter overrides inherited from
/// enclosing instances with an instance's own `#(.$mfactor(...))` list:
/// multiplicative parameters ($mfactor/$hflip/$vflip) multiply down the
/// hierarchy, additive ones ($xposition/$yposition/$angle) sum (LRM 6.3.6).
/// Both sides hold FINAL (rename-applied) expression text, so the composed
/// text splices verbatim into any inlined body.
/// LRM 9.18 Table 9-29's *Allowed values* column, checked for an instance
/// override written as a plain numeric literal (round-3 audit -- the column
/// was unenforced on every route).
///
/// | parameter | allowed |
/// |---|---|
/// | `$mfactor` | `> 0` |
/// | `$hflip`, `$vflip` | `+1` or `-1` |
/// | `$angle` | any real; normalised to `0 <= $angle < 360` rather than refused |
/// | `$xposition`, `$yposition` | any |
///
/// `$mfactor` is the one that produces wrong numbers rather than a wrong
/// label: it drives the LRM 6.3.6 multiplicity transform, so a negative value
/// sign-inverts every flow contribution -- a plain resistor model measured
/// **+3 mA out** under `#(.$mfactor(-3))`, with no diagnostic anywhere. The
/// identical value written on the netlist line (`m=-3`) has been refused by
/// ngspice's own parameter setter all along; this closes the Verilog-A route
/// the same check never covered.
///
/// Only a literal is judged. An override built from a paramset card parameter
/// is not known until run time, which is the same boundary the constant-only
/// `sqrt` domain check draws, and stating it is better than guessing.
fn hsp_range_error(sys: ParamSysFun, text: &str) -> Option<String> {
    let val: f64 = text.trim().parse().ok()?;
    let bad = |allowed: &str| {
        Some(format!(
            "instance parameter '.{}' is set to {text}, which LRM 9.18 Table 9-29 does not \
             allow ({allowed})",
            sys.sysfun_text(),
        ))
    };
    match sys {
        ParamSysFun::mfactor if !(val > 0.0) => bad(
            "$mfactor > 0 -- a multiplicity is a count of devices in parallel: a \
             negative one sign-inverts every flow contribution the instance makes, \
             and zero is not a device. (The netlist spelling `m=0` is a separate, \
             deliberate SPICE idiom for disabling an instance; Table 9-29 governs \
             this one.)",
        ),
        ParamSysFun::hflip | ParamSysFun::vflip if val != 1.0 && val != -1.0 => {
            bad("$hflip and $vflip are +1 or -1 -- they say whether the instance is mirrored")
        }
        _ => None,
    }
}

fn merge_sys_overrides(
    outer: &[(ParamSysFun, String)],
    inner: &[(ParamSysFun, String)],
) -> Vec<(ParamSysFun, String)> {
    let mut out = outer.to_vec();
    for (sys, v) in inner {
        match out.iter_mut().find(|(s, _)| s == sys) {
            Some((_, existing)) => {
                let op = if sys.composes_multiplicatively() { '*' } else { '+' };
                *existing = format!("({existing}){op}({v})");
            }
            None => out.push((*sys, v.clone())),
        }
    }
    out
}

/// Builds the `render_with_holes` holes that apply a child instance's
/// hierarchical system parameter overrides (`#(.$mfactor(4))`, LRM 6.3.6)
/// to one of its `analog` blocks or functions.
///
/// Reads compose: every `$mfactor`-family SYSFUN token in the body is
/// replaced by `($mfactor*(<ov>))` (multiplicative) or `($xposition+(<ov>))`
/// (additive), so the child sees the effective value.
///
/// `$mfactor` additionally applies the standard multiplicity transform --
/// the child stands for `m` identical copies in parallel, solved as one:
/// every FLOW contribution's RHS is scaled by `m` (`<+ (m)*(...)`), every
/// flow PROBE is divided by `m` (reading the per-copy current back out of
/// the scaled system), and every noise call's amplitude is divided by
/// `sqrt(m)` (so a flow-contributed noise POWER scales by `m·` after the
/// RHS scaling, and a potential-contributed one by `1/m` -- both the
/// parallel-combination results). All edits are single-token holes
/// (the `<+` operator, the statement's `;`, a callee name, a closing
/// paren), so they never nest and the flat hole machinery applies them in
/// one pass. Probe references that must stay bare probes (`ddx`'s second
/// argument, `$limit`'s first) are exempted from the division.
///
/// Deliberately NOT handled: indirect contributions (`V(x): I(x) == 0`) and
/// noise calls routed through variables keep their unscaled form.
fn hier_sys_override_holes(
    item: &syntax::SyntaxNode,
    sys: &[(ParamSysFun, String)],
    flow_access: &HashSet<String>,
    excluded: &[Range<usize>],
) -> Vec<(Range<usize>, String)> {
    let base = item.text_range().start();
    let m_text =
        sys.iter().find(|(s, _)| *s == ParamSysFun::mfactor).map(|(_, v)| v.clone());
    let mut holes: Vec<(Range<usize>, String)> = Vec::new();

    let callee = |call: &ast::Call| -> Option<(String, Range<usize>)> {
        match call.function_ref()? {
            ast::FunctionRef::Path(p) => {
                let tok = p.as_raw_ident()?;
                Some((tok.text().to_string(), rel_range(base, tok.text_range())))
            }
            ast::FunctionRef::SysFun(s) => {
                let tok = s.sysfun_token()?;
                Some((tok.text().to_string(), rel_range(base, tok.text_range())))
            }
        }
    };

    if let Some(m) = &m_text {
        // flow contributions: `I(...) <+ rhs;` becomes `I(...) <+ (m)*(rhs);`
        let mut lhs_ranges: Vec<Range<usize>> = Vec::new();
        for node in item.descendants() {
            let Some(assign) = ast::Assign::cast(node) else { continue };
            if assign.op() != Some(ast::AssignOp::Contribute) {
                continue;
            }
            let Some(ast::Expr::Call(target)) = assign.lval() else { continue };
            lhs_ranges.push(rel_range(base, target.syntax().text_range()));
            let is_flow = callee(&target).is_some_and(|(n, _)| flow_access.contains(&n));
            if !is_flow {
                continue;
            }
            let op_tok = assign
                .syntax()
                .children_with_tokens()
                .filter_map(|el| el.into_token())
                .find(|t| t.kind() == syntax::SyntaxKind::CONTR);
            let semi = assign
                .syntax()
                .parent()
                .and_then(ast::AssignStmt::cast)
                .and_then(|s| s.semicolon_token());
            let (Some(op_tok), Some(semi)) = (op_tok, semi) else { continue };
            holes.push((rel_range(base, op_tok.text_range()), format!("<+ ({m})*(")));
            holes.push((rel_range(base, semi.text_range()), ");".to_owned()));
        }
        // probe references that must stay bare probes -- exempt from division
        let mut skip: Vec<Range<usize>> = Vec::new();
        for node in item.descendants() {
            let Some(call) = ast::Call::cast(node) else { continue };
            let Some((name, _)) = callee(&call) else { continue };
            let Some(args) = call.arg_list() else { continue };
            match name.as_str() {
                "ddx" => {
                    if let Some(arg) = args.args().nth(1) {
                        skip.push(rel_range(base, arg.syntax().text_range()));
                    }
                }
                "$limit" => {
                    if let Some(arg) = args.args().next() {
                        skip.push(rel_range(base, arg.syntax().text_range()));
                    }
                }
                _ => {}
            }
        }
        // flow probes divide by m; noise calls divide by sqrt(m)
        for node in item.descendants() {
            let Some(call) = ast::Call::cast(node) else { continue };
            let Some((name, name_range)) = callee(&call) else { continue };
            let Some(rp) = call.arg_list().and_then(|a| a.r_paren_token()) else { continue };
            let range = rel_range(base, call.syntax().text_range());
            // a call the LRM 5.6.8.1 hierarchical-contribution transform
            // already rewrote holds holes of its own; leave it alone
            if excluded.iter().any(|r| *r == range) {
                continue;
            }
            let is_noise = matches!(
                name.as_str(),
                "white_noise" | "flicker_noise" | "noise_table" | "noise_table_log"
            );
            let is_flow_probe = flow_access.contains(&name)
                && !lhs_ranges.contains(&range)
                && !skip.iter().any(|s| s.start <= range.start && range.end <= s.end);
            let divisor = match (is_flow_probe, is_noise) {
                (true, _) => format!(")/({m}))"),
                (_, true) => format!(")/sqrt({m}))"),
                _ => continue,
            };
            holes.push((name_range, format!("({name}")));
            holes.push((rel_range(base, rp.text_range()), divisor));
        }
    }

    // reads of every overridden system parameter compose with the outer value
    for el in item.descendants_with_tokens() {
        let Some(tok) = el.into_token() else { continue };
        if tok.kind() != syntax::SyntaxKind::SYSFUN {
            continue;
        }
        let Some(sys_fn) = ParamSysFun::from_sysfun_text(tok.text()) else { continue };
        let Some((_, v)) = sys.iter().find(|(s, _)| *s == sys_fn) else { continue };
        let op = if sys_fn.composes_multiplicatively() { '*' } else { '+' };
        let composed = format!("({}{op}({v}))", tok.text());
        // LRM 9.18 Table 9-29 (round-3 audit): `$angle` composes as a sum
        // "modulo 360 degrees", with the allowed range 0 <= $angle < 360.
        // `x - 360*floor(x/360)` is the non-negative remainder, and it is the
        // one form that stays correct for a negative composed angle.
        // `merge_sys_overrides` has already folded every enclosing instance's
        // override into `v`, so this hole is applied once per read and the
        // text is duplicated once, not per hierarchy level.
        let composed = if sys_fn == ParamSysFun::angle {
            format!("(({composed}) - 360.0*floor(({composed})/360.0))")
        } else {
            composed
        };
        holes.push((rel_range(base, tok.text_range()), composed));
    }
    holes.sort_by_key(|(r, _)| r.start);
    holes
}

/// Rewrites `$param_given(<name>)` calls whose argument is in `given` --
/// the FINAL flattened names of parameters overridden from inside the
/// Verilog-A hierarchy (instance `#(...)` values and applied `defparam`
/// targets) -- to the literal `(1)`: LRM 6.3.5/9.19, such a parameter IS
/// given, but compile-time flattening bakes the override in as the new
/// default, which OSDI would report as "not given". Same textual post-pass
/// shape as `resolve_port_connected` below.
fn resolve_param_given(body: &str, given: &HashSet<String>) -> String {
    const NEEDLE: &str = "$param_given";
    if given.is_empty() || !body.contains(NEEDLE) {
        return body.to_string();
    }
    let is_ident_char = |c: char| c.is_ascii_alphanumeric() || c == '_' || c == '$';
    let mut out = String::with_capacity(body.len());
    let mut rest = body;
    while let Some(pos) = rest.find(NEEDLE) {
        let after = &rest[pos + NEEDLE.len()..];
        let open = after.trim_start();
        let replacement = open.strip_prefix('(').and_then(|inner| {
            let inner = inner.trim_start();
            let end = inner.find(|c: char| !is_ident_char(c)).unwrap_or(inner.len());
            let ident = &inner[..end];
            let close = inner[end..].trim_start().strip_prefix(')')?;
            given.contains(ident).then_some(("(1)", close))
        });
        match replacement {
            Some((lit, remainder)) => {
                out.push_str(&rest[..pos]);
                out.push_str(lit);
                rest = remainder;
            }
            None => {
                out.push_str(&rest[..pos + NEEDLE.len()]);
                rest = after;
            }
        }
    }
    out.push_str(rest);
    out
}

/// Rewrites `$port_connected(<name>)` calls in an already-rendered instance
/// body to the literal `(1)`/`(0)` recorded for `<name>` in `conn` (keyed by
/// the RENDERED argument name — see the call site). Calls whose argument is
/// not in the map (bit-selects, expressions, ports of a nested not-yet-
/// rendered instance) are left untouched.
fn resolve_port_connected(body: &str, conn: &HashMap<String, bool>) -> String {
    const NEEDLE: &str = "$port_connected";
    if conn.is_empty() || !body.contains(NEEDLE) {
        return body.to_string();
    }
    let is_ident_char = |c: char| c.is_ascii_alphanumeric() || c == '_' || c == '$';
    let mut out = String::with_capacity(body.len());
    let mut rest = body;
    while let Some(pos) = rest.find(NEEDLE) {
        let after = &rest[pos + NEEDLE.len()..];
        // Parse `( <ident> )` directly after the needle, tolerating spaces.
        let open = after.trim_start();
        let replacement = open.strip_prefix('(').and_then(|inner| {
            let inner = inner.trim_start();
            let end = inner.find(|c: char| !is_ident_char(c)).unwrap_or(inner.len());
            let ident = &inner[..end];
            let close = inner[end..].trim_start().strip_prefix(')')?;
            conn.get(ident).map(|&c| (if c { "(1)" } else { "(0)" }, close))
        });
        match replacement {
            Some((lit, remainder)) => {
                out.push_str(&rest[..pos]);
                out.push_str(lit);
                rest = remainder;
            }
            None => {
                out.push_str(&rest[..pos + NEEDLE.len()]);
                rest = after;
            }
        }
    }
    out.push_str(rest);
    out
}

/// Enhancement-41: returns the trimmed text if it is a plain scalar identifier
/// (a candidate for an implicit net) — letters/digits/`_`/`$`, not starting
/// with a digit. Anything else (bit-selects, expressions, literals) is not.
fn as_plain_ident(text: &str) -> Option<&str> {
    let t = text.trim();
    let mut chars = t.chars();
    let first = chars.next()?;
    if !(first.is_ascii_alphabetic() || first == '_') {
        return None;
    }
    if !chars.all(|c| c.is_ascii_alphanumeric() || c == '_' || c == '$') {
        return None;
    }
    Some(t)
}

/// Enhancement-41: every identifier the module itself declares (net/port base
/// names, bus/array base names, parameters, variables, branches, functions,
/// instance names) — a plain-identifier port connection naming NONE of these
/// is an implicit net.
fn declared_names(module: &TreeModule, tree: &ItemTree) -> HashSet<String> {
    let base = |name: &Name| {
        let s = name.to_string();
        match s.find('[') {
            Some(i) => s[..i].to_string(),
            None => s,
        }
    };
    let mut names: HashSet<String> = module.nodes.iter().map(|n| base(&n.name)).collect();
    names.extend(module.buses.iter().chain(module.var_arrays.iter()).map(|b| b.base_name.to_string()));
    for item in &module.items {
        match *item {
            ModuleItem::Parameter(id) => {
                names.insert(tree[id].name.to_string());
            }
            ModuleItem::AliasParameter(id) => {
                names.insert(tree[id].name.to_string());
            }
            ModuleItem::Variable(id) => {
                names.insert(tree[id].name.to_string());
            }
            ModuleItem::Branch(id) => {
                names.insert(tree[id].name.to_string());
            }
            ModuleItem::Function(id) => {
                names.insert(tree[id].name.to_string());
            }
            ModuleItem::Instantiation(id) => {
                names.insert(base(&tree[id].name));
            }
            ModuleItem::Scope(_) | ModuleItem::Node(_) => (),
        }
    }
    names
}

/// A binding for one syntactic port: either a single resolved net
/// (scalar port), or one resolved net per bit (bus port).
#[derive(Clone)]
enum PortBinding {
    Scalar(String),
    Bus(BTreeMap<i32, String>),
}

/// The full renaming/binding context for rendering one module's body:
/// `subst` covers ordinary whole-identifier renames (nets, vars, params,
/// bus *base* names, ...); `bus_ports` covers bus-typed ports, which need
/// the token-sequence-aware substitution described in this module's doc
/// comment instead.
/// Enhancement-86 absolute-hierarchical-reference prefixes (`<top>`, `<top>.<chain>`)
/// -- the SAME for every inlined instance of one top-module flatten. Shared via `Rc`
/// (see `Scope::abs`) instead of being cloned into each instance's `inst_prefixes`,
/// which made flattening O(N^2) in the instance count (a `u[0:N]` array or generate
/// loop hung the compiler). `ancestors` is the precomputed set of every proper "a.b"
/// prefix of `map`'s keys, so `find_instance_path_holes`' ancestor test is O(1).
#[derive(Default)]
struct AbsPrefixes {
    map: HashMap<String, String>,
    ancestors: HashSet<String>,
}

impl AbsPrefixes {
    fn new(map: HashMap<String, String>) -> Self {
        let ancestors = build_ancestors(&map);
        AbsPrefixes { map, ancestors }
    }
}

/// Every proper "a.b" prefix of the keys (so "a.b.c" contributes "a" and "a.b"):
/// membership answers "does some key start with `x.`?" in O(1).
fn build_ancestors(prefixes: &HashMap<String, String>) -> HashSet<String> {
    let mut set = HashSet::new();
    for key in prefixes.keys() {
        let mut idx = 0;
        while let Some(dot) = key[idx..].find('.') {
            set.insert(key[..idx + dot].to_owned());
            idx += dot + 1;
        }
    }
    set
}

#[derive(Clone, Default)]
struct Scope {
    subst: HashMap<String, String>,
    bus_ports: HashMap<Name, BTreeMap<i32, String>>,
    /// Enhancement-49: every reachable instance chain from this scope
    /// (`"u1"`, `"u1.u2"`, `"u1[2]"`, ...) mapped to the composed flattening
    /// prefix of that instance's locals -- used to rewrite hierarchical
    /// references (`V(u1.m)`, `u1.r`) to the flattened names (`u1__m`).
    inst_prefixes: HashMap<String, String>,
    /// Enhancement-86 absolute prefixes, shared (not cloned) across every instance
    /// of the current top-module flatten -- see `AbsPrefixes`.
    abs: Rc<AbsPrefixes>,
}

/// Tries to constant-fold a `[msb:lsb]` instance-array range, mirroring
/// `hir_def::item_tree::lower::fold_width_range` (private to that crate).
fn fold_width_range(range: &ast::Range) -> Option<(i32, i32)> {
    let msb = range.start()?.as_constexprval()?;
    let lsb = range.end()?.as_constexprval()?;
    match (msb, lsb) {
        (ConstExprValue::Int(msb), ConstExprValue::Int(lsb)) => Some((msb, lsb)),
        _ => None,
    }
}

fn is_trivia(kind: TokenKind) -> bool {
    matches!(kind, TokenKind::Whitespace | TokenKind::LineComment | TokenKind::BlockComment { .. })
}

/// Scans `text` for `ident '[' int_literal ']'` token sequences where
/// `ident` names a bus port in `bus_ports`, producing one hole per match
/// that replaces the *entire* sequence with the resolved per-bit text (see
/// this module's doc comment for why a bus port can't use plain
/// whole-identifier substitution). A bus port reference with no matching
/// bit entry, or not immediately followed by a bit-select, is left alone
/// (degrading to a plain, unresolved identifier -- the same graceful
/// "downstream diagnostic instead of a crash" fallback used elsewhere in
/// this pass).
/// Enhancement-49: finds hierarchical instance-path references (`u1.m`,
/// `u1.u2.x`, `u1[2].m`, optionally behind `$root.<top>.` / `<top>.`) in raw
/// module text and produces holes replacing them with the flattened
/// (prefix-composed) names. The longest matching instance chain wins; exactly
/// one member identifier is taken after the chain (a member followed by
/// another `.` -- e.g. a block inside the child -- is left untouched for
/// name resolution to diagnose). Bus selects after the member stay in place
/// (`u1.b[2]` -> `u1__b[2]`).

/// Enhancement-86: finds `<chain>.branch(<port>)` port-branch probes in raw
/// module text, resolving `<chain>` (with an optional `$root.` opener and
/// `[int]` instance-array segments) through `prefixes`. Returns the resolved
/// instance prefix and the port name for each hit, so
/// `render_instance_content` synthesizes the matching 0V ammeter.
fn find_port_branch_probes(
    text: &str,
    prefixes: &HashMap<String, String>,
) -> Vec<(String, String)> {
    let mut spans = Vec::new();
    let mut pos = 0usize;
    for tok in lexer::tokenize(text) {
        let start = pos;
        let end = pos + usize::from(tok.len);
        pos = end;
        spans.push((start, end, tok.kind));
    }
    let next_sig = |mut j: usize| {
        while j < spans.len() && is_trivia(spans[j].2) {
            j += 1;
        }
        j
    };
    let prev_sig = |j: usize| -> Option<usize> {
        let mut j = j.checked_sub(1)?;
        while is_trivia(spans[j].2) {
            j = j.checked_sub(1)?;
        }
        Some(j)
    };
    let txt = |j: usize| &text[spans[j].0..spans[j].1];

    let mut out = Vec::new();
    for i in 0..spans.len() {
        if spans[i].2 != TokenKind::SimpleIdent || txt(i) != "branch" {
            continue;
        }
        // `. branch ( < port > )`
        let Some(dot) = prev_sig(i) else { continue };
        if spans[dot].2 != TokenKind::Dot {
            continue;
        }
        let op = next_sig(i + 1);
        if spans.get(op).map(|s| s.2) != Some(TokenKind::OpenParen) {
            continue;
        }
        let lt = next_sig(op + 1);
        if spans.get(lt).map(|s| s.2) != Some(TokenKind::Lt) {
            continue;
        }
        let pid = next_sig(lt + 1);
        if spans.get(pid).map(|s| s.2) != Some(TokenKind::SimpleIdent) {
            continue;
        }
        let gt = next_sig(pid + 1);
        if spans.get(gt).map(|s| s.2) != Some(TokenKind::Gt) {
            continue;
        }
        let cp = next_sig(gt + 1);
        if spans.get(cp).map(|s| s.2) != Some(TokenKind::CloseParen) {
            continue;
        }
        let port = txt(pid).to_owned();

        // walk LEFT from the dot collecting `ident` / `ident[int]` segments
        let mut segs: Vec<String> = Vec::new();
        let mut cursor = dot;
        loop {
            let Some(seg_end) = prev_sig(cursor) else { break };
            let seg = if spans[seg_end].2 == TokenKind::CloseBracket {
                let Some(litj) = prev_sig(seg_end) else { break };
                let Some(obj) = prev_sig(litj) else { break };
                let Some(idj) = prev_sig(obj) else { break };
                if !matches!(spans[litj].2, TokenKind::Literal { .. })
                    || spans[obj].2 != TokenKind::OpenBracket
                    || spans[idj].2 != TokenKind::SimpleIdent
                {
                    break;
                }
                cursor = idj;
                format!("{}[{}]", txt(idj), txt(litj))
            } else if spans[seg_end].2 == TokenKind::SimpleIdent {
                cursor = seg_end;
                txt(seg_end).to_owned()
            } else if spans[seg_end].2 == TokenKind::SystemCallIdent && txt(seg_end) == "$root" {
                segs.push("$root".to_owned());
                break;
            } else {
                break;
            };
            segs.push(seg);
            let Some(dj) = prev_sig(cursor) else { break };
            if spans[dj].2 != TokenKind::Dot {
                break;
            }
            cursor = dj;
        }
        segs.reverse();
        if segs.is_empty() {
            continue;
        }
        if segs.first().map(String::as_str) == Some("$root") {
            segs.remove(0);
        }
        let chain = segs.join(".");
        if let Some(prefix) = prefixes.get(&chain) {
            out.push((prefix.clone(), port));
        }
    }
    out
}

fn find_instance_path_holes(
    text: &str,
    inst_prefixes: &HashMap<String, String>,
    abs: &AbsPrefixes,
) -> Vec<(Range<usize>, String)> {
    if inst_prefixes.is_empty() && abs.map.is_empty() {
        return Vec::new();
    }
    // Every instance-path reference (`u1.m`, `$root.top.x`, `u[0].branch(..)`) contains
    // a '.', so text with none has no path holes at all. Bailing here is what keeps the
    // whole pass linear: `resolve_port_bindings` runs `apply_rename` (hence this) once
    // PER instance-array element over the (dot-free) port-connection text.
    if !text.contains('.') {
        return Vec::new();
    }
    // A chain key / ancestor is looked up in this scope's OWN prefixes (small -- built
    // per call) and the shared Enhancement-86 absolute prefixes (whose ancestor set is
    // precomputed ONCE in `AbsPrefixes`). Both are O(1) lookups -- scanning all keys, or
    // rebuilding the absolute ancestor set per call, made flattening O(N^2) in the count.
    let inst_ancestors = build_ancestors(inst_prefixes);
    let is_chain_key = |c: &str| inst_prefixes.contains_key(c) || abs.map.contains_key(c);
    let has_descendant = |c: &str| inst_ancestors.contains(c) || abs.ancestors.contains(c);
    let mut spans = Vec::new();
    let mut pos = 0usize;
    for tok in lexer::tokenize(text) {
        let start = pos;
        let end = pos + usize::from(tok.len);
        pos = end;
        spans.push((start, end, tok.kind));
    }
    let next_sig = |mut j: usize| {
        while j < spans.len() && is_trivia(spans[j].2) {
            j += 1;
        }
        j
    };
    // reads one path segment at spans[i]: `ident` or `ident [ int ]`;
    // returns (segment text, index just past it)
    let read_segment = |i: usize| -> Option<(String, usize)> {
        let (start, end, kind) = *spans.get(i)?;
        if kind != TokenKind::SimpleIdent {
            return None;
        }
        let mut seg = text[start..end].to_owned();
        let j = next_sig(i + 1);
        if spans.get(j).map(|s| s.2) == Some(TokenKind::OpenBracket) {
            let k = next_sig(j + 1);
            if let Some(&(ls, le, TokenKind::Literal { .. })) = spans.get(k) {
                if let Ok(idx) = text[ls..le].parse::<i32>() {
                    let m = next_sig(k + 1);
                    if spans.get(m).map(|s| s.2) == Some(TokenKind::CloseBracket) {
                        // only treat `[int]` as part of the segment when the
                        // combined name is a known instance chain element
                        // (otherwise it is an ordinary bus select)
                        let candidate = format!("{seg}[{idx}]");
                        if is_chain_key(&candidate) || has_descendant(&candidate) {
                            seg = candidate;
                            return Some((seg, m + 1));
                        }
                    }
                }
            }
        }
        Some((seg, i + 1))
    };

    let mut holes: Vec<(Range<usize>, String)> = Vec::new();
    let mut i = 0usize;
    while i < spans.len() {
        let (start, _end, kind) = spans[i];
        // optional `$root .` opener (the top-module alias entry in
        // `inst_prefixes` then absorbs the following `<top> .` segment)
        let (chain_start_idx, root_skipped) = if kind == TokenKind::SystemCallIdent
            && &text[spans[i].0..spans[i].1] == "$root"
        {
            let j = next_sig(i + 1);
            if spans.get(j).map(|s| s.2) == Some(TokenKind::Dot) {
                (next_sig(j + 1), true)
            } else {
                i += 1;
                continue;
            }
        } else {
            (i, false)
        };

        let Some((first_seg, after_first)) = read_segment(chain_start_idx) else {
            i += 1;
            continue;
        };
        if !is_chain_key(&first_seg) && !has_descendant(&first_seg) {
            i += 1;
            continue;
        }

        // extend the chain greedily while `. <segment>` still names a chain
        let mut chain = first_seg;
        let mut cursor = after_first;
        loop {
            let j = next_sig(cursor);
            if spans.get(j).map(|s| s.2) != Some(TokenKind::Dot) {
                break;
            }
            let k = next_sig(j + 1);
            let Some((seg, after_seg)) = read_segment(k) else { break };
            let candidate = format!("{chain}.{seg}");
            if is_chain_key(&candidate) || has_descendant(&candidate) {
                chain = candidate;
                cursor = after_seg;
            } else {
                break;
            }
        }

        let Some(prefix) = inst_prefixes.get(&chain).or_else(|| abs.map.get(&chain)) else {
            i += 1;
            continue;
        };

        // exactly one member identifier after the chain
        let j = next_sig(cursor);
        if spans.get(j).map(|s| s.2) != Some(TokenKind::Dot) {
            i += 1;
            continue;
        }
        let k = next_sig(j + 1);
        let Some(&(ms, me, mkind)) = spans.get(k) else {
            i += 1;
            continue;
        };
        if !matches!(mkind, TokenKind::SimpleIdent | TokenKind::EscapedIdent) {
            i += 1;
            continue;
        }
        // Enhancement-86: `<chain>.branch(a, b)` / `<chain>.branch(a)` /
        // `<chain>.branch(<p>)` -- the LRM's unnamed-branch and port-branch
        // references into an instance. The net forms expand to the
        // prefixed net pair (V/I of the child's unnamed branch is exactly
        // V/I of the same flattened node pair); the port form names the
        // 0V ammeter `render_instance_content` synthesizes for it.
        if mkind == TokenKind::SimpleIdent && &text[ms..me] == "branch" {
            let op = next_sig(k + 1);
            if spans.get(op).map(|s| s.2) == Some(TokenKind::OpenParen) {
                let hole_start =
                    if root_skipped { start } else { spans[chain_start_idx].0 };
                let a = next_sig(op + 1);
                match spans.get(a).map(|s| s.2) {
                    Some(TokenKind::Lt) => {
                        let pid = next_sig(a + 1);
                        let gt = next_sig(pid + 1);
                        let cp = next_sig(gt + 1);
                        if spans.get(pid).map(|s| s.2) == Some(TokenKind::SimpleIdent)
                            && spans.get(gt).map(|s| s.2) == Some(TokenKind::Gt)
                            && spans.get(cp).map(|s| s.2) == Some(TokenKind::CloseParen)
                        {
                            let port = &text[spans[pid].0..spans[pid].1];
                            holes.push((
                                hole_start..spans[cp].1,
                                render_name(&format!("{prefix}pflow__{port}")),
                            ));
                            i = cp + 1;
                            continue;
                        }
                    }
                    Some(TokenKind::SimpleIdent) => {
                        let x = &text[spans[a].0..spans[a].1];
                        let q = next_sig(a + 1);
                        match spans.get(q).map(|s| s.2) {
                            Some(TokenKind::CloseParen) => {
                                holes.push((
                                    hole_start..spans[q].1,
                                    render_name(&format!("{prefix}{x}")),
                                ));
                                i = q + 1;
                                continue;
                            }
                            Some(TokenKind::Comma) => {
                                let yj = next_sig(q + 1);
                                let cp = next_sig(yj + 1);
                                if spans.get(yj).map(|s| s.2) == Some(TokenKind::SimpleIdent)
                                    && spans.get(cp).map(|s| s.2)
                                        == Some(TokenKind::CloseParen)
                                {
                                    let y = &text[spans[yj].0..spans[yj].1];
                                    holes.push((
                                        hole_start..spans[cp].1,
                                        format!(
                                            "{}, {}",
                                            render_name(&format!("{prefix}{x}")),
                                            render_name(&format!("{prefix}{y}"))
                                        ),
                                    ));
                                    i = cp + 1;
                                    continue;
                                }
                            }
                            _ => (),
                        }
                    }
                    _ => (),
                }
            }
            // malformed branch(...) tail: leave untouched
            i = k + 1;
            continue;
        }
        // a member followed by a further `.` (block/child scopes inside the
        // instance) is out of scope for the rewrite -- leave it untouched
        let m = next_sig(k + 1);
        if spans.get(m).map(|s| s.2) == Some(TokenKind::Dot) {
            i = m;
            continue;
        }
        let member = if mkind == TokenKind::EscapedIdent {
            text[ms + 1..me].to_owned()
        } else {
            text[ms..me].to_owned()
        };
        // a top-alias chain composes to an empty prefix, meaning the member
        // is the top module's own item -- rewrite drops the qualification
        let hole_start = if root_skipped { start } else { spans[chain_start_idx].0 };
        holes.push((hole_start..me, render_name(&format!("{prefix}{member}"))));
        i = k + 1;
    }
    holes
}

fn find_bus_port_holes(text: &str, bus_ports: &HashMap<Name, BTreeMap<i32, String>>) -> Vec<(Range<usize>, String)> {
    if bus_ports.is_empty() {
        return Vec::new();
    }
    let mut spans = Vec::new();
    let mut pos = 0usize;
    for tok in lexer::tokenize(text) {
        let start = pos;
        let end = pos + usize::from(tok.len);
        pos = end;
        spans.push((start, end, tok.kind));
    }

    let mut holes = Vec::new();
    let mut i = 0usize;
    while i < spans.len() {
        let (start, end, kind) = spans[i];
        if kind == TokenKind::SimpleIdent {
            if let Some(bits) = bus_ports.get(&Name::resolve(&text[start..end])) {
                let mut j = i + 1;
                while j < spans.len() && is_trivia(spans[j].2) {
                    j += 1;
                }
                if j < spans.len() && spans[j].2 == TokenKind::OpenBracket {
                    let mut k = j + 1;
                    while k < spans.len() && is_trivia(spans[k].2) {
                        k += 1;
                    }
                    if let Some(&(lit_start, lit_end, lit_kind)) = spans.get(k) {
                        if matches!(lit_kind, TokenKind::Literal { .. }) {
                            if let Ok(bit) = text[lit_start..lit_end].parse::<i32>() {
                                let mut m = k + 1;
                                while m < spans.len() && is_trivia(spans[m].2) {
                                    m += 1;
                                }
                                if let Some(&(bracket_start, bracket_end, TokenKind::CloseBracket)) = spans.get(m) {
                                    let _ = bracket_start;
                                    if let Some(replacement) = bits.get(&bit) {
                                        holes.push((start..bracket_end, replacement.clone()));
                                        i = m + 1;
                                        continue;
                                    }
                                }
                            }
                        }
                    }
                }
            }
        }
        i += 1;
    }
    holes
}

/// Rewrites `text`'s `SimpleIdent` tokens using `scope.subst` (exact
/// whole-token match only), while replacing each byte range in `holes`
/// (given relative to the start of `text`; combined with `scope`'s own
/// bus-port holes and sorted internally) with its associated *already
/// fully-resolved* replacement text verbatim -- tokens inside a hole are
/// never individually inspected/renamed, which is what makes composing
/// renamed scopes (an already-flattened nested instance's text, or a
/// parent-scope override expression) correct: opaque foreign text is never
/// accidentally re-renamed using the wrong scope's `subst`.
/// Renders a resolved name back into source text: a plain identifier verbatim,
/// anything else as an escaped identifier (`\name `, whitespace-terminated) --
/// needed when a substitution value (e.g. an instance-prefixed child local that
/// was declared escaped, `\n-1` -> `u1_n-1`) contains characters a plain
/// identifier cannot (Enhancement-46).
fn render_name(name: &str) -> String {
    let mut chars = name.chars();
    let plain = matches!(chars.next(), Some(c) if c.is_ascii_alphabetic() || c == '_')
        && chars.all(|c| c.is_ascii_alphanumeric() || c == '_' || c == '$');
    if plain {
        name.to_owned()
    } else {
        format!("\\{name} ")
    }
}

fn render_with_holes(text: &str, holes: &[(Range<usize>, String)], scope: &Scope) -> String {
    let mut all_holes = find_bus_port_holes(text, &scope.bus_ports);
    all_holes.extend(find_instance_path_holes(text, &scope.inst_prefixes, &scope.abs));
    all_holes.extend(holes.iter().cloned());
    all_holes.sort_by_key(|(r, _)| r.start);

    let tokens = lexer::tokenize(text);
    let mut out = String::with_capacity(text.len());
    let mut pos = 0usize;
    let mut holes = all_holes.iter().peekable();

    for tok in tokens {
        let start = pos;
        let end = pos + usize::from(tok.len);
        pos = end;

        if let Some((range, replacement)) = holes.peek() {
            if start >= range.start && start < range.end {
                if start == range.start {
                    out.push_str(replacement);
                }
                if end >= range.end {
                    holes.next();
                }
                continue;
            }
        }

        let raw = &text[start..end];
        if tok.kind == TokenKind::SimpleIdent {
            if let Some(replacement) = scope.subst.get(raw) {
                out.push_str(&render_name(replacement));
                continue;
            }
        } else if tok.kind == TokenKind::EscapedIdent {
            // an escaped identifier's resolved name drops the backslash
            // (Enhancement-46); the substituted value is re-escaped if needed
            if let Some(replacement) = scope.subst.get(&raw[1..]) {
                out.push_str(&render_name(replacement));
                continue;
            }
        }
        out.push_str(raw);
    }
    out
}

fn apply_rename(text: &str, scope: &Scope) -> String {
    render_with_holes(text, &[], scope)
}

fn rel_range(base: TextSize, range: TextRange) -> Range<usize> {
    let base: u32 = base.into();
    let start: u32 = range.start().into();
    let end: u32 = range.end().into();
    (start - base) as usize..(end - base) as usize
}

/// Finds a bus (net or variable array) declared in `scope` named exactly
/// `text` (trimmed) with exactly `width` bits -- the "is this port/array
/// actual meant to be sliced" check described in this module's doc
/// comment. Requiring an exact width match (rather than "wide enough")
/// keeps the heuristic conservative: a plain scalar net, or a bus of the
/// wrong width, is left alone (bound/broadcast verbatim) rather than
/// guessed at.
fn find_matching_caller_bus<'a>(scope: &'a TreeModule, text: &str, width: usize) -> Option<&'a BusDecl> {
    let name = Name::resolve(text.trim());
    scope.buses.iter().chain(scope.var_arrays.iter()).find(|b| {
        b.base_name == name && {
            let (lo, hi) = b.min_max();
            (hi - lo + 1) as usize == width
        }
    })
}


/// Parses a constant part-select actual `base[msb:lsb]` (integer-literal
/// bounds; Enhancement-85). Anything else -- plain nets, single bit-selects,
/// expressions, non-constant bounds -- returns None and follows the ordinary
/// binding path.
fn as_part_select(text: &str) -> Option<(&str, i32, i32)> {
    let text = text.trim();
    let open = text.find('[')?;
    let base = text[..open].trim_end();
    if base.is_empty() || !as_plain_ident(base).is_some() {
        return None;
    }
    let inner = text[open + 1..].strip_suffix(']')?;
    let (msb, lsb) = inner.split_once(':')?;
    Some((base, msb.trim().parse().ok()?, lsb.trim().parse().ok()?))
}

/// True if `caller` declares a bus (net or variable array) named `base`
/// whose declared range covers bits `lo..=hi` -- the validity check for a
/// part-select actual (Enhancement-85).
fn find_matching_caller_bus_covering(caller: &TreeModule, base: &str, lo: i32, hi: i32) -> bool {
    let name = Name::resolve(base);
    caller.buses.iter().chain(caller.var_arrays.iter()).any(|b| {
        b.base_name == name && {
            let (blo, bhi) = b.min_max();
            blo <= lo && hi <= bhi
        }
    })
}

/// Binds one syntactic port (`port_name`, in `target`) to `net_text` (raw,
/// as written in the instantiating module `caller`), producing either a
/// single scalar binding, or -- if `port_name` names a bus in `target` --
/// one binding per bit, sliced from a same-width bus named `net_text` in
/// `caller` (see `find_matching_caller_bus`). An actual that resolves to
/// no matching-width source for a multi-bit port is a size-mismatch error
/// (LRM 6.5.7.1: "The sizes of the ports and net need to match") -- it
/// used to be broadcast verbatim onto every bit as a best-effort fallback,
/// so a scalar net on a 2-bit port silently wired the same net to both
/// bits.
fn bind_port(
    result: &mut HashMap<Name, PortBinding>,
    target: &TreeModule,
    caller: &TreeModule,
    port_name: &Name,
    net_text: &str,
    errors: &mut Vec<String>,
) {
    let bus = target.buses.iter().chain(target.var_arrays.iter()).find(|b| &b.base_name == port_name);
    let Some(bus) = bus else {
        // A width-1 part-select onto a scalar port degrades to the single
        // bit-select it denotes (`in[2:2]` == `in[2]`); wider slices onto a
        // scalar port keep the raw text and fail downstream with the
        // ordinary unresolved-connection diagnostics.
        if let Some((base, msb, lsb)) = as_part_select(net_text) {
            if msb == lsb {
                result.insert(port_name.clone(), PortBinding::Scalar(format!("{base}[{msb}]")));
                return;
            }
        }
        result.insert(port_name.clone(), PortBinding::Scalar(net_text.to_string()));
        return;
    };

    let (lo, hi) = bus.min_max();
    let width = (hi - lo + 1) as usize;

    // Part-select actual `base[msb:lsb]` (Enhancement-85): slice those bits
    // of the caller's bus onto the port, ascending-to-ascending -- the same
    // bit-order convention the full-bus slicing below uses.
    if let Some((base, msb, lsb)) = as_part_select(net_text) {
        let (slo, shi) = if msb <= lsb { (msb, lsb) } else { (lsb, msb) };
        let slice_width = (shi - slo + 1) as usize;
        if slice_width == width && find_matching_caller_bus_covering(caller, base, slo, shi) {
            let mut bits = BTreeMap::new();
            for bit in lo..=hi {
                bits.insert(bit, format!("{base}[{}]", slo + (bit - lo)));
            }
            result.insert(port_name.clone(), PortBinding::Bus(bits));
            return;
        }
        // width mismatch / unknown base: fall through to the ordinary path,
        // whose size check below produces the diagnostic
    }

    let caller_bus = find_matching_caller_bus(caller, net_text, width);
    if caller_bus.is_none() && width > 1 {
        // A width-1 bus port still takes a scalar actual (sizes match); a
        // wider one must connect to something that actually has its width.
        errors.push(format!(
            "port '{port_name}' of module '{}' is {width} bits wide but its connection \
             '{}' is not a matching {width}-bit source in module '{}' (LRM 6.5.7.1: the \
             sizes of the port and the net shall match; connect a {width}-bit bus, a \
             matching part-select, or a '{{...}}' concatenation)",
            target.name,
            net_text.trim(),
            caller.name,
        ));
        return;
    }

    let mut bits = BTreeMap::new();
    for bit in lo..=hi {
        let text = match caller_bus {
            Some(caller_bus) => {
                let (caller_lo, _) = caller_bus.min_max();
                format!("{net_text}[{}]", caller_lo + (bit - lo))
            }
            None => net_text.to_string(),
        };
        bits.insert(bit, text);
    }
    result.insert(port_name.clone(), PortBinding::Bus(bits));
}

/// The module's syntactic port list, in true header-declaration order
/// (`module foo(p, n, bus);`), used for positional port-connection
/// matching. Reading this from the AST header (rather than reconstructing
/// order from `Module::nodes`) is necessary because a vectored port's
/// extra bits (beyond its first) are appended to `nodes` wherever their
/// `[msb:lsb]` width clause happens to be declared in the module body,
/// not kept adjacent to the port's original header position.
fn target_port_names(module_ast: &ast::ModuleDecl) -> Vec<Name> {
    let Some(ports) = module_ast.module_ports() else { return Vec::new() };
    ports
        .ports()
        .flat_map(|port| match port.kind() {
            ast::ModulePortKind::Name(name) => vec![name.as_name()],
            ast::ModulePortKind::PortDecl(decl) => decl.names().map(|n| n.as_name()).collect(),
        })
        .collect()
}

/// Runs `apply_rename` over every raw (unrenamed) text held in a
/// `PortBinding`/plain-`String` map, producing the fully-resolved form the
/// callee expects to receive (see `render_with_holes`'s "resolve, then
/// recurse" doc comment).
fn resolve_port_bindings(raw: HashMap<Name, PortBinding>, scope: &Scope) -> HashMap<Name, PortBinding> {
    raw.into_iter()
        .map(|(k, v)| {
            let v = match v {
                PortBinding::Scalar(text) => PortBinding::Scalar(apply_rename(&text, scope)),
                PortBinding::Bus(bits) => {
                    PortBinding::Bus(bits.into_iter().map(|(bit, text)| (bit, apply_rename(&text, scope))).collect())
                }
            };
            (k, v)
        })
        .collect()
}

impl ElabCtx<'_> {
    fn module_ast(&self, ast_id: AstId<ast::ModuleDecl>) -> ast::ModuleDecl {
        self.ast_id_map.get(ast_id).to_node(self.parse.tree().syntax())
    }

    /// Resolves an instantiation's port-connection list against the target
    /// module's declared ports, returning *raw, un-renamed* source text
    /// (the caller is responsible for running it through its own `Scope`
    /// before handing it further down -- see `resolve_port_bindings`).
    fn raw_port_bindings(
        &mut self,
        caller: &TreeModule,
        target: &TreeModule,
        target_ast: &ast::ModuleDecl,
        unit: &ast::InstanceUnit,
    ) -> HashMap<Name, PortBinding> {
        let mut result = HashMap::new();
        let Some(port_conns) = unit.port_conns() else { return result };
        let conns: Vec<_> = port_conns.port_conns().collect();
        let port_names = target_port_names(target_ast);

        // Enhancement-392: the connection list is CHECKED against the target's
        // declared ports. It used to be zipped positionally -- which silently
        // truncates, so a surplus actual was dropped and a missing one left the
        // port unconnected -- and named connections were bound without asking
        // whether the port exists. Both compiled clean, with no diagnostic, and
        // produced a device wired differently from what was written.
        //
        // Verilog-A creates IMPLICIT NETS (Enhancement-41), so a mistyped net name
        // can never be caught here -- it just becomes a new net. That makes
        // checking the things that CAN be checked, the arity and the port names,
        // matter more rather than less.
        let inst_name =
            unit.name().map(|n| n.syntax().text().to_string()).unwrap_or_else(|| "?".into());
        // Enhancement-395: the LRM forbids MIXING positional and named connections
        // in one instantiation. Both orders were accepted and the device came out
        // silently DISCONNECTED (every probe read 0), because the named branch
        // below simply ignores the dotless entries while the positional branch is
        // never taken.
        let n_named = conns.iter().filter(|c| c.dot_token().is_some()).count();
        if n_named != 0 && n_named != conns.len() {
            self.port_conn_errors.push(format!(
                "instance '{}' of module '{}' mixes positional and named port connections; \
                 use one form or the other",
                inst_name, target.name,
            ));
        }
        if conns.iter().all(|c| c.dot_token().is_none()) {
            if conns.len() != port_names.len() {
                self.port_conn_errors.push(format!(
                    "instance '{}' of module '{}' connects {} port(s) but '{}' declares {} ({})",
                    inst_name,
                    target.name,
                    conns.len(),
                    target.name,
                    port_names.len(),
                    port_names.iter().map(|n| n.to_string()).collect::<Vec<_>>().join(", "),
                ));
            }
            for (name, conn) in port_names.iter().zip(conns.iter()) {
                if let Some(net) = conn.net() {
                    self.bind_port_actual(&mut result, target, caller, name, &net);
                }
            }
        } else {
            // Enhancement-395: a port named twice was accepted and the LAST
            // binding silently won, leaving the earlier actual unconnected.
            let mut seen: Vec<Name> = Vec::with_capacity(conns.len());
            for conn in &conns {
                if let (Some(name), Some(net)) = (conn.name(), conn.net()) {
                    let pname = name.as_name();
                    if seen.contains(&pname) {
                        self.port_conn_errors.push(format!(
                            "instance '{}' connects port '.{}' more than once",
                            inst_name, pname,
                        ));
                        continue;
                    }
                    seen.push(pname.clone());
                    if !port_names.contains(&pname) {
                        self.port_conn_errors.push(format!(
                            "instance '{}' connects '.{}', which is not a port of module '{}' ({})",
                            inst_name,
                            pname,
                            target.name,
                            port_names.iter().map(|n| n.to_string()).collect::<Vec<_>>().join(", "),
                        ));
                        continue;
                    }
                    self.bind_port_actual(&mut result, target, caller, &pname, &net);
                }
            }
        }
        result
    }

    /// Enhancement-59: binds one port actual, dispatching a concatenation
    /// (`{a, c}` -- LRM 6.5 net concatenation in a port connection) to a
    /// per-bit expansion and everything else to the plain `bind_port` path.
    fn bind_port_actual(
        &mut self,
        result: &mut HashMap<Name, PortBinding>,
        target: &TreeModule,
        caller: &TreeModule,
        port_name: &Name,
        net: &ast::Expr,
    ) {
        if let ast::Expr::ConcatExpr(concat) = net {
            self.bind_port_concat(result, target, caller, port_name, concat);
        } else {
            bind_port(
                result,
                target,
                caller,
                port_name,
                &net.syntax().text().to_string(),
                &mut self.port_conn_errors,
            );
        }
    }

    /// Expands a concatenated port actual bit-by-bit onto a vectored port.
    /// Each concat element contributes either one bit (a scalar net, a
    /// bit-select, ...) or -- when it names a same-scope bus used whole --
    /// all of that bus's bits in ITS declared msb-to-lsb order. The
    /// resulting bit list maps onto the port in the PORT's declared
    /// msb-to-lsb order (leftmost concat element = port msb), so both
    /// `[1:0]` and `[0:1]` declaration styles connect as written. A bit
    /// count that doesn't match the port width is a hard error (collected
    /// in `port_conn_errors`; rendering itself has no error channel).
    fn bind_port_concat(
        &mut self,
        result: &mut HashMap<Name, PortBinding>,
        target: &TreeModule,
        caller: &TreeModule,
        port_name: &Name,
        concat: &ast::ConcatExpr,
    ) {
        // flatten the concat's elements into msb-first bit texts
        let mut bit_texts: Vec<String> = Vec::new();
        for elem in concat.exprs() {
            let text = elem.syntax().text().to_string().trim().to_string();
            let elem_name = Name::resolve(&text);
            let caller_bus =
                caller.buses.iter().chain(caller.var_arrays.iter()).find(|b| b.base_name == elem_name);
            match caller_bus {
                // a whole bus contributes every bit, msb first as declared
                Some(bus) => {
                    let step: i32 = if bus.msb >= bus.lsb { -1 } else { 1 };
                    let mut bit = bus.msb;
                    loop {
                        bit_texts.push(format!("{text}[{bit}]"));
                        if bit == bus.lsb {
                            break;
                        }
                        bit += step;
                    }
                }
                None => bit_texts.push(text),
            }
        }

        let bus = target.buses.iter().chain(target.var_arrays.iter()).find(|b| &b.base_name == port_name);
        let Some(bus) = bus else {
            // scalar port: a one-element concat is just that element
            if bit_texts.len() == 1 {
                result.insert(port_name.clone(), PortBinding::Scalar(bit_texts.pop().unwrap()));
            } else {
                self.port_conn_errors.push(format!(
                    "concatenation of {} nets is connected to scalar port '{}'",
                    bit_texts.len(),
                    port_name
                ));
            }
            return;
        };

        let (lo, hi) = bus.min_max();
        let width = (hi - lo + 1) as usize;
        if bit_texts.len() != width {
            self.port_conn_errors.push(format!(
                "concatenation connected to port '{}' has {} net(s) but the port is {} bits wide",
                port_name,
                bit_texts.len(),
                width
            ));
            return;
        }

        let mut bits = BTreeMap::new();
        let step: i32 = if bus.msb >= bus.lsb { -1 } else { 1 };
        let mut bit = bus.msb;
        for text in bit_texts {
            bits.insert(bit, text);
            bit += step;
        }
        result.insert(port_name.clone(), PortBinding::Bus(bits));
    }

    /// Same as `raw_port_bindings` but for `#(...)` parameter overrides.
    fn resolve_param_bindings(
        &mut self,
        target: &TreeModule,
        overrides: Option<ast::ParamOverrides>,
    ) -> (HashMap<Name, String>, Vec<(ParamSysFun, String)>) {
        let mut result = HashMap::new();
        let mut sys_overrides: Vec<(ParamSysFun, String)> = Vec::new();
        let Some(overrides) = overrides else { return (result, sys_overrides) };
        let assigns: Vec<_> = overrides.param_assigns().collect();
        // Book audit (paramsets): only an overridable parameter can be named --
        // not a `localparam`, and not a paramset twin's internal declarations
        // (its bound target parameters, and the `name$paramset` clones).
        let param_names: Vec<Name> = target
            .items
            .iter()
            .filter_map(|it| match it {
                ModuleItem::Parameter(p)
                    if !self.tree[*p].is_local && !self.tree[*p].name.to_string().contains('$') =>
                {
                    Some(self.tree[*p].name.clone())
                }
                _ => None,
            })
            .collect();
        // Book audit (paramsets), LRM 3.4.7: an `aliasparam` of the target may be
        // named in the override list in place of the parameter it aliases -- for
        // a module, and for a paramset (`rp #(.LL(3u))` with `aliasparam LL = LEN;`).
        let alias_src: HashMap<Name, Name> = target
            .items
            .iter()
            .filter_map(|it| match it {
                ModuleItem::AliasParameter(a) => {
                    let alias = &self.tree[*a];
                    let src = alias.src.as_ref()?;
                    (!src.is_root_path && src.segments.len() == 1)
                        .then(|| (alias.name.clone(), src.segments[0].clone()))
                }
                _ => None,
            })
            .collect();
        let resolve_alias = |mut name: Name| {
            for _ in 0..8 {
                match alias_src.get(&name) {
                    Some(src) => name = src.clone(),
                    None => break,
                }
            }
            name
        };

        // Enhancement-392: an override naming a parameter the target does not have
        // used to be accepted and silently DROPPED, so `#(.vth0(0.7))` with a
        // typo left the default in place while the model appeared to work. Both
        // `defparam` and ngspice's own `.model` card already reject the same
        // mistake ("defparam target(s) did not resolve" /
        // "unrecognized parameter (zz) - ignored"); this brings the instance
        // override into line with them.
        // A SYSTEM parameter override (`#(.$mfactor(2))`, LRM 6.3.6) is written
        // with a dot and a NAME wrapping a SYSFUN token (see `param_assign` in
        // the parser). It names nothing the target declares, so it is handled
        // first in the named branch below -- collected into `sys_overrides`
        // rather than checked against `param_names`. Keying "is this named?"
        // off the DOT keeps it out of the positional branch.
        let inst_of = format!("of module '{}'", target.name);
        // The LRM's parameter_value_assignment grammar (Syntax 6-2) makes the
        // list ALL-ordered or ALL-named; a mixed list used to bind only the
        // named half while the positional values were silently dropped (the
        // equivalent mixing for PORT connections was already rejected).
        let n_positional = assigns.iter().filter(|a| a.dot_token().is_none()).count();
        if n_positional != 0 && n_positional != assigns.len() {
            self.hier_param_errors.push(format!(
                "instance parameter overrides {} mix positional and named forms in one \
                 '#(...)' list; the LRM (6.3.2/6.3.3) allows one form or the other, not both",
                inst_of,
            ));
        }
        if assigns.iter().all(|a| a.dot_token().is_none()) {
            if assigns.len() > param_names.len() {
                self.hier_param_errors.push(format!(
                    "instance {} supplies {} positional parameter override(s) but '{}' declares {}",
                    inst_of,
                    assigns.len(),
                    target.name,
                    param_names.len(),
                ));
            }
            for (name, assign) in param_names.iter().zip(assigns.iter()) {
                if let Some(val) = assign.val() {
                    result.insert(name.clone(), val.syntax().text().to_string());
                }
            }
        } else {
            // Enhancement-395: the same parameter overridden twice
            // (`#(.g(1e-3), .g(5e-3))`) was accepted and the LAST value silently
            // won, so the result depended on the order the two were written.
            let mut seen_params: Vec<Name> = Vec::with_capacity(assigns.len());
            for assign in &assigns {
                // `.$mfactor(4)` / `.$xposition(...)`: a hierarchical system
                // parameter override (LRM 6.3.6). Collected separately -- it
                // binds no declared parameter; `render_instance_content`
                // applies it as the LRM's multiplicity/geometry transform.
                if let Some(tok) = assign.name().and_then(|n| n.sysfun_token()) {
                    match ParamSysFun::from_sysfun_text(tok.text()) {
                        Some(sys) => {
                            if sys_overrides.iter().any(|(s, _)| *s == sys) {
                                self.hier_param_errors.push(format!(
                                    "instance parameter '.{}' is overridden more than once",
                                    tok.text(),
                                ));
                            } else if let Some(val) = assign.val() {
                                let text = val.syntax().text().to_string();
                                if let Some(err) = hsp_range_error(sys, &text) {
                                    self.hier_param_errors.push(err);
                                } else {
                                    sys_overrides.push((sys, text));
                                }
                            }
                        }
                        None => self.hier_param_errors.push(format!(
                            "'.{}' names no overridable hierarchical system parameter; only \
                             $mfactor, $xposition, $yposition, $angle, $hflip and $vflip may \
                             be overridden on an instance (LRM 6.3.6)",
                            tok.text(),
                        )),
                    }
                    continue;
                }
                if let Some(nm) = assign.name() {
                    let pname = resolve_alias(nm.as_name());
                    if seen_params.contains(&pname) {
                        self.hier_param_errors.push(format!(
                            "instance parameter '.{}' is overridden more than once",
                            pname,
                        ));
                        continue;
                    }
                    seen_params.push(pname);
                }
                // Enhancement-87: a hierarchical override target
                // (`#(.blk.p(4))`, parsed as more than one NAME child) tries
                // to reach a block-scoped parameter, which is local to its
                // block. The LRM permits only a module-level parameter name
                // here (LRM 6.3.2 / the page-112 `// error` case).
                let names: Vec<_> = assign
                    .syntax()
                    .children()
                    .filter(|c| c.kind() == syntax::SyntaxKind::NAME)
                    .collect();
                if names.len() > 1 {
                    self.hier_param_errors.push(format!(
                        "instance parameter override '.{}' targets a hierarchical/block-scoped \
                         parameter, which cannot be overridden this way; only a module-level \
                         parameter of '{}' may be named in an instance parameter assignment",
                        names.iter().map(|n| n.text().to_string()).collect::<Vec<_>>().join("."),
                        target.name,
                    ));
                    continue;
                }
                if let (Some(name), Some(val)) = (assign.name(), assign.val()) {
                    let pname = resolve_alias(name.as_name());
                    // LRM 3.4.4/3.4.8: a whole ARRAY parameter may be overridden at
                    // instantiation with an assignment pattern of matching size
                    // (`leaf #(.cf('{9.0, 8.0, 7.0})) ...`). The item tree splits an
                    // array parameter into per-element scalars (`cf[0]`, ...), so the
                    // base name is not in `param_names` -- but the RENDERED module
                    // still declares the array with its `'{...}` default, and the
                    // default-replacement below keys on the base name, so binding the
                    // base name to the pattern text is all that is needed.
                    if !param_names.contains(&pname) {
                        if let Some(arr) =
                            target.param_arrays.iter().find(|b| b.base_name == pname)
                        {
                            // compare against the OUTERMOST dimension: a flat 1-D
                            // pattern lists that many elements, and a multi-dim
                            // pattern lists that many nested sub-patterns
                            let (msb, lsb) = arr.dims[0];
                            let want = ((msb - lsb).unsigned_abs() as usize) + 1;
                            let elems = ast::ArrayExpr::cast(val.syntax().clone())
                                .map(|a| a.syntax().children().count());
                            match elems {
                                Some(got) if got == want => {
                                    result.insert(pname, val.syntax().text().to_string());
                                }
                                Some(got) => {
                                    self.hier_param_errors.push(format!(
                                        "instance parameter override '.{}' supplies {} element(s) \
                                         but the array parameter has {} (LRM 3.4.4: the sizes \
                                         shall match)",
                                        pname, got, want,
                                    ));
                                }
                                None => {
                                    self.hier_param_errors.push(format!(
                                        "instance parameter override '.{}' targets an array \
                                         parameter; use an assignment pattern of {} element(s), \
                                         e.g. .{}('{{...}})",
                                        pname, want, pname,
                                    ));
                                }
                            }
                            continue;
                        }
                        // Book audit (paramsets), LRM 6.4: a parameter the paramset
                        // fixes is not the instance's to override
                        if target.paramset.is_some()
                            && target.items.iter().any(|it| matches!(it,
                                ModuleItem::Parameter(p) if self.tree[*p].name == pname))
                        {
                            self.hier_param_errors.push(format!(
                                "instance of paramset '{}' overrides '{}', which the paramset \
                                 fixes with `.{} = ...`; an instance may override only the \
                                 paramset's own parameters (LRM 6.4)",
                                target.name, pname, pname,
                            ));
                            continue;
                        }
                        self.hier_param_errors.push(format!(
                            "instance parameter override '.{}' names no parameter of module                              '{}'{}",
                            pname,
                            target.name,
                            if param_names.is_empty() {
                                ", which declares none".to_string()
                            } else {
                                format!(
                                    " (it declares {})",
                                    param_names
                                        .iter()
                                        .map(|n| n.to_string())
                                        .collect::<Vec<_>>()
                                        .join(", ")
                                )
                            },
                        ));
                        continue;
                    }
                    result.insert(pname, val.syntax().text().to_string());
                }
            }
        }
        (result, sys_overrides)
    }

    /// Book audit (paramsets), LRM 6.4.2: chooses, for one instance of an
    /// overloaded paramset name, the member of the family. The clause's rules,
    /// in order: every parameter the instance overrides is a parameter of the
    /// paramset (an alias counts); the paramset's own parameters, overridden or
    /// defaulted, lie within their declared ranges; its local parameters within
    /// theirs; the underlying module has every port the instance connects by
    /// name. Among the survivors: the fewest un-overridden parameters, then the
    /// most ranged local parameters, then the fewest unconnected ports; more
    /// than one left is an error, as is none. A value or a bound that is not a
    /// literal cannot be judged here and is taken as satisfied.
    fn select_paramset_overload(
        &mut self,
        members: &[ItemTreeId<TreeModule>],
        inst: &ast::Instantiation,
        _scope: &Scope,
    ) -> Result<ItemTreeId<TreeModule>, String> {
        let file = self.parse.tree();
        let family = self.tree[members[0]].name.to_string();
        // the instance's overrides: (name, folded value), positional as None names
        let mut named: Vec<(String, Option<f64>)> = Vec::new();
        let mut positional: Vec<Option<f64>> = Vec::new();
        if let Some(ov) = inst.param_overrides() {
            for a in ov.param_assigns() {
                let val = a.val().and_then(|v| const_real_of(&v));
                match a.name() {
                    Some(n) if a.dot_token().is_some() => {
                        if n.sysfun_token().is_some() {
                            continue;
                        }
                        named.push((n.as_name().to_string(), val));
                    }
                    _ => positional.push(val),
                }
            }
        }
        let connected: Vec<String> = inst
            .instance_units()
            .next()
            .and_then(|u| u.port_conns())
            .map(|pc| pc.port_conns().filter_map(|c| c.name().map(|n| n.as_name().to_string())).collect())
            .unwrap_or_default();
        let n_connected = inst
            .instance_units()
            .next()
            .and_then(|u| u.port_conns())
            .map(|pc| pc.port_conns().count())
            .unwrap_or(0);

        struct Cand {
            id: ItemTreeId<TreeModule>,
            ordinal: usize,
            unoverridden: usize,
            ranged_locals: usize,
            unconnected: usize,
        }
        let mut cands: Vec<Cand> = Vec::new();
        let mut rejected: Vec<String> = Vec::new();
        for (k, &id) in members.iter().enumerate() {
            let ordinal = k + 1;
            let Some(ps_ast) = self.tree[id].paramset else { continue };
            let ps = self.ast_id_map.get(ps_ast).to_node(file.syntax());
            // own parameters: (name, is_local, default, constraints)
            let mut own: Vec<(String, bool, Option<f64>, ast::Param)> = Vec::new();
            for pd in ps.param_decls() {
                let is_local = pd.localparam_token().is_some();
                for p in pd.paras() {
                    let Some(n) = p.name() else { continue };
                    let d = p.default().and_then(|e| const_real_of(&e));
                    own.push((n.syntax().text().to_string(), is_local, d, p));
                }
            }
            let alias: HashMap<String, String> = ps
                .alias_params()
                .filter_map(|a| {
                    let name = a.name()?.syntax().text().to_string();
                    let ast::ParamRef::Path(src) = a.src()? else { return None };
                    Some((name, src.as_raw_ident()?.text().to_owned()))
                })
                .collect();
            let resolve = |n: &str| alias.get(n).cloned().unwrap_or_else(|| n.to_owned());
            // rule 1
            let mut values: HashMap<String, Option<f64>> = HashMap::new();
            let mut ok = true;
            for (n, v) in &named {
                let n = resolve(n);
                if own.iter().any(|(o, local, ..)| *o == n && !local) {
                    values.insert(n, *v);
                } else {
                    rejected.push(format!("{family} #{ordinal}: '{n}' is not one of its parameters"));
                    ok = false;
                }
            }
            let non_local: Vec<&(String, bool, Option<f64>, ast::Param)> =
                own.iter().filter(|(_, local, ..)| !local).collect();
            if positional.len() > non_local.len() {
                rejected.push(format!(
                    "{family} #{ordinal}: {} positional overrides for {} parameters",
                    positional.len(),
                    non_local.len()
                ));
                ok = false;
            }
            for (v, (n, ..)) in positional.iter().zip(non_local.iter()) {
                values.insert(n.clone(), *v);
            }
            if !ok {
                continue;
            }
            // rules 2 and 3: every own parameter and local, at its value, within its ranges
            let mut ranged_locals = 0usize;
            for (n, local, default, p) in &own {
                if *local && p.constraints().next().is_some() {
                    ranged_locals += 1;
                }
                let value = values.get(n).copied().flatten().or(*default);
                let Some(value) = value else { continue };
                if let Some(bad) = constraints_reject(p, value) {
                    rejected.push(format!("{family} #{ordinal}: {n} = {value} is outside {bad}"));
                    ok = false;
                    break;
                }
            }
            if !ok {
                continue;
            }
            // rule 4: the module at the end of the chain has the connected ports
            let mut end = id;
            let mut guard = 0;
            while let Some(a) = self.tree[end].paramset {
                let decl = self.ast_id_map.get(a).to_node(file.syntax());
                let Some(next) = decl.target().and_then(|t| self.by_name.get(&t.as_name()).copied())
                else {
                    break;
                };
                end = next;
                guard += 1;
                if guard > 32 {
                    break;
                }
            }
            let ports: Vec<String> = self.tree[end]
                .nodes
                .iter()
                .filter(|n| n.is_port)
                .map(|n| n.name.to_string())
                .collect();
            if let Some(missing) = connected.iter().find(|c| !ports.contains(c)) {
                rejected.push(format!("{family} #{ordinal}: its module has no port '{missing}'"));
                continue;
            }
            let unoverridden = non_local.iter().filter(|(n, ..)| !values.contains_key(n)).count();
            let unconnected = ports.len().saturating_sub(n_connected);
            cands.push(Cand { id, ordinal, unoverridden, ranged_locals, unconnected });
        }
        if cands.is_empty() {
            return Err(format!(
                "no paramset '{family}' applies to instance '{}' (LRM 6.4.2): {}",
                inst.instance_units().next().and_then(|u| u.name()).map(|n| n.syntax().text().to_string()).unwrap_or_default(),
                rejected.join("; ")
            ));
        }
        let best_key = |c: &Cand| (c.unoverridden, usize::MAX - c.ranged_locals, c.unconnected);
        let best = cands.iter().map(best_key).min().unwrap();
        let winners: Vec<&Cand> = cands.iter().filter(|c| best_key(c) == best).collect();
        if winners.len() > 1 {
            return Err(format!(
                "paramset '{family}' is ambiguous for instance '{}' (LRM 6.4.2): members {} all apply \
                 with {} un-overridden parameter(s)",
                inst.instance_units().next().and_then(|u| u.name()).map(|n| n.syntax().text().to_string()).unwrap_or_default(),
                winners.iter().map(|c| format!("#{}", c.ordinal)).collect::<Vec<_>>().join(", "),
                best.0
            ));
        }
        Ok(winners[0].id)
    }

    /// Book audit (paramsets): composes one paramset level of an instantiated
    /// chain. `env` holds the values arriving from outside -- the instance's
    /// overrides for the outermost level, the outer paramset's `.x = e;` texts
    /// for an inner one -- keyed by this level's names. Each own parameter takes
    /// its `env` value or its default (a `localparam` always its default), earlier
    /// own names substituted textually; each `.x = e;` then yields the next
    /// level's value with this level's names substituted. An `env` entry this
    /// level does not declare passes through to the next (Enhancement-21's
    /// pass-through of an unbound module parameter), unless the level fixes that
    /// name itself, which is an error (LRM 6.4: "an instance of the paramset that
    /// attempts to override any of the other parameters of the underlying module
    /// would generate an error").
    fn compose_paramset_level(
        &mut self,
        ps: &ast::ParamsetDecl,
        ps_name: &Name,
        target_id: ItemTreeId<TreeModule>,
        mut env: HashMap<Name, String>,
    ) -> (PsLevel, HashMap<Name, String>, Vec<(ParamSysFun, String)>) {
        let mut values: HashMap<String, String> = HashMap::new();
        for pd in ps.param_decls() {
            let is_local = pd.localparam_token().is_some();
            for param in pd.paras() {
                let Some(name) = param.name() else { continue };
                let key = name.as_name();
                let default = param
                    .default()
                    .map(|d| d.syntax().text().to_string())
                    .unwrap_or_else(|| "0".to_owned());
                let val = match if is_local { None } else { env.remove(&key) } {
                    Some(v) => v,
                    None => substitute_paramset_text(&default, &values, &HashMap::new()),
                };
                values.insert(key.to_string(), format!("({val})"));
            }
        }
        // an alias of this level's own parameter, named by the instance
        for al in ps.alias_params() {
            let (Some(name), Some(ast::ParamRef::Path(src))) = (al.name(), al.src()) else {
                continue;
            };
            if let (Some(v), Some(src)) = (env.remove(&name.as_name()), src.as_raw_ident()) {
                values.insert(src.text().to_owned(), format!("({v})"));
            }
        }
        let target_vars: HashSet<String> = self.tree[target_id]
            .items
            .iter()
            .filter_map(|it| match it {
                ModuleItem::Variable(v) => Some(self.tree[*v].name.to_string()),
                _ => None,
            })
            .collect();
        let mut next: HashMap<Name, String> = HashMap::new();
        let mut level_sys: Vec<(ParamSysFun, String)> = Vec::new();
        let mut var_overrides: Vec<(String, String)> = Vec::new();
        for ov in ps.overrides() {
            let Some(name_ref) = ov.name() else { continue };
            let val = ov
                .val()
                .map(|v| substitute_paramset_text(&v.syntax().text().to_string(), &values, &HashMap::new()))
                .unwrap_or_default();
            if let Some(tok) = name_ref.sysfun_token() {
                if let Some(sys) = ParamSysFun::from_sysfun_text(tok.text()) {
                    level_sys.push((sys, val));
                }
                continue;
            }
            let name = name_ref.as_name();
            if target_vars.contains(&name.to_string()) {
                var_overrides.push((name.to_string(), val));
            } else {
                next.insert(name, format!("({val})"));
            }
        }
        for (k, v) in env {
            if next.contains_key(&k) {
                self.hier_param_errors.push(format!(
                    "instance of paramset '{ps_name}' overrides '{k}', which the paramset fixes \
                     with `.{k} = ...`; an instance may override only the paramset's own \
                     parameters (LRM 6.4)"
                ));
            } else {
                next.insert(k, v);
            }
        }
        let var_names: Vec<String> = ps
            .var_decls()
            .flat_map(|vd| vd.vars().filter_map(|v| v.name()).map(|n| n.syntax().text().to_string()).collect::<Vec<_>>())
            .collect();
        let level = PsLevel { decl: ps.clone(), values, var_names, var_overrides };
        (level, next, level_sys)
    }

    /// Builds the "flatten this module's own declarations, in order,
    /// expanding any nested instantiations" text shared by both top-level
    /// modules (`scope` empty, so nothing is renamed and nothing is
    /// overridden -- everything just passes through) and inlined instances
    /// (`scope` maps every locally-declared name to its prefixed/bound
    /// form).
    /// Enhancement-49: recursively collects every instance chain reachable
    /// from `module_id` (`"u1"`, `"u1.u2"`, `"u1[2]"`, ...) mapped to the
    /// composed flattening prefix of that instance's locals, rooted at
    /// `outer_prefix`. Drives the hierarchical-reference rewrite in
    /// `find_instance_path_holes`.
    fn collect_inst_prefixes(
        &self,
        module_id: ItemTreeId<TreeModule>,
        outer_prefix: &str,
        chain: &str,
        out: &mut HashMap<String, String>,
    ) {
        for item in &self.tree[module_id].items {
            let ModuleItem::Instantiation(id) = item else { continue };
            let inst = &self.tree[*id];
            let Some(&target) = self.by_name.get(&inst.module) else { continue };
            let name = inst.name.to_string();
            let base = match name.find('[') {
                Some(i) => name[..i].to_owned(),
                None => name.clone(),
            };
            let pfx = match inst.array_index {
                Some(i) => format!("{outer_prefix}{base}_{i}__"),
                None => format!("{outer_prefix}{base}__"),
            };
            let chain_key =
                if chain.is_empty() { name.clone() } else { format!("{chain}.{name}") };
            out.insert(chain_key.clone(), pfx.clone());
            self.collect_inst_prefixes(target, &pfx, &chain_key, out);
        }
    }

    /// Resolves a dotted instance path (`c1.c2.mid`) starting at `module`,
    /// walking instantiations by name, and answers whether the FINAL member
    /// is a net of the target module (`Some(true)`), one of its named
    /// branches (`Some(false)`), or neither/unresolvable (`None`).
    fn hier_member_is_net(
        &self,
        module: ItemTreeId<TreeModule>,
        path: &str,
    ) -> Option<bool> {
        let path = path.trim();
        let segs: Vec<&str> = path.split('.').collect();
        if segs.len() < 2 {
            return None;
        }
        let ident_ish = |s: &str| {
            !s.is_empty()
                && s.chars().all(|c| c.is_ascii_alphanumeric() || matches!(c, '_' | '$' | '[' | ']'))
        };
        if !segs.iter().all(|s| ident_ish(s)) {
            return None;
        }
        let mut cur = module;
        for seg in &segs[..segs.len() - 1] {
            let mut next = None;
            for item in &self.tree[cur].items {
                let ModuleItem::Instantiation(id) = item else { continue };
                let inst = &self.tree[*id];
                if inst.name.to_string() == *seg {
                    next = self.by_name.get(&inst.module).copied();
                    break;
                }
            }
            cur = next?;
        }
        let mem = segs[segs.len() - 1];
        let mem_base = mem.split('[').next().unwrap_or(mem);
        let m = &self.tree[cur];
        for item in &m.items {
            if let ModuleItem::Branch(id) = item {
                if self.tree[*id].name.to_string() == mem_base {
                    return Some(false);
                }
            }
        }
        // A PORT member is excluded: after flattening a port is renamed to
        // whatever net it is BOUND to, not to a prefixed name of its own, so
        // a hierarchical reference to it cannot resolve at all -- that is the
        // documented "hierarchical access to child port nets" gap, and the
        // ordinary rename path keeps its honest located error.
        let is_port_name = m.nodes.iter().any(|n| {
            n.is_port && n.name.to_string().split('[').next() == Some(mem_base)
        });
        if is_port_name {
            return None;
        }
        let is_net = m.nodes.iter().any(|n| {
            let s = n.name.to_string();
            s == mem || s.split('[').next() == Some(mem_base)
        }) || m.buses.iter().any(|b| b.base_name.to_string() == mem_base);
        is_net.then_some(true)
    }

    /// LRM 5.6.8.1 with 5.5.4 (behavior audit): a direct (or indirect)
    /// contribution whose target references a HIERARCHICAL net -- e.g.
    /// `V(p, c1.mid) <+ 0.5;` -- creates a NEW unnamed branch in the module
    /// containing the contribution, distinct from any branch the child
    /// itself has between the same nodes. The plain textual rewrite aliased
    /// `c1.mid` to the child's net, so the parent's contribution landed on
    /// the child's own unnamed branch: the potential/flow retention rule
    /// then discarded the child's flow contribution (warning L022 on fully
    /// legal code) and the child's probes of its branch read the merged
    /// current.
    ///
    /// The fix gives each such target its own NAMED branch -- named branches
    /// are distinct identities even over the same node pair -- by declaring
    /// `branch (<final args>) <prefix>__hierbrN;` and splicing the branch
    /// name over the call's argument list. Probes in the same module whose
    /// argument pair textually matches a contributed pair are aliased onto
    /// the same branch (same order directly, reversed order negated), which
    /// is 5.5.4's same-module-same-branch rule. Hierarchical references to a
    /// child's NAMED branch are left alone: 5.6.8.2 says those merge.
    ///
    /// Returns the holes plus the touched call ranges (so the `$mfactor`
    /// transform skips its probe wrapping there). Not handled: contributed
    /// and probed orders never seen together accumulate on two branches
    /// instead of one, probes textually preceding the module's only
    /// contribution in a LATER analog block keep the aliased-net read, and
    /// an aliased probe inside an `#(.$mfactor(n))` child skips the
    /// per-copy division.
    fn hier_contrib_holes(
        &self,
        item: &syntax::SyntaxNode,
        module: ItemTreeId<TreeModule>,
        scope: &Scope,
        prefix: &str,
        decls: &mut Vec<String>,
        branches: &mut HashMap<String, String>,
        pairs: &mut Vec<(Vec<String>, String)>,
    ) -> (Vec<(Range<usize>, String)>, Vec<Range<usize>>) {
        let base = item.text_range().start();
        let mut holes: Vec<(Range<usize>, String)> = Vec::new();
        let mut touched: Vec<Range<usize>> = Vec::new();

        let norm = |e: &ast::Expr| e.syntax().text().to_string().split_whitespace().collect::<String>();
        // (normalized raw arg texts, splice range over the argument list, final renamed args)
        let analyze = |call: &ast::Call| -> Option<(Vec<String>, Range<usize>, Vec<String>)> {
            let args: Vec<ast::Expr> = call.arg_list()?.args().collect();
            if args.is_empty() || args.len() > 2 {
                return None;
            }
            let mut any_hier = false;
            for arg in &args {
                let txt = arg.syntax().text().to_string();
                if txt.contains(".branch(") || txt.contains('<') {
                    return None;
                }
                if !find_instance_path_holes(&txt, &scope.inst_prefixes, &scope.abs).is_empty() {
                    // only a hierarchical NET reference creates the new branch;
                    // a child's named branch merges (5.6.8.2), and anything
                    // unresolvable keeps its existing diagnostics
                    if self.hier_member_is_net(module, txt.trim()) != Some(true) {
                        return None;
                    }
                    any_hier = true;
                }
            }
            if !any_hier {
                return None;
            }
            let splice = rel_range(
                base,
                TextRange::new(
                    args.first().unwrap().syntax().text_range().start(),
                    args.last().unwrap().syntax().text_range().end(),
                ),
            );
            let final_args: Vec<String> = args
                .iter()
                .map(|a| {
                    let t = a.syntax().text().to_string();
                    apply_rename(t.trim(), scope)
                })
                .collect();
            Some((args.iter().map(norm).collect(), splice, final_args))
        };

        // pass 1: contribution targets
        for node in item.descendants() {
            let Some(assign) = ast::Assign::cast(node) else { continue };
            if !matches!(
                assign.op(),
                Some(ast::AssignOp::Contribute | ast::AssignOp::IndirectBranch)
            ) {
                continue;
            }
            let Some(ast::Expr::Call(target)) = assign.lval() else { continue };
            let Some((raw, splice, final_args)) = analyze(&target) else { continue };
            let key = final_args.join(",");
            let name = match branches.get(&key) {
                Some(n) => n.clone(),
                None => {
                    let name = format!("{prefix}__hierbr{}", branches.len());
                    decls.push(format!(
                        "branch ({}) {}; // LRM 5.6.8.1 hierarchical-contribution branch",
                        final_args.join(", "),
                        name,
                    ));
                    branches.insert(key, name.clone());
                    name
                }
            };
            holes.push((splice, name.clone()));
            touched.push(rel_range(base, target.syntax().text_range()));
            if !pairs.iter().any(|(r, _)| *r == raw) {
                pairs.push((raw, name));
            }
        }
        if pairs.is_empty() {
            return (holes, touched);
        }

        // pass 2: probes of a contributed pair alias onto the same branch
        for node in item.descendants() {
            let Some(call) = ast::Call::cast(node) else { continue };
            let is_access = match call.function_ref() {
                Some(ast::FunctionRef::Path(p)) => p
                    .as_raw_ident()
                    .is_some_and(|t| self.access_names.contains(t.text())),
                _ => false,
            };
            if !is_access {
                continue;
            }
            let call_range = rel_range(base, call.syntax().text_range());
            if touched.iter().any(|r| *r == call_range) {
                continue; // a contribution target already rewritten above
            }
            let Some(args) = call.arg_list() else { continue };
            let probe_args: Vec<String> = args.args().map(|a| norm(&a)).collect();
            if probe_args.is_empty() || probe_args.len() > 2 {
                continue;
            }
            let matched = pairs.iter().find_map(|(raw, name)| {
                if *raw == probe_args {
                    Some((name.clone(), false))
                } else if raw.len() == 2
                    && probe_args.len() == 2
                    && raw[0] == probe_args[1]
                    && raw[1] == probe_args[0]
                {
                    Some((name.clone(), true))
                } else {
                    None
                }
            });
            let Some((name, reversed)) = matched else { continue };
            let access = call
                .function_ref()
                .and_then(|f| match f {
                    ast::FunctionRef::Path(p) => {
                        p.as_raw_ident().map(|t| t.text().to_string())
                    }
                    _ => None,
                })
                .unwrap_or_default();
            let replacement = if reversed {
                format!("(-{access}({name}))")
            } else {
                format!("{access}({name})")
            };
            holes.push((call_range.clone(), replacement));
            touched.push(call_range);
        }
        (holes, touched)
    }

    /// Enhancement-58: scan one module's `defparam` statements and record each
    /// as `flattened_target_name -> override_value_text`. The target path is
    /// resolved through the same instance-chain rewrite E-49 uses for ordinary
    /// hierarchical references (`find_instance_path_holes`): `u1.u2.r` becomes
    /// `u1__u2__r`, exactly the flattened name the target parameter is given
    /// when its instance is inlined; a single-segment target (a same-module
    /// parameter) resolves to itself. The value expression is rename-applied
    /// (it may reference the enclosing module's own parameters).
    fn collect_defparams(&mut self, module_ast: &ast::ModuleDecl, scope: &Scope) {
        for node in module_ast.syntax().children() {
            if node.kind() != syntax::SyntaxKind::DEFPARAM {
                continue;
            }
            // Direct children alternate: [target PATH, value expr, ...].
            let parts: Vec<_> = node.children().collect();
            let mut i = 0;
            while i + 1 < parts.len() {
                let path_node = &parts[i];
                let value_node = &parts[i + 1];
                i += 2;
                if path_node.kind() != syntax::SyntaxKind::PATH {
                    continue;
                }
                let path_text = path_node.text().to_string();
                let path_text = path_text.trim();
                // resolve the hierarchical target to its flattened name. A
                // `defparam` path is a single `chain.member`, so the rewrite
                // (when the chain resolves) yields exactly one hole whose
                // replacement is the flattened target name.
                let holes = find_instance_path_holes(path_text, &scope.inst_prefixes, &scope.abs);
                let flat = match holes.first() {
                    Some((_, repl)) => repl.clone(),
                    // single-segment (same-module) target, or a chain that did
                    // not resolve: use the (rename-applied) path as-is -- if it
                    // matches no parameter, the unresolved-target diagnostic fires
                    None => apply_rename(path_text, scope),
                };
                let value = apply_rename(&value_node.text().to_string(), scope);
                self.defparam_src.insert(flat.clone(), path_text.to_string());
                self.defparam_overrides.insert(flat, value);
            }
        }
    }

    fn render_items(
        &mut self,
        target_id: ItemTreeId<TreeModule>,
        scope: &Scope,
        param_binding: &HashMap<Name, String>,
        port_names: &HashSet<Name>,
        prefix: &str,
        sys_overrides: &[(ParamSysFun, String)],
    ) -> String {
        let target_ast = self.module_ast(self.tree[target_id].ast_id);
        // Enhancement-58: collect this module's `defparam` overrides before
        // rendering its items, so a `defparam` written after (or before) the
        // parameter it targets, and one targeting a nested instance, are both
        // seen when the target parameter's declaration is rendered.
        self.collect_defparams(&target_ast, scope);
        let mut out = String::new();
        // Enhancement-41: net declarations synthesised for implicit nets found in
        // this module's instantiation connections, prepended to the rendered body
        // so they precede every use.
        let mut implicit_decls = Vec::new();
        // LRM 5.6.8.1: named branches synthesised for hierarchical
        // contribution targets, shared across this module's analog blocks
        // (key: final renamed argument pair -> branch name).
        let mut hier_branches: HashMap<String, String> = HashMap::new();
        let mut hier_pairs: Vec<(Vec<String>, String)> = Vec::new();

        for item in target_ast.module_items() {
            match item {
                // A body port-direction declaration (`inout p, n;`) only
                // ever names ports; when inlining an instance its ports are
                // bound to already-declared outer identities (or a fresh
                // internal net), so re-declaring them as ports here would
                // collide with that outer declaration -- drop entirely.
                ast::ModuleItem::BodyPortDecl(_) if !port_names.is_empty() => continue,
                // Enhancement-86: a port-branch declaration (`branch (<p>)
                // pb;`) has no port to attach to once the instance is
                // flattened; its names alias the synthesized 0V ammeter (see
                // `render_instance_content`), so the declaration is dropped.
                ast::ModuleItem::BranchDecl(decl)
                    if !port_names.is_empty()
                        && matches!(
                            decl.branch_kind(),
                            Some(ast::BranchKind::PortFlow(_))
                        ) =>
                {
                    continue
                }
                ast::ModuleItem::Instantiation(nested) => {
                    out.push_str(&self.expand_instantiation(
                        target_id,
                        &nested,
                        scope,
                        prefix,
                        &mut implicit_decls,
                        sys_overrides,
                    ));
                }
                // An analog block gets the LRM 5.6.8.1 hierarchical-
                // contribution branch transform; a body under
                // `#(.$mfactor(n))`-family overrides additionally gets the
                // LRM 6.3.6 transform (reads compose; flow contributions,
                // probes and noise scale). Both splice in as holes.
                ref body @ (ast::ModuleItem::AnalogBehaviour(_) | ast::ModuleItem::Function(_)) => {
                    let node = body.syntax();
                    let mut holes = Vec::new();
                    let mut excluded = Vec::new();
                    if matches!(body, ast::ModuleItem::AnalogBehaviour(_)) {
                        let (h, ex) = self.hier_contrib_holes(
                            node,
                            target_id,
                            scope,
                            prefix,
                            &mut implicit_decls,
                            &mut hier_branches,
                            &mut hier_pairs,
                        );
                        holes.extend(h);
                        excluded = ex;
                    }
                    if !sys_overrides.is_empty() {
                        holes.extend(hier_sys_override_holes(
                            node,
                            sys_overrides,
                            &self.flow_access,
                            &excluded,
                        ));
                    }
                    if holes.is_empty() {
                        out.push_str(&apply_rename(&node.text().to_string(), scope));
                    } else {
                        holes.sort_by_key(|(r, _)| r.start);
                        out.push_str(&render_with_holes(&node.text().to_string(), &holes, scope));
                    }
                }
                ast::ModuleItem::ParamDecl(decl) => {
                    let base = decl.syntax().text_range().start();
                    let mut holes = Vec::new();
                    for param in decl.paras() {
                        let (Some(name), Some(default)) = (param.name(), param.default()) else {
                            continue;
                        };
                        // Enhancement-58: a `defparam` targeting this parameter's
                        // final flattened name wins over an instance `#(...)`
                        // override (LRM 2.6: defparam has highest precedence).
                        let flat = scope
                            .subst
                            .get(&name.to_string())
                            .cloned()
                            .unwrap_or_else(|| name.to_string());
                        let defparam = self.defparam_overrides.get(&flat).cloned();
                        if let Some(ov) = defparam {
                            holes.push((rel_range(base, default.syntax().text_range()), ov));
                            self.defparam_applied.insert(flat);
                        } else if let Some(bound) = param_binding.get(&name.as_name()) {
                            holes.push((rel_range(base, default.syntax().text_range()), bound.clone()));
                        }
                    }
                    out.push_str(&render_with_holes(&decl.syntax().text().to_string(), &holes, scope));
                }
                // A net/discipline declaration (`electrical p, n;`, or a
                // vectored `electrical [3:0] p, bus;`) may name a mix of
                // ports and ordinary internal nets/buses (both share this
                // syntax); same reasoning as `BodyPortDecl` above, but only
                // the port *names* need dropping from the list, not
                // necessarily the whole statement -- a bus-typed port is
                // dropped exactly like a scalar one (it's fully handled by
                // `render_instance_content`'s per-bit port binding; its own
                // `[msb:lsb]` declaration would just redeclare an identity
                // that already belongs to an outer/bound net).
                ast::ModuleItem::NetDecl(decl) if !port_names.is_empty() => {
                    // keep each surviving net's nodeset initializer
                    // (`electrical m = -1.0;`, Enhancement-45) -- initializers
                    // are numeric constants, so no renaming applies inside them
                    let kept: Vec<String> = decl
                        .declarators()
                        .into_iter()
                        .filter_map(|(n, init)| {
                            let name = n.as_name();
                            if port_names.contains(&name) {
                                None
                            } else {
                                let key = name.to_string();
                                let renamed =
                                    render_name(&scope.subst.get(&key).cloned().unwrap_or(key));
                                Some(match init {
                                    Some(e) => format!("{renamed} = {}", e.syntax().text()),
                                    None => renamed,
                                })
                            }
                        })
                        .collect();
                    if !kept.is_empty() {
                        let discipline = decl
                            .discipline()
                            .map(|d| d.syntax().text().to_string())
                            .unwrap_or_default();
                        // `ground gnd;` / `wire w;`-style declarations carry a
                        // net-type token instead of (or before) a discipline;
                        // dropping it rendered ` a1__gnd;` (Enhancement-86)
                        let net_type = decl
                            .net_type_token()
                            .map(|t| format!("{} ", t.text()))
                            .unwrap_or_default();
                        let width = decl
                            .width()
                            .map(|w| format!("{} ", w.syntax().text()))
                            .unwrap_or_default();
                        out.push_str(&format!(
                            "{net_type}{discipline} {width}{};",
                            kept.join(", ")
                        ));
                    }
                }
                other => out.push_str(&apply_rename(&other.syntax().text().to_string(), scope)),
            }
            out.push('\n');
        }
        if implicit_decls.is_empty() {
            out
        } else {
            format!("{}\n{}", implicit_decls.join("\n"), out)
        }
    }

    /// Expands one instantiation statement (all of its comma-separated
    /// `InstanceUnit`s, each possibly further expanded into several array
    /// elements) into final, ready-to-splice text. `parent_id` is the
    /// module the instantiation statement itself lives in -- needed both
    /// to resolve its own `buses`/`var_arrays` for the port-slicing
    /// heuristic (see this module's doc comment) and, for an instance
    /// array, to additionally slice a matching-width bus port actual
    /// per array element rather than broadcasting it to every element.
    fn expand_instantiation(
        &mut self,
        parent_id: ItemTreeId<TreeModule>,
        inst: &ast::Instantiation,
        scope: &Scope,
        prefix: &str,
        implicit_decls: &mut Vec<String>,
        inherited_sys: &[(ParamSysFun, String)],
    ) -> String {
        let Some(module_name) = inst.module().map(|n| n.as_name()) else { return String::new() };
        let Some(&target_id) = self.by_name.get(&module_name) else {
            let instances: Vec<_> = inst
                .instance_units()
                .filter_map(|u| u.name().map(|n| n.as_name().to_string()))
                .collect();
            // `electrical out[0:2];` parses as an instantiation of "module
            // electrical" -- when the unresolved name is a discipline, what
            // the user actually wrote is a name-then-range net declaration,
            // which deserves its own message (range-then-name works).
            let is_discipline =
                self.tree.data.disciplines.iter().any(|d| d.name == module_name);
            // A paramset whose target failed to resolve contributes no twin
            // module (see UnknownParamsetTarget), so an instantiation of it
            // lands here; say so instead of claiming the name doesn't exist.
            let is_dropped_paramset = self.parse.tree().items().any(|it| {
                matches!(&it, ast::Item::ParamsetDecl(ps)
                    if ps.name().map(|n| n.as_name()) == Some(module_name.clone()))
            });
            let msg = if is_discipline {
                format!(
                    "name-then-range bus declarations like '{} {}[msb:lsb];' are not \
                     supported; declare the range before the name: '{} [msb:lsb] {};'",
                    module_name,
                    instances.join("', '"),
                    module_name,
                    instances.join(", "),
                )
            } else if is_dropped_paramset {
                format!(
                    "instance '{}' instantiates paramset '{}', which was dropped because \
                     its target module could not be resolved",
                    instances.join("', '"),
                    module_name,
                )
            } else {
                format!(
                    "instance '{}' refers to module '{}', which is not defined anywhere \
                     in this compilation unit",
                    instances.join("', '"),
                    module_name,
                )
            };
            self.unknown_module_errors.push(msg);
            return String::new();
        };
        // Book audit (paramsets): an instance of a paramset is an instance of the
        // module at the end of its chain, with the module's parameters bound by
        // the paramsets' `.x = e;` statements -- each level's own parameters
        // taking the instance's override or their default -- and the paramsets'
        // variables and statements appended to the flattened body (LRM 6.4,
        // 6.4.1, 6.4.3). Enhancement-21's twin served the netlist route only:
        // an instance rendered the target module's text, so the bindings were
        // lost and the instance ran at the module's defaults.
        let mut target_id = target_id;
        // Book audit (paramsets), LRM 6.4.2: the name may head an overloaded
        // family; select the member for this instance
        if self.tree[target_id].paramset.is_some() {
            let members: Vec<ItemTreeId<TreeModule>> = self
                .tree
                .data
                .modules
                .iter_enumerated()
                .filter(|(id, m)| {
                    *id == target_id || m.overload_family.as_ref() == Some(&module_name)
                })
                .map(|(id, _)| id)
                .collect();
            if members.len() > 1 {
                match self.select_paramset_overload(&members, inst, scope) {
                    Ok(id) => target_id = id,
                    Err(msg) => {
                        self.hier_param_errors.push(msg);
                        return String::new();
                    }
                }
            }
        }
        let mut ps_levels: Vec<PsLevel> = Vec::new();
        let (param_raw, sys_raw) = if self.tree[target_id].paramset.is_some() {
            let twin = self.tree[target_id].clone();
            let (mut env, mut sys) = self.resolve_param_bindings(&twin, inst.param_overrides());
            let file = self.parse.tree();
            while let Some(ps_ast) = self.tree[target_id].paramset {
                let ps = self.ast_id_map.get(ps_ast).to_node(file.syntax());
                let ps_name = self.tree[target_id].name.clone();
                let Some(next) = ps.target().and_then(|t| self.by_name.get(&t.as_name()).copied())
                else {
                    break;
                };
                let (level, next_env, level_sys) =
                    self.compose_paramset_level(&ps, &ps_name, next, env);
                sys = merge_sys_overrides(&sys, &level_sys);
                ps_levels.push(level);
                env = next_env;
                target_id = next;
            }
            (env, sys)
        } else {
            self.resolve_param_bindings(&self.tree[target_id].clone(), inst.param_overrides())
        };
        let target = self.tree[target_id].clone();
        let target_ast = self.module_ast(target.ast_id);
        let parent = self.tree[parent_id].clone();

        let param_binding: HashMap<Name, String> =
            param_raw.into_iter().map(|(k, v)| (k, apply_rename(&v, scope))).collect();
        // The instance's own `.$mfactor(...)`-family overrides (rename-applied
        // to final text), composed with the ones inherited from every
        // enclosing instance -- a grandchild under `.$mfactor(2)` inside a
        // child under `.$mfactor(4)` is effectively scaled by 8 (LRM 6.3.6).
        let own_sys: Vec<(ParamSysFun, String)> =
            sys_raw.into_iter().map(|(s, v)| (s, apply_rename(&v, scope))).collect();
        let sys_binding = merge_sys_overrides(inherited_sys, &own_sys);

        let mut out = String::new();
        for unit in inst.instance_units() {
            let Some(unit_name) = unit.name() else { continue };
            let base_name = unit_name.as_name();

            let mut port_raw = self.raw_port_bindings(&parent, &target, &target_ast, &unit);

            // Enhancement-41: IMPLICIT NETS. A plain-identifier connection that names
            // nothing declared in the parent module is implicitly declared as a scalar
            // net (LRM structural-connection semantics; Verilog-A derives the
            // discipline from the connected port rather than `default_discipline`,
            // which the Verilog-A appendix excludes). The net is a local of the
            // *parent*, so it takes the parent's instance prefix (keeping separate
            // flattened instances of the same parent from accidentally sharing one
            // net), its declaration is emitted once into the parent's rendered body,
            // and two connections implying different disciplines are a hard error.
            let parent_decls = declared_names(&parent, self.tree);
            // Enhancement-340: iterate the port bindings in a DETERMINISTIC order.
            //
            // `port_raw` is a HashMap, so `iter_mut()` yields its entries in hash
            // order -- and Rust seeds its hashers randomly PER PROCESS, so that order
            // varies from run to run. The loop below emits an implicit-net DECLARATION
            // the first time it meets each undeclared name, so the declaration order,
            // and with it the string-interner ids, the node numbering and the SSA value
            // numbering, all inherited that randomness. Two compilations of the same
            // source produced different (though equivalent) MIR: `lrm_p150_1.va`, whose
            // `comparator C1(.cout(aa0), .inp(in), .inm(aa2))` introduces two implicit
            // nets on ONE instance, flipped `Spur(27)`/`Spur(28)` between 'aa0' and
            // 'aa2' about half the time. Not a miscompile -- the permutation is
            // consistent and the simulated output is byte-identical -- but builds were
            // not reproducible, and it defeated MIR-diff output-preservation checking.
            //
            // Order by the TARGET's declared port order, which is both deterministic
            // and the order a reader would expect; ports not found there (which the
            // lookup below already tolerates) fall back to their name, so the order is
            // total regardless.
            let mut ordered: Vec<Name> = port_raw.keys().cloned().collect();
            ordered.sort_by_key(|n| {
                (target.nodes.iter().position(|x| &x.name == n).unwrap_or(usize::MAX),
                 n.to_string())
            });
            for port_name in &ordered {
                let port_name = port_name.clone();
                let Some(binding) = port_raw.get_mut(&port_name) else { continue };
                let port_name = &port_name;
                let PortBinding::Scalar(text) = binding else { continue };
                let Some(ident) = as_plain_ident(text) else { continue };
                if parent_decls.contains(ident) {
                    continue;
                }
                let discipline = target
                    .nodes
                    .iter()
                    .find(|n| &n.name == port_name)
                    .and_then(|n| n.discipline(self.tree).clone())
                    .map(|d| d.to_string())
                    .unwrap_or_else(|| "electrical".to_owned());
                let final_name = format!("{prefix}{ident}");
                match self.implicit_nets.get(&final_name) {
                    None => {
                        implicit_decls.push(format!(
                            "{discipline} {final_name}; // implicit net (Enhancement-41)"
                        ));
                        self.implicit_nets.insert(final_name.clone(), discipline);
                    }
                    Some(existing) if existing != &discipline => {
                        self.implicit_conflicts.push(format!(
                            "implicit net '{ident}' is connected to ports of conflicting \
                             disciplines '{existing}' and '{discipline}' -- declare it \
                             explicitly",
                        ));
                    }
                    Some(_) => (),
                }
                *text = final_name;
            }

            let indices: Vec<Option<i32>> = match unit.width().and_then(|r| fold_width_range(&r)) {
                Some((msb, lsb)) => {
                    let (lo, hi) = if msb <= lsb { (msb, lsb) } else { (lsb, msb) };
                    // Enhancement-148: an instance array is flattened into one rendered
                    // copy per element; refuse an absurd count instead of exhausting
                    // memory (mirrors the item-tree / net-array caps).
                    if (hi as i64 - lo as i64) + 1 > (1 << 20) {
                        self.unknown_module_errors.push(format!(
                            "instance array '{base_name}[{msb}:{lsb}]' expands to {} instances, \
                             exceeding the limit",
                            (hi as i64 - lo as i64) + 1
                        ));
                        vec![None]
                    } else {
                        (lo..=hi).map(Some).collect()
                    }
                }
                None => vec![None],
            };

            for (elem_pos, idx) in indices.iter().enumerate() {
                // For an instance array, a *scalar* port bound to a bare
                // identifier naming a matching-width bus in the parent's
                // scope is sliced per array element (`p[elem_pos]`)
                // instead of broadcasting the same connection to every
                // element -- the array-equivalent of `bind_port`'s
                // per-bit slicing. Bus-typed ports (already resolved as
                // `PortBinding::Bus`) are left as-is; combining a bus port
                // with an instance array simultaneously is out of scope.
                let mut port_raw_elem = port_raw.clone();
                if indices.len() > 1 {
                    for (port_name, binding) in port_raw.iter() {
                        let PortBinding::Scalar(text) = binding else { continue };
                        if let Some(caller_bus) = find_matching_caller_bus(&parent, text, indices.len()) {
                            let (caller_lo, _) = caller_bus.min_max();
                            let bit = caller_lo + elem_pos as i32;
                            port_raw_elem
                                .insert(port_name.clone(), PortBinding::Scalar(format!("{text}[{bit}]")));
                        }
                    }
                }
                let port_binding = resolve_port_bindings(port_raw_elem, scope);

                let child_prefix = match idx {
                    Some(i) => format!("{prefix}{base_name}_{i}__"),
                    None => format!("{prefix}{base_name}__"),
                };
                out.push_str(&self.render_instance_content(
                    target_id,
                    &child_prefix,
                    &port_binding,
                    &param_binding,
                    &sys_binding,
                    &ps_levels,
                ));
                out.push('\n');
            }
        }
        out
    }

    /// Renders one instance's flattened body: a `Scope` covering every
    /// name the target module itself declares (ports bound to the caller's
    /// net, or a fresh internal net if left open; everything else
    /// prefixed) plus any fresh open-port net declarations, followed by
    /// the target's own (recursively expanded) items.
    fn render_instance_content(
        &mut self,
        target_id: ItemTreeId<TreeModule>,
        prefix: &str,
        port_binding: &HashMap<Name, PortBinding>,
        param_binding: &HashMap<Name, String>,
        sys_binding: &[(ParamSysFun, String)],
        ps_levels: &[PsLevel],
    ) -> String {
        let target = self.tree[target_id].clone();
        let mut scope = Scope::default();
        // Enhancement-49: the child's own hierarchical references into ITS
        // sub-instances rewrite through the composed prefixes
        self.collect_inst_prefixes(target_id, prefix, "", &mut scope.inst_prefixes);
        // Enhancement-86: absolute (`<top>.`-qualified / `$root.`) references resolve
        // from ANY inlined body, not just the top module's own text. Share the (identical
        // for every instance) prefix map by Rc instead of cloning its N entries into this
        // scope -- the per-instance clone made the whole flatten O(N^2) in the count.
        scope.abs = Rc::clone(&self.abs_prefixes);
        let mut extra_decls = Vec::new();

        // Enhancement-86: ports that need a synthesized 0V ammeter -- because
        // the child itself declares a port branch over them (`branch (<p>)
        // pb;`, which after flattening has no port left to attach to), or
        // because some body probes `<chain>.branch(<p>)` for this instance.
        let mut ammeter_ports: BTreeSet<String> =
            self.port_ammeters.get(prefix).cloned().unwrap_or_default();
        let mut port_branch_names: Vec<(String, String)> = Vec::new();
        for item in &target.items {
            let ModuleItem::Branch(id) = item else { continue };
            let branch = &self.tree[*id];
            let hir_def::item_tree::BranchKind::PortFlow(path) = &branch.kind else {
                continue;
            };
            let Some(port) = path.segments.last() else { continue };
            ammeter_ports.insert(port.to_string());
            port_branch_names.push((branch.name.to_string(), port.to_string()));
        }
        // NOTE: a vectored port's bits beyond the first are appended to
        // `nodes` wherever their `[msb:lsb]` clause is declared in the
        // module body (see `target_port_names`'s doc comment), so `nodes`
        // is *not* cleanly partitioned into "first `num_ports` entries are
        // ports"; `node.is_port` (set correctly on every bit) is the only
        // reliable per-node test. `port_names` holds *base* names (a bus
        // port's `p[2]` node contributes `p`, matching what `decl.names()`
        // yields for the source-level `electrical [1:0] p;` declaration,
        // and what a bus's own `BusDecl::base_name` is) so every "is this
        // name a port" check below compares at the same granularity.
        let port_names: HashSet<Name> = target
            .nodes
            .iter()
            .filter(|n| n.is_port)
            .map(|n| {
                let s = n.name.to_string();
                match s.find('[') {
                    Some(i) => Name::resolve(&s[..i]),
                    None => n.name.clone(),
                }
            })
            .collect();

        for node in target.nodes.iter() {
            if !node.is_port {
                if !node.name.to_string().contains('[') {
                    // internal bus/array bits are renamed via their base name
                    // below (`buses`/`var_arrays`); only insert a direct entry
                    // here for genuinely scalar internal nets.
                    scope.subst.insert(node.name.to_string(), format!("{prefix}{}", node.name));
                }
                continue;
            }
            // A bus port's bits are grouped by base name below (in one
            // `scope.bus_ports` entry per base), so only scalar ports are
            // handled per-node here.
            if node.name.to_string().contains('[') {
                continue;
            }
            let bound = match port_binding.get(&node.name) {
                Some(PortBinding::Scalar(text)) => text.clone(),
                _ => {
                    let fresh = format!("{prefix}open__{}", node.name);
                    let discipline =
                        node.discipline(self.tree).map(|d| d.to_string()).unwrap_or_else(|| "electrical".to_owned());
                    extra_decls.push(format!("{discipline} {fresh};"));
                    fresh
                }
            };
            // Enhancement-86: the port-branch ammeter. The child's body sees a
            // fresh internal net; a named 0V branch from the caller's net to
            // it carries exactly the child's current INTO the port (positive
            // hi->lo == into the child, matching E-29's I(<p>) sign), so
            // `I(<chain>.branch(<p>))` probes and the child's own
            // `branch (<p>) pb` declarations both read it.
            if ammeter_ports.contains(&node.name.to_string()) {
                let discipline = node
                    .discipline(self.tree)
                    .map(|d| d.to_string())
                    .unwrap_or_else(|| "electrical".to_owned());
                let fresh = format!("{prefix}pflow_net__{}", node.name);
                let ammeter = format!("{prefix}pflow__{}", node.name);
                extra_decls.push(format!("{discipline} {fresh};"));
                extra_decls.push(format!("branch ({bound}, {fresh}) {ammeter};"));
                extra_decls.push(format!("analog V({ammeter}) <+ 0.0;"));
                scope.subst.insert(node.name.to_string(), fresh);
            } else {
                scope.subst.insert(node.name.to_string(), bound);
            }
        }

        // Bus ports: one `scope.bus_ports` entry per base name, filling in
        // a fresh net (declaring it) for any bit left unbound.
        for bus in target.buses.iter().chain(target.var_arrays.iter()) {
            if !port_names.contains(&bus.base_name) {
                continue;
            }
            if scope.bus_ports.contains_key(&bus.base_name) {
                continue;
            }
            let (lo, hi) = bus.min_max();
            let bound_bits = match port_binding.get(&bus.base_name) {
                Some(PortBinding::Bus(bits)) => bits.clone(),
                _ => BTreeMap::new(),
            };
            let mut bits = BTreeMap::new();
            for bit in lo..=hi {
                let text = bound_bits.get(&bit).cloned().unwrap_or_else(|| {
                    let bit_name = bus_bit_name(&bus.base_name, bit);
                    let fresh = format!("{prefix}open__{}", bit_name.to_string().replace(['[', ']'], "_"));
                    let discipline = target
                        .nodes
                        .iter()
                        .find(|n| n.name == bit_name)
                        .and_then(|n| n.discipline(self.tree))
                        .map(|d| d.to_string())
                        .unwrap_or_else(|| "electrical".to_owned());
                    extra_decls.push(format!("{discipline} {fresh};"));
                    fresh
                });
                bits.insert(bit, text);
            }
            scope.bus_ports.insert(bus.base_name.clone(), bits);
        }

        // Bus *ports* are entirely handled above (per-bit) -- the bare
        // base name of a bus port never legally appears standalone in
        // Verilog-A (every use requires a bit-select), so it must not get
        // its own `scope.subst` entry.
        // Enhancement-363: `param_arrays` must be renamed too. A module has THREE
        // array collections -- `buses` (vectored nets/ports), `var_arrays` (array
        // variables, E-4) and `param_arrays` (array-valued parameters, E-14) --
        // but this loop chained only the first two, so an array PARAMETER kept its
        // bare name while every scalar parameter got the `{prefix}` rename below.
        // Two instances then both declared `cf[0]`, `cf[1]`, ... and name
        // resolution rejected the second: "'cf[0]' was already declared in this
        // scope". That made a module with an array parameter impossible to
        // instantiate twice, and also collided across two DIFFERENT modules that
        // happened to share an array-parameter name -- legal Verilog-A, refused.
        for bus in
            target.buses.iter().chain(target.var_arrays.iter()).chain(target.param_arrays.iter())
        {
            if port_names.contains(&bus.base_name) {
                continue;
            }
            scope.subst.entry(bus.base_name.to_string()).or_insert_with(|| format!("{prefix}{}", bus.base_name));
        }
        for item in &target.items {
            let renamed = match *item {
                ModuleItem::Variable(id) => Some(self.tree[id].name.clone()),
                ModuleItem::Parameter(id) => Some(self.tree[id].name.clone()),
                ModuleItem::Branch(id) => Some(self.tree[id].name.clone()),
                ModuleItem::Function(id) => Some(self.tree[id].name.clone()),
                ModuleItem::AliasParameter(id) => Some(self.tree[id].name.clone()),
                _ => None,
            };
            if let Some(name) = renamed {
                scope.subst.insert(name.to_string(), format!("{prefix}{name}"));
            }
        }
        // Book audit (paramsets), LRM 6.4.3: a module variable a paramset of the
        // chain redeclares steps aside -- the paramset's is the one reported (or,
        // without a description, the one that hides the module's).
        let ps_names = paramset_level_names(ps_levels, prefix);
        for item in &target.items {
            let ModuleItem::Variable(id) = item else { continue };
            let name = self.tree[*id].name.to_string();
            if ps_levels.iter().any(|l| l.var_names.contains(&name)) {
                scope.subst.insert(name.clone(), format!("{prefix}{name}__ps"));
            }
        }
        // Enhancement-86: a child's own port-branch names alias the synthesized
        // ammeter (overriding the generic `{prefix}{name}` rename above); the
        // declaration itself is dropped by `render_items`.
        for (branch_name, port) in &port_branch_names {
            scope.subst.insert(branch_name.clone(), format!("{prefix}pflow__{port}"));
        }

        // A parameter overridden by this instance's `#(...)` list IS "given"
        // (LRM 6.3.5); record its FINAL flattened name for the
        // `$param_given` rewrite that runs over the finished output.
        for name in param_binding.keys() {
            if let Some(flat) = scope.subst.get(&name.to_string()) {
                self.params_given_in_va.insert(flat.clone());
            }
        }

        let body =
            self.render_items(target_id, &scope, param_binding, &port_names, prefix, sys_binding);

        // `$port_connected(p)` must be decided HERE, where the binding is
        // known: after flattening, an open port is just a synthesized local
        // net, no longer a port reference, so leaving the call in the
        // rendered text failed validation for exactly the unconnected case
        // the builtin exists to detect. The call's argument has already been
        // renamed by `render_items` (to the caller's net, or to the fresh
        // `open__` net), so connectivity is keyed by the RENDERED name.
        // Top-level modules are untouched and keep the native OSDI path.
        let mut port_connectivity: HashMap<String, bool> = HashMap::new();
        for node in target.nodes.iter().filter(|n| n.is_port) {
            let name = node.name.to_string();
            if name.contains('[') {
                continue; // $port_connected takes a scalar port per the LRM
            }
            if let Some(rendered) = scope.subst.get(&name) {
                let connected =
                    matches!(port_binding.get(&node.name), Some(PortBinding::Scalar(_)));
                port_connectivity.insert(rendered.clone(), connected);
            }
        }
        let body = resolve_port_connected(&body, &port_connectivity);

        let mut out = extra_decls.join("\n");
        if !out.is_empty() {
            out.push('\n');
        }
        out.push_str(&body);
        out.push_str(&render_paramset_levels(ps_levels, &ps_names, &scope));
        out
    }

    /// Top-level entry for one module declared directly in the source
    /// file: keeps its header/`endmodule` footer byte-for-byte, only
    /// replacing the item-list region when the module directly contains at
    /// least one instantiation (a module with none is returned verbatim,
    /// unchanged, to keep this pass a no-op for the common case).
    fn flatten_top_level_module(&mut self, module_id: ItemTreeId<TreeModule>, module_ast: &ast::ModuleDecl) -> String {
        let module = &self.tree[module_id];
        let has_instantiation =
            module.items.iter().any(|it| matches!(it, ModuleItem::Instantiation(_)));
        if !has_instantiation {
            return module_ast.syntax().text().to_string();
        }

        let items: Vec<_> = module_ast.module_items().collect();
        // The item TREE reported an instantiation, but the parsed AST's item list can be
        // empty on a malformed module where parser error-recovery and the item-tree
        // builder disagree. With no AST items there is nothing to flatten, so return the
        // module verbatim rather than panicking on items.first()/last().unwrap() below.
        if items.is_empty() {
            return module_ast.syntax().text().to_string();
        }
        let base = module_ast.syntax().text_range().start();
        let full = module_ast.syntax().text().to_string();
        let rel_start = rel_range(base, items.first().unwrap().syntax().text_range()).start;
        let rel_end = rel_range(base, items.last().unwrap().syntax().text_range()).end;

        // Enhancement-49: hierarchical references (`u1.m`, `$root.<top>.u1.m`,
        // `<top>.x`) rewrite to the flattened names via the instance-chain map;
        // the `<top>` alias entries make `$root.`-anchored and top-qualified
        // spellings resolve identically to the unqualified ones.
        let mut scope = Scope::default();
        self.collect_inst_prefixes(module_id, "", "", &mut scope.inst_prefixes);
        let top_name = self.tree[module_id].name.to_string();
        let alias: Vec<(String, String)> = scope
            .inst_prefixes
            .iter()
            .map(|(k, v)| (format!("{top_name}.{k}"), v.clone()))
            .collect();
        scope.inst_prefixes.extend(alias);
        scope.inst_prefixes.insert(top_name.clone(), String::new());

        // Enhancement-86: publish the unambiguous absolute spellings
        // (`<top>` and `<top>.<chain>`) for every inlined child's scope, so
        // sibling bodies can resolve absolute hierarchical references
        // (`V(top.a1.b)`, `$root.top.d1.branch(a,b)`).
        let abs_map: HashMap<String, String> = scope
            .inst_prefixes
            .iter()
            .filter(|(k, _)| *k == &top_name || k.starts_with(&format!("{top_name}.")))
            .map(|(k, v)| (k.clone(), v.clone()))
            .collect();
        self.abs_prefixes = Rc::new(AbsPrefixes::new(abs_map));

        // Enhancement-86: pre-scan EVERY module's text for port-branch probes
        // (`<chain>.branch(<port>)`) resolvable under this top module, so the
        // targeted instances synthesize their 0V ammeter regardless of the
        // order the referencing bodies render in.
        self.port_ammeters.clear();
        for item in self.parse.tree().items() {
            let ast::Item::ModuleDecl(m) = item else { continue };
            let text = m.syntax().text().to_string();
            for (prefix, port) in find_port_branch_probes(&text, &scope.inst_prefixes) {
                self.port_ammeters.entry(prefix).or_default().insert(port);
            }
        }

        let body =
            self.render_items(module_id, &scope, &HashMap::new(), &Default::default(), "", &[]);
        format!("{}{}{}", &full[..rel_start], body, &full[rel_end..])
    }
}
