# Enhancement-739: `.disto` for compiled devices includes the nonlinearity of their charges — the driver built its Volterra tensors under operating-point evaluation flags, which never compute the reactive Jacobian, so every finite difference of that Jacobian was zero and the j·ω pass rotated an empty tensor; a device whose only nonlinearity is a charge reported no distortion at all, and a diode's diffusion charge was a sixth low in HD2 and two fifths low in HD3 against the transient; two flags on the evaluation

**Scope:** F9 of the
[options-and-convergence hunt](../docs/bug_hunts/2026-09-26_ngspice-osdi-options-and-convergence.md).
One file changes, `ngspice-46/src/osdi/osdidisto.c`: the `OsdiSimInfo` the
distortion driver hands to `osdi_numdisto_build` gains `CALC_REACT_JACOBIAN |
CALC_REACT_RESIDUAL`. The compiler, the OSDI ABI, the numeric differencing
in `osdidistonum.c`, the built-in devices' distortion code and every other
analysis are untouched.

**Suites:** `osdidisto` 12 of 12 (8 of 12 on the E-738 binary: the four
checks added here fail there, the charge polynomial reporting 0 + j0);
`distoexact` under both solvers; `limitdisto` 7 of 7; the full sweep 532
of 532.

## What was wrong

E-359 builds the second- and third-order tensors a Volterra analysis needs
by evaluating each compiled instance at perturbed node voltages and
differencing the Jacobian arrays the model writes back. It handles the
resistive and the reactive Jacobian in two passes, and rotates the reactive
result by j·ω "exactly as `diodisto.c` does". The evaluations it perturbs
ran under flags that "mirror a DC operating-point eval":

```
CALC_RESIST_JACOBIAN | CALC_RESIST_RESIDUAL | CALC_OP |
CALC_RESIST_LIM_RHS | ENABLE_LIM | ANALYSIS_DC | ANALYSIS_STATIC
```

A DC evaluation never computes the reactive Jacobian. So at every probe
step `write_jacobian_array_react` returned whatever the last transient or AC
evaluation had left in the instance, every finite difference of it was
zero, and the reactive tensor the second pass rotated was empty. The
resistive part was right to six digits — the suites compared it against
closed forms and against the built-in diode — and the charge part was
silently absent.

Measured on the E-738 binary. A module whose only nonlinearity is a charge,
`I(p,n) <+ ddt(c1·V + c3·V³)`, driven at 10 MHz with `distof1 0.1`, reports
0 + j0 in both harmonic plots, while a tight transient at the same drive
shows a second harmonic of 4.17 mV (5.9 % THD). The compiled diode of the
benchmark suite, which mirrors the built-in's junction and diffusion
charges, against the built-in on the same card, second harmonic of `v(a)`
at 10 MHz:

| diode card | compiled `.disto` | built-in `.disto` | transient `fourier` |
|---|---|---|---|
| no charge storage | −1.06562e-4 + j1.45169e-5 | −1.06561e-4 + j1.45169e-5 | — |
| `cjo=2p vj=0.8 m=0.4` | −8.47e-5 + j5.56e-5 | −8.53e-5 + j5.45e-5 | — |
| `tt=5n` | **−7.55e-5 + j6.32e-5** | −1.152e-4 + j1.57e-5 | 1.164e-4 at 82°, the built-in's |

The junction capacitance's share of the distortion is about 1 %, which is
the 1 % the `cjo` pair disagreed by; the diffusion charge's share is large,
and the transient's `fourier` sides with the built-in to three digits. The
two models' charges are the same function: a 10 MHz transient of the
`tt`-only pair agrees to 4e-6 V at reltol 1e-5.

## What changed

The driver's flags gain `CALC_REACT_JACOBIAN | CALC_REACT_RESIDUAL`, with a
comment saying why. Nothing else: the probe steps, the step sizes, the
node-coordinate tensors, the j·ω rotation and the frequency loop are E-359's
as they were. The operating point after a `.disto` equals the one before to
the bit, the invariant E-359 set, since the driver's last act is still the
unperturbed evaluation.

## Verification

`osdidisto` gains two models and four checks:

- `va/dst_qcube.va`, a charge polynomial `Q = c1·V + c2·V² + c3·V³` at zero
  bias, whose harmonics have a closed form: with `I = dQ/dt` the n-th order
  current source is j·ω_out times the n-th order term of Q, solved at ω_out
  against the source resistance and the linear capacitance c1. Check [9]
  pins HD2 and HD3 against it at 1 MHz; measured 1.4e-9 and 1.6e-12
  relative, bound 1e-6, and 0 + j0 before this change.
- `va/dst_diodeq.va`, the benchmark suite's `vadiode.va` under the suite's
  name, with junction and diffusion charge. Checks [10] and [11] compare its
  HD2 and HD3 and its two-tone f1+f2, f1−f2 and IM3 against the built-in
  diode on the same card at 1, 10 and 100 MHz as complex values; worst
  relative difference 6.1e-6 (the `$vt` constant), bound 1e-4; before this
  change the `tt` term put the second harmonic 15 % and the third 40 % off.
- Check [12] is the one the suite lacked: the charge polynomial's `.disto`
  against the time domain, the same drive as a real sine, a tight transient
  and ngspice's own `fourier`. HD2 3.105e-4 against 3.096e-4, HD3 1.145e-4
  against 1.140e-4; the tolerances (2 %, 5 %) are the transient's.

The three earlier `osdidisto` oracles, `distoexact` under both solvers and
`limitdisto` are unchanged and pass. Sparse and KLU give the same
charge-polynomial numbers to the bit.

## What this does not do

- It does not change the resistive path, the built-in devices' `.disto`,
  or any analysis other than `.disto`.
- It does not make the compiled `.disto` exact: the tensors are still
  finite differences of the analytic Jacobian, accurate to the 1e-9 the
  checks measure, as E-359 states.
- It does not revisit E-359's step-size rule for charges whose curvature
  differs greatly from the resistive part's; the exponential diffusion
  charge of a diode passes at 6e-6 against the built-in, and nothing
  measured asks for more.
