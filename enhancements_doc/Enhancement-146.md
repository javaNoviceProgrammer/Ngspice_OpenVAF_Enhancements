# Enhancement-146 — universal `sweep` command and `.sweep` card

ngspice's `.dc` card sweeps a knob and records the result, but the knob can only be
a **source**, a **resistor**, or a device **instance** parameter (`@m1[w]`). It
cannot step a **model** parameter or a symbolic **`.param`** — as the companion
investigation for Enhancement-144/145 showed, those need `altermod` and
`alterparam` + `reset` respectively, which `.dc` does not do. So there was no way to
say "sweep this model's `is`" or "sweep this `.param` and plot the response."

Enhancement-146 adds a **universal `sweep`** command (and a matching **`.sweep`**
netlist card) that sweeps *any* knob. It **auto-detects** which kind each knob is
and applies it with the right mechanism — the same three the built-in optimizer
uses (Enhancement-130/144/145):

| knob | detected as | applied with |
|---|---|---|
| device / instance / source / resistor (`R1`, `V1`, `@m1[w]`) | instance/device | `alter` (in place) |
| `@<model>[<param>]` (`@dmod[is]`) | model param | `altermod` (in place) |
| a netlist `.param` (`rtop`) | `.param` | `alterparam` + `reset` (re-source) |

## Usage

```
sweep <knob> (<start> <stop> <step> | lin|dec|oct <N> <start> <stop> | list <v>...)
      [-analysis <cmd>] [-output <name>=<expr> ...]

.sweep <knob> ...            (the same, as a netlist card)
```

- **sweep specification** — a `<start> <stop> <step>` range, `lin|dec|oct <N>` (N
  points total / per decade / per octave), or an explicit `list` of values.
- **`-analysis <cmd>`** — the analysis to run at each point (default `op`); any
  ngspice analysis command (`ac dec 20 1 1meg`, `tran 1u 1m`, …).
- **`-output <name>=<expr>`** — an output to record (repeatable). `<expr>` is any
  ngspice expression (its **last** value is taken). The optional `<name>=` gives the
  result vector a clean name, so `plot gain` works even when the expression is a
  function like `mag(v(out))`. With **no** `-output`, every node voltage of the
  analysis is recorded — the `.dc`-like default.

Results go into a new plot named **`sweep`** whose scale is the knob values, so
`plot <output>` shows the output versus the swept knob. The per-point analysis
plots are kept too (`tran1`, `tran2`, …) for overlaying waveforms. Console chatter
from the inner analyses is suppressed via the `ft_optimizing` flag.

### Examples

```spice
* sweep a model parameter (impossible with .dc) and plot the AC gain
sweep @dmod[is] dec 10 1e-15 1e-12 -analysis ac dec 20 1 1meg -output g=mag(v(out))

* sweep a .param straight from the netlist
.sweep rr 1k 5k 1k -analysis ac lin 1 1k 1k -output gain=mag(v(out))
```

## Implementation notes

- New front-end command in `frontend/com_sweep.c` (+ `com_sweep.h`), registered in
  `commands.c` / `com_commands.h` and the frontend `Makefile.am`.
- **Knob-kind auto-detection** (`sw_kind`): for `@X[y]`, `ft_sim->findModel(ckt, X)`
  decides model (→ `altermod`) vs instance (→ `alter`); for a bare name,
  `nupa_get_param(name, &found)` decides `.param` (→ `alterparam` + `reset`) vs
  device (→ `alter`). Both are lightweight, silent lookups.
- The engine sets the knob, runs the `-analysis` command (dispatched synchronously
  through the command table, like the optimizer's `opt_run_cmd`), and evaluates each
  output expression, collecting the results; then it emits the summary plot via the
  nutmeg vector API (`plot_alloc` / `dvec_alloc` / `vec_new`) — the same layer a
  front-end command must use (Enhancement-142).
- **`.sweep` card**: `frontend/inp.c` recognizes a top-level `.sweep` line and adds
  it (minus the leading `.`) to the post-parse control list, so it runs as a `sweep`
  command after the circuit is built.
- **Re-entrancy guard**: a `.param` knob re-sources the deck (`reset`), which re-runs
  a `.sweep` card — a static `sweep_active` flag makes that nested invocation a
  no-op, so the sweep cannot recurse.

## Verification

`examples/sweep_examples/verify_sweep.py` (11/11; front-end command, solver-independent):

- **[1]** an instance/resistor `sweep R1` over a divider reproduces the analytic
  `R2/(R1+R2)` **and matches the built-in `.dc R1` exactly** — the generalization is
  faithful.
- **[2]** a voltage-source sweep gives the linear `v(out)`.
- **[3]** a **model-parameter** sweep `@rmod[r]` (Verilog-A model `r`, via `altermod`).
- **[4]** a symbolic **`.param`** sweep (via `alterparam` + `reset`).
- **[5]** the three kinds are each routed correctly by auto-detection.
- **[6]** the **`.sweep` card** equals the command form and does **not** recurse on
  the `.param` re-source.
- **[7]** an **AC** inner analysis with a named output matches the analytic low-pass
  `|H(1kHz)|`.
- **[8]** a **transient** inner analysis (settled node voltage).
- **[9]** the `lin N` / `list` / `start stop step` specs give the right points.
- **[10]** multiple `-output`s are all recorded.

`sweep_demo.cir` and `sweep_card_demo.cir` are runnable demos.

## Scope and follow-ups

A universal parametric sweep of any circuit knob, with a chosen inner analysis and
arbitrary output expressions, from the command line or the netlist. Follow-ups: a
nested (multi-knob) sweep, and a `.step`-style automatic overlay of the retained
per-point waveform plots.
