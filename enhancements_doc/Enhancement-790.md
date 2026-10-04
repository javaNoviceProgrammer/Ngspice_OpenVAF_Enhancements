# Enhancement-790: lint L037 reports `$mfactor` carried as a factor — the CMC mismatch rule in `r3_cmc` drew ten false warnings

**Scope:** F7 of the
[openvaf-r hunt of 2026-10-04](../docs/bug_hunts/2026-10-04_openvaf-r-run-time-domains-filters-and-instances.md).
openvaf: `hir_ty/src/validation/body.rs` (`lint_mfactor_double_scaling`: `tainted_read` follows
arithmetic and the linear operators only). `examples/inputport_examples/` (checks [9]–[11]).
**openvaf only.**

**Suites:** [`inputport_examples`](../examples/inputport_examples/) 11 of 11 per solver (2 per solver
fail on the E-788 binaries: [10] and [11]); the `hir` UI snapshot `const_sysfun` unchanged; the `hir`
and `hir_ty` tests; every bundled Verilog-A file compiled with the old and the new lint (below); the
full sweep, 536 of 536.

## What was wrong

E-686 added L037 for the LRM's `badres`, `I(a,b) <+ V(a,b) / r * $mfactor`: the simulator multiplies
every flow contribution by `$mfactor` itself (LRM 6.3.6), so a value that already carries it is
scaled twice. The lint tainted every variable whose value *read* `$mfactor` — through any
expression, every function call included — and reported a flow contribution that read a tainted
name.

The CMC standard resistor `r3_cmc` reads `$mfactor` once (`mMod = $mfactor`) and uses it for the
mismatch statistics: the per-device sigma scales as 1/sqrt(m), m parallel devices averaging their
mismatch (`weff_um + nsmm_w*smm_w/sqrt(mMod*len)`, `exp(0.01*(... smm_rsh/sqrt(mMod*len*wid)))`),
and in a switch condition (`if ((rc1_tnom/mMod) <= rthresh)`), which the lint exempts. None of its
contributions is proportional to m, and that is the CMC's intended use of `$mfactor`. The taint
reached all of them: ten warnings, in each of the corpus's two versions of the model.

## The change

A value is reported when it carries `$mfactor` as a *factor*. The taint follows `*`, `/` (a
division by `$mfactor` undoes the simulator's scaling, the same misuse), `+`, `-`, a negation, `**`
on a tainted base, both arms of a `?:`, a variable assigned such a value, and the operators linear
in their first argument — `ddt`, `idt`, the `laplace_*` and `zi_*` filters, `absdelay`,
`transition`, `slew`, `white_noise` and `flicker_noise` (a noise power multiplied by `$mfactor` is
multiplied again by the simulator, as a `ddt` of a scaled charge is). Any other call (`sqrt`, `exp`,
a user function), a comparison and an array index end it.

## The checks

inputport, three checks:

- [9] warned once each: a `ddt` of a scaled charge, a division by `$mfactor`, a negation, a `?:`
  arm, a `**` base, a `laplace_nd` and a `transition` of a scaled value;
- [10] silent: the CMC mismatch shape (`w = w0 + smm / sqrt($mfactor * l)` in the contribution), an
  `exp` of it, a user function of `$mfactor`, a comparison used as a number;
- [11] the corpus `r3_cmc` compiles without L037.

E-686's checks are unchanged: `badres`, the variable route and the noise contribution are warned;
`parares`, a `?:` condition, a potential contribution, a display and an opvar are not.

Compiled with the old and the new lint (`--dry-run`), the 1026 Verilog-A files bundled in the
repository (examples, the VA corpus, the integration models, the test data) differ in two only:

| file | old | new |
|---|---|---|
| `VA_TEST/.../r3_cmc/vacode/r3_cmc.va` | 10 | 0 |
| `VA_TEST/.../r3_cmc/vacode110/r3_cmc.va` | 10 | 0 |
| `examples/lrm_examples/va/lrm_p155_1.va` (the LRM's `badres`) | 1 | 1 |
| `openvaf/test_data/ui/const_sysfun.va` | 1 | 1 |

The `hir` integration snapshots, which run only with `--include_ignored`, fail the same fourteen
models with and without the change on older drift (L029 and other later lints); none mentions L037.

## Limits

- A function call ends the taint, so `I <+ V/r * sqrt($mfactor)` (scaled by m^1.5) and a user
  function returning its argument times `$mfactor` are not reported. The LRM asks for a warning on
  double scaling; a value that depends on m only through a function is not that, and the mismatch
  rule is the common case.
