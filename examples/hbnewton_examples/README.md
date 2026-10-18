# hbnewton_examples — Enhancements 902 and 903

The harmonic-balance Newton on overdriven stages: F8 of the
[analyses correctness campaign of 2026-10-16](../../docs/bug_hunts/2026-10-16_ngspice-openvaf-r-analyses-correctness-campaign.md).
`hb` gave up on 5 of 20 overdriven common-emitter stages after minutes of source stepping, its
residual stalled at 1e-10.

The stages are the campaign's Family B common-emitter stages: a Gummel–Poon BJT driven into
saturation, whose diffusion capacitance (`tr` = 5 ns) swings through orders of magnitude each
period. The reference is a settled transient run by the suite, its harmonics fitted on whole
periods.

[E-902](../../enhancements_doc/Enhancement-902.md), the Jacobian:
- **[1]** Seed 111 at K = 16 converges.
- **[2]** Seed 111 at K = 48 converges, harmonics 0 to 6 within 1e-4 of the transient.
- **[3]** The last level ends quadratically: its last step cuts |F| at least 100 times.

[E-903](../../enhancements_doc/Enhancement-903.md), the spectrum of a real signal:
- **[4]** Seed 105 at K = 48 converges.
- **[5]** Every node's dc harmonic is real, exactly.

Both:
- **[6]** Sparse and KLU take the same iterations and continuation steps.
- **[7]** A two-tone `qpss … hb` of the stage converges.

Run: `python3 verify_hbnewton.py` (7 checks per solver, about 25 s each). On the E-901 binaries
all 7 fail; the stalls there take about 30 minutes.
