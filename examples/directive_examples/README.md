# Compiler directive examples (version7 / Enhancement-6)

Self-contained correctness example for the ten Verilog-A/AMS **compiler
directives** added in Enhancement-6 (`` `default_discipline ``,
`` `celldefine ``/`` `endcelldefine ``, `` `unconnected_drive ``/
`` `nounconnected_drive ``, `` `timescale ``, `` `line ``, `` `pragma ``,
`` `undefineall ``, `` `default_nettype ``), covering **DC**, **AC**, and
**Transient** analysis. Everything here uses the **version7** toolchain:

- compiler : `../OpenVAF-master-20260610/target/opt/openvaf-r`
- simulator: `../ngspice-46/build/src/ngspice`

See `../Enhancement-6.md` (§1) for the full implementation writeup — before
this enhancement, every one of these directives hard-failed compilation as
an undefined macro call instead of being parsed/ignored, which broke real
foundry `.va` files that carry this boilerplate.

## The model: a gain buffer wrapped in every new directive

`directive_demo.va` is an ordinary gain buffer (`V(out) <+ gain * V(in)`),
deliberately wrapped in all ten directives to prove they no longer break
compilation:

```verilog
`default_discipline electrical
`default_nettype none
`celldefine
`timescale 1ns/1ps
`unconnected_drive pull1
`include "disciplines.vams"

module directive_demo(in, out);
    inout in, out;
    electrical in, out;
    parameter real gain = 0.5 from (0:inf);
    analog begin
        V(out) <+ gain * V(in);
    end
endmodule

`nounconnected_drive
`endcelldefine
`pragma protect begin
`pragma protect end
`undefineall
```

## Results

| Analysis | Sweep | Expected | Observed |
|---|---|---|---|
| DC | `V(in)` −1V to 2V | `out = 0.5 * in` | exact match (`dc_plot.png`) |
| AC | 1Hz–100MHz | flat 0.5 gain (≈ −6dB), 0° phase | flat, matches (`ac_plot.png`) |
| Transient | 10kHz sine | output = 0.5× scaled sine | matches (`tran_plot.png`) |

## Layout

```
directive_examples/
  directive_demo.va    gain buffer wrapped in all 10 new directives
  directive_demo.osdi  compiled with version7 openvaf-r
  dc_sim.cir / ac_sim.cir / tran_sim.cir
  dc_result.txt / ac_result.txt / tran_result.txt   raw wrdata output
  dc_plot.png / ac_plot.png / tran_plot.png
```

## Reproduce

```bash
OPENVAF=../OpenVAF-master-20260610/target/opt/openvaf-r
NGSPICE=../ngspice-46/build/src/ngspice

$OPENVAF directive_demo.va -o directive_demo.osdi
$NGSPICE -b dc_sim.cir
$NGSPICE -b ac_sim.cir
$NGSPICE -b tran_sim.cir
```
