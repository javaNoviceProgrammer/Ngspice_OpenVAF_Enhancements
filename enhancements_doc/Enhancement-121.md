# Enhancement-121 — the PAC conversion-matrix engine

The **third and central step** of the RF periodic small-signal suite. [PSS](Enhancement-117.md)
finds the periodic operating point, [E-119](Enhancement-119.md) retains it, and
[E-120](Enhancement-120.md) turns it into the harmonics `G_k`, `C_k` of the
periodically time-varying device Jacobian. E-121 assembles those harmonics into
the **harmonic conversion matrix** and solves it — the numerical heart of periodic
AC (PAC), periodic noise, and PXF.

## The idea

A circuit linearized about its PSS steady state has a `T`-periodic Jacobian
(`T = 1/f0`). A small tone injected at frequency `f_in` therefore does **not**
produce a response only at `f_in`: the periodic time-variation mixes it up and
down by every multiple of the fundamental, so the response appears at all
**sidebands** `f_in + k·f0` (`k = −M … M`). Writing the response as that sideband
sum and balancing harmonics gives a block linear system — the conversion matrix —
whose block `(n, m)` is

```
H_{nm} = G_{n−m} + j·ω_m·C_{n−m},   ω_m = 2π·(f_in + m·f0)
```

built from the Jacobian harmonics `G_k`, `C_k`. It has size `(2M+1)·N`
(`N` = circuit unknowns). Solving `H·X = B` for a stimulus `B` injected at one
sideband yields the responses `X` at **all** sidebands — the conversion gains that
PAC reports.

## What E-121 does

In `dcpss.c`, after the retained operating point exists:

1. **Samples the full Jacobian.** Extends E-120 from the osc-node diagonal to
   *every* structural nonzero of the matrix: it enumerates the nonzeros
   (`SMPfindElt`, which is KLU-aware and non-creating), then at each of the `P`
   retained samples restores that instant's bias, re-linearizes (`CKTload` with
   `MODEINITSMSIG`) and stamps `G + jC` (`CKTacLoad` at `ω = 1`), reading each
   entry's real part `G(t)` and imaginary part `C(t)`.
2. **Extracts the harmonics.** A complex DFT of each entry's `G(t)`, `C(t)` over
   the period gives `G_k`, `C_k` for `k = 0 … 2M` (`G_{−k} = conj(G_k)` since the
   time series is real).
3. **Assembles the conversion matrix** `H_{nm} = G_{n−m} + j·ω_m·C_{n−m}` — a
   `(2M+1)N` complex block matrix, block-Toeplitz in the harmonic index with the
   per-sideband `ω_m` on the reactive term.
4. **Solves it.** A unit current is injected at the osc node in the 0-th sideband
   and the system is solved by a dense complex LU (`pss_csolve`, partial
   pivoting). The block count is small for the circuits PAC targets, so a direct
   dense factor is exact and simplest; a production PAC on large circuits would
   assemble this as a sparse block system.
5. **Reports the sideband responses** at `−1 / 0 / +1` — the conversion gains.

## Verification

The 1 MHz-driven RC low-pass (`R = 1k`, `C = 1n`), probed at `f_in = f0/2 = 500 kHz`:

```
PAC conversion matrix: f_in = 500000 Hz, 7 sidebands, unit I at osc node
  sideband -1 (-500000 Hz): |V| = 3.1688e-14
  sideband +0 (500000 Hz):  |V| = 303.314
  sideband +1 (1.5e+06 Hz): |V| = 1.23414e-14
  expected sideband-0 driving-point |Z| = 303.314 Ohm (linear, from G0/C0)
```

For a **linear** circuit the periodic Jacobian is time-invariant, so the
off-diagonal harmonic blocks `G_k, C_k (k ≠ 0)` vanish and `H` is block-diagonal —
its 0-block is exactly the ordinary AC matrix at `f_in`. The engine therefore
reproduces the **AC driving-point impedance** at `f_in`,

```
|Z(f_in)| = 1 / |1/R + j·2π·f_in·C| = 1 / |1e−3 + j·3.1416e−3| = 303.31 Ω,
```

to six figures (**sideband 0 = 303.314 Ω**), while the ±1 sidebands come back at
`~3e−14` — floating-point zero relative to 303 (ratio `~1e−16`): **no spurious
conversion** for a circuit that does not mix. The linear case pins the whole
pipeline — nonzero-enumeration, per-sample re-linearization, harmonic DFT, block
assembly, and the complex solve — to an exact analytic value; a **pumped
nonlinear** circuit (a mixer, a switched-capacitor stage) fills the off-diagonal
blocks and produces genuine conversion between sidebands through the *same* code
path.

`verify_rcpss.py` asserts the reported `f_in`, that all three sidebands are
present, that the reported and analytic driving-point `|Z|` agree, that sideband 0
equals that impedance, and that the ±1 conversion is `< 1e−6` of sideband 0.

## Files changed

| File | Change |
|---|---|
| `ngspice-46/src/spicelib/analysis/dcpss.c` | `pss_csolve` (dense complex LU) and `pss_pac_report` — sample the full periodic Jacobian, DFT to harmonics, assemble the `(2M+1)N` conversion matrix, inject a sideband-0 stimulus, solve, report the sideband gains; called from the retained-operating-point block |
| `examples/rfpss_examples/verify_rcpss.py` | assert the PAC sideband-0 response equals the analytic AC driving-point impedance and that the ±1 sidebands carry no converted energy |

## Scope

E-121 delivers the conversion-matrix **engine** and verifies it against the exact
linear driving-point response. It runs automatically off the retained PSS
operating point and reports the sideband conversion gains. The remaining PAC work
is user-facing wrapping — a dedicated `.pac` command that sweeps `f_in` and writes
the conversion gains as an output vector, and reusing the same conversion matrix
for **periodic noise** (fold device-noise sidebands through `Hᵀ`) and **PXF** —
all of which now stand on this solve.
