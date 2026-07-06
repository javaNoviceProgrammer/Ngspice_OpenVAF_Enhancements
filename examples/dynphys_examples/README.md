# Enhancement-75 — dynamic physics validation

The companion of Enhancement-57's `physcheck_examples/`: where that suite
validated the **static** laws of compiled industry models (DC curves,
autodiff Jacobians, noise), this one validates the **charges** — the
reactive paths of the toolchain: `ddt()` lowering, the reactive autodiff
Jacobian, the jω AC stamping, and the transient integrator, checked
against physics that must hold *across analyses*.

## The laws

1. **One charge model, two code paths** — PSP103's gate capacitance
   measured from AC (`Im(i_g)/ω`, the jω reactive Jacobian) equals the
   capacitance measured from a slow transient ramp (`i_g/(dV_g/dt)`, the
   integrator) across the accumulation-to-inversion transition: worst
   relative difference 6×10⁻⁴ over a 4× capacitance swing.
2. **Charge conservation** — over a closed gate-bias loop the net gate
   charge integrates to 8×10⁻⁵ of the one-way charge: the charge model is
   conservative and the integrator preserves it.
3. **Junction charge extraction** — the leakage-subtracted transient
   integral of diode_cmc's reverse-ramp current equals ∫C(V)dV of the
   AC-measured capacitance (the physical charge-extraction technique) to
   0.5%; C(V) is monotone under reverse bias. The leakage subtraction is
   itself the instructive part: the raw integral is 200× too large —
   reverse DC current dominates a 200 µs ramp.
4. **Linear response** — a PSP103 common-source stage driven with a 1 mV
   transient sine reproduces the `.ac` prediction to 2×10⁻⁶ in magnitude
   and 0.001° in phase (quadrature demodulation of the steady state) at
   1 MHz and 10 MHz: the reactive matrix is the same matrix in both
   analyses.

## Files

- `verify_dynphys.py` — the suite (9 checks); needs the `VA_TEST/` corpus
  and skips gracefully without it.
- `plot_dynphys.py` — renders `plots/*.png` from the verify run's
  artifacts (run the verify first).
