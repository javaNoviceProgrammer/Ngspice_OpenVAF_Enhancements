# Vectored net / bus port examples (version4)

Self-contained correctness examples for OpenVAF/ngspice **vectored net
("bus") declaration** support (`<discipline> [msb:lsb] name;` with
bit-select `name[i]` access), covering **DC**, **AC**, and **transient**
analysis. Everything here uses the **version4** toolchain:

- compiler : `../OpenVAF-master/target/release/openvaf-r` (or `../bin/macos/apple-silicon/openvaf-r`)
- simulator: `../bin/macos/apple-silicon/ngspice`

See `../Enhancement-3.md` for the full implementation writeup.

## The model: a 4-tap fractional buffer

`bus_buffer.va` drives a single input onto a 4-bit vectored **output port**,
declared non-ANSI style (bare names in the module header, direction and
width given in the body):

```verilog
`include "disciplines.vams"

module bus_buffer(in, out);
    input in;
    output [0:3] out;
    electrical in;
    electrical [0:3] out;

    parameter real gain = 1.0 from (0:inf);

    analog begin
        V(out[0]) <+ 0.25 * gain * V(in);
        V(out[1]) <+ 0.50 * gain * V(in);
        V(out[2]) <+ 0.75 * gain * V(in);
        V(out[3]) <+ 1.00 * gain * V(in);
    end
endmodule
```

`output [0:3] out;` expands into four independent scalar OSDI terminals
(`out[0]`..`out[3]`), each driven by its own bit-select branch contribution
`V(out[i]) <+ ...`. Each tap is a purely resistive/algebraic fraction of the
input — `out[0]` = 0.25·`gain`·`in`, `out[1]` = 0.5·`gain`·`in`, `out[2]` =
0.75·`gain`·`in`, `out[3]` = `gain`·`in` — so this exercises bus
declaration, port expansion, and bit-select `V()` access end-to-end with an
easy-to-verify closed-form expected result.

## The test circuit

All three `.cir` files instantiate the model with `gain=1.0` and a single
voltage source driving `in`. The bus port's four terminals connect
positionally, in ascending bit order, to four separate netlist nodes:

```
.model buf4 bus_buffer (gain=1.0)
Nbuf1 in out0 out1 out2 out3 buf4
```

## Results

| Analysis | Sweep | Expected | Observed |
|---|---|---|---|
| DC | `V(in)` from −2V to 2V | `out[i] = (0.25, 0.5, 0.75, 1.0)[i] * V(in)` | exact match across the sweep |
| AC | 1 kHz – 1 GHz | flat gain per tap: −12.04 dB / −6.02 dB / −2.50 dB / 0 dB, 0° phase (purely algebraic, no reactive elements) | flat across the full sweep, matches `20*log10(tap fraction)` exactly |
| Transient | 1 kHz sine on `V(in)` | each tap tracks `V(in)` instantaneously, scaled by its fraction | overlays exactly, no lag |

![DC sweep](dc.png)
![AC response](ac.png)
![Transient response](tran.png)

## Layout

```
bus_examples/
  bus_buffer.va        4-tap fractional buffer with a [0:3] bus output port
  bus_buffer.osdi      compiled with version4 openvaf-r
  dc_sim.cir            DC sweep of V(in)
  ac_sim.cir            AC sweep 1kHz-1GHz
  tran_sim.cir          1kHz sine transient
  _setup.sh             picks the right bin/<os>/<arch> binaries and recompiles
                         the model for this platform (sourced by run_examples.sh)
  run_examples.sh        runs all three with ngspice and writes dc/ac/tran.txt
  plot_results.py       plots dc/ac/tran.txt to dc/ac/tran.png
  dc.txt, ac.txt, tran.txt   raw wrdata output from the last run
  dc.png, ac.png, tran.png  plotted results (see above)
```

`dc_sim.cir`/`ac_sim.cir`/`tran_sim.cir` reference `OSDIFILE`/`RESULTFILE`
placeholders rather than hardcoded paths — `run_examples.sh` substitutes
them at run time, so the checked-in netlists stay portable across machines
and OS/architectures.

## Reproduce

```bash
# run DC, AC, transient (compiles bus_buffer.va for this platform first)
bash run_examples.sh

# plot the results
python3 plot_results.py
```
