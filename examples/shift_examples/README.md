# `<<<` / `>>>` arithmetic shift operator examples (version7 / Enhancement-6)

Self-contained correctness example for the Verilog-A **arithmetic shift
operators** `<<<` (left) and `>>>` (right, sign-extending) added in
Enhancement-6, covering **DC**, **AC**, and **Transient** analysis.
Everything here uses the **version7** toolchain:

- compiler : `../OpenVAF-master-20260610/target/opt/openvaf-r`
- simulator: `../ngspice-46/build/src/ngspice`

See `../Enhancement-6.md` (§2) for the full implementation writeup,
including a real pre-existing **lexer bug** found and fixed along the way:
the three-character `<<<`/`>>>` tokens only consumed two of their three
characters, so `<<<` previously mis-tokenized as `<<` followed by a stray
`<`.

## The model: a quantizer + shifter

`shift_demo.va` quantizes `V(in)` into a signed integer code via `floor()`,
then computes both an arithmetic-left-shifted and an arithmetic-right-shifted
(sign-extending) version of that code and outputs their difference — a
purely integer/bit-manipulation chain with a directly visible staircase
transfer curve:

```verilog
module shift_demo(in, out);
    inout in, out;
    electrical in, out;
    parameter integer shift_amount = 2 from [0:8];
    integer code, shifted_up, shifted_down;
    real out_val;

    analog begin
        code = floor(V(in) * 16);              // quantize -16..16 -> integer code
        shifted_up = code <<< shift_amount;     // arithmetic left shift (== <<)
        shifted_down = code >>> shift_amount;   // arithmetic right shift (sign-extending)
        out_val = shifted_up - shifted_down;
        V(out) <+ out_val;
    end
endmodule
```

## Results

| Analysis | Sweep | Expected | Observed |
|---|---|---|---|
| DC | `V(in)` −1V to 1V | signed staircase, sign-extension visible for negative input | matches (`dc_plot.png`) |
| AC | 1Hz–100MHz, biased at 0.3V | ~zero small-signal gain (integer ops have zero derivative a.e.) | flat near-zero (`ac_plot.png`) |
| Transient | ±1V triangle wave | staircase output tracking the ramp | matches (`tran_plot.png`) |

The AC result is a deliberate, documented negative result: `floor()`/shift
derivatives are zero almost everywhere, so there is no meaningful linearized
small-signal transfer function for this operator class — confirmed rather
than hidden.

## Layout

```
shift_examples/
  shift_demo.va    quantizer + <<< / >>> demo
  shift_demo.osdi  compiled with version7 openvaf-r
  dc_sim.cir / ac_sim.cir / tran_sim.cir
  dc_result.txt / ac_result.txt / tran_result.txt
  dc_plot.png / ac_plot.png / tran_plot.png
```

## Reproduce

```bash
OPENVAF=../OpenVAF-master-20260610/target/opt/openvaf-r
NGSPICE=../ngspice-46/build/src/ngspice

$OPENVAF shift_demo.va -o shift_demo.osdi
$NGSPICE -b dc_sim.cir
$NGSPICE -b ac_sim.cir
$NGSPICE -b tran_sim.cir
```
