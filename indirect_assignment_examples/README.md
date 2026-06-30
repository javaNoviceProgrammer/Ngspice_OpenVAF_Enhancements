# Indirect branch assignment examples (version3)

Self-contained correctness examples for OpenVAF/ngspice **indirect branch
assignment** support (`<lhs> : <rhs> == <expr>;`), covering **DC**, **AC**,
and **transient** analysis. Everything here uses the **version3** toolchain:

- compiler : `../OpenVAF-master/target/release/openvaf-r` (or `../bin/macos/apple-silicon/openvaf-r`)
- simulator: `../bin/macos/apple-silicon/ngspice`

See `../Enhancement-2.md` for the full implementation writeup.

## The model: an ideal op-amp

`opamp.va` is the canonical LRM example (Accellera Std VAMS-2023, p. 114):

```verilog
`include "disciplines.vams"

module opamp(out, pin, nin);
    inout out, pin, nin;
    electrical out, pin, nin;
    analog
        V(out):V(pin,nin) == 0;
endmodule
```

This declares an ideal, infinite-gain, zero-output-impedance op-amp: `out` is
driven by a free unknown (an ideal voltage source), solved each time step so
that `V(pin,nin) == 0` — i.e. the two inputs are forced to the same voltage,
with the output sourcing/sinking whatever is needed to make that true.

## The test circuit: unity-gain buffer

All three `.cir` files instantiate the op-amp with negative feedback
(`nin` tied directly to `out`) and a small load resistor:

```
.model amp opamp()
Namp1 out pin out amp
RL out 0 1k
```

With `nin == out`, the constraint `V(pin,nin) == 0` becomes `V(out) == V(pin)`
— a unity-gain voltage follower. This is the simplest circuit that exercises
the feature end-to-end (the op-amp alone, without feedback, is
under-determined).

## Results

| Analysis | Sweep | Expected | Observed |
|---|---|---|---|
| DC | `V(pin)` from −2V to 2V | `V(out) == V(pin)` | exact match across the sweep |
| AC | 1 kHz – 1 GHz | 0 dB gain, 0° phase (ideal, infinite bandwidth) | flat 0 dB / 0° across the full sweep |
| Transient | 1 MHz sine on `V(pin)` | `V(out)` tracks `V(pin)` with no lag | overlays exactly |

![DC sweep](dc.png)
![AC response](ac.png)
![Transient response](tran.png)

## Layout

```
indirect_assignment_examples/
  opamp.va            ideal op-amp:  V(out):V(pin,nin) == 0
  opamp.osdi          compiled with version3 openvaf-r
  dc_sim.cir           unity-gain buffer, DC sweep of V(pin)
  ac_sim.cir           unity-gain buffer, AC sweep 1kHz-1GHz
  tran_sim.cir         unity-gain buffer, 1MHz sine transient
  run_examples.sh      runs all three with ngspice and writes dc/ac/tran.txt
  plot_results.py      plots dc/ac/tran.txt to dc/ac/tran.png
  dc.txt, ac.txt, tran.txt   raw wrdata output from the last run
  dc.png, ac.png, tran.png  plotted results (see above)
```

## Reproduce

```bash
# (re)compile the model
../bin/macos/apple-silicon/openvaf-r opamp.va -o opamp.osdi

# run DC, AC, transient
bash run_examples.sh

# plot the results
python3 plot_results.py
```
