# Enhancement-205 — low-rank residue factorization in `pre_snp`

The E-200/201 `pre_snp` shared-pole realization emits **O(N²)** output-coupling terms
and **O(N·Np)** `laplace_nd` filters, so OpenVAF's compile time grows super-linearly
with the port count (an N=32 block takes ~80 s to compile, and that — not the vector
fit — is what caps the practical port count at ~20–24).

But when an N-port block's ports couple through only a **few shared modes** — the
common case for multi-port filters, cavities, and packages with a shared plane — each
pole's N×N residue matrix has **rank r ≪ N**. E-205 exploits that structure.

## How it works

Per *channel* (the conductance `d`, the capacitance `e`, and every pole section) the
emitter builds the N×N real weight matrix and picks, via an in-C Jacobi **SVD**, the
cheaper of:

- a **dense** emit — a term per significant entry, one `laplace_nd` per input port; or
- a **low-rank** emit `W = U·Vᵀ` (rank r).

Because `laplace` is linear,

```
Σⱼ V[j][m]·laplace(V(pⱼ))  =  laplace(Σⱼ V[j][m]·V(pⱼ))
```

so the low-rank form filters the **r combined inputs** `u_m = Σⱼ V[j][m]·V(pⱼ)` **once**
(r filters, not N) and distributes them to the outputs via `U`. This collapses filters
from **O(N·Np) → O(r·Np)** and coupling terms from **O(N²) → O(N·r)**.

A **full-rank** block (e.g. a distributed ladder) has no such structure, so every
channel keeps the dense form — the emit is a strict no-op there.

## Payoff (a 3-shared-mode block)

| N | dense compile | low-rank compile | dense filters | low-rank filters |
|---|---|---|---|---|
| 16 | 16.9 s | 1.5 s | 96 | 8 |
| 24 | 42 s | 5.7 s | 144 | 10 |
| 32 | 81 s | 11.6 s | 192 | 8 |

The response is exact: AC to ~4e-7, transient to ~3e-5 (tolerance-limited), both versus
the forced-dense build of the same fit.

## Escape hatch

Set `PRE_SNP_DENSE=1` in the environment to force the old dense realization (for
reproducibility or A/B comparison).

## Verify

```
python3 verify_lowrank.py
```

Five checks: a 12-port / 3-mode block emits far fewer filters low-rank than dense; its
AC and transient match the forced-dense build of the same fit (and the transient stays
bounded — the low-rank capacitance term stays PSD); and a full-rank 8-port ladder gets
**no** compression with **bit-identical** AC — the auto-detect leaves full-rank blocks
alone.
