# `last_crossing()` examples (version7 / Enhancement-6)

Self-contained correctness example for the Verilog-A `last_crossing(expr,
dir)` operator added in Enhancement-6, covering **DC**, **AC**, and
**Transient** analysis. Everything here uses the **version7** toolchain:

- compiler : `../OpenVAF-master-20260610/target/release/openvaf-r`
- simulator: `../ngspice-46/build/src/ngspice` — **must** be this patched
  build; a stock ngspice will not export the `OsdiLastCrossingInfo`
  symbols/runtime this example depends on.

See `../Enhancement-6.md` (§5) for the full implementation writeup. This is
the one Enhancement-6 feature that needed genuine simulator changes, not
just a compiler-side transform: an additive, backward-compatible **OSDI ABI
extension** (`osdi_0_4_enhancement2.h`, following the `absdelay()`
extension's precedent) plus a matching patch to `ngspice-46`'s runtime
(waveform history, crossing detection/interpolation, matrix stamping).

## The model: watch a node and report its last crossing time

```verilog
module last_crossing_demo(in, out);
    inout in, out;
    electrical in, out;
    parameter integer dir = 1 from [-1:1];
    analog begin
        V(out) <+ last_crossing(V(in), dir);
    end
endmodule
```

`V(out)` reports the simulation time of the most recent zero-crossing of
`V(in)`'s *accepted-timepoint history* matching the requested direction
(`dir>0`: rising, `dir<0`: falling, `dir==0`: either) — a genuinely
history-dependent quantity, not derivable from `V(in)`'s instantaneous
value.

## Results

| Analysis | Sweep | Expected | Observed |
|---|---|---|---|
| DC | `V(in)` −1V to 1V | flat `0.0` (a static DC sweep has no transient history to search) | flat `0.0` (`dc_plot.png`) — correct, documented behavior, not a bug |
| AC | 1kHz–100MHz, biased at 0V | zero small-signal gain (crossing time has zero Jacobian sensitivity to the instantaneous input by design) | flat zero (`ac_plot.png`) |
| Transient | 100kHz sine, `dir=1` (rising) | output steps to `10µs`, `20µs`, `30µs`, ... at each rising crossing | matches to 0.015% (e.g. `1.0000148e-5` vs theoretical `1.0e-5`) (`tran_plot.png`, dual-axis) |

Two real bugs were found and fixed only by testing against actual
simulation (both compiled cleanly and were only visible at runtime — see
`../Enhancement-6.md` §5.4): an `int`→`real` type-cast bug for the `dir`
argument, and a shared accepted-timepoint-timeline initialization bug that
only manifested when a circuit used `last_crossing` with no `absdelay`
present.

## Layout

```
last_crossing_examples/
  last_crossing_demo.va    last_crossing() demo
  last_crossing_demo.osdi  compiled with version7 openvaf-r
  dc_sim.cir / ac_sim.cir / tran_sim.cir
  dc_result.txt / ac_result.txt / tran_result.txt
  dc_plot.png / ac_plot.png / tran_plot.png
```

## Reproduce

```bash
OPENVAF=../OpenVAF-master-20260610/target/release/openvaf-r
NGSPICE=../ngspice-46/build/src/ngspice   # must be this patched build

$OPENVAF last_crossing_demo.va -o last_crossing_demo.osdi
$NGSPICE -b dc_sim.cir
$NGSPICE -b ac_sim.cir
$NGSPICE -b tran_sim.cir
```
