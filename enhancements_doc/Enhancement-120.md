# Enhancement-120 — periodic small-signal Jacobian harmonics

Second step toward periodic AC (`.pac`). PAC/pnoise/PXF solve a **harmonic
conversion matrix** whose blocks are the harmonics `G_k`, `C_k` of the
periodically time-varying device Jacobian — the conductance `G(t) = ∂I/∂V` and
capacitance `C(t) = ∂Q/∂V` swept along the PSS steady-state waveform. E-119
retained the periodic operating point; E-120 turns it into those Jacobian
harmonics.

## What it does

For each of the P retained samples the routine (`pss_jacobian_report` in
`dcpss.c`):

1. **restores that instant's bias** — the node voltages and device states from the
   E-119 retained operating point;
2. **re-linearizes** the devices at that bias (`CKTload` with `MODEINITSMSIG`);
3. **stamps `G + jC`** into the complex matrix (`CKTacLoad` at `ω = 1`, so the
   imaginary part is exactly `C`);
4. **reads the (osc, osc) diagonal** — its real part is the node's conductance
   `g(t)`, its imaginary part the capacitance `c(t)`.

The DFT of `g(t)` and `c(t)` across the period gives the periodic Jacobian's
harmonics: flat (DC only) for a linear circuit, rich for a pumped nonlinear one.
The osc-node diagonal is reported as a verifiable slice of the full `G_k`/`C_k`
that the PAC conversion matrix (E-121) will be assembled from.

### One subtlety worth recording

After PSS the matrix is in **real** mode. `CKTacLoad`'s `SMPcClear` only clears the
imaginary part when the matrix is flagged complex, so on the first attempt `C(t)`
**accumulated** across samples (`≈ s·C1`, whose DFT is a ramp: DC `≈ (P/2)·C1` with
`1/k` harmonics) while `G(t)` was already correct. The fix is to put the matrix in
complex mode first — `spSetComplex` for Sparse, the `KLUmatrixIsComplex` +
`DEVbindCSCComplex` path for KLU (as `acan.c` does) — so each sample's stamp starts
from a cleared complex matrix.

## Verification

The 1 MHz-driven RC low-pass (`R1=1k`, `C1=1n`), osc node `b`:

```
periodic small-signal Jacobian at osc node (1024 samples, 10 harmonics):
  G(t): DC = 0.001 S, |G1| = 4.24e-20, |G2| = 2.15e-19, |G3| = 1.35e-19
  C(t): DC = 1e-09 F, |C1| = 2.32e-25, |C2| = 1.72e-25, |C3| = 2.21e-25
```

- **G(t) DC = 0.001 S = 1/R1**, **C(t) DC = 1e-9 F = C1** — the extracted Jacobian
  equals the *exact* known small-signal values.
- **All harmonics ≈ 0** — the Jacobian is correctly time-invariant for a linear
  circuit (no spurious harmonics).

Because the routine re-linearizes at each sampled bias, a **nonlinear** device
whose slope varies with its operating point (a diode's `g = (Is/Vt)·exp(V/Vt)`,
a switching mixer) yields genuinely time-varying `g(t)`, `c(t)` and hence
non-trivial harmonics — the very content PAC converts between sidebands. The
linear check pins the extraction to exact analytic values; the harmonic machinery
that carries the time-variation is the same code path.

`verify_rcpss.py` asserts the extracted `G(t)`/`C(t)` DC values equal `1/R1` and
`C1` and that their harmonics vanish.

## Files changed

| File | Change |
|---|---|
| `ngspice-46/src/spicelib/analysis/dcpss.c` | `pss_jacobian_report`: walk the retained operating point, re-linearize + AC-stamp per sample, read the osc-node `G(t)`/`C(t)`, DFT to harmonics; complex-mode setup so the imaginary stamp does not accumulate |
| `examples/rfpss_examples/verify_rcpss.py` | assert `G(t)` DC == `1/R1`, `C(t)` DC == `C1`, harmonics ≈ 0 |

## Scope

E-120 reports the osc-node diagonal of the periodic Jacobian as a verified slice.
**E-121** generalizes to all matrix entries, assembles the `(2K+1)N` harmonic
conversion matrix, sweeps the input frequency, extracts the output sidebands
(conversion gains), and wires up the `.pac` command.
