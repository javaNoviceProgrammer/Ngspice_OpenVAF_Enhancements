# Enhancement-75 — dynamic physics validation: the reactive paths cross-checked

This document describes Enhancement-75: the **dynamic** companion of
Enhancement-57's physics suite. Where physcheck validated the static laws
of compiled industry models (DC curves, autodiff Jacobians, noise), this
suite validates the **charges** — the reactive paths of the toolchain
(`ddt()` lowering, the reactive autodiff Jacobian, the jω AC stamping,
and the transient integrator) against physics that must hold *across
analyses*. Like E-57, the deliverable is the guard itself: **no toolchain
defects were found**, and no compiler or ngspice sources changed.

## The four laws (9 checks, ALL PASS)

**[1] One charge model, two code paths.** PSP103's gate capacitance from
AC (`Im(i_g)/ω` — the jω reactive Jacobian) equals the capacitance from a
slow transient ramp (`i_g/(dV_g/dt)` — the integrator on the same charge
model) at five biases across the accumulation-to-inversion transition:
worst relative difference **6.3×10⁻⁴** over a 4× capacitance swing
(305 → 1235 fF), plus the physically-required monotone rise.

**[2] Charge conservation.** Over a closed gate-bias loop (0 → 1.2 → 0 V
triangle) the net gate charge integrates to **7.8×10⁻⁵** of the one-way
charge: PSP103's charge model is conservative, and the integrator
preserves that property through 12 000 accepted timepoints.

**[3] Junction charge extraction.** The transient integral of
diode_cmc's current over a slow reverse ramp, **with the static I(V)
leakage subtracted point-wise** (the physical charge-extraction
technique), equals ∫C(V)dV of the AC-measured capacitance over the same
interval to **0.5%**; C(V) decreases monotonically under reverse bias.
The subtraction is the instructive part: the raw integral is **200× too
large** — reverse DC leakage (~nA) dominates the ~20 pA displacement
current over a 200 µs ramp. A dynamic check that forgets the static
component measures the wrong physics.

**[4] Linear response.** A PSP103 common-source stage (1 kΩ load) driven
with a 1 mV transient sine reproduces the `.ac` prediction — obtained
from the same operating point — to **1.5×10⁻⁷/1.7×10⁻⁶ in magnitude and
0.000°/0.001° in phase** at 1 MHz and 10 MHz (quadrature demodulation of
the steady state, four whole cycles after ten settling cycles): the
reactive matrix built by the transient integrator is the same matrix the
AC analysis factorizes.

## Why these four

Together they close the loop E-57 opened: static Jacobian ≡ DC curves
(E-57 [4]) and now reactive Jacobian ≡ transient charge ≡ AC imaginary
part, on flagship corpus models rather than toy circuits. A regression
anywhere in the `ddt()`/charge pipeline — lowering, the reactive
dimension of autodiff, OSDI's `load_jacobian_react`/`load_spice_rhs`, the
integrator interface — lands in one of these numbers.

## Examples (`dynphys_examples/`, 9 checks, ALL PASS)

`verify_dynphys.py` (corpus-based, skips gracefully without `VA_TEST/`;
compiles with relative paths per the E-74 provenance rule) +
`plot_dynphys.py` rendering the committed plots: the Cgg(V) transition
curve (transient-continuous, AC points on it), the antisymmetric
closed-loop gate current, and the steady-state sine segment.

## Regression

No compiler or ngspice source changes; all 68 example verify suites pass
(this suite included), the integration suite 28/28, the VA_TEST corpus
compiles 92/92.
