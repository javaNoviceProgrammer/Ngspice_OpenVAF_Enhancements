# Enhancement-201 — `pre_snp` scalability (fast vector fitting + shared-pole realization)

The [Enhancement-200](Enhancement-200.md) `pre_snp` converter worked, but a stress
test (generate an N-port R-L-C network, extract its S-parameters, round-trip through
`pre_snp`, compare DC/AC/transient) showed it **struggled from about 8 ports up**: an
8-port took ~190&nbsp;s, and larger port counts were simply infeasible. Two things
scaled badly, both in `snp2va.c`:

- the **pole identification** stacked all `N²` elements into one dense least-squares
  matrix of size `(2·Ns·N²) × (N²·(Np+2)+Np)` — **O(N⁴) memory, O(N⁶) compute**,
  re-solved dozens of times over the order climb (≈8&nbsp;TB of RAM at N=100);
- the **emitted model** gave every one of the `N²` elements its own `laplace_nd`
  bank — **O(N²·Np)** filter sections and OSDI state.

Four fixes rebuild the scalability; the fit now runs to **N=100** and the end-to-end
ceiling rises from ~8 to ~20–24 ports.

## The four fixes

1. **Fast Vector Fitting** (Deschrijver/Gustavsen). The stacked pole-ID matrix has
   block-arrow structure: each element's residue columns are independent and couple
   only through the shared common-pole (σ) columns. Instead of forming that matrix,
   each element block is Householder-reduced on its own (a small `2Ns×(Np+2)` QR)
   and only its residual rows — the part orthogonal to that element's own columns —
   are stacked into one tall `((2Ns−Np−2)·Ne) × Np` system solved for σ. Memory drops
   **O(N⁴)→O(N²)**, compute **O(N⁶)→O(N²·Ns·Np²)**.

2. **Reciprocity.** A passive network has symmetric `Y`; when detected, only the
   upper triangle (`N(N+1)/2` elements) is fit and the residues are mirrored — ~2×
   fewer solves.

3. **Iteration cap.** Pole relocation now stops as soon as the poles settle
   (relative move `< 1e-4`) instead of a fixed 12 sweeps — typically 3–5.

4. **Shared-pole realization.** All `N²` elements share the same poles, so the
   pole-filters are computed **once per input port** — a real pole gives one filter
   `V(pj)/(s−p)`, a conjugate pair two real basis filters `(s−σ)/D` and `ω/D`, with
   the residue entering each output as a real scalar weight. Each output current is
   then a cheap weighted sum. This is **O(N·Np)** `laplace_nd` and OSDI state instead
   of O(N²·Np) — the difference between a model that compiles/simulates at large N and
   one that does not.

## Three latent bugs the stress test also surfaced

- **Order-selection double-free.** At higher pole counts a relocated pole set could
  lose its adjacent-conjugate-pair structure (a "pair" split by numerical noise, or a
  near-real pole with a tiny imaginary part), and `build_basis`/`ctil_to_cres` — which
  walk `i+=2` on a complex pole — then wrote one slot past the residue array. Fixed by
  a `canon_poles` step that snaps near-real poles to real and rebuilds exact adjacent
  conjugate pairs.
- **256-entry stack array.** The Touchstone parser assembled each frequency's matrix
  in a fixed `cplx pv[16*16]`, hard-capping the port count at 16 (N=32 smashed the
  stack). Moved to the heap; the auto-detect limit was lifted to 512 ports.
- **OpenVAF crash on integer literals.** A `laplace_nd` coefficient array assigned to
  a variable (as the shared realization does) crashes OpenVAF when a coefficient is an
  integer literal like `'{1}` — which `%.12g` produces for `1.0`. The emitter now
  forces a real literal (`'{1.0}`).

## Results

- Fit at **N=8: 220&nbsp;s → 3.6&nbsp;s**. N=64 fits in 47&nbsp;s (was ~860&nbsp;GB of
  RAM); **N=100 fits in 2.75&nbsp;min** at 9.6×10⁻⁴ error.
- Model size: `laplace_nd` count is now `N·Np` (65 at N=8, 449 at N=32) rather than
  `~N²·Np/2` (256, 7168).
- **Correctness preserved.** DC/AC/transient still overlay the original subcircuit
  (N=8 unchanged; N=16 — previously infeasible — matches to 1.3%). Full example
  regression **164/164**; the E-200 example suite passes (now 9 checks).
- The remaining bottleneck is **OpenVAF's compile time** for the (now far smaller)
  shared model — ~26&nbsp;s at N=16, ~43&nbsp;s at N=20 — so the practical end-to-end
  ceiling is ~N=20–24 while the fit itself scales to N=100. (The separate ngspice
  `.sp` extraction cost only matters when *generating* S-parameters, not for real
  `.sNp` from a measurement or EM solver.)

## Verification

[`examples/presnp_examples/verify_presnp.py`](../examples/presnp_examples/verify_presnp.py)
gains two checks (9 total): an **8-port** coupled ladder — the size the old converter
struggled at — converts+compiles in a few seconds with the fast fit and the compact
shared-pole model, and the resulting device matches the original network in AC. The
E-200 order/realization guards (4-port double-free + transient-divergence) and the
resonator/3-port checks continue to pass.
