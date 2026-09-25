# Enhancement-721: the caret label of a constant-argument diagnostic reads "invalid argument for sqrt", not "invalid the argument for sqrt" — the one renderer wrapped the noun phrase its callers pass with an article, so that the headline reads, in a second template that cannot take one; and a warning, which points at a constant the LRM gives a defined meaning, no longer calls it invalid

**Scope:** F2 of the
[second correctness campaign of 2026-09-25](../docs/bug_hunts/2026-09-25_openvaf-r-correctness-campaign-2.md).
**Compiler only.** `hir_ty/src/validation.rs` (the renderer of
`BodyValidationDiagnostic::InvalidBuiltinArg`).
[`examples/domainrt_examples/`](../examples/domainrt_examples/) (`arglabel.va`, section 6,
6 checks, 34 per solver). The hunt page; handbook §4.3.

**Suites:** `domainrt` 34 of 34 per solver, both solvers (30 of 34 on the E-719
binaries); `hunt2diag` 15 of 15, `hunt17diag` 24 of 24, `deckdomain` 45 of 45,
`exportname` 19 of 19, `limguard` 110 of 110, `lrmops` 26 of 26, `powguard` 37 of 37,
`langguard` 132 of 132 and `vafcrash2` 22 of 22 unchanged; the compiler workspace tests
green apart from the three pre-existing sourcegen drift failures (221 passed); no build
warnings; full sweep, run alone.

## What was wrong

```
error: sqrt: the argument is -1, which is outside the domain of sqrt (values >= 0); the result would be NaN
  |
5 |   x = sqrt(-1.0) + ln(0.0) + pow(-2.0, 0.5) + slew(V(a), 1e5, 1e5);
  |            ^^^^ invalid the argument for sqrt
```

and beside it `invalid the base for pow`, `invalid the maximum negative rate for slew`,
`invalid the denominator for %`, `invalid the format for $strobe`, `invalid the degree
for $discontinuity`, `invalid the standard deviation for $rdist_normal`, `invalid the
step bound for $bound_step`: every diagnostic that E-396, E-509 and their successors
raise for a constant argument, some fifty call sites of `bad_arg` and `warn_arg` in
`hir_ty/src/validation/body.rs`. Each site passes the offending thing as a noun phrase
*with* its article — "the argument", "the base", "the maximum negative rate" — because
the headline is `"{builtin}: {what} {why}"` and reads as a sentence that way. The caret
label was the same phrase in a second template, `"invalid {what} for {builtin}"`, which
cannot take an article. The three `noise_table` sites, which pass "table" bare, were
the only labels that read.

The `warn_arg` sites had a second problem in the same label. A warning is raised where
the LRM *defines* the behaviour — an `absdelay` whose constant delay exceeds its
`maxdelay` (LRM 4.5.7: the maximum is substituted), a `zi_*` filter with a zero
transition time (LRM 4.5.12: assign it to a variable first) — and E-514 made them
warnings precisely because refusing the program would be wrong. Their label still said
`invalid the delay for absdelay`.

## What changed

At the one renderer (`hir_ty/src/validation.rs`), and nowhere else: the label strips
a leading "the " from the phrase and reads `invalid {noun} for {builtin}` —
`invalid argument for sqrt`, `invalid base for pow`, `invalid maximum negative rate for
slew`, `invalid second operand (the modulus divisor) for %`, and `invalid table for
noise_table` as before — and a warning's label is `{what} given to {builtin}`:
`the delay given to absdelay`, `the transition time given to zi_nd`. The headline, the
note ("checked only when the argument is written out as a constant …") and the
severities are untouched; the fifty call sites are untouched.

## Verification

`domainrt` section 6, `arglabel.va`: `sqrt(-4.0)`, `slew(V(a), 1e5, 1e5)`,
`absdelay(V(a), 2e-6, 1e-6)` and `noise_table('{1.0, 2.0, 3.0})` in one module — three
errors and one warning; the labels `invalid argument for sqrt`, `invalid maximum
negative rate for slew`, `invalid table for noise_table` and `the delay given to
absdelay` are read off the output, and "invalid the" appears nowhere in it. On the E-719
binaries the module is refused with the same headlines, the `noise_table` label is
the same, and the other three labels and the absence check fail. The 28 checks of E-509
unchanged.

By hand: the two probe modules of the campaign and of this fold (`sqrt`, `ln`, `pow`,
`atanh`, `acos`, `slew`, `absdelay`, `zi_nd`, `$rdist_normal`, `noise_table`, `%`); the
suites that pin these diagnostics' headlines; the workspace tests; the sweep.

## What this does not do

- The headlines are as they were; a suite that pins "outside the domain of sqrt" or
  "must be less than zero, but is" sees no change.
- A caller that passes its phrase without an article ("table") is not given one: the
  label is `invalid table for noise_table`, which reads, and the headline
  `noise_table: table has 3 entries; …` is a matter for that caller.
- The compile-time-versus-run-time policy of E-396 and E-509 — a constant argument is
  checked, a card value or a solution-derived one is not — is untouched.
