# Array-variable declaration examples (version5)

Self-contained correctness example for OpenVAF **array-variable
declaration** support (`<type> [msb:lsb] name;`, with indexed read/write
`name[i]` access via a compile-time-constant `i`). Everything here uses
the **version5** toolchain:

- compiler : `../OpenVAF-master-20260610/target/release/openvaf-r` (or `../bin/macos/apple-silicon/openvaf-r`)
- simulator: `../bin/macos/apple-silicon/ngspice`

See `../Enhancement-4.md` (Part 2) for the full implementation writeup,
including why this needed almost no new lowering code (it reuses
Enhancement-3's bit-select machinery, generalized to resolve to a
variable instead of only a net).

## The model: a 5-tap weighted sum

`array_var_fir.va` declares a 5-element `real` array variable, writes
each element individually, then reads them all back in a single
expression:

```verilog
`include "disciplines.vams"

module array_var_fir(in, out);
    input in;
    output out;
    electrical in, out;

    real [0:4] coeffs;

    analog begin
        coeffs[0] = 0.1;
        coeffs[1] = 0.2;
        coeffs[2] = 0.3;
        coeffs[3] = 0.2;
        coeffs[4] = 0.2;
        V(out) <+ (coeffs[0] + coeffs[1] + coeffs[2] + coeffs[3] + coeffs[4]) * V(in);
    end
endmodule
```

`real [0:4] coeffs;` expands into five independent scalar variables
(`coeffs[0]`..`coeffs[4]`) at compile time — there is no genuine runtime
array storage. The coefficients sum to exactly 1.0, so `V(out)` should
track `V(in)` 1:1 — an easy-to-verify closed-form expected result.

## Results

| Analysis | Sweep | Expected | Observed |
|---|---|---|---|
| DC | `V(in)` from −2V to 2V | `out = in` exactly (coefficients sum to 1.0) | exact 1:1 match across the sweep |

## Diagnostics (not included as `.cir`/CI fixtures, verified by hand — see Enhancement-4.md)

- `coeffs[10] = 1.0;` against a declared `[0:4]` array → out-of-range bit-select error.
- `V(out) <+ coeffs * V(in);` (missing `[i]`) → bare-reference error.
- `real [0:2] tmp;` declared inside an `analog function` → unsupported-scope error (array variables are module-body scope only).

## Layout

```
array_var_examples/
  array_var_fir.va    5-tap weighted-sum model exercising declare/write/read
  array_var_fir.osdi  compiled with version5 openvaf-r (macOS/Apple Silicon snapshot)
  dc_sim.cir           DC sweep of V(in)
  _setup.sh            picks the right bin/<os>/<arch> binaries and recompiles
                        the model for this platform (sourced by run_examples.sh)
  run_examples.sh       runs the DC sweep with ngspice and writes dc.txt
  dc.txt               raw wrdata output from the last run
```

`dc_sim.cir` references `OSDIFILE`/`RESULTFILE` placeholders rather than
hardcoded paths — `run_examples.sh` substitutes them at run time, so the
checked-in netlist stays portable across machines and OS/architectures.

## Reproduce

```bash
# run the DC sweep (compiles array_var_fir.va for this platform first)
bash run_examples.sh
```
