# Enhancement-886: `newtrunc` and its three tolerances say they have no effect, and what is used instead — `ltereltol`, `lteabstol` and `ltetrtol` were taken without a word

**Scope:** N4 of the
[transient stress campaign of 2026-10-12](../docs/bug_hunts/2026-10-12_transient-sparse-klu-stress-campaign.md).

ngspice: `spicelib/analysis/cktsopt.c`, `CKTsetOpt`: `OPT_LTERELTOL`, `OPT_LTEABSTOL` and
`OPT_LTETRTOL` warn in a build without `PREDICTOR`, and `OPT_NEWTRUNC`'s warning says what runs
instead. Stock options.

`examples/transnotes_examples/` (new, shared with [E-885](Enhancement-885.md),
[E-887](Enhancement-887.md) and [E-888](Enhancement-888.md)). **ngspice only.**

**Suites:**
- [`transnotes_examples`](../examples/transnotes_examples/): [4] is this enhancement's, 11 of 11
  per solver. On the E-883 binaries [4] fails.
- `inputguard` passes.
- The full sweep: 587 of 587.

## What was wrong

`.option newtrunc` selects a truncation estimate from node voltages: the difference between a
predictor and the corrector. The predictor is compiled in only by `--enable-predictor`
(`PREDICTOR`), which also changes every device's Newton start, and this build, like stock
ngspice's default, does not have it. `newtrunc` said so:

```
Warning: Option 'newtrunc' ignored,
    compilation with preprocessor flag 'PREDICTOR' is required.
```

Its three tolerances, `ltereltol`, `lteabstol` and `ltetrtol`, were stored and read by nothing,
and said nothing. Family A's `newtrunc` rows were trap rows.

## The change

```
Warning -- Option newtrunc is ignored: the voltage-based truncation estimate needs the predictor, which this build does not have (ngspice configured with --enable-predictor has it). The estimate from the charges, set by reltol, abstol, chgtol and trtol, is used.

Warning -- Option ltereltol has no effect: it is a tolerance of newtrunc's voltage-based truncation estimate, which this build does not have (see newtrunc). The estimate from the charges, set by reltol, abstol, chgtol and trtol, is used.
```

`lteabstol` and `ltetrtol` say the same. `newtrunc=0` and a deck without them say nothing. In a
build with `PREDICTOR` nothing changes.

## The checks

`transnotes_examples`:
- **[4]** `newtrunc` says it is ignored and that the charge estimate is used; `ltereltol`,
  `lteabstol` and `ltetrtol` each say they have no effect; a deck without them prints neither.
