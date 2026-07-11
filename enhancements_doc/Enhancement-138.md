# Enhancement-138 — Two-tone small-signal QPnoise (quasi-periodic noise)

With the quasi-periodic steady state (E-136 `qpss … hb`) and its small-signal response
(E-137 `qpac`) in place, this enhancement adds the **noise** analysis on the same
retained operating point — **QPnoise**, the two-tone analogue of `pnoise`:

```
qpnoise <output_node> <f_in>
```

Run after a `qpss <expr> <f1> <f2> hb`, it reports the **output** and **input-referred**
noise density at `f_in`, folding every device's noise contribution over all sidebands
`f_in + k1·f1 + k2·f2`. Under a two-tone pump a device's noise at each sideband is
*converted* (folded) to the output — the effect behind mixer/PA noise figure that a
static `.noise` cannot see.

## Method

QPnoise is `pnoise` (E-124) on the two-tone harmonic set. The transfer from a noise
injection at **every** (node, sideband) to the output is obtained from **one adjoint
solve** of the 2-D conversion matrix:

```
Hᵀ · Ψ = e_{out,(0,0)}
```

`qp_solve_adjoint` reuses `qp_build_matrix` (the same matrix the QPSS Newton used as its
Jacobian), transposes it, and puts a unit at the output node in the `(0,0)` sideband.
`Ψ_{(k1,k2),j}` is then the transimpedance from `(node j, sideband (k1,k2))` to the
output. The device noise routines (`DEVnoise`/`NevalSrc`, OSDI `load_noise`) already
compute `S·|transimpedance|²` reading the transimpedance from `CKTrhs`/`CKTirhs`, so
loading each sideband's adjoint transfer into `CKTrhs` and summing over **all Nh
harmonics** folds the noise exactly:

```
onoise(f_in) = Σ_{k1,k2}  Σ_devices  S_dev · |Ψ_{(k1,k2)}|²
```

The devices are biased at the quasi-periodic operating point (the phase-`(0,0)` sample
of the retained `V`) so each PSD is at the periodic bias. Input-referred noise divides by
the source→output conversion gain at `(0,0)` (the QPAC gain from the captured `AC`-source
stimulus). Since QPnoise only *reads* the retained conversion data, it is
**solver-independent** (KLU and Sparse bit-identical) by construction.

The key structural fact: with **no pump** the conversion matrix is block-diagonal, so
`Ψ` is non-zero only in the `(0,0)` block and QPnoise collapses to ordinary `.noise`.

## Verification

`verify_qpnoise.py` (6/6), numpy-free:

- **reduce-to-noise** — with the pump ~0, QPnoise's `onoise` equals the plain `.noise`
  `onoise_spectrum` at `f_in` to machine precision (the definitive correctness anchor);
- **thermal law** — that value is exactly `4kTR` of the 1 kΩ resistor
  (`4·1.380649e−23·300.15·1000`);
- **conversion active** — under a real two-tone pump the folded `onoise` differs from the
  no-pump value (the matrix is no longer block-diagonal; sidebands contribute and the
  pump-induced conductance loads the node);
- **input-referred** — `inoise = onoise / gain²`;
- **clean failure** — `qpnoise` without a prior `qpss … hb` reports "no QPSS operating
  point";
- **solver parity** — KLU and Sparse `onoise` are bit-identical.

The QPSS suites are unaffected: E-133 stays 11/11, E-136 7/7, E-137 7/7.

## Files changed

| File | Change |
|---|---|
| `ngspice-46/src/spicelib/analysis/dcpss.c` | `QPnoiseAnalyze` (bias at the QPSS operating point, minimal `NOISEAN` context, fold device noise over all sidebands via the adjoint, input-refer through the QPAC gain) and `qp_solve_adjoint` (transpose the 2-D conversion matrix, solve `Hᵀ Ψ = e_{out,(0,0)}`) |
| `ngspice-46/src/frontend/com_qpnoise.c` / `.h`, `commands.c`, `com_commands.h`, `Makefile.am` (+ `Makefile.in`) | the `qpnoise` command (resolve the output node, run `QPnoiseAnalyze`) |
| `ngspice-46/src/include/ngspice/cktdefs.h` | `QPnoiseAnalyze` prototype |
| `examples/qpss_examples/verify_qpnoise.py` | the 6-check QPnoise suite |

## Scope

Two-tone small-signal noise around the E-136 QPSS operating point, single spot frequency
per call, output and input-referred density, folding all sidebands. Uses the stationary
device PSD at the operating-point bias (matching `pnoise`'s default). Follow-ups:
cyclostationary device noise (average the PSD over the two-tone period, as `pnoise` does
with `cyclo`), a frequency sweep, quasi-periodic transfer function (QPXF), and more than
two tones.
