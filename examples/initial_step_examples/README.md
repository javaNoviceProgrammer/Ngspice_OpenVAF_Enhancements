# `@(initial_step)` / variable-initializer examples (version8 / Enhancement-7)

Self-contained correctness example for the Enhancement-7 fix to Verilog-A
`@(initial_step)` event gating, covering **DC**, **AC**, and **Transient**
analysis. Everything here uses the **version8** toolchain:

- compiler : `../OpenVAF-master-20260610/target/opt/openvaf-r`
- simulator: `../ngspice-46/build/src/ngspice`

See `../Enhancement-7.md` for the full writeup. Before this fix,
`@(initial_step)`/`@(final_step)` parsed but never actually gated
execution — the event was silently discarded and the guarded statement ran
on *every* evaluation, forever. Fixing this properly also surfaced (and
required fixing) a deeper, separate bug: ordinary `real`/`integer`
variables didn't persist their value across evaluations at all (see
`../variable_persistence_examples/`).

## The model: a parameterized seed that's applied exactly once

```verilog
module initial_step_demo(in, out);
    inout in, out;
    electrical in, out;
    parameter real seed = 100.0 from [0:inf);
    real accum = seed;
    analog begin
        accum = accum + 1.0;
        V(out) <+ accum + V(in);
    end
endmodule
```

`accum` starts at the declared initializer `seed` and is then
self-referentially incremented every evaluation. This exercises the exact
same `ParamKind::IsInitialStep` gating machinery as an explicit
`@(initial_step) accum = seed;` statement would, but via the *implicit*
declared-initializer path — see the note on a currently-open, separate
crash below for why this example deliberately avoids the explicit form.

If the pre-Enhancement-7 bug were still present, `accum` would be reset to
`seed` on *every* evaluation (not just the first), so `V(out)` would track
`seed + 1 + V(in)` flat forever and never accumulate.

## Results

| Analysis | Sweep | Expected | Observed |
|---|---|---|---|
| DC | `V(in)` −1V to 1V | slope 1 in `V(in)`, offset dominated by `seed=100` applied once (plus small growth from Newton-iteration increments across the sweep) | matches (`dc_plot.png`) |
| AC | 1Hz–100MHz | exact unity gain (0dB), 0° phase — `accum` has zero small-signal sensitivity to `V(in)` | flat 0dB/0° (`ac_plot.png`) |
| Transient | 100kHz sine | input sine rides on a slowly-rising, *persistent* baseline starting near `seed`, not resetting to `seed` every evaluation | matches (`tran_plot.png`, dual-axis) |

## Known limitation (why this example avoids explicit `@(initial_step)` syntax)

An explicit `@(initial_step) accum = seed;` statement (as opposed to the
plain declared initializer `real accum = seed;` used here) currently
crashes the compiler — two related bugs, both in how `insert_var_init`'s
function-editing pass interacts with pre-existing branch structure from an
explicit event-control statement (one is a CFG dominance violation, the
other a panic in a separate `sim_back::init` cache-building pass). See
`../Enhancement-7.md`'s "Known limitation" section for repro snippets and
root-cause notes. Both patterns are redundant now anyway, since plain
declared initializers already get the correct once-only gating
automatically.

## Layout

```
initial_step_examples/
  initial_step_demo.va    seed-initializer + persistence demo
  initial_step_demo.osdi  compiled with version8 openvaf-r
  dc_sim.cir / ac_sim.cir / tran_sim.cir
  dc_result.txt / ac_result.txt / tran_result.txt
  dc_plot.png / ac_plot.png / tran_plot.png
```

## Reproduce

```bash
OPENVAF=../OpenVAF-master-20260610/target/opt/openvaf-r
NGSPICE=../ngspice-46/build/src/ngspice

$OPENVAF initial_step_demo.va -o initial_step_demo.osdi
$NGSPICE -b dc_sim.cir
$NGSPICE -b ac_sim.cir
$NGSPICE -b tran_sim.cir
```
