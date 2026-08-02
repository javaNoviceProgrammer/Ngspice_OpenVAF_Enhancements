# `transition()` edge-shaping examples (version7 / Enhancement-6)

Self-contained correctness example for the Verilog-A `transition(x, td,
trise, tfall)` operator added in Enhancement-6, covering **DC**, **AC**, and
**Transient** analysis. Everything here uses the **version7** toolchain:

- compiler : `../OpenVAF-master-20260610/target/opt/openvaf-r`
- simulator: `../ngspice-46/build/src/ngspice`

See `../Enhancement-6.md` (§3) for the full implementation writeup.

## The model: a delayed, rate-shaped comparator

`transition_demo.va` compares `V(in)` against a fixed threshold, then
shapes the resulting 0/1 signal with a delay and independent rise/fall
times:

```verilog
module transition_demo(in, out);
    inout in, out;
    electrical in, out;
    parameter real td = 1n from [0:inf);
    parameter real trise = 2n from (0:inf);
    parameter real tfall = 3n from (0:inf);
    integer cmp;
    analog begin
        cmp = V(in) > 0.5 ? 1 : 0;
        V(out) <+ transition(cmp, td, trise, tfall);
    end
endmodule
```

`transition(x, td, trise, tfall)` is realized as `slew(absdelay(x, td),
1/trise, 1/tfall)`: the delay stage reuses `absdelay`'s exact mechanism, the
rate stage reuses `slew`'s tracking loop (see `slew_examples/`).
`trise`/`tfall` are transition *times* per the LRM, converted to rates via
`rate = 1/t` — exact for a unit-amplitude (comparator-style) input, which is
what this model exercises.

## Results

| Analysis | Sweep | Expected | Observed |
|---|---|---|---|
| DC | `V(in)` 0V to 1V | hard step at the 0.5V threshold (DC steady-state is unaffected by edge shaping) | matches (`dc_plot.png`) |
| AC | 1kHz–10GHz, biased at 0.3V (below threshold) | ~zero small-signal gain (comparator has zero local derivative away from threshold) | flat near-zero (`ac_plot.png`) |
| Transient | pulse crossing the 0.5V threshold | `td` delay followed by asymmetric rise/fall shaping | matches (`tran_plot.png`) |

## Layout

```
transition_examples/
  transition_demo.va    transition() edge-shaping demo
  transition_demo.osdi  compiled with version7 openvaf-r
  dc_sim.cir / ac_sim.cir / tran_sim.cir
  dc_result.txt / ac_result.txt / tran_result.txt
  dc_plot.png / ac_plot.png / tran_plot.png
```

## Reproduce

```bash
OPENVAF=../OpenVAF-master-20260610/target/opt/openvaf-r
NGSPICE=../ngspice-46/build/src/ngspice

$OPENVAF transition_demo.va -o transition_demo.osdi
$NGSPICE -b dc_sim.cir
$NGSPICE -b ac_sim.cir
$NGSPICE -b tran_sim.cir
```
