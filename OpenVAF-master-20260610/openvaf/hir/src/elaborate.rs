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

use basedb::{AstId, AstIdMap, BaseDB, VfsStorage};
use hir_def::db::HirDefDB;
use hir_def::item_tree::{bus_bit_name, BusDecl, ItemTree, Module as TreeModule, ModuleItem};
use hir_def::nameres::diagnostics::DefDiagnostic;
use hir_def::ItemTreeId;
use syntax::name::{AsName, Name};
use syntax::{ast, AstNode, ConstExprValue, Parse, SourceFile, TextRange, TextSize};
use tokens::lexer::TokenKind;

use crate::db::CompilationDB;


/// Expands the LRM's predefined source-location macros as a textual
/// pre-pass, before preprocessing/elaboration ever run: `` `__FILE__ ``
/// becomes a string literal holding the root file's BASENAME (basename, not
/// the full path, for the same provenance reason Enhancement-58 names the
/// synthetic elaboration files by basename: the expanded string is baked
/// into the compiled .osdi, and an absolute path would leak the build
/// machine's layout), and `` `__LINE__ `` becomes the 1-based line number of
/// the occurrence in the user's file. Replacements are inline (no newlines
/// added or removed), so all later line numbers stay exact. Occurrences
/// inside string literals and comments are left untouched.
///
/// Scope: the ROOT file only. The standard headers never use these macros,
/// and a use inside a `` `define `` body expands here, textually, to the
/// definition site's location (documented; the LRM's C-style "line of use"
/// would need real preprocessor tokens, which are (kind, span) pairs into
/// existing source text and cannot carry synthesized values).
pub(crate) fn expand_source_location_macros(db: &mut CompilationDB) -> anyhow::Result<()> {
    let root_file = db.compilation_unit().root_file();
    let Ok(text) = db.file_text(root_file) else { return Ok(()) };
    if !text.contains("`__FILE__") && !text.contains("`__LINE__") {
        return Ok(());
    }

    let root_path = db.vfs().read().file_path(root_file).to_string();
    let base_name = root_path.rsplit(['/', '\\']).next().unwrap_or(root_path.as_str()).to_owned();
    let file_lit = format!("\"{base_name}\"");

    let bytes = text.as_bytes();
    let mut out = String::with_capacity(text.len());
    let mut line = 1usize;
    let mut i = 0usize;
    #[derive(PartialEq)]
    enum St {
        Code,
        Str,
        LineComment,
        BlockComment,
    }
    let mut st = St::Code;
    while i < bytes.len() {
        let c = bytes[i] as char;
        match st {
            St::Code => {
                if c == '`'
                    && (bytes[i..].starts_with(b"`__FILE__") || bytes[i..].starts_with(b"`__LINE__"))
                    // word boundary: `__FILE__X is some other macro
                    && !bytes.get(i + 9).is_some_and(|b| b.is_ascii_alphanumeric() || *b == b'_')
                {
                    if bytes[i..].starts_with(b"`__FILE__") {
                        out.push_str(&file_lit);
                    } else {
                        out.push_str(&line.to_string());
                    }
                    i += 9;
                    continue;
                }
                match c {
                    '"' => st = St::Str,
                    '/' if bytes.get(i + 1) == Some(&b'/') => st = St::LineComment,
                    '/' if bytes.get(i + 1) == Some(&b'*') => st = St::BlockComment,
                    _ => (),
                }
            }
            St::Str => match c {
                '\\' => {
                    // keep the escaped character (incl. \") opaque
                    out.push(c);
                    i += 1;
                    if let Some(&n) = bytes.get(i) {
                        if n as char == '\n' {
                            line += 1;
                        }
                        out.push(n as char);
                        i += 1;
                    }
                    continue;
                }
                '"' => st = St::Code,
                _ => (),
            },
            St::LineComment => {
                if c == '\n' {
                    st = St::Code;
                }
            }
            St::BlockComment => {
                if c == '*' && bytes.get(i + 1) == Some(&b'/') {
                    out.push('*');
                    out.push('/');
                    i += 2;
                    st = St::Code;
                    continue;
                }
            }
        }
        if c == '\n' {
            line += 1;
        }
        out.push(c);
        i += 1;
    }

    let synth_name = format!("/{base_name}__srcloc.va");
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
            "+" => {
                *pos += 1;
                acc += parse_mul(text, toks, pos, params)?;
            }
            "-" => {
                *pos += 1;
                acc -= parse_mul(text, toks, pos, params)?;
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
            Some(-parse_unary(text, toks, pos, params)?)
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
    decls: &mut Vec<(String, usize, usize)>,
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
    decls.push((name, expr_lo, expr_hi));
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

    let mut rewrites: Vec<(usize, usize, String)> = Vec::new();
    for (rs, re) in regions {
        // pass 1: collect integer parameter defaults in this module
        let mut decls: Vec<(String, usize, usize)> = Vec::new();
        let mut p = rs;
        while p < re {
            if matches!(raw(sig[p]), "parameter" | "localparam") {
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
                            collect_param_group(&text, &spans, &sig, group_start, q, &mut decls);
                            group_start = q + 1;
                        }
                        _ => {}
                    }
                    q += 1;
                }
                collect_param_group(&text, &spans, &sig, group_start, end, &mut decls);
                p = end;
            }
            p += 1;
        }
        // resolve to a name -> value map (fixpoint: a parameter default may
        // reference an earlier/later parameter of the same module)
        let mut map: HashMap<String, i32> = HashMap::new();
        loop {
            let mut changed = false;
            for (name, lo, hi) in &decls {
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

        // pass 3 (Enhancement-92): a parameter that shaped a declaration width
        // is *structural* -- the OSDI descriptor has one fixed node/array count,
        // so the value must not change at simulation time. Rewrite its
        // declaration to `localparam` (splitting a multi-parameter declaration
        // so only the structural names freeze, and dropping the now-illegal
        // range constraint). Without this an override that grows the parameter
        // would leave the frozen width behind while behavioural code (a runtime
        // loop bound, say) follows the new value -- a silent out-of-bounds.
        freeze_width_parameters(&text, &spans, &sig, rs, re, &frozen, &mut rewrites);
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
/// Scope (per Verilog-A LRM and this enhancement's design): `generate for`
/// may only produce structural/declarative module items (net/instance/
/// variable/parameter declarations) -- never an `analog` block. Only
/// `generate for` is supported; `generate if`/`generate case` are out of
/// scope (see module docs / Enhancement-8 writeup).
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
fn render_module_with_generates(module_ast: &ast::ModuleDecl) -> anyhow::Result<String> {
    let has_generate = module_ast.module_items().any(|it| {
        matches!(it, ast::ModuleItem::GenerateFor(_) | ast::ModuleItem::GenvarDecl(_)
            | ast::ModuleItem::GenerateIf(_) | ast::ModuleItem::GenerateCase(_))
    });
    if !has_generate {
        return Ok(module_ast.syntax().text().to_string());
    }

    let mut out = String::new();
    for item in module_ast.module_items() {
        match item {
            ast::ModuleItem::GenvarDecl(_) => {
                // Compile-time-only; dropped entirely, never reaches `hir_def`.
            }
            ast::ModuleItem::GenerateFor(gen_for) => {
                out.push_str(&render_generate_for(&gen_for, &HashMap::new(), "", &Scope::default())?);
            }
            ast::ModuleItem::GenerateIf(gen_if) => {
                out.push_str(&render_generate_if(&gen_if, &HashMap::new(), "", &Scope::default())?);
            }
            ast::ModuleItem::GenerateCase(gen_case) => {
                out.push_str(&render_generate_case(&gen_case, &HashMap::new(), "", &Scope::default())?);
            }
            other => out.push_str(&other.syntax().text().to_string()),
        }
        out.push('\n');
    }

    let items: Vec<_> = module_ast.module_items().collect();
    let base = module_ast.syntax().text_range().start();
    let full = module_ast.syntax().text().to_string();
    let rel_start = rel_range(base, items.first().unwrap().syntax().text_range()).start;
    let rel_end = rel_range(base, items.last().unwrap().syntax().text_range()).end;
    Ok(format!("{}{}{}", &full[..rel_start], out, &full[rel_end..]))
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
    // the label is optional since Enhancement-67 (anonymous blocks are
    // legal 1364-2005); it only feeds the generated comment.
    let label =
        body.label().map(|l| l.syntax().text().to_string()).unwrap_or_else(|| "genblk".to_owned());

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
        out.push_str(&render_generate_block(&body, &env, &iter_suffix, outer_scope)?);
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
) -> anyhow::Result<String> {
    let mut scope = outer_scope.clone();
    if !suffix.is_empty() {
        for name in collect_declared_names(block) {
            scope.subst.insert(name.clone(), format!("{name}{suffix}"));
        }
    }

    let mut out = String::new();
    for item in block.items() {
        match item {
            ast::ModuleItem::GenvarDecl(_) => {}
            ast::ModuleItem::GenerateFor(inner) => {
                out.push_str(&render_generate_for(&inner, env, suffix, &scope)?);
            }
            ast::ModuleItem::GenerateIf(inner) => {
                out.push_str(&render_generate_if(&inner, env, suffix, &scope)?);
            }
            ast::ModuleItem::GenerateCase(inner) => {
                out.push_str(&render_generate_case(&inner, env, suffix, &scope)?);
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
    if cond {
        return render_generate_block(&then_block, env, suffix, scope);
    }
    // else side: either a nested `else if` (a GENERATE_IF child) or a block
    if let Some(else_if) = support_child_generate_if(gen_if) {
        return render_generate_if(&else_if, env, suffix, scope);
    }
    if let Some(else_block) = blocks.next() {
        return render_generate_block(&else_block, env, suffix, scope);
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
                return render_generate_block(&block, env, suffix, scope);
            }
        }
    }
    if let Some(arm) = default_arm {
        let block = arm
            .block()
            .ok_or_else(|| anyhow::anyhow!("generate case: default arm is missing its block"))?;
        return render_generate_block(&block, env, suffix, scope);
    }
    Ok(String::new())
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
    let mut names = Vec::new();
    for item in body.items() {
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
            _ => {}
        }
    }
    names
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
        abs_prefixes: HashMap::new(),
        port_ammeters: HashMap::new(),
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
                    *anchor_name != name && !find_instance_path_holes(&text, map).is_empty()
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
    abs_prefixes: HashMap<String, String>,
    /// Enhancement-86: instance prefixes whose listed ports need a
    /// synthesized 0V ammeter because some body probes
    /// `<chain>.branch(<port>)` — collected by a pre-scan over every
    /// module's text before the top module renders.
    port_ammeters: HashMap<String, BTreeSet<String>>,
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
#[derive(Default, Clone)]
struct Scope {
    subst: HashMap<String, String>,
    bus_ports: HashMap<Name, BTreeMap<i32, String>>,
    /// Enhancement-49: every reachable instance chain from this scope
    /// (`"u1"`, `"u1.u2"`, `"u1[2]"`, ...) mapped to the composed flattening
    /// prefix of that instance's locals -- used to rewrite hierarchical
    /// references (`V(u1.m)`, `u1.r`) to the flattened names (`u1__m`).
    inst_prefixes: HashMap<String, String>,
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
) -> Vec<(Range<usize>, String)> {
    if inst_prefixes.is_empty() {
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
                        if inst_prefixes.keys().any(|c| {
                            c == &candidate || c.starts_with(&format!("{candidate}."))
                        }) {
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
        if !inst_prefixes.contains_key(&first_seg)
            && !inst_prefixes.keys().any(|c| c.starts_with(&format!("{first_seg}.")))
        {
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
            if inst_prefixes.contains_key(&candidate)
                || inst_prefixes.keys().any(|c| c.starts_with(&format!("{candidate}.")))
            {
                chain = candidate;
                cursor = after_seg;
            } else {
                break;
            }
        }

        let Some(prefix) = inst_prefixes.get(&chain) else {
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
    all_holes.extend(find_instance_path_holes(text, &scope.inst_prefixes));
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
/// `caller` if one exists (see `find_matching_caller_bus`), else
/// `net_text` broadcast verbatim to every bit as a best-effort fallback.
fn bind_port(result: &mut HashMap<Name, PortBinding>, target: &TreeModule, caller: &TreeModule, port_name: &Name, net_text: &str) {
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
        // whose broadcast produces the standard downstream diagnostics
    }

    let caller_bus = find_matching_caller_bus(caller, net_text, width);

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

        if conns.iter().all(|c| c.name().is_none()) {
            for (name, conn) in port_names.iter().zip(conns.iter()) {
                if let Some(net) = conn.net() {
                    self.bind_port_actual(&mut result, target, caller, name, &net);
                }
            }
        } else {
            for conn in &conns {
                if let (Some(name), Some(net)) = (conn.name(), conn.net()) {
                    self.bind_port_actual(&mut result, target, caller, &name.as_name(), &net);
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
            bind_port(result, target, caller, port_name, &net.syntax().text().to_string());
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
    ) -> HashMap<Name, String> {
        let mut result = HashMap::new();
        let Some(overrides) = overrides else { return result };
        let assigns: Vec<_> = overrides.param_assigns().collect();
        let param_names: Vec<Name> = target
            .items
            .iter()
            .filter_map(|it| match it {
                ModuleItem::Parameter(p) => Some(self.tree[*p].name.clone()),
                _ => None,
            })
            .collect();

        if assigns.iter().all(|a| a.name().is_none()) {
            for (name, assign) in param_names.iter().zip(assigns.iter()) {
                if let Some(val) = assign.val() {
                    result.insert(name.clone(), val.syntax().text().to_string());
                }
            }
        } else {
            for assign in &assigns {
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
                    result.insert(name.as_name(), val.syntax().text().to_string());
                }
            }
        }
        result
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
                let holes = find_instance_path_holes(path_text, &scope.inst_prefixes);
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
                    ));
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
        let target = self.tree[target_id].clone();
        let target_ast = self.module_ast(target.ast_id);
        let parent = self.tree[parent_id].clone();

        let param_raw = self.resolve_param_bindings(&target, inst.param_overrides());
        let param_binding: HashMap<Name, String> =
            param_raw.into_iter().map(|(k, v)| (k, apply_rename(&v, scope))).collect();

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
            for (port_name, binding) in port_raw.iter_mut() {
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
    ) -> String {
        let target = self.tree[target_id].clone();
        let mut scope = Scope::default();
        // Enhancement-49: the child's own hierarchical references into ITS
        // sub-instances rewrite through the composed prefixes
        self.collect_inst_prefixes(target_id, prefix, "", &mut scope.inst_prefixes);
        // Enhancement-86: absolute (`<top>.`-qualified / `$root.`) references
        // resolve from ANY inlined body, not just the top module's own text.
        for (k, v) in &self.abs_prefixes {
            scope.inst_prefixes.entry(k.clone()).or_insert_with(|| v.clone());
        }
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
        for bus in target.buses.iter().chain(target.var_arrays.iter()) {
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
        // Enhancement-86: a child's own port-branch names alias the synthesized
        // ammeter (overriding the generic `{prefix}{name}` rename above); the
        // declaration itself is dropped by `render_items`.
        for (branch_name, port) in &port_branch_names {
            scope.subst.insert(branch_name.clone(), format!("{prefix}pflow__{port}"));
        }

        let body = self.render_items(target_id, &scope, param_binding, &port_names, prefix);

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
        self.abs_prefixes = scope
            .inst_prefixes
            .iter()
            .filter(|(k, _)| *k == &top_name || k.starts_with(&format!("{top_name}.")))
            .map(|(k, v)| (k.clone(), v.clone()))
            .collect();

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

        let body = self.render_items(module_id, &scope, &HashMap::new(), &Default::default(), "");
        format!("{}{}{}", &full[..rel_start], body, &full[rel_end..])
    }
}
