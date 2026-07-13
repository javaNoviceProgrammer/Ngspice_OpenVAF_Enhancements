# Enhancement-179 — standard-analyses audit: referee battery + three fixes

The gap-analysis doc marks the "Standard analyses (analog)" table all on-par with the commercial reference — but `.tf`, `.sens`, `.disto`, and the `.meas` evaluators are 1990s SPICE3 code whose *values* had never been checked against independent physics. This audit builds the referees (the [E-171](Enhancement-171.md)/[175](Enhancement-175.md)/[177](Enhancement-177.md)/[178](Enhancement-178.md) pattern: probe the region no prior test could see), certifies most of the table, and fixes the three defects the referees caught — one of them 35 years old.

![stdaudit](../examples/stdaudit_examples/stdaudit.png)

## The fixes

**1. `.tf` current-output impedance — a Berkeley SPICE3 bug (tfanal.c).** For `.tf i(vm) vin` the output impedance solve forces 1V on the sense branch and inverts the resulting branch current — but clamps it as `1/MAX(1e-20, rhs)`. The branch current is *negative* for every passive network (the input-impedance path immediately above divides by `−rhs`), so the clamp always won: **every current-output `.tf` reported output impedance 1e20**, since SPICE3 (1988). Fixed with the sign and `fabs` guard of the input path; the feedback-amp referee now gets RL + node-Thevenin to all printed digits (`1000.990` vs hand-computed `1000.990001`).

**2. KLU AC sensitivity silently truncated to one point (cktsens.c).** The KLU complex-conversion block inside the AC frequency loop reused `i` — the outer loop variable — for its `DEVmaxnum` device walk, so after the first frequency `i ≈ DEVmaxnum` terminated the sweep. One correct row, no error message. This was in the [E-114](Enhancement-114.md) KLU-enablement code, and E-62's single-point AC-sens check is exactly why it survived: the surviving point *was* correct. Fixed (local index; the dead second block hardened too); the full sweep now matches the analytic `dV/dC = −jωR/(1+jωRC)²` to 6 digits under both solvers.

**3. `.meas DERIV{ATIVE}` implemented (com_measure2.c).** The measure parser has accepted `DERIV` since the SPICE3-era port, but evaluation fell into an explicit *"currently not supported"* stub (with an empty `#if 0 measure_deriv()` marked "still some more work to do...."). Implemented: a 3-point Lagrange-quadratic derivative on the nonuniform time grid (exact for the parabolic local model, robust to breakpoint-duplicated timepoints), in both `AT=val` and `WHEN expr` forms, sharing FIND's parse/locate flow. Verified against the analytic sine slope to 5 digits (`10882.7` vs `10882.796` at the v=1 rising crossing) and ≈0 at the crest. The `DERIVATIVE` and `INTEGRAL` long spellings from the manual are now accepted (only `DERIV`/`INTEG` matched before), and a pre-existing `-Wmissing-prototypes` warning in the same file is silenced.

## Measured-correct

- **`.disto`** — the 1990 Volterra kernels hold up impressively. HD2/HD3 match an analytic diode-kernel referee to ≤0.06% **including a frequency-dependent load** (the harmonic responses correctly use Z(2ω), Z(3ω) — the analog of the E-177 folding-frequency bug is *not* present); the two-tone SIM2 path (f1+f2, f1−f2, 2f1−f2) matches including third-order cascade terms; DISTOF1/DISTOF2 amplitude scaling is exactly quadratic/cubic/bilinear; and nonlinear junction-capacitance harmonics agree with the [E-134](Enhancement-134.md) Harmonic Balance engine to ~6 digits — two fully independent engines, 36 years apart.
- **`.noise` integrals** — `onoise_total²` ≡ the band-limited analytic (→ kT/C wide-band) to 0.06% at 20 pts/dec, and the flicker log-integral `KF·I²·ln(f2/f1)·Zt²` to 6 digits (`Nintegrate`'s power-law rule is exact on 1/f). The diode's per-generator summary slots are clean zeros after the E-178 sidewall fix.
- **`.sens`** — DC sensitivities at a *nonlinear* operating point (dv/dRs, dv/dIS — model parameters included) match central finite differences to 5–6 digits.
- **`.pz` at a nonlinear OP** — works; the E-62 "nonlinear pz quirk" was the input *convention*: a bias source sitting on the injection node shorts it, and ngspice's "input shorted on the way to the output" refusal is correct. The driving-point form (`.pz a 0 a 0 cur pol`) returns the linearized pole −(1/Rs+g_d)/C to 0.02% under both solvers.
- **`.op`/`.dc`/`.tran`/`.meas`** — hard-DC homotopy lands both solvers on the identical operating point; trap and Gear both track the analytic RC decay to ≤4e-7 at measure points; the `.meas` battery (RMS/AVG/PP/WHEN/INTEG) is exact to ~1e-6.

## Verification

[`examples/stdaudit_examples/verify_stdaudit.py`](../examples/stdaudit_examples/verify_stdaudit.py) — 8 checks × both solvers: disto vs Volterra (frequency-dependent), SIM2 + scaling, disto ≡ HB, noise integrals, `.tf` exact incl. the current-output fix (pre-fix 1e20 signature absent), `.sens` DC-vs-FD + the complete 3-point AC sweep (the KLU regression guard), nonlinear-OP pz, and the `.meas` battery incl. DERIV/INTEGRAL. Full example regression: 148/148.
