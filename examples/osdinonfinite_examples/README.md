# osdinonfinite_examples — Enhancement-854

[E-854](../../enhancements_doc/Enhancement-854.md): F10 of the
[second robustness and correctness campaign of 2026-10-10](../../docs/bug_hunts/2026-10-10_ngspice-openvaf-r-second-robustness-campaign.md).

`V(o) <+ ln(V(x))` is evaluated at Newton's zero start: ln(0) = −∞. Every homotopy restarts from
the same point, and the operating point ended "Timestep too small; cause unrecorded", naming
neither the device nor the value. Under KLU it named the singular node instead.

Each OSDI instance's right-hand-side rows and Jacobian entries are now checked as it loads. A
value that is not finite makes the instance the cause the failure names. A warning, once per
instance, says which value and at what terminal voltages.

The models:
- `lnout.va` — the campaign's `ln(V(x))` output.
- `divg.va` — a current 1/(1 + 1/V): 0 at 0 V, with a derivative that is not.
- `lnguard.va` — (control) the same `ln()` with a guard.

The checks:
- **[1]** `lnout` at the zero start: the op fails "trouble with lm-instance n1", not "cause
  unrecorded".
- **[2]** The warning names `n1`, module `lnout`, the residual of `flow(o)`, NaN and x = 0 V,
  once.
- **[3]** The same in a transient: the initial timepoint names `n1`.
- **[4]** `divg`: named too.
- **[5]** (control) `lnguard` converges to ln(1.056), with no warning.

Run: `python3 verify_osdinonfinite.py` (5 checks per solver). On the E-852 binaries [1] to [4]
fail.
