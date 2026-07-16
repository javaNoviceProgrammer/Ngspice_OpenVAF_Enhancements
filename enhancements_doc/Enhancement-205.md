# Enhancement-205 — low-rank residue factorization in `pre_snp`

A scalability enhancement for the N-port Touchstone device. The `pre_snp` converter
([E-200](Enhancement-200.md)/[E-201](Enhancement-201.md)) turns a `.sNp` S-parameter
file into a Verilog-A n-port and compiles it with `openvaf-r`. E-201 made the *vector
fit* scale to ~N=100, but the emitted model's **compile time** — dominated by an
**O(N²)-term, O(N·Np)-filter** shared-pole realization — caps the practical port count
at ~20–24 (N=32 compiles in ~80 s). E-205 lifts that ceiling for the common class of
blocks whose ports couple through a few shared modes.

## The structure

The shared-pole realization writes, for each output port `i`,

```
I(p_i) <+ Σ_j d_ij·V(p_j) + Σ_j e_ij·ddt(V(p_j)) + Σ_sections Σ_j W^sc_ij · laplace(V(p_j))
```

Each pole section's weights `W^sc_ij` form an N×N matrix. For a block whose ports
couple through `M` shared resonant modes (multi-port filters, cavities, packages with
a shared plane), each pole's residue matrix is an outer product `a·aᵀ` — **rank 1** —
so `W^sc` has rank `r ≪ N`. The dense emit ignores this and pays O(N²) terms + N
filters per section regardless.

## The realization

Per channel (`d`, `e`, and each pole section) the emitter builds the N×N real weight
matrix and, via a new in-C one-sided **Jacobi SVD**, chooses the cheaper of a dense
emit or a low-rank emit `W = U·Vᵀ` (rank r kept above `tol_rank = 1e-7`, so a clean
singular-value gap compresses fully while a slowly-decaying channel stays dense):

- **cost** `2N·r (+r filters)` vs dense `nnz (+N filters)` — pick the smaller.
- **Input combining is the key.** Because `laplace` is linear,
  `Σⱼ V[j][m]·laplace(V(pⱼ)) = laplace(Σⱼ V[j][m]·V(pⱼ))`, so the low-rank form filters
  the **r combined inputs** `u_m = Σⱼ V[j][m]·V(pⱼ)` **once** and distributes them via
  `U`. This drops filters from **O(N·Np) → O(r·Np)** — the piece that actually
  dominates the compile — and coupling terms from **O(N²) → O(N·r)**.

A full-rank block keeps the dense form on every channel, so it is emitted exactly as
before (verified bit-identical). The passivity projection of the capacitance `e`
(E-201) is preserved, so the low-rank transient stays stable.

## Results

Measured on a 3-shared-mode block (openvaf-r compile of the emitted `.va`):

| N | dense compile | low-rank compile | dense→low-rank filters |
|---|---|---|---|
| 16 | 16.9 s | **1.5 s** | 96 → 8 |
| 24 | 42 s | **5.7 s** | 144 → 10 |
| 32 | 81 s | **11.6 s** | 192 → 8 |

Compile time goes from super-linear to ~linear (constant filter count), a **~7–14×**
speedup, with the response exact — AC to ~4e-7, transient to ~3e-5 — versus a
forced-dense build of the same fit. A full-rank ladder is unchanged (bit-identical AC,
same filter count).

## Files changed

`ngspice-46/src/frontend/snp2va.c` only: a one-sided `jacobi_svd`, an `emit_filter`
helper, the per-channel dense/low-rank chooser and input-combined low-rank emit, and
the `PRE_SNP_DENSE` env-var escape hatch. Verify: `examples/lowrank_examples/`
(5 checks — compression, AC + transient == forced-dense, full-rank fallback).

## Scope

E-205 changes only how the fitted model is *realized* in Verilog-A; the vector fit and
its accuracy are untouched. Low-rank compression activates automatically when the
device's coupling is low-rank and is a no-op otherwise.
