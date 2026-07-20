# `rfstab` — two-port stability & gain report (Enhancement-253)

The first of the RF **design-aid** additions on top of the existing S-parameter
machinery (`.sp`, n-port, Touchstone, `stb`, `loadpull`, noise figure). After a
`.sp` analysis publishes the scattering parameters `S_1_1 … S_2_2` versus
`frequency`, the `rfstab` command post-processes them into the standard
linear-two-port figures of merit, one value per frequency:

| quantity | formula |
|---|---|
| determinant `Δ` | `S11·S22 − S12·S21` |
| Rollett `K` | `(1 − |S11|² − |S22|² + |Δ|²) / (2·|S12·S21|)` |
| stability `μ` (load) | `(1 − |S11|²) / (|S22 − Δ·S11*| + |S12·S21|)` |
| stability `μ'` (source) | `(1 − |S22|²) / (|S11 − Δ·S22*| + |S12·S21|)` |
| max stable gain `MSG` | `|S21|/|S12|` (dB) |
| max available gain `MAG` | `|S21|/|S12|·(K − √(K²−1))`, `K>1` (dB) |

A two-port is **unconditionally stable** at a frequency iff `K > 1` and `|Δ| < 1`
(equivalently `μ > 1`). The results are stored as real vectors `k`, `magdelta`,
`mu`, `mu_src`, `gmax`, `msg`, `stable` versus `frequency` in a fresh `rfstab`
plot, and a summary (stability verdict, worst-case `K`/`μ`, gain range) is
printed.

```
.sp lin 101 1meg 10g 1
.control
run
rfstab              * or: rfstab S_1_1 S_1_2 S_2_1 S_2_2  (e.g. a Touchstone plot)
plot k mu           * stability factors vs frequency
plot gmax msg       * gain circles / MAG-MSG
.endc
```

It only reads vectors, so it is analysis- and solver-independent.

## Verification

`verify_rfstab.py` (both solvers, no numpy — Python's built-in `complex` is
enough):
1. a passive T-attenuator (R1=R3=25, R2=100, Z0=50) has **hand-computed** metrics
   `K=2.125`, `μ=2.33333`, `|Δ|=0.212121`, `MSG=0 dB`, `MAG=−6.02060 dB`,
   `stable`, which `rfstab` reproduces exactly;
2. for a common-source MOSFET amplifier (a non-reciprocal, well-conditioned
   two-port), the four S-parameters are read back and `K/Δ/μ/MSG/MAG` are
   recomputed independently in pure Python, matching `rfstab` to ~3e-7.

## Scope

New frontend command (`frontend/com_rfstab.c`); the ngspice binary is rebuilt. No
solver, analysis, or numerical change — `rfstab` is pure post-processing of the
S-parameters a `.sp` (or Touchstone) run already produced.
