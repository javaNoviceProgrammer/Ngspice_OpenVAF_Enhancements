# Enhancement-828: `pss` and `hb` fire `@(final_step)`, at the end of the period, on the steady state

**Scope:** F12 of the
[ngspice + OSDI hunt of 2026-10-08](../docs/bug_hunts/2026-10-08_ngspice-osdi-hierarchy-sweeps-events-and-outputs.md).

ngspice:
- `spicelib/analysis/dcpss.c`: `DCpss` fires the final step once the period is confirmed,
  before its small-signal reports.
- `frontend/com_hb.c`: `com_hb` puts the steady state at t = T into `CKTrhsOld` and fires the
  final step.
- `osdi/osdiload.c`: `OSDIforgetBiasPoint`, declared in `include/ngspice/osdiitf.h`.

`examples/rebinfinal_examples/` (section [3], four checks). **ngspice only.**

**Suites:** [`rebinfinal_examples`](../examples/rebinfinal_examples/) 15 of 15 per solver (2 of
the 4 checks in [3] fail on the E-825 binaries; the other two are the `tran` and `qpss`
controls). The full sweep, 545 of 545.

## What was wrong

A module counting its step events, in a driven RC deck:

| analysis | `initial_step` | `final_step` |
|---|---|---|
| `tran 1n 2u` | 1 | 1 |
| `.pss 1meg 1u b 1024 10 50 5u` + `run` | 1 | **0** |
| `hb 1meg 8` | 1 | **0** |

Enhancement-683 made every analysis fire `@(final_step)` once. `pss` and `hb` end in their own
code, and neither called it. A model that closes a file or reports a tracked peak there never
did under them.

## The change

- **`pss`.** `DCpss` fires the final step when the period is confirmed. `CKTrhsOld` then holds
  the last accepted point, the end of the steady-state period, before the Jacobian report and
  the PAC/pnoise/PXF/PSP sweeps load the devices at the retained samples. A run relaunched at a
  corrected frequency fires in its own confirmed branch, and the outer run falls through, so
  the step fires once.
- **`hb`.** HB's last point is the end of the period, t = T. Each node's voltage there is the
  sum of its two-sided harmonics: cos(kωT) = 1, and the imaginary parts of a real signal
  cancel. `com_hb` puts that into `CKTrhsOld`, with the time T, and fires the step.

  HB assembles its harmonic Jacobian from small-signal loads at every sample, and each of those
  re-took Enhancement-677's bias-point capture. The final step evaluates at that capture when
  it is valid, so it read the last sample's solution: −0.14895 V where the steady state is
  −0.14515 V. `OSDIforgetBiasPoint` drops the capture first.

## The checks

`rebinfinal_examples` [3], the driven RC deck with the counting module:
- `pss`: one final step after one initial step (was none). It sees the value its own
  time-domain plot ends on.
- `hb 1meg 8`: one final step (was none). It sees the sum of the real parts of node b's
  harmonics, −0.14515 V.
- `tran` and `qpss` (controls): one final step each.

## Limits

- `hbosc`, the autonomous HB command, was not checked.
