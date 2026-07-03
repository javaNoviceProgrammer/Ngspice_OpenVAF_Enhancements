# Enhancement-27 — `idtmod(...)` modulo-integrator fix (version11)

This document describes the change made to **OpenVAF-r** in the `version11/`
directory to fix **`idtmod(expr, ic, modulus[, offset[, ...]])`**, the Verilog-AMS
modulo time-integrator (the standard VCO/PLL phase integrator). `idtmod` compiled
and its integration was correct for the first period, but the modulo **wrap** was
broken — and there was a second, unrelated argument bug.

## The two bugs

**1. The modulo wrap diverged.** `idtmod` lowers to an implicit DAE equation whose
reactive residual is the integrated state `q = val` (so `d(val)/dt = expr`). The
old lowering (`lower_integral`) detected `val > modulus` and set the residual to
`[val − min, F_ZERO]` — forcing `val = min` **and zeroing the reactive residual**.
But the transient integrator computes the branch current from the reactive
residual's history: at the wrap step it becomes `≈ (0 − q_{n-1})/dt` with
`q_{n-1} ≈ modulus`, an enormous term the resistive part then "cancels" by driving
`val ≈ q_{n-1}/dt`. So the state either **got stuck** (a VCO froze at ~0.297) or
**blew up** (a sawtooth shot to ~−799) at the first wrap. Only the first period —
before any wrap — worked.

**2. The offset argument was wrong.** For `idtmod(expr, ic, modulus, offset)` the
offset was read from `args[2]` (which is the *modulus*) instead of `args[3]`, so
`IdtKind::ModulusOffset` used the wrong offset entirely.

## The fix

Integrate the DAE **state unbounded** — plain integration in the residual, exactly
like `idt`, with **no** discontinuity for the transient integrator to trip over —
and apply the modulo wrap only to the **returned value**:

```
result = offset + floor_mod(val − offset, modulus),   floor_mod(x, m) = x − m·floor(x/m)  ∈ [0, m)
```

so the returned value lands in `[offset, offset+modulus)` (correct even when the
integral goes negative), and the offset now reads `args[3]`. Because the DAE state
stays smooth, the transient integrator never sees the wrap discontinuity, so it no
longer diverges. `hir_lower/src/expr.rs` only — no OSDI ABI change, no ngspice
change.

## Verification

`examples/idtmod_examples/verify_idtmod.py` (`ALL PASS`):

- **VCO** — a modulo-1 phase drives `sin(2π·phase)`; the output tracks
  `sin(2π·freq·t)` to ~1e-4 across three periods (it used to freeze after one);
- **sawtooth** — `idtmod(1, 0, 2, off)` produces a clean sawtooth whose value stays
  in `[off, off+2)` and wraps correctly for both `off=0` and `off=5` (~1e-16 error
  away from the wraps) — exercising the fixed offset argument.

Plain `idt` (no modulus) is unchanged and still exact, and every prior example
folder still passes.

## Known limitations

- The DAE state integrates unbounded, so over very long runs (many millions of
  wraps) the phase magnitude grows and the wrapped output loses a little floating-
  point resolution. A bounded-state modulo integrator would need simulator-side
  breakpoint/state-reset support that OSDI does not expose; the unbounded-state
  form is correct and, crucially, does not diverge.
- The `tol`/`nature` argument forms are accepted but tolerance is not separately
  modelled (unchanged from before).
