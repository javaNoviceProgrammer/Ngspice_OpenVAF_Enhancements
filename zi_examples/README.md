# `zi_nd()` z-domain filter examples (version7 / Enhancement-6)

Self-contained correctness example for the Verilog-A `zi_nd`/`zi_np`/
`zi_zd`/`zi_zp` z-domain filter operators added in Enhancement-6, covering
**DC**, **AC**, and **Transient** analysis. Everything here uses the
**version7** toolchain:

- compiler : `../OpenVAF-master-20260610/target/release/openvaf-r`
- simulator: `../ngspice-46/build/src/ngspice`

See `../Enhancement-6.md` (§4) for the full implementation writeup.

## The model: a discrete first-order lowpass, bilinear-transformed to continuous

`zi_lpf.va` realizes a discrete z-domain lowpass `H(z) = b0/(1-a1*z^-1)`,
sampled at period `tstep`, matched to a continuous-time RC lowpass with time
constant `tau` via `a1 = exp(-tstep/tau)`, `b0 = 1-a1` (so DC gain is
exactly unity by construction):

```verilog
module zi_lpf(in, out);
    inout in, out;
    electrical in, out;
    parameter real tau = 10e-6 from (0:inf);
    parameter real tstep = 1e-6 from (0:inf);
    parameter real a1 = exp(-tstep / tau);
    parameter real b0 = 1.0 - a1;
    analog begin
        V(out) <+ zi_nd(V(in), '{b0}, '{1.0, -a1}, tstep);
    end
endmodule
```

Unlike `laplace_*`, a true z-domain filter needs the simulator to hold the
output between samples — dedicated per-timestep/breakpoint support this
codebase doesn't have. Instead this applies the standard **bilinear
(Tustin) transform** to convert the z-domain transfer function into an
equivalent *continuous* s-domain transfer function at compile time, then
reuses the exact same continuous state-space realization `laplace_*` uses.
This is exact at DC and near-DC, with the standard/documented
frequency-warping deviation as frequency approaches the Nyquist rate
(`1/(2*tstep)`).

## Results

| Analysis | Sweep | Expected | Observed |
|---|---|---|---|
| DC | `V(in)` −1V to 1V | exact unity DC gain (`b0 = 1-a1` by construction) | exact match (`dc_plot.png`) |
| AC | 100Hz–1MHz | first-order lowpass, `-3dB` at `1/(2π·tau) ≈ 15.9kHz`; frequency warping visible approaching Nyquist (500kHz) | matches the predicted corner, plus the documented warping artifact in the phase near 1MHz (`ac_plot.png`) |
| Transient | step input | ~63% rise at `t=tau=10µs` (RC step response) | ~61.4% (small, expected deviation from the 10:1 `tstep:tau` bilinear warping) (`tran_plot.png`) |

## Layout

```
zi_examples/
  zi_lpf.va    zi_nd() first-order lowpass demo
  zi_lpf.osdi  compiled with version7 openvaf-r
  dc_sim.cir / ac_sim.cir / tran_sim.cir
  dc_result.txt / ac_result.txt / tran_result.txt
  dc_plot.png / ac_plot.png / tran_plot.png
```

## Reproduce

```bash
OPENVAF=../OpenVAF-master-20260610/target/release/openvaf-r
NGSPICE=../ngspice-46/build/src/ngspice

$OPENVAF zi_lpf.va -o zi_lpf.osdi
$NGSPICE -b dc_sim.cir
$NGSPICE -b ac_sim.cir
$NGSPICE -b tran_sim.cir
```
