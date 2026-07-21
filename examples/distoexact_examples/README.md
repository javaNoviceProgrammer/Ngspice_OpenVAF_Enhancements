# `.disto` is machine-exact — and warns on behavioral nonlinearities (Enhancement-255)

A correctness proof on the RF/distortion frontier, in the E-251 (Harmonic-Balance)
mold: `.disto` (the classic 1990 Volterra small-signal distortion analysis) is
shown to be **machine-exact** against ngspice's own independent large-signal
engines, and the one common *unsupported* nonlinearity — a behavioral **B-source**
— now **warns** instead of silently reporting zero.

## The oracle-based proof

`.disto` reports the pure 2nd/3rd-order Volterra kernels scaled by the
DISTOF1/DISTOF2 source magnitudes — amplitude-independent physics. Harmonic
Balance and two-tone QPSS-HB are *independent* engines that include **all** orders;
at small drive `A` their harmonic / mixing amplitudes converge onto the Volterra
result with higher-order leakage `~A²`. So `HB(A) → .disto` as `A → 0` — exactly
the HB-proof structure (E-251) applied to distortion. Because HB and `.disto` share
ngspice's *identical* device model, model-constant ambiguity (V_T, the DC
operating point) cancels, so the agreement measures the `.disto` engine itself.

- **[1] Single-tone HD2/HD3 (diode) == HB.** As `A` shrinks 1e-3 → 1e-4 the
  HB-vs-`.disto` relative error tightens `4.0e-5 → 2.6e-7` (HD2), confirming
  `HB → .disto`; and `.disto`'s output scales *exactly* as `A²` (HD2) / `A³` (HD3),
  so the DISTOF1 magnitude is applied exactly and the kernels are
  amplitude-independent.
- **[2] Two-tone IM3 (2f1−f2, diode) == QPSS-HB** to `~1e-5`, with `.disto`'s IM3
  scaling exactly as `A³`.

The existing `stdaudit` checks bound `.disto` against a *Python* Volterra referee
at ≤1–3% (that residual is the referee's own V_T/formula precision). This proves
the tighter truth: against the independent engine, `.disto` is exact to the
reference engine's resolution.

## The behavioral-source fix (Enhancement-255)

`.disto` needs per-device Taylor coefficients (`DEVdisto`). The
arbitrary/behavioral source — a `B` line, or the `POLY` form of `E`/`G` (device
type `ASRC`) — has no such routine, so its nonlinearity contributes **zero** to
`.disto`. E-62 made the analogous OSDI (Verilog-A) case warn loudly; the B-source
slipped through *silently* because it is a built-in device. Now it warns:

```
Warning: behavioral source (B, or POLY E/G; device type 'ASRC') has no distortion model;
         .disto does not include its nonlinearities.
```

Check **[3]** exercises this: a B-source `i = g1·v + g3·v³` reports `.disto` = 0
**and** emits the warning, while QPSS-HB of the same polynomial gives the true
`IM3 = (3/4)·g3·A³` — showing exactly what the warning now flags. (Linear
controlled sources use the dedicated VCVS/VCCS/CCCS/CCVS devices, so they are
unaffected.)

## Verification

`verify_distoexact.py` runs the three checks under **both** solvers. Scratch decks
are `_*.cir` (gitignored).

## Scope

One-line change in `spicelib/analysis/cktdisto.c` (extends the E-62 warning loop to
the `ASRC` device); the ngspice binary is rebuilt. No change to the `.disto`
numerics — the analysis was already exact; this proves it and closes the silent
behavioral-source gap.
