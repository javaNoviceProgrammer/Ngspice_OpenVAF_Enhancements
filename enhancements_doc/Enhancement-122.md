# Enhancement-122 — the `.pac` command (periodic AC)

The **user-facing periodic-AC analysis**, built on the conversion-matrix engine of
[E-121](Enhancement-121.md). Where E-121 solved the harmonic conversion matrix at a
single probe frequency and reported it to stderr, `.pac` sweeps a small-signal
input frequency and writes the response as a proper complex output vector — a
first-class analysis you drive from a netlist and read back with `print`/`plot`.

## The command

```
.pac Fguess StabTime OscNode Points Harmonics SC_iter Steady_coeff \
     <DEC|OCT|LIN> Npts Fstart Fstop
```

The first seven fields are exactly the [`.pss`](Enhancement-117.md) parameters —
`.pac` runs a periodic steady state to find the operating point it linearizes
around — followed by an `.ac`-style frequency sweep (`Npts` per decade/octave, or
total for linear). It reuses the PSS analysis internally: the parser sets the PSS
parameters plus the `pac_*` sweep parameters and a `PSSdoPAC` flag, and `DCpss`,
after retaining the periodic operating point, runs the sweep.

## What it does

`dcpss.c` factors the E-121 engine into two reusable pieces:

- **`pac_extract_harmonics`** — walk the retained operating point, sample every
  Jacobian nonzero's `G(t)`, `C(t)` over the period, and complex-DFT them to the
  harmonics `G_k`, `C_k`. Done **once** (the harmonics do not depend on the input
  frequency).
- **`pac_solve_at`** — at a given input frequency `f_in`, assemble the conversion
  matrix `H_{nm} = G_{n−m} + j·ω_m·C_{n−m}` (only the `ω_m = 2π(f_in + m·f0)`
  terms change per frequency), inject a unit current at the osc node in the 0-th
  sideband, and solve by dense complex LU.

`pac_sweep` then extracts the harmonics once and loops the input frequency
(lin/dec/oct), solving at each point and emitting the **0-th-sideband node
responses** as a complex `"PAC Analysis"` plot versus frequency (through the same
`OUTpBeginPlot`/`OUTpData` path as `.ac`, so `print`/`plot`/`wrdata` all work).

## Verification

The 1 MHz-driven RC low-pass (`R=1k`, `C=1n`), swept 10 kHz–1 MHz (10 points/decade):

```
Index   frequency       mag(b)
0       1.000000e+04    9.980319e+02
...
10      1.000000e+05    8.467330e+02
...
20      1.000000e+06    1.571767e+02
```

For this **linear** circuit the periodic Jacobian is time-invariant, so the
conversion matrix is block-diagonal and its 0-block is the ordinary AC matrix at
`f_in`. The PAC sideband-0 response at the osc node `b` therefore equals the **AC
driving-point impedance** across the whole sweep,

```
|Z(f)| = 1 / |1/R + j·2π·f·C|,
```

and it does — to a **worst-case relative error of 1.6e−7** over all 21 points
(998.0 Ω at 10 kHz → 157.2 Ω at 1 MHz, matching the analytic values to six-plus
figures). `verify_rcpac.py` parses the swept output vector and asserts every point
against `|Z(f)|`.

A **pumped nonlinear** circuit fills the off-diagonal harmonic blocks, so its
sideband-0 response is the genuine periodic-AC response (which differs from a plain
`.ac` because it accounts for the periodic operating point) — through the same code
path.

## Files changed

| File | Change |
|---|---|
| `ngspice-46/src/include/ngspice/pssdefs.h` | `PSSan`: add `PSSdoPAC` + `PACfStart`/`PACfStop`/`PACpoints`/`PACstepType`; param enum `PAC_*` |
| `ngspice-46/src/spicelib/analysis/psssetp.c` | `PSSsetParm` cases + `PSSparms` entries for the `pac_*` parameters |
| `ngspice-46/src/spicelib/parser/inp2dot.c` | `dot_pac` — parse the `.pac` card onto the PSS analysis with the sweep params + `PSSdoPAC`; dispatch `.pac` |
| `ngspice-46/src/spicelib/analysis/dcpss.c` | factor the E-121 engine into `pac_extract_harmonics` + `pac_solve_at`; add `pac_sweep` (frequency sweep → complex `"PAC Analysis"` plot); call it from `DCpss` when `PSSdoPAC` |
| `examples/rfpss_examples/rc_pac.cir`, `verify_rcpac.py` | `.pac` example + a check that the swept sideband-0 response equals the analytic AC driving-point impedance |

## Scope

E-122 delivers a working `.pac` command with correct, verified periodic-AC output.
The present stimulus is a unit current at the osc (probe) node and the output is the
0-th sideband; the natural extensions are a **source-referenced stimulus** (drive a
named small-signal source, as `.ac` does) and **multi-sideband conversion-gain
output** (emit every sideband `f_in + k·f0` as its own vector). Both reuse the same
conversion-matrix solve, which is also the substrate for **periodic noise** (fold
device-noise sidebands through `Hᵀ`) and **PXF**.
