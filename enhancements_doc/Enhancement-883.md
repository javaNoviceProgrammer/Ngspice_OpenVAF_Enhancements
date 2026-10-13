# Enhancement-883: an unknown integration method is named, and so is the method that runs instead — `method=trbdf` ran trap after "unsupported integration method"

**Scope:** D3 of the
[transient stress campaign of 2026-10-12](../docs/bug_hunts/2026-10-12_transient-sparse-klu-stress-campaign.md).

ngspice: `spicelib/analysis/cktsopt.c`, `CKTsetOpt`: `OPT_METHOD` with a name it does not know
warns and keeps the current method, instead of returning `E_METHOD`.

`examples/transopts_examples/` (new, shared with [E-881](Enhancement-881.md) and
[E-882](Enhancement-882.md)). **ngspice only.**

**Suites:**
- [`transopts_examples`](../examples/transopts_examples/): [6] is this enhancement's, 7 of 7 per
  solver. On the E-875 binaries [6] fails.
- The full sweep: 585 of 585.

## What was wrong

`.option method=trbdf`, a typo for `trbdf2`, printed

```
setAnalysisParm(options) ci_curOpt: unsupported integration method
```

and the run went on with trap. The message named neither the value nor the method that ran.
`method=bdf` and `method=gear2` did the same.

## The change

An unknown name is reported with the value, the names that exist and the method that is kept:

```
Warning -- Option method = trbdf is unknown (use trap, gear, trbdf2, sdirk or adams); ignored, keeping trap
```

After an `option method=gear`, an unknown name says `keeping gear`. The generic line is no longer
printed.

## The checks

`transopts_examples`:
- **[6]** `method=trbdf` names the value and the valid ones, and says trap is kept. After
  `option method=gear`, `method=foo` says gear is kept. The generic "unsupported integration
  method" line is gone.
