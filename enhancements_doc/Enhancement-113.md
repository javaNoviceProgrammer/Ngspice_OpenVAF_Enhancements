# Enhancement-113 — KLU support for noise and pole-zero analysis

Two analyses used to refuse the **KLU** solver outright:

```
.option klu
   noise ...   →  Error: Noise simulation is not (yet) supported with 'option KLU'.   (noisean.c)
   pz    ...   →  Error: Pole/zero analysis is not (yet) supported with 'option KLU'.  (pzan.c)
```

so every `.noise` / `.pz` deck had to fall back to Sparse 1.3. This enhancement
makes **noise** work under KLU, and **pole-zero** work under KLU for the common
single-ended case.

## Noise — the real reason it was disabled

Noise uses the **adjoint method**: it solves the *transposed* system
`Aᵀ·x = e` for the output port, then propagates each internal noise source
through `x`. The transposed complex solve is `SMPcaSolve`. Its Sparse branch
correctly calls `spSolveTransposed`, but its **KLU branch called the
*non-transposed* `klu_z_solve`** — so for any **asymmetric** matrix (every circuit
with a transistor or controlled source) it silently produced the **wrong** noise.
A symmetric RC divider can't reveal it (`Aᵀ = A`); a VCCS makes it obvious
(`9.1e-9` wrong vs `2.0e-7` correct). That silent-wrong result is why noise was
disabled under KLU rather than merely slow.

**Fix** (`src/maths/KLU/klusmp.c`): `SMPcaSolve`'s KLU branch now uses the
transposed solve `klu_z_tsolve(…, conj_solve = 0, …)`, matching `spSolveTransposed`.
The noise guard in `noisean.c` is removed.

Verified: KLU noise now matches Sparse **exactly** — resistor thermal noise,
asymmetric VCCS circuits, real **OSDI device models** (induced-gate-noise
`noisejw`: `1.02622732e-08` under both), and the integrated onoise/inoise totals.
`.sp` S-parameters share the same `SMPcaSolve` adjoint and are corrected too.

## Pole-zero — single-ended works; balanced-output stays on Sparse

The pole-zero path was already almost fully wired for KLU (`cktpzset.c` binding,
`spDeterminant_KLU`, complex LU). The blanket guard in `pzan.c` is removed, and
single-ended pole-zero — a **grounded** output reference, the overwhelmingly
common case — now runs under KLU and matches Sparse across poles, zeros and
current-mode (RC pole `−1000`, high-pass zero at the origin, active 2-pole
circuits, all identical to Sparse).

The one exception kept behind a **targeted guard** is a **non-grounded output
reference** (balanced/differential output). Its zeros phase folds columns
(`SMPcAddCol`/`SMPcZeroCol` in `CKTpzLoad`) at solve time — which Sparse survives
via dynamic Markowitz re-ordering on every factorization, but KLU cannot, because
its symbolic ordering is fixed once at `klu_analyze`. (Enabling KLU partial
pivoting lets it factor, but then the pz determinant — which the whole method
depends on — comes out wrong, because the pivoted+scaled factorization isn't
unwound by `spDeterminant_KLU`.) That case now returns a clear error directing to
`.option sparse`, instead of the earlier blanket refusal.

## Files changed

| File | Change |
|---|---|
| `ngspice-46/src/maths/KLU/klusmp.c` | `SMPcaSolve` KLU branch: transposed solve `klu_z_tsolve` (was `klu_z_solve`) — the adjoint fix that makes noise/S-parameters correct under KLU |
| `ngspice-46/src/spicelib/analysis/noisean.c` | remove the KLU refusal guard |
| `ngspice-46/src/spicelib/analysis/pzan.c` | remove the blanket KLU refusal guard; add a targeted guard for balanced-output (non-grounded reference) pole-zero |
| `examples/_setup.py` | dual-solver harness: noise and single-ended pole-zero now run (and pass) under KLU; only balanced-output pole-zero and AC sensitivity are skipped as Sparse-only |

## Scope and remaining KLU limitations

Under KLU: **noise ✅**, **single-ended pole-zero ✅** (+ latent `.sp` adjoint
fix). Still Sparse-only: **balanced-output pole-zero** (above) and **AC
sensitivity** (`.sens … ac`; DC `.sens` is fine) — a separate analysis with its
own KLU gap, out of scope here. The full example suite is `101/101` under both
solvers; this moved **10 examples** from KLU-skipped to KLU-passing (the noise +
single-ended-pz suite), leaving only the `analyses` example skipped under KLU for
its AC-sensitivity sub-test.
