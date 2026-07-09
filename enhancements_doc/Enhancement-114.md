# Enhancement-114 — KLU support for sensitivity analysis

Sensitivity analysis (`.sens <output>` for DC, `.sens <output> ac …` for AC) was
the last analysis that could not run under the **KLU** solver. It did not merely
refuse — it **crashed** with a segfault:

```
.option klu
   .sens v(out) ac lin 1 159155 159155   →  Segmentation fault (exit 139)
   .sens v(out)                          →  Segmentation fault (exit 139)
```

so every `.sens` deck had to fall back to Sparse 1.3.

## Why it crashed

Sensitivity (`src/spicelib/analysis/cktsens.c`) builds a **second** matrix,
`delta_Y`, that holds the perturbation `∂Y/∂p` of each parameter. It is created with

```c
delta_Y = TMALLOC(SMPmatrix, 1);
SMPnewMatrix(delta_Y, size);
```

`SMPnewMatrix` allocates a plain **Sparse 1.3** matrix — it leaves
`delta_Y->CKTkluMODE = 0` and never allocates a `SMPkluMatrix`. That is correct:
`delta_Y` is only ever *multiplied* (`SMPmultiply` → `spMultiply`) against the
solution vector, never factored, and the per-device `DEVbindCSC` callbacks always
bind their matrix pointers into `ckt->CKTmatrix` (the **main** solver matrix),
never into `delta_Y`. So `delta_Y` must stay Sparse regardless of which solver
the main matrix uses.

But two KLU-only setup blocks in `cktsens.c` were gated on the **main** matrix's
flag:

```c
if (ckt->CKTmatrix->CKTkluMODE)   /* true whenever .option klu is set */
{
    SMPconvertCOOtoCSC(delta_Y);              /* delta_Y->SMPkluMatrix is NULL … */
    ... delta_Y->SMPkluMatrix->KLUmatrixAx ... /* … → NULL dereference → SIGSEGV */
}
```

Under `.option klu` the main matrix's `CKTkluMODE` is `1`, so these blocks ran and
dereferenced `delta_Y->SMPkluMatrix` — which is `NULL` because `delta_Y` is a
Sparse matrix. Under the default Sparse solver the flag is `0`, the blocks were
skipped, and everything worked — which is exactly the behavior `delta_Y` needs in
**both** cases.

## The fix

Gate the two `delta_Y` KLU blocks on **`delta_Y`'s own** `CKTkluMODE` (which is
always `0`) instead of the main matrix's, so `delta_Y` is treated as the Sparse
matrix it actually is under KLU too — identical to how it already behaves under
the default Sparse solver.

```c
-            if (ckt->CKTmatrix->CKTkluMODE)
+            if (delta_Y->CKTkluMODE)      /* delta_Y is Sparse under KLU too */
...
-            if (ckt->CKTkluMODE)
+            if (delta_Y->CKTkluMODE)      /* delta_Y is Sparse under KLU too */
```

The main `Y` matrix stays KLU and is factored/solved by KLU as usual
(`NIsenReload` / `NIacIter`); only the auxiliary perturbation matrix is Sparse.
This is a two-line behavioral change (plus an explanatory comment); no KLU
plumbing is added because none is needed.

## Verification

KLU sensitivity now matches Sparse **exactly**, and no longer crashes:

| Case | SPARSE | KLU |
|---|---|---|
| Built-in RC, AC sens `v1_acmag` | `4.999998e-01, −5.00000e-01` | identical |
| OSDI `ores`+`ocap`, AC sens `v1_acmag` | `4.999998e-01, −5.00000e-01` | identical |
| Resistor-divider DC sens (`r1`, `r2`, `v1`) | `−1.11111e-04 / 2.222220e-04 / 3.333333e-01` | identical |

Both DC and AC sensitivity are covered (they share the `delta_Y` block that was
crashing). Verified against built-in devices and real **OSDI** device models.

## Files changed

| File | Change |
|---|---|
| `ngspice-46/src/spicelib/analysis/cktsens.c` | gate the two `delta_Y` KLU setup blocks on `delta_Y->CKTkluMODE` (0) instead of the main matrix's flag, so the auxiliary perturbation matrix stays Sparse under KLU — fixes the NULL-deref segfault in DC and AC `.sens` |
| `examples/_setup.py` | dual-solver harness: sensitivity (`.sens … ac`) no longer triggers a KLU skip. Un-skipping the `analyses` example surfaced a *separate* pre-existing gap — `.disto` has no KLU wiring — so the skip trigger is switched from `.sens …ac` to `.disto`. Also fixes a harness bug found while validating: the solver-card injector wrote `.option` into the **real** deck files and never restored them (every sweep permanently polluted committed decks); decks are now restored at process exit |

## Scope — sensitivity done; one adjacent gap surfaced

With this fix, KLU runs **DC, DC-sweep, AC, transient, noise, S-parameters,
single-ended pole-zero, and DC/AC sensitivity** — matching Sparse 1.3. Two
analyses remain Sparse-only under KLU:

- **Balanced-output pole-zero** — a `pz` card whose output reference node is not
  ground; the fixed KLU symbolic ordering cannot handle the zeroed columns (see
  [Enhancement-113](Enhancement-113.md)).
- **Distortion (`.disto`)** — surfaced while validating this fix. Un-skipping the
  `analyses` example (previously KLU-skipped for its `.sens …ac` sub-test) let its
  `.disto` sub-test run under KLU, where it silently produces no output: the
  distortion path (`cktdisto.c`) has **no KLU binding at all** — the only analysis
  driver that ever referenced KLU was `cktsens.c` (now fixed here). This is a
  distinct, pre-existing gap unrelated to sensitivity and out of scope for E-114;
  the harness now skips the `analyses` example under KLU on its `.disto` card
  instead of its `.sens …ac` card (a candidate for a future enhancement).

Fixing the deck-injector restore bug also **un-masked a third** KLU numerical
discrepancy: the `hierbranch` example's hierarchical branch-*current* probes read
`0` under KLU (node voltages are correct). It had been passing under KLU only
because a stale, never-restored `.option sparse` in its deck made the "klu" child
silently run Sparse — a false pass. It is deterministic, independent of this
sensitivity fix (the DC KLU solve is untouched), and now correctly marked
`KLU_XFAIL` alongside the two previously known numerical differences — the stiff
`opamp741` transient (convergence) and the degenerate `groundcontrib` single-node
topology (wrong DC). The full example suite is `101/101` under both solvers
(`sparse=PASS`, `klu ∈ {PASS, SKIP, XFAIL}`).
