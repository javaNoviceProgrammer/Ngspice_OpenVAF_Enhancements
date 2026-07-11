# Enhancement-139 — Cyclostationary QPnoise

E-138 QPnoise folds each device's noise through the 2-D conversion-matrix adjoint, taking
the device power spectral density `S` **once** at the operating-point bias. But under a
two-tone pump a device's bias swings over the period, so its noise `S(t)` is
**cyclostationary** — a diode's shot noise `2qI_D(t)` spikes when the junction conducts,
a switching mixer's noise is gated by the LO. This enhancement adds that mode:

```
qpnoise <output_node> <f_in> cyclo
```

The stationary form (no `cyclo`) is unchanged.

## Method

Mirroring the single-tone cyclostationary `pnoise` (E-126), instead of the frequency-domain
fold `Σ_{(k1,k2)} S·|Ψ_{(k1,k2)}|²` (a single-bias `S`) the `cyclo` path uses the identity

```
onoise(f_in) = (1/P) · Σ_s  S(t_s) · |A_s|²,     A_s(j) = Σ_{(k1,k2)} Ψ_{(k1,k2)}(j) · e^{j 2π (k1 s1/P1 + k2 s2/P2)}
```

where `Ψ` is the same adjoint transfer as E-138 and `A_s` is its **inverse 2-D DFT** — the
time-domain transimpedance at phase-grid sample `s = (s1,s2)`. The device is re-biased at
each sample's quasi-periodic operating point (reconstructed from the retained `V` by the
same `qp_synth` the QPSS Newton used), its noise `S(t_s)` evaluated there, folded through
`A_s`, and averaged over the `P1×P2` grid. By Parseval this reduces **exactly** to the
stationary sum — and hence to `.noise` — whenever `S(t)` is constant.

**The junction-limiting subtlety (same as E-134).** A diode/BJT/MOS limits its internal
junction voltage against a stored value, so a single `MODEINITSMSIG` load at the prescribed
sample voltage leaves it pinned at a stale bias — and its shot noise would not track the
sample, making the "cyclostationary" result collapse back onto the stationary one. Each
sample therefore **settles** the device first (repeated `MODEINITFLOAT` loads walk the
junction to the fixed node voltages) before the PSD is read.

## Verification

`verify_qpnoise.py` grows to 10/10 — the six E-138 checks plus four for the `cyclo` mode:

- **cyclo reduce-to-noise** — with the pump ~0 the PSD is constant, so `cyclo` equals the
  plain `.noise` at `f_in` (Parseval);
- **Parseval under pump** — a thermal resistor's noise is bias-*independent*, so even under
  a full two-tone pump `cyclo` still equals the stationary result exactly;
- **cyclostationary diode** — a hard-pumped diode (its junction switching on and off) has
  strongly bias-dependent shot noise, so `cyclo` differs from the single-bias stationary
  estimate by **>2×** (here ~8×) — the cyclostationary noise enhancement of a switching
  mixer, captured only when the per-sample junction settling is in place;
- **solver parity** — the `cyclo` result is bit-identical under KLU and Sparse.

The other quasi-periodic suites are unaffected: E-133 11/11, E-136 7/7, E-137 7/7.

## Files changed

| File | Change |
|---|---|
| `ngspice-46/src/spicelib/analysis/dcpss.c` | `QPnoiseAnalyze` gains a `cyclo` argument and a cyclostationary branch: IDFT the adjoint transfers to the time domain, re-bias (with junction settling) and evaluate each device's PSD at every `P1×P2` phase sample, average `S(t_s)·|A_s|²`; `qp_harm` stores the extraction grid `P1`/`P2` |
| `ngspice-46/src/frontend/com_qpnoise.c`, `commands.c` | parse the optional `cyclo` keyword; help string |
| `ngspice-46/src/include/ngspice/cktdefs.h` | `QPnoiseAnalyze` prototype gains `cyclo` |
| `examples/qpss_examples/verify_qpnoise.py` | four cyclostationary checks (10/10) |

## Scope

Cyclostationary two-tone noise: the device PSD is averaged over the two-tone period on the
`P1×P2` phase grid, with per-sample junction settling so real semiconductors are
cyclostationary. Follow-ups (unchanged from E-138): a frequency sweep, quasi-periodic
transfer function (QPXF), and more than two tones.
