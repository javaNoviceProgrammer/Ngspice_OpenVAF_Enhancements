# `slew()` rate-limiter examples (version7 / Enhancement-6)

Self-contained correctness example for the Verilog-A `slew(x, max_pos_rate,
max_neg_rate)` operator added in Enhancement-6, covering **DC**, **AC**, and
**Transient** analysis. Everything here uses the **version7** toolchain:

- compiler : `../OpenVAF-master-20260610/target/release/openvaf-r`
- simulator: `../ngspice-46/build/src/ngspice`

See `../Enhancement-6.md` (§3) for the full implementation writeup.

## The model: a saturating tracking loop

`slew_demo.va` simply passes `V(in)` through `slew()`:

```verilog
module slew_demo(in, out);
    inout in, out;
    electrical in, out;
    parameter real rise = 1e6 from (0:inf);
    parameter real fall = 2e6 from (0:inf);
    analog begin
        V(out) <+ slew(V(in), rise, fall);
    end
endmodule
```

The LRM's `slew()` is an ideal, non-smooth rate limiter, which is not
directly expressible as a well-posed continuous residual (the DC operating
point would be undetermined). Instead this is realized as a **saturating
tracking loop**, `dy/dt = clamp(K*(x - y), -fall, rise)` for a large gain
`K = 1e9 (1/s)` — well-posed at DC (`y = x` uniquely) and reproducing the
rate-limited ramp whenever `x` moves faster than the bound allows.

## Results

| Analysis | Sweep | Expected | Observed |
|---|---|---|---|
| DC | `V(in)` −1V to 1V | steady-state tracking, `out = in` | exact match (`dc_plot.png`) |
| AC | 1kHz–10GHz | first-order lowpass, pole at `K/2π ≈ 159MHz` | matches to the predicted corner (`ac_plot.png`) |
| Transient | pulse (`rise=1e6 V/s`, `fall=2e6 V/s`) | asymmetric rate-limited ramp | measured rates match the specified bounds to 3+ sig figs (`tran_plot.png`) |

## Layout

```
slew_examples/
  slew_demo.va    slew() rate-limiter demo
  slew_demo.osdi  compiled with version7 openvaf-r
  dc_sim.cir / ac_sim.cir / tran_sim.cir
  dc_result.txt / ac_result.txt / tran_result.txt
  dc_plot.png / ac_plot.png / tran_plot.png
```

## Reproduce

```bash
OPENVAF=../OpenVAF-master-20260610/target/release/openvaf-r
NGSPICE=../ngspice-46/build/src/ngspice

$OPENVAF slew_demo.va -o slew_demo.osdi
$NGSPICE -b dc_sim.cir
$NGSPICE -b ac_sim.cir
$NGSPICE -b tran_sim.cir
```
