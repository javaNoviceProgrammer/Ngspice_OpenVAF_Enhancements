# Enhancement-124 — periodic noise (`.pnoise`)

The second RF periodic small-signal analysis on the conversion-matrix engine. Where
[`.pac`](Enhancement-122.md) propagates a deterministic small signal, `.pnoise`
propagates **noise**: each device's noise sources are converted between sidebands by
the periodic operating point, and the output noise at a given frequency is the sum
of every source folded through the harmonic conversion matrix. This is the analysis
that gives a mixer its noise figure or an oscillator its phase-noise skirt.

## The idea, and how it reuses ngspice's noise machinery

Ordinary `.noise` computes, per frequency, the **adjoint transimpedance** — solve
`Yᵀ x = e_out`, leaving in `CKTrhs`/`CKTirhs` the transfer from every node to the
output — and then each device's noise routine adds `S·|Δtransimpedance|²` to the
output noise (`S` = the device's noise PSD). The device routines (`NevalSrc`,
OSDI `load_noise`) read that transimpedance straight from `CKTrhs`/`CKTirhs`.

`.pnoise` keeps *exactly* those device routines and only changes the transfer they
see. It solves the **adjoint of the conversion matrix**, `Hᵀ Ψ = e_{out,0}`, whose
sideband-`k` block `Ψ_k` is the transfer from a noise injection at sideband `k` to
the output at sideband 0. Then, per frequency:

```
onoise(f) = Σ_k  Σ_devices  S · |Ψ_k(p) − Ψ_k(n)|²
```

is computed by **loading `Ψ_k` into `CKTrhs`/`CKTirhs` and calling the device noise
routines once per sideband `k = −M … M`, accumulating** — each device folds its own
noise correctly, with no per-device special-casing, so `.pnoise` covers resistors,
OSDI/Verilog-A devices, transistors, everything `.noise` does. A minimal local
`NOISEAN` job (with `NStpsSm = 0`, `prtSummary` off) gives those routines the
context they expect while the summary/integration side effects stay dormant. The
input-referred spectrum divides by the source→output **conversion** gain (the
[E-123](Enhancement-123.md) source-referenced solve at sideband 0).

## The command

```
.pnoise Fguess StabTime OscNode Points Harmonics SC_iter Steady_coeff \
        OutNode InSrc <DEC|OCT|LIN> Npts Fstart Fstop
```

The first seven fields are the [`.pss`](Enhancement-117.md) parameters, then the
output node, the input source (for the input-referred spectrum), and an `.ac`-style
sweep. It reuses the PSS analysis via a `PSSdoPnoise` flag and produces a
`PNoise Analysis` plot with `onoise_spectrum` and `inoise_spectrum` vectors.

## Verification

The 1 MHz-driven RC low-pass (`R=1k`, `C=1n`), output `b`, swept 10 kHz–1 MHz:

```
Index   frequency       onoise_spectrum
0       1.000000e+04    1.651088e-17
...
10      1.000000e+05    1.188432e-17
...
20      1.000000e+06    4.095038e-19
```

Because the circuit is **linear**, the periodic Jacobian is time-invariant: the
conversion matrix is block-diagonal, only sideband 0 contributes, and `.pnoise`
must reduce to ordinary `.noise`. It does — the output noise density equals the
analytic thermal-noise result

```
S_out(f) = 4·k·T·R1 / (1 + (2π·f·R1·C1)²)   [V²/Hz]
```

to a worst-case relative error of **8e−7** across the sweep (`1.65e−17` at 10 kHz
down to `4.10e−19` at 1 MHz), and it matches a plain `.noise` run of the same
network **to every printed digit**. A pumped nonlinear circuit fills the
off-diagonal conversion blocks, so its noise genuinely folds between sidebands
(up/down-conversion, phase noise) through the same code path. `verify_rcpnoise.py`
asserts pnoise against both the analytic law and the `.noise` reference.

## Files changed

| File | Change |
|---|---|
| `ngspice-46/src/include/ngspice/pssdefs.h` | `PSSan`: `PSSdoPnoise`, `PnOutNode`, `PnInSrc`; `PNOISE_*` param ids |
| `ngspice-46/src/spicelib/analysis/psssetp.c` | `pnoise` / `pnoise_out` / `pnoise_insrc` setters + IFparm entries |
| `ngspice-46/src/spicelib/parser/inp2dot.c` | `dot_pnoise` — parse the `.pnoise` card onto the PSS analysis |
| `ngspice-46/src/spicelib/analysis/dcpss.c` | `pac_solve_adjoint` (transposed conversion solve) and `pnoise_sweep` — fold every device's noise over sidebands via the device noise routines and a local `NOISEAN` context; called from `DCpss` when `PSSdoPnoise` |
| `examples/rfpss_examples/rc_pnoise.cir`, `verify_rcpnoise.py` | `.pnoise` example + checks vs. the analytic law and `.noise` |

## Scope

`.pnoise` delivers a working periodic-noise analysis that reuses every device noise
model and reduces exactly to `.noise` in the linear limit. The first cut evaluates
each device's noise PSD at the periodic operating-point sample (a stationary
approximation of the cyclostationary source); harmonic (cyclostationary) noise-PSD
modulation and a dedicated phase-noise (jitter) output are the natural refinements.
The same conversion-matrix adjoint is the last piece needed for **PXF** (periodic
transfer function).
