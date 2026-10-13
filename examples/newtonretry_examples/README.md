# newtonretry_examples — Enhancement-878

[E-878](../../enhancements_doc/Enhancement-878.md): F5 of the
[transient stress campaign of 2026-10-12](../../docs/bug_hunts/2026-10-12_transient-sparse-klu-stress-campaign.md).

`PREDICTOR` is not compiled in, so a transient step starts at `CKTrhsOld`. After a step whose
Newton iteration failed, that held the failed iteration, and the retry started there. A Van der
Pol oscillator built from a cubic B-source ran one iteration out to 1e10 V and beyond; from there a
cubic needs some 60 Newton steps back against `itl4`'s 10, so no smaller step converged, and the
run ended in "Timestep too small" under every method, solver and tolerance. A retry now starts
where the step started.

The checks, on that oscillator (limit cycle peak 2.0198 V, scipy Radau):
- **[1]** It runs to the end under trap, Gear, `trbdf2` and `sdirk`.
- **[2]** At `reltol=1e-6` its peak is within 0.1 % of 2.0198 V.
- **[3]** With the cubic's argument clamped at ±1e10 V it also runs.
- **[4]** (control) Clamped at ±1 kV, which the true path never reaches, it runs at
  `reltol=1e-6` and peaks within 0.1 % of 2.0198 V.

Run: `python3 verify_newtonretry.py` (4 checks per solver). On the E-875 binaries [1] to [3] fail.
