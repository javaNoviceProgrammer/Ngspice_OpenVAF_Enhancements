# mutsystem_examples — Enhancement-872

[E-872](../../enhancements_doc/Enhancement-872.md): found while folding F4 of the
[Sparse and KLU correctness campaign of 2026-10-11](../../docs/bug_hunts/2026-10-11_sparse-klu-correctness-campaign.md).

`MUTtemp` groups coupled inductors into systems to check that each is positive definite. It
freed the systems at the end, while the inductors and couplings kept pointing at them; only
`INDsetup` cleared those pointers. A second `MUTtemp` with no setup between, as at every point of
a `dc temp` sweep, found them non-NULL. It took each pair to be in a system already and wrote
into freed memory: under Guard Malloc, a SIGSEGV in `MUTtemp`. No system was built again either,
so a coupling that went wrong at a later temperature was never reported.

The links are now cleared before the systems are freed, and each system's report is given once.

The checks:
- **[1]** L1 with `tc1=-0.02` turns negative at 100 °C in a `dc temp` sweep: the inductive-system
  report names it (E-869 was silent).
- **[2]** k = 1.5 through an 11-point temperature sweep: "not positive definite" is reported once,
  not at every point.
- **[3]** (control) k = 0.9 through the sweep: no report, 11 points.
- **[4]** The sweep under Guard Malloc runs to the end. This runs on macOS and is skipped where
  `/usr/lib/libgmalloc.dylib` is absent.

Run: `python3 verify_mutsystem.py` (4 checks per solver). On the E-869 binaries [1] fails, and
[4] dies with SIGSEGV.
