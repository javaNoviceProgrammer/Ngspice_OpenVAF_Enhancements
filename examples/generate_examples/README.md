# `generate for` / `genvar` examples (version9)

Self-contained correctness example for OpenVAF's new **`generate for` /
`genvar`** support (Enhancement-8, Feature B), covering a **DC** sweep.
Uses the **version9** toolchain:

- compiler : `../OpenVAF-master-20260610/target/opt/openvaf-r` (built with `--features openvaf-driver/llvm18`)
- simulator: `../ngspice-46/build/src/ngspice` (locally built, OSDI-capable — not the system-wide `ngspice`)

See `../Enhancement-8.md` for the full implementation writeup.

## The model: a `generate for`-built resistor ladder

`resistor_ladder_generate.va` builds a 4-element series-resistor chain with
a compile-time loop instead of 4 hand-written instantiations:

```verilog
module ladder_generate(in, out);
    inout in, out;
    electrical in, out;
    electrical [0:4] node;
    genvar i;

    resistor #(.r(1e3)) rin(in, node[0]);

    generate
        for (i = 0; i < 4; i = i + 1) begin : gen_block
            resistor #(.r(1e3)) r(node[i], node[i+1]);
        end
    endgenerate

    resistor #(.r(1e3)) rout(node[4], out);
endmodule
```

The `generate for` loop unrolls at compile time into 4 concrete resistor
instantiations (`r_0`..`r_3`), each wiring adjacent elements of the
`node[0:4]` array — identical in shape to `resistor_ladder_manual.va`,
which writes those 4 instantiations by hand as the ground-truth reference:

```verilog
module ladder_manual(in, out);
    ...
    resistor #(.r(1e3)) rin(in, node[0]);
    resistor #(.r(1e3)) r_0(node[0], node[1]);
    resistor #(.r(1e3)) r_1(node[1], node[2]);
    resistor #(.r(1e3)) r_2(node[2], node[3]);
    resistor #(.r(1e3)) r_3(node[3], node[4]);
    resistor #(.r(1e3)) rout(node[4], out);
endmodule
```

Both together form a 6 x 1 kohm = 6 kohm series chain between `in` and
`out`, loaded by `Rload = 1 Mohm` to ground — an ordinary two-resistor
voltage divider.

## Compile-time verification (`--dump-mir`)

Before running ngspice, both `.va` files were compiled with `--dump-mir`
and the resulting "Optimized model setup MIR" compared: both produce the
same block/branch/phi structure (`br v20, block4, block3`, ...), differing
only in SSA value numbers — i.e. `generate for` elaborates to *exactly* the
same compiled structure as the hand-written version, not merely equivalent
runtime behavior.

## Running

```sh
../OpenVAF-master-20260610/target/opt/openvaf-r resistor_ladder_generate.va -o resistor_ladder_generate.osdi
../OpenVAF-master-20260610/target/opt/openvaf-r resistor_ladder_manual.va -o resistor_ladder_manual.osdi
../ngspice-46/build/src/ngspice -b dc_sim_generate.cir
../ngspice-46/build/src/ngspice -b dc_sim_manual.cir
python3 compare_ladder.py
```

`compare_ladder.py` cross-checks the `generate for` DC sweep against both
(a) the hand-written `ladder_manual` circuit, bit-for-bit, and (b) an
independent analytical resistor-divider computation, and plots `dc.png`.

Result: `generate` vs. `manual` differ by exactly `0.0` at every swept
point (bit-exact); both differ from the analytical prediction by at most
`2.068e-09` V (floating-point noise level, matching the tolerance other
example folders in this project use).

## Scope / known limitations

Per this enhancement's design (see `Enhancement-8.md`): `generate for` is
**structural/declarative only** — it can generate repeated net, instance,
variable, and parameter declarations, but per the Verilog-A LRM it may
never emit a new `analog` block. `generate if` / `generate case` are not
implemented (only `generate for`, with an ascending-integer `genvar` loop).
The loop bound, initial value, and step must all constant-fold to integer
literals at compile time (`NonConstantGenerateBound` is reported otherwise).
