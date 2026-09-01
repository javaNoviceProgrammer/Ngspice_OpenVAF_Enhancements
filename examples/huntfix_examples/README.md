# huntfix — the bug-hunt round's fixes, pinned

A one-hour adversarial hunt over ngspice + OSDI surfaced 19 findings;
16 were fixed (3 retracted as artifacts of the hunt harness itself).
This suite pins the fixes that live outside the `osdimc` machinery
(whose own hardening is pinned in `examples/osdimc_examples/`):

- **The headline (F7): a noise-only contribution must not reclassify a
  branch.** BSIM4's access-region noise — `I(di,d) <+ white_noise(...)`,
  reversed spelling, lowered *after* the conditional `V(d,di) <+ 0.0`
  collapse hint — used to erase the collapse from the compiled topology
  through the last-write-wins `IsVoltageSrc` place: the internal drain
  floated and the whole transistor conducted **exactly zero at every
  bias**, silently. LRM 4.6.4 makes noise zero in large-signal analyses,
  so it carries no source kind; `hir_lower` now keeps the classification.
  Pinned on the minimal shape (`hfnoise.va`) and on stock `bsim4.va`
  itself, which conducts −1.27 mA at Vgs=Vds=1 V.
- `altermod` of a **string** parameter works (`@mm[mode] = "quad"` used to
  die with `no such vector "quad"`); a whole-**array** altermod gets
  honest per-element guidance instead of "has no parameter", and the
  per-element spelling is verified numerically.
- Repeated `run` of a **multi-analysis deck** (.op+.ac+.tran) loses no
  jobs (the batch epilogue's `.op` save-all was analysis-restricted).
- `alter` **refuses non-representable values** (`1e400` used to silently
  make a resistor an open circuit with rc=0).
- **Rawfile roundtrips keep qualified cross-plot names** (`dc2.i(v1)`
  came back as the unaddressable `i(dc2.i(v1))`).
- `alter` of a model parameter through a device name **points at
  `altermod`** instead of denying the parameter exists.

Run `python3 verify_huntfix.py` — 12 checks, both solvers.
