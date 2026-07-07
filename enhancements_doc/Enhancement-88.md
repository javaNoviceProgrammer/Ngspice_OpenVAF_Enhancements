# Enhancement-88 — the legacy `generate` statement (version11)

This document describes Enhancement-88: support for the obsolete
Verilog-A 1.0 `generate` statement (LRM Annex C.4), the last unsupported
*analog-block* looping construct — `generate <id> (<start>, <end> [,
<incr>]) <body>`.

## What it is

Unlike the modern module-level `generate for` (Enhancement-8, which
produces structural items), the legacy `generate` is a **behavioral
statement inside an analog block** that unrolls its body at compile time,
substituting the index with each successive constant value. It is the
form the LRM's own page-438 flash-ADC example uses:

```verilog
analog begin
   thresh = fullscale/2.0;
   sample = V(in);
   generate i (bits-1, 0) begin           // i = 7, 6, ..., 0  (descending)
      V(out[i]) <+ transition(sample > thresh, dly, ttime);
      if (sample > thresh) sample = sample - thresh;
      sample = 2.0*sample;
   end
end
```

The unroll must be a **compile-time** replication (not a runtime loop):
`out[i]` selects a bus *node*, so the index has to become a literal
`out[7]`, `out[6]`, … — a runtime index cannot select a node. The body is
also stateful across iterations (`sample` is halved each step), so the
unroll **order** is load-bearing.

## Implementation

A self-contained textual pre-pass, `elaborate_legacy_generate`
(`hir/src/elaborate.rs`), run before the module-level generate pass and
before name resolution (the index is not a declared variable, so the
substitution has to happen on source text). This mirrors the E-8/E-67
generate-for machinery and the E-85 `__FILE__` textual pre-pass, and
avoids threading a new statement kind through parser → hir_def → hir_lower
for an obsolete construct.

- **Scan**: tokenize; find `generate` followed by an identifier that is
  not `for`/`if`/`case` (those are the module-level regions, left
  untouched) — unambiguous since the legacy form always names an index.
- **Bounds**: `<start>`, `<end>`, optional `<incr>` are evaluated by a
  small constant-integer token evaluator (decimal literals, `+ - * /`,
  unary `-`, parens). Direction defaults to ±1 from the bound ordering.
- **Body**: a balanced `begin … end` or a single statement to the next
  `;`.
- **Unroll**: per iteration, the index is substituted by its literal
  (whole-identifier), and each bit-select `[<expr>]` whose contents then
  constant-fold is rewritten to `[<literal>]` (a bus bit-select requires a
  literal index — `out[7+1]` is rejected, so `out[i+1]` must fold to
  `out[8]`). The iteration blocks are wrapped in one outer `begin … end`
  so the whole expansion is a single statement, valid whether the
  `generate` sat inside an `analog begin … end` or was the direct body of
  `analog`. A fixpoint loop handles nested legacy generates.
- **Bounds must be elaboration-time constants.** A parameter bound
  (`generate i (bits-1, 0)`) is a targeted error — a runtime-bindable
  parameter cannot shape a compile-time unroll, the same scope decision
  as `generate for`/`generate if` (Enhancement-67).

## Verification

- `legacygen_examples` 6/6: the LRM flash-ADC (constant width) compiles
  and, for a 0.7 V DC input, produces the exact 4-bit code `1011`
  (per-bit runtime pins in ngspice — proving index substitution,
  descending order, and the stateful accumulation); a parameter-bound
  legacy generate is rejected with the targeted diagnostic.
- Probed additionally: ascending direction, `analog`-direct (no
  enclosing `begin`) body, single-statement body, and `[k+1]` bracket
  folding to a literal.
- LRM suite: `lrm_p438_1` pin updated from the old parse error to the
  new bound-constant diagnostic — it stays a limitation because it uses
  *both* a parameter bound and a parameter bus width (7/7, 40/19/21).
- Modern `generate for`/`if`/`case` untouched (generate suite 9/9); full
  regression + 28 integration tests; parser/hir snapshot tests green.

## Gotchas recorded

- A bus bit-select requires a **literal** integer, not a constant
  expression (`out[7+1]` is a compile error), so index substitution must
  be followed by bracket-content constant folding.
- Wrapping the unrolled iterations in a single outer `begin … end` is
  what makes the expansion valid in both analog-block contexts (nested
  block vs. `analog`'s single-statement body) — emitting bare adjacent
  blocks breaks the `analog <stmt>` form.
