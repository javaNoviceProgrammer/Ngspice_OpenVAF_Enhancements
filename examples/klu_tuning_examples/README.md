# klu_tuning_examples — KLU matrix reordering + scaling controls (Enhancement-152)

The KLU direct linear solver (opt-in via `.option klu`) previously ran on its
compiled-in defaults: **AMD** fill-reducing ordering, **max** row scaling, and the
**BTF** (block-triangular-form) permutation on. Enhancement-152 exposes those
knobs — plus a fixed `klu_memgrow_factor` — as `.option`s, so the reordering and
scaling can be tuned per circuit instead of being fixed.

## Options

```
.option klu klu_ordering=amd|colamd     fill-reducing ordering (default amd)
.option klu klu_scale=none|sum|max      matrix row scaling      (default max)
.option klu klu_btf=on|off              block-triangular form   (default on)
.option klu_memgrow_factor=<f>          KLU work-array growth   (default 1.2)
```

- **`klu_ordering`** — the fill-reducing permutation KLU computes before
  factoring. **AMD** (approximate minimum degree) is the default; **COLAMD**
  (column approximate minimum degree) can produce less fill on some structures.
- **`klu_scale`** — row equilibration applied before factoring: **max** (divide
  each row by its largest magnitude, the default), **sum** (by the row's
  1-norm), or **none**. Scaling improves the conditioning of badly-scaled
  matrices.
- **`klu_btf`** — whether KLU first permutes the matrix to block-triangular form
  (default on). Turning it off factors the whole matrix as one block.
- **`klu_memgrow_factor`** — the factor by which KLU grows its work arrays when it
  runs out of space (this option was previously a no-op — it silently collapsed
  to a boolean; Enhancement-152 fixes it to take the real value).

All of these are **safe**: they change only *how* KLU factors the matrix, never
the physical solution. They apply only under `.option klu` (the KLU solver).

## Files

- **`klu_tuning_demo.cir`** — a resistor grid solved with the default ordering and
  again with COLAMD + sum scaling + BTF off; both give the identical node voltage.
  Run with `ngspice -b klu_tuning_demo.cir`.
- **`verify_klu_tuning.py`** — validation (KLU-only, so no dual-solver harness):
  1. every ordering/scaling/BTF setting gives the **physically identical**
     solution (agree to ~1e-14 relative);
  2. the knobs actually **reach KLU** — AMD vs COLAMD, and scale=max vs
     scale=none, change the factorization arithmetic, so the full-precision
     result differs in its last digits (a tiny, deterministic, nonzero diff);
  3. an invalid value (`klu_ordering=foo`, …) is rejected with a warning;
  4. the compiled-in defaults are **unchanged** — a plain `.option klu` equals
     `klu_ordering=amd klu_scale=max klu_btf=on` bit-for-bit;
  5. a wide-dynamic-range (badly-scaled) network solves correctly under every
     scaling mode.

```
python3 verify_klu_tuning.py
```

## Notes

- These options only affect the **KLU** solver; the default **Sparse 1.3** solver
  has its own reordering (`spOrderAndFactor`) and is unaffected. See
  [`ngspice_solver_notes.md`](../../docs/internals/ngspice_internals/ngspice_solver_notes.md)
  for the KLU-vs-Sparse comparison.
- On most well-conditioned circuits AMD/max/BTF-on (the defaults) are already a
  good choice; the value of the knobs is on unusual matrix structures (where a
  different ordering reduces fill) or badly-scaled matrices (where a scaling
  choice matters).
- Every SPICE deck's first line is the **title** (ignored by the parser).
