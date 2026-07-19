# Enhancement-230 — openvaf-r crash hardening (fuzzing, round 3)

A third robustness round on the `openvaf-r` Verilog-A → OSDI compiler, following
[E-213](Enhancement-213.md) and [E-220](Enhancement-220.md). The full production
corpus was recompiled (**92 / 92 standalone models, identical verdicts** — nothing
regressed) and a fresh mutation-fuzz campaign was run — ~19,500 iterations over
diverse compact-model seeds (BSIM-CMG, PSP, HICUM, MEXTRAM, VBIC, EKV, Angelov,
…) with keyword / attribute / bracket / number injection.

The fuzzer found **three distinct ways to panic the compiler** (exit 101,
*"OpenVAF encountered a problem and has crashed!"*) on malformed input. All three
are the E-213 panic class: the panic hook caught each, so the compiler was never
memory-unsafe — but a crash with no diagnostic is the wrong outcome for a bad
input, which should be a clean error. All three are fixed; a re-fuzz of the fixed
compiler is **0 panics, 0 hangs**.

## The three root causes

### 1. `begin :` with a missing name — `hir_def` name resolution panic

A named sequential block is `begin : name … end`. Item-tree lowering
(`item_tree/lower.rs`) decided whether a block is a *named scope* by testing
`block.block_scope().is_some()` — i.e. whether the `:` scope syntax is present —
but stored `name = block_scope().and_then(|it| it.name()?…)`, which is `None`
when the colon is there but the **name identifier is missing or invalid**
(`begin :` followed by a keyword, EOF, …). Such a block was still linked into the
item tree as a scope, so name resolution later did

```rust
self.tree.block_scope(ast).name.clone()
    .expect("Item tree must only contain named blocks")   // nameres/collect.rs:553
```

and panicked on the `None`.

**Fix:** gate the named-scope treatment on `name.is_some()` (in both the Enter
and Leave halves of the walk, keeping the scope stack balanced). A nameless
`begin :` is simply not treated as a scope; the parser already reports the
missing block name separately.

### 2. Port-flow read of an attributed, direction-declared port — `hir_ty` panic

The type-validation diagnostic *"expected a port reference but no direction was
declared"* (`validation.rs`) builds its report by labelling each of the node's
declarations, and did:

```rust
NodeTypeDecl::Port(_) => unreachable!(),
```

assuming the offending node has only `Net` declarations. But a node can carry
**both** a `Net` decl (its `electrical` net type) and a `Port` decl (its entry in
the module port list). Reached via an attribute in the port list
(`module m( (* … *) g, s )`) together with a port-flow read `x = I(<s>)`, the node
has both — so the `unreachable!()` fired.

**Fix:** the label builder now skips `Port` decls (`filter_map` returning `None`)
instead of `unreachable!()`. The diagnostic still reports; it just doesn't try to
label the port-list entry as a net declaration.

### 3. Unterminated string literal — `syntax` slice panic

`StrLit::value()` (`syntax/ast/expr_ext.rs`) stripped the surrounding quotes with

```rust
&src[1..src.len() - 1]
```

A malformed / unterminated string literal that the lexer still classified as a
`StrLit` can be a **lone `"`** (length 1), making the range `[1..0]` — start
`> ` end — which panics (*"byte range starts at 1 but ends at 0"*). Reached via an
attribute with an unterminated string value (`(* d=" … *)`).

**Fix:** a saturating range, `src.get(1..src.len().saturating_sub(1)).unwrap_or("")`.
This is the same class as the [E-220](Enhancement-220.md) include-path slice, at a
different site — string literals in expressions and attributes rather than
`` `include `` paths.

## Behaviour-preserving

- **Corpus head-to-head:** all **92 standalone** production models compile to the
  **identical verdict** before and after — 0 flips.
- The fixes only change what happens on *malformed* input (crash → clean error);
  no valid program is affected.

## Verification (`examples/vafcrash3_examples`)

`verify_vafcrash3.py` drives a minimal repro for each root cause — a `begin :`
with a missing name (and nested / empty variants), a port-list attribute plus a
port-flow read / `$port_connected`, and an attribute with an unterminated string
(the saved `crash_strlit.va` fixture) — and asserts each now yields a clean
**ERROR** (nonzero exit, no panic / crash / hang, each was exit 101 on the shipped
binary). Regression controls confirm a valid named block, a proper directioned
port with a port-flow read, and an attribute with a well-formed string all still
compile.

## Scope

`openvaf-r` compiler only, three files (`hir_def/src/item_tree/lower.rs`,
`hir_ty/src/validation.rs`, `syntax/src/ast/expr_ext.rs`); no ngspice, device, or
ABI change. The robustness report
([OpenVAF_robustness_report](../docs/internals/openvaf_internals/OpenVAF_robustness_report.md))
is updated with the Round-3 result.
