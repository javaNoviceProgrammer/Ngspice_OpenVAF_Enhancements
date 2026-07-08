# Enhancement-110 — `errpreset`: coordinated accuracy presets for ngspice

A SPICE-class simulator's accuracy and convergence are governed by roughly eight
interacting options — `reltol`, `abstol`, `vntol`, `chgtol`, `trtol`, the gmin-
and source-stepping counts, and the DC iteration limit `itl1`. Setting them well
means understanding how they trade off, and setting them *consistently* is easy
to get wrong. Commercial tools solve this with a single knob: Spectre's
`errpreset=conservative|moderate|liberal` selects one validated, coordinated
combination. This enhancement adds the same control to ngspice.

```
.option errpreset=conservative   ; accurate / robust, slower
.option errpreset=moderate       ; ngspice's historical defaults (backward compatible)
.option errpreset=liberal        ; fast, looser accuracy
```

## What each preset sets

`moderate` is exactly ngspice's existing default set, so the feature is
**fully backward-compatible** — a netlist that does not mention `errpreset`
behaves precisely as before. `conservative` tightens every tolerance, tightens
the LTE control (`trtol`), and adds DC-robustness (more gmin/source steps, a
higher iteration limit). `liberal` loosens the tolerances and the LTE control
for speed.

| option | conservative | moderate (= default) | liberal |
|---|---|---|---|
| `reltol` | 1e-4 | 1e-3 | 1e-2 |
| `abstol` | 1e-13 | 1e-12 | 1e-10 |
| `vntol` | 1e-7 | 1e-6 | 1e-4 |
| `chgtol` | 1e-15 | 1e-14 | 1e-12 |
| `trtol` | 1 | 7 | 20 |
| `srcsteps` / `gminsteps` | 10 / 10 | 1 / 1 | 1 / 1 |
| `itl1` | 200 | 100 | 100 |

The integration method (`trapezoidal`) and `maxord` (2) are **not** changed by
the preset: switching to Gear would trade accuracy for stability, which does not
belong in a "conservative = more accurate" knob. The presets vary only the
tolerances, the LTE tightness, and DC-convergence aids. (The values live in one
function and are easy to retune later.)

## Explicit options always win — regardless of order

The subtle part is coexistence with individual options. `.option
errpreset=liberal reltol=1e-4` must keep the tight `reltol` — and so must
`.option reltol=1e-4 errpreset=liberal`, even though `.options` are parsed in
text order. This is handled without any deferred-apply machinery:

- each individual tolerance case records a bit in a new `TSKtolGiven` mask when
  the user sets that option explicitly;
- `errpreset` writes only the fields whose bit is **clear**.

So in either order the explicit value survives: if the explicit option is parsed
first, its bit is set and `errpreset` skips that field; if `errpreset` is parsed
first, it sets the field and the later explicit option simply overwrites it. The
verify suite checks both orders give an identical result.

## Files changed

All changes are **purely additive** (82 insertions, 0 deletions) and confined to
ngspice's option-handling layer — no numerical-core or device code is touched.

| File | What changed |
|---|---|
| `ngspice-46/src/include/ngspice/optdefs.h` | Added the `OPT_ERRPRESET` option code to the enum, and eight `ERRP_*` bit constants (one per tolerance field the preset touches) used to track which options the user set explicitly. |
| `ngspice-46/src/include/ngspice/tskdefs.h` | Added `unsigned int TSKtolGiven` to the task struct — the bitmask of explicitly-given tolerance options (the override guard). |
| `ngspice-46/src/spicelib/analysis/cktsopt.c` | Added the static helper `ckt_apply_errpreset()` (the conservative/moderate/liberal value table + the "only write un-given fields" logic); added the `case OPT_ERRPRESET` that maps the string to a preset (prefix match on `cons`/`mod`/`lib`, warns on anything else); set the `ERRP_*` given-bit in each of the eight individual option cases (`RELTOL`, `ABSTOL`, `VNTOL`, `TRTOL`, `CHGTOL`, `ITL1`, `SRCSTEPS`, `GMINSTEPS`); and added the `{ "errpreset", OPT_ERRPRESET, IF_SET\|IF_STRING, … }` entry to the `OPTtbl` keyword table so `.option errpreset=…` is recognized. |
| `ngspice-46/src/spicelib/analysis/cktntask.c` | Initialised `TSKtolGiven = 0` in both task-creation paths (the copy-from-defaults path and the hard-coded-defaults path) — a fresh task has no user-given options yet. |

## Verification

[`examples/errpreset_examples/`](../examples/errpreset_examples/) (9/9), driving
an adaptive-stepping RC transient through the committed ngspice:

- the three presets order the accepted time-point count **conservative (323) >
  moderate (165) ≥ liberal (145)** — tighter tolerances resolve the pulse edges
  more finely;
- **`moderate` reproduces the no-errpreset default exactly** (165 = 165) —
  backward compatibility;
- an explicit `reltol=1e-4` overrides the preset and gives the **same result in
  either `.options` order** (153 = 153), and differs from plain liberal (145);
- a preset can be loosened by an explicit value (`errpreset=conservative
  reltol=1e-2` drops from 323 to 169);
- an unknown preset warns (`unknown errpreset '…'`) and the run still completes.

Regression: a representative slice of the existing suites (`operator`,
`simctrl`, `noise`, `clog2`, `ceil`) pass unchanged against the rebuilt ngspice,
confirming the additive option handling changes nothing for netlists that do not
use `errpreset`.
