# XSPICE integrators are second-order accurate (Enhancement-312)

Found while oracle-checking the XSPICE `s_xfer` (Laplace transfer-function) code
model against a closed-form transient. Its error fell only as **O(h)** — first
order — where every native ngspice storage element (capacitor, inductor) is
second order. Halving the timestep barely halved the error instead of quartering
it. Two independent causes, one shared across *all* integrating code models and
one specific to `s_xfer`.

**(a) The shared integrator was backward Euler, not trapezoidal.** Every XSPICE
code model that integrates — `s_xfer`, `int`, `d_dt`, … — funnels through
`cm_static_integrate()` in
[cm.c](../../ngspice-46/src/xspice/cm/cm.c). Its trapezoidal, order-2 arm carried
a self-documented stand-in (`/* WARNING - This code needs to be redone */`) that
works out algebraically to `y(n) = y(n-1) + h·u(n)` — backward Euler, an O(h)
method. It is now the real rule `y(n) = y(n-1) + (h/2)(u(n)+u(n-1))`. The previous
integrand `u(n-1)` lives in the spare state double `cm_analog_alloc` already
reserves per integrator, rotated through the `CKTstates[]` history for free — the
standard SPICE companion-model idiom.

**(b) `s_xfer` fed its loop back one step late.** Its controller-canonical
feedback read the fed-back integrator states from the **previous timestep**
(`cm_analog_get_ptr(i,1)`), making the loop explicit/lagged and capping it at
O(h) on its own. It now reads the **current-iteration** states
(`cm_analog_get_ptr(i,0)`), solving the loop implicitly within each Newton step.

Both integration methods — trapezoidal and Gear — now converge at O(h²).

## Verify

```sh
python3 verify_sxferorder.py
```

Six checks under both linear solvers. The distinguishing signature of the bug is
the **convergence order**, which a single binary can measure on its own: halving
the timestep quarters an O(h²) error but only halves an O(h) one. So the order
test **fails on a pre-fix build** (ratios ~2, fitted p ≈ 1.0) and **passes here**
(ratios ~4, p ≈ 2.1) with no reference binary needed. Oracle: a first-order
low-pass `H(s)=1/(1+τs)` driven by `sin(ωt)` from rest, whose exact response
`y(t) = A[ωτ·e^(−t/τ) + sin(ωt) − ωτ·cos(ωt)]` (A = 1/(1+(ωτ)²)) has an LHP pole
that damps the startup transient, leaving a clean O(h²) steady-state error. A
second, resonant, second-order `s_xfer` driven at resonance confirms the now-
implicit feedback stays convergent and hits its analytic peak gain 1/(2ζ)=1.667.
The XSPICE code models load from the prebuilt bundle via `SPICE_LIB_DIR` (set by
`_setup`); if unavailable in this checkout, the test self-skips.
