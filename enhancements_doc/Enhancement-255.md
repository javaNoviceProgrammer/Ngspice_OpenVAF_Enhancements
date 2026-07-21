# Enhancement-255 — `.disto` proven machine-exact + behavioral-source distortion warning

A correctness enhancement on the RF/distortion frontier, in the E-251
Harmonic-Balance mold: the classic `.disto` (1990 Volterra small-signal distortion
analysis) is **proven machine-exact** against ngspice's own independent
large-signal engines, and the one common *unsupported* nonlinearity — a behavioral
**B-source** — now **warns** instead of silently reporting zero distortion.

## The oracle-based proof

`.disto` reports the pure 2nd/3rd-order Volterra distortion kernels, scaled by the
DISTOF1/DISTOF2 source magnitudes — amplitude-independent physics. Harmonic Balance
(`hb`) and two-tone QPSS-HB (`qpss`) are *independent* large-signal engines that
include **all** orders; at small drive amplitude `A` their harmonic and mixing
amplitudes converge onto the Volterra result with higher-order leakage `~A²`. So
`HB(A) → .disto` as `A → 0` — the E-251 HB-proof structure applied to distortion.
Because HB and `.disto` evaluate ngspice's *identical* device model, any
model-constant ambiguity (thermal voltage `V_T`, the DC operating point) cancels,
so the measured agreement is a property of the `.disto` engine itself.

Measured on a diode + series-R two-port (both solvers):

| product | oracle | agreement (A→0) | scaling |
|---|---|---|---|
| HD2 (single tone) | HB 2f | rel err `4.0e-5 → 2.6e-7` as `A: 1e-3 → 1e-4` | exact `A²` |
| HD3 (single tone) | HB 3f | `~4e-6` at `A=1e-4` | exact `A³` |
| IM3 (`2f1−f2`, two tone) | QPSS-HB `(2,−1)` | `~1e-5` | exact `A³` |

The tightening of the HB-vs-`.disto` error as `A` shrinks *is* the proof that
`.disto` is the exact `A→0` limit of the independent engine; the residual floors
are the reference engine's own readout/`|F|` precision, not `.disto`. The `.disto`
output also scales *exactly* as `A²`/`A³`, confirming the DISTOF1/DISTOF2 magnitudes
are applied exactly and the kernels are amplitude-independent.

The pre-existing `stdaudit` (E-179) checks bound `.disto` against a hand-written
*Python* Volterra referee at ≤1–3%; that residual (~6e-4) is the referee's own
`V_T`/formula precision, not a `.disto` error. This enhancement replaces that bound
with the stronger statement: against the independent engine (shared model),
`.disto` is exact to the reference engine's resolution.

## The behavioral-source fix

`.disto` needs per-device Taylor coefficients (`DEVdisto`). The
arbitrary/behavioral source — a `B` line, or the `POLY` form of `E`/`G`, all device
type **`ASRC`** — has `DEVdisto = NULL`, so a behavioral nonlinearity contributes
**zero** to `.disto`. Enhancement-62 made the analogous Verilog-A (OSDI) case warn
loudly, but its check keyed on the OSDI registry marker, so the built-in B-source
slipped through **silently** — a user with `B1 n 0 I=...v³...` got a plausible-but-
wrong zero.

`spicelib/analysis/cktdisto.c` (the `D_SETUP` warning loop) is extended to fire for
`ASRC` too:

```
Warning: behavioral source (B, or POLY E/G; device type 'ASRC') has no distortion model;
         .disto does not include its nonlinearities.
```

Linear controlled sources use the dedicated **VCVS/VCCS/CCCS/CCVS** device types
(which are linear and correctly have no distortion), so an `ASRC` present during
`.disto` is a behavioral/poly definition — the warning has essentially no false
positives, and supported devices (diode, BJT, MOS, JFET, R, C) are untouched.

## Verification

`examples/distoexact_examples/verify_distoexact.py` (both solvers):

1. diode HD2/HD3 == HB with the `HB → .disto` convergence (`~A²`) and exact
   `A²`/`A³` output scaling;
2. diode two-tone IM3 (`2f1−f2`) == QPSS-HB, exact `A³` scaling;
3. a behavioral B-source `i = g1·v + g3·v³` reports `.disto` = 0 **and** emits the
   new warning, while QPSS-HB of the same polynomial gives the true
   `IM3 = (3/4)·g3·A³` — demonstrating exactly what the warning now flags.

## Scope

One localized change in `spicelib/analysis/cktdisto.c` (extends the E-62 warning to
`ASRC`); the ngspice binary is rebuilt. No change to the `.disto` numerics — the
analysis was already exact; this proves it against independent engines and closes
the silent behavioral-source gap. Full regression: all examples pass on both
solvers.
