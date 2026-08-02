# Variable-persistence examples (version8 / Enhancement-7)

Self-contained correctness example for the Enhancement-7 fix that gives
ordinary Verilog-A `real`/`integer` analog-block variables genuine
persistence across evaluations, covering **DC**, **AC**, and **Transient**
analysis. Everything here uses the **version8** toolchain:

- compiler : `../OpenVAF-master-20260610/target/opt/openvaf-r`
- simulator: `../ngspice-46/build/src/ngspice`

See `../Enhancement-7.md` for the full writeup. This is the deeper of the
two Enhancement-7 findings: while fixing `@(initial_step)` gating (see
`../initial_step_examples/`), testing against a real simulation revealed
that **ordinary variables were being silently reset to their default value
on every single evaluation**, not just the first — with zero event-control
involved. Root cause: two `todo!("hidden state")` panics sitting in the
pre-existing codebase (the read side was scaffolded but never backed by
real storage) and an `insert_var_init` pass that unconditionally replaced
every read of a variable's "previous value" with its declared initializer.

## The model: the minimal accumulator

```verilog
module persist_demo(in, out);
    inout in, out;
    electrical in, out;
    real accum;
    analog begin
        accum = accum + 1.0;
        V(out) <+ accum;
    end
endmodule
```

No parameters, no event-control statements at all — this isolates the
persistence fix from the `@(initial_step)` gating fix (covered separately
in `../initial_step_examples/`). Before the fix, `accum` read back `0.0`
every evaluation regardless of what any earlier evaluation had computed, so
`V(out)` stayed flat at exactly `1.0` forever, no matter how long the
transient ran.

`accum` is purely a diagnostic evaluation counter: it increments once per
simulator evaluation (including intermediate Newton iterations), not once
per physical timepoint, so it is intentionally *not* a meaningful function
of `V(in)` — see the DC/AC notes below.

## Results

| Analysis | Sweep | Expected | Observed |
|---|---|---|---|
| DC | `V(in)` −1V to 1V | not a real function of `V(in)` — a roughly-monotonic curve driven by Newton-iteration count per sweep point, included for honesty about what this operator does and doesn't do | matches (`dc_plot.png`) — same "documented negative result" spirit as `last_crossing_examples/`'s DC plot in Enhancement-6 |
| AC | 1Hz–100MHz | ~zero small-signal gain (`accum`'s recurrence has zero dependence on `V(in)`) | flat ~zero (`ac_plot.png`) |
| Transient | 100µs, DC input | the key demo: a clean, sustained, roughly linear ramp over the whole transient, proving `accum` is never silently reset | matches (`tran_plot.png`) |

## Layout

```
variable_persistence_examples/
  persist_demo.va    minimal accumulator, no parameters/event-control
  persist_demo.osdi  compiled with version8 openvaf-r
  dc_sim.cir / ac_sim.cir / tran_sim.cir
  dc_result.txt / ac_result.txt / tran_result.txt
  dc_plot.png / ac_plot.png / tran_plot.png
```

## Reproduce

```bash
OPENVAF=../OpenVAF-master-20260610/target/opt/openvaf-r
NGSPICE=../ngspice-46/build/src/ngspice

$OPENVAF persist_demo.va -o persist_demo.osdi
$NGSPICE -b dc_sim.cir
$NGSPICE -b ac_sim.cir
$NGSPICE -b tran_sim.cir
```
