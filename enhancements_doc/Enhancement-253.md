# Enhancement-253 — `rfstab`: two-port stability & gain report

The first of a set of RF **design-aid** additions layered on top of the existing
S-parameter machinery (`.sp`, native n-port, Touchstone I/O, `stb` loop-gain,
`loadpull`, noise figure). ngspice can *compute* S-parameters but not turn them
into the stability and gain figures of merit an RF designer works with; `rfstab`
closes that gap.

## What it does

After a `.sp` analysis publishes the scattering parameters `S_1_1 … S_2_2` versus
`frequency`, the `rfstab` command post-processes them into the standard
linear-two-port metrics, one value per frequency point:

```
  determinant   D  = S11*S22 - S12*S21
  Rollett       K  = (1 - |S11|^2 - |S22|^2 + |D|^2) / (2*|S12*S21|)
  mu-factor     mu = (1 - |S11|^2) / (|S22 - D*conj(S11)| + |S12*S21|)   (load)
  mu'-factor    mu'= (1 - |S22|^2) / (|S11 - D*conj(S22)| + |S12*S21|)   (source)
  max stable    MSG = |S21|/|S12|                      (power gain, dB)
  max available MAG = |S21|/|S12|*(K - sqrt(K^2-1))    (power gain, K>1, dB)
```

A two-port is **unconditionally stable** at a frequency iff `K > 1` and
`|D| < 1`, equivalently `mu > 1` (and `mu' > 1`). The results are stored as real
vectors — `k`, `magdelta` (|D|), `mu`, `mu_src`, `gmax` (MAG where K>1 else MSG),
`msg`, `stable` (1/0) — versus `frequency` in a fresh `rfstab` plot, ready to
`plot`/`wrdata`, and a summary is printed:

```
RF two-port stability (101 frequency points):
  unconditionally stable at ALL points (K > 1 and |Delta| < 1 everywhere).
  worst-case K   = 2.125
  worst-case mu  = 2.333   (unconditionally stable iff > 1)
  max |Delta|    = 0.2121
  max gain (MAG) = -6.021 .. -6.021 dB
```

## Usage

```
rfstab                      * uses the .sp defaults S_1_1 S_1_2 S_2_1 S_2_2
rfstab S_1_1 S_1_2 S_2_1 S_2_2   * or name the four vectors (e.g. a Touchstone plot)
```

It only reads vectors (via the expression evaluator) and publishes vectors, so it
runs after any `.sp` and is independent of the linear solver. Implementation is a
single self-contained frontend command (`frontend/com_rfstab.c`), modelled on the
project's `stb` command (E-198).

## Verification

`examples/rfstab_examples/verify_rfstab.py` (both solvers, numpy-free — Python's
built-in `complex` suffices):

1. a passive T-attenuator (R1=R3=25, R2=100, Z0=50) has hand-computed metrics
   `K=2.125`, `mu=2.33333`, `|Delta|=0.212121`, `MSG=0 dB`, `MAG=-6.02060 dB`,
   `stable=1` — `rfstab` reproduces them exactly;
2. for a common-source MOSFET amplifier (a non-reciprocal, well-conditioned
   two-port), the four S-parameters are read back and `K/Delta/mu/MSG/MAG` are
   recomputed independently in pure Python, matching `rfstab` to ~3e-7.

## Scope

New frontend command only (`frontend/com_rfstab.c`, `com_rfstab.h`, registered in
`commands.c` / `com_commands.h` / `Makefile.am`); the ngspice binary is rebuilt.
No solver, analysis, or numerical change — `rfstab` is pure post-processing of
S-parameters a `.sp` (or Touchstone) run already produced. Full regression: all
examples pass.
