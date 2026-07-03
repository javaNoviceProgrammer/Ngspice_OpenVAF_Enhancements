# idtmod_examples — `idtmod(...)` modulo integrator fix (Enhancement-27)

Demonstrates **`idtmod(expr, ic, modulus[, offset])`**, the Verilog-AMS modulo
time-integrator (the standard VCO/PLL phase integrator), using **version11's own**
`openvaf-r` and `ngspice-46`.

## What was broken

`idtmod` integrated correctly for the **first period**, but at the first modulo
wrap it broke:

- the DAE integrator's reactive residual was forced to zero at the wrap while its
  previous value was `~modulus`, so the trapezoidal `d/dt` term exploded — the
  state got **stuck** (a VCO froze at ~0.297) or **diverged** (a sawtooth shot to
  ~−799);
- the **offset** form `idtmod(expr, ic, modulus, offset)` read `args[2]` (the
  *modulus*) as the offset, so it used the wrong value entirely.

## The fix

Integrate the DAE **state unbounded** (smooth — no discontinuity for the transient
integrator to trip over) and apply the modulo wrap only to the **returned value**:

```
idtmod = offset + floor_mod(∫expr − offset, modulus)
```

(`floor_mod(x,m) = x − m·floor(x/m)` stays in `[0, m)`). The offset argument is
also fixed to `args[3]`. This is a `hir_lower`-only change — no OSDI/ngspice change.

## Run

```
python3 verify_idtmod.py
```

Expected (`ALL PASS`):

- **VCO** — a modulo-1 phase drives `sin(2π·phase)`; the output tracks
  `sin(2π·freq·t)` across several periods (it used to freeze after one);
- **sawtooth** — `idtmod(1, 0, modu, off)` produces a clean sawtooth whose value
  stays in `[off, off+modu)` and wraps correctly, for both `off=0` and `off=5`
  (the offset form used to read the modulus as the offset).

## Notes / limitations

- The DAE state integrates unbounded, so over *very* long runs (many millions of
  wraps) the phase magnitude grows and floating-point resolution of the wrapped
  output degrades slightly. A bounded-state modulo integrator would need
  simulator-side breakpoint/state-reset support (not available through OSDI); the
  unbounded-state form is correct and does not diverge.
- The `tol`/`nature` argument forms are accepted; tolerance is not separately
  modelled (as before).
