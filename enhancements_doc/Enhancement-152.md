# Enhancement-152 — KLU matrix reordering and scaling controls

This build's **KLU** direct linear solver (opt-in via `.option klu`,
[Enhancement-112](Enhancement-112.md) onward) ran on its **compiled-in defaults** —
AMD fill-reducing ordering, `max` row scaling, BTF (block-triangular-form)
permutation on — with no way to change them. The only KLU knob exposed,
`klu_memgrow_factor`, was moreover **broken** (it collapsed the real value to a
boolean). So "matrix reordering + scaling beyond KLU defaults" was a ⚠️ row in the
[gap analysis](../docs/internals/ngspice_internals/ngspice_gaps.md).

Enhancement-152 exposes KLU's reordering and scaling as `.option`s and fixes the
memgrow knob.

## Options

```
.option klu klu_ordering=amd|colamd     fill-reducing ordering (default amd)
.option klu klu_scale=none|sum|max      matrix row scaling      (default max)
.option klu klu_btf=on|off              block-triangular form   (default on)
.option klu_memgrow_factor=<f>          KLU work-array growth   (default 1.2)
```

- **`klu_ordering`** — the fill-reducing permutation computed before factoring:
  **AMD** (approximate minimum degree, default) or **COLAMD** (column AMD), which
  can give less fill on some structures.
- **`klu_scale`** — row equilibration before factoring: **max** (each row by its
  largest magnitude, default), **sum** (by the row's 1-norm), or **none**;
  improves the conditioning of badly-scaled matrices.
- **`klu_btf`** — whether KLU first permutes to block-triangular form (default on).
- **`klu_memgrow_factor`** — the KLU work-array growth factor; previously a no-op
  (`task->TSKkluMemGrowFactor = (val->rValue == 1.2)` set a boolean), now takes
  the real value.

All of these change only *how* KLU factors the matrix, never the physical
solution, and apply only under `.option klu`.

## Implementation notes

The knobs follow ngspice's existing option-plumbing chain, exactly mirroring
`klu_memgrow_factor`:

1. **`optdefs.h`** — new `OPT_KLU_ORDERING` / `OPT_KLU_SCALE` / `OPT_KLU_BTF`.
2. **`cktsopt.c`** — option-table entries (`IF_STRING`, friendly names) and
   handlers that map the strings to KLU's integer codes on the task
   (`amd`→0/`colamd`→1; `none`→0/`sum`→1/`max`→2; `on`→1/`off`→0), plus the
   `klu_memgrow_factor` bugfix.
3. **`tskdefs.h` / `cktdefs.h` / `smpdefs.h`** — `TSKklu*` / `CKTklu*` fields on the
   task, circuit, and matrix structs.
4. **`cktntask.c`** — defaults (0/2/1, matching `klu_defaults`) and task copy.
5. **`cktdojob.c`** — task → circuit; **`niinit.c`** — circuit → `SMPmatrix`.
6. **`klusmp.c`** — in `SMPnewMatrix`, after `klu_defaults()`, set
   `Common->ordering/scale/btf` from the matrix fields (the defaults match
   `klu_defaults`, so behaviour is unchanged unless the user sets an option).

Front-end/solver-plumbing only; the KLU numerics are untouched.

## Verification

`examples/klu_tuning_examples/verify_klu_tuning.py` (KLU-only), on a resistor grid
large enough that AMD and COLAMD differ:

- **[1]** every ordering/scaling/BTF setting gives the **physically identical**
  solution (max relative spread ~**2.8e-14**) — the knobs are safe.
- **[2]** the knobs actually **reach KLU**: AMD vs COLAMD (rel. diff 1.2e-14) and
  scale=max vs scale=none (2.8e-14) change the factorization arithmetic, so the
  full-precision result differs in its last digits — a tiny, deterministic,
  nonzero difference (the solution is the same; the roundoff is not).
- **[3]** an invalid value (`klu_ordering=foo`, …) is rejected with a warning.
- **[4]** the compiled-in defaults are unchanged — a plain `.option klu` equals
  `klu_ordering=amd klu_scale=max klu_btf=on` **bit-for-bit**.
- **[5]** a wide-dynamic-range (badly-scaled) network solves correctly under
  none/sum/max scaling.

`klu_tuning_demo.cir` solves a grid with the defaults and again with COLAMD + sum
scaling + BTF off — the same node voltage to 12 digits.

## Scope and follow-ups

User control of KLU's fill-reducing ordering, row scaling, and BTF permutation
(and a fixed memgrow knob) — matrix reordering and scaling beyond the compiled-in
defaults. These affect only the KLU solver; the default Sparse 1.3 solver has its
own reordering. Follow-ups: an auto-ordering heuristic that picks AMD vs COLAMD by
measured fill, exposing KLU's pivot-tolerance/`condest` reporting, and a
verbose factorization summary (ordering, fill-in, condition estimate).
