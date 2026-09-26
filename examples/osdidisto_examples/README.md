# `.disto` for Verilog-A devices — `osdidisto` (Enhancement-352, 359, 739)

`.disto` is a Volterra-series analysis: it needs each device's Taylor
expansion to third order, not the operating-point linearisation the Jacobian
gives. E-352 had the compiler emit those coefficients; E-359 replaced that
with numerical differencing of the model's analytic Jacobian at the
operating point in ngspice, so nothing is needed from the compiler. E-739
made the differencing cover the reactive Jacobian too, so the nonlinearity
of a device's charges enters the kernels.

## Files

- `verify_osdidisto.py` — the checks; compiles the models in `va/` itself.
- `va/dst_cubic.va` — a current polynomial whose Taylor coefficients are its
  parameters, for closed-form oracles.
- `va/dst_mixer.va` — a pure cross term, for the multi-variable oracle.
- `va/dst_diode.va` — an ideal diode, for the two-tone comparison with the
  built-in.
- `va/dst_qcube.va` — a charge polynomial (E-739), for the reactive
  closed-form oracle and the transient comparison.
- `va/dst_diodeq.va` — the benchmark suite's `vadiode.va` under the suite's
  name, junction and diffusion charge included (E-739).

## Checks

| # | what | oracle |
|---|---|---|
| 1 | HD2 and HD3 of the current polynomial | closed form, no simulator |
| 2 | HD2 scales as A², HD3 as A³ | arithmetic |
| 3 | two-tone f1+f2, f1−f2, IM3 of the ideal diode | ngspice's built-in diode |
| 4 | a pure cross term | closed form |
| 5 | a linear model yields no distortion | zero |
| 6 | a ground-referenced nonlinearity contributes | closed form |
| 7 | a second model type does not silence the first | the first alone |
| 8 | a zero-step sweep is refused | no output |
| 9 | HD2 and HD3 of the charge polynomial (E-739) | Volterra closed form: the n-th order current source is j·ω_out times the n-th order term of Q |
| 10 | HD2 and HD3 of the diode with charge storage at 1, 10, 100 MHz (E-739) | the built-in diode on the same card, complex values |
| 11 | its two-tone products at the same frequencies (E-739) | the built-in diode |
| 12 | the charge polynomial's `.disto` against the time domain (E-739) | a tight transient and ngspice's `fourier` |

Checks 9 to 12 fail on a binary before E-739: the charge polynomial reports
0 + j0, the diode's diffusion charge is a sixth low in HD2 and two fifths in
HD3.

## Run

```
python3 examples/osdidisto_examples/verify_osdidisto.py
```
