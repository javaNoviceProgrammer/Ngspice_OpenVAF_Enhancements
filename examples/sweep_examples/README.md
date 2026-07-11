# Universal `sweep` command + `.sweep` card (Enhancement-146)

`sweep` varies **any** circuit knob over a range and records one or more outputs
into a plottable result — a generalization of `.dc`, which can only step a source,
a resistor, or a device **instance** parameter. `sweep` additionally handles
**model** parameters and symbolic **`.param`** values, auto-detecting which kind
each knob is and applying it with the right mechanism:

| knob | detected as | applied with |
|---|---|---|
| device / instance / source / resistor (`R1`, `V1`, `@m1[w]`) | instance/device | `alter` |
| `@<model>[<param>]` (`@dmod[is]`) | model param | `altermod` |
| a netlist `.param` (`rtop`) | `.param` | `alterparam` + `reset` |

```
sweep <knob> (<start> <stop> <step> | lin|dec|oct <N> <start> <stop> | list <v>...)
      [-analysis <cmd>] [-output <name>=<expr> ...]
```

- **`-analysis`** — the analysis to run at each point (default `op`); `ac …`, `tran …`, etc.
- **`-output name=expr`** — an output to record (repeatable). With no `-output`, every
  node voltage is recorded (like `.dc`). The `name=` prefix gives the result vector a
  clean name so `plot name` works for function expressions like `mag(v(out))`.

The results go into a new plot named `sweep`, with the knob values as the scale, so
`plot <output>` shows the output versus the swept knob. A **`.sweep`** card runs the
same thing straight from the netlist.

Files:
- `sweep_demo.cir` — command form (sweep a resistor).
- `sweep_card_demo.cir` — `.sweep` card form (sweep a `.param`, AC gain output).
- `resmod.va` — a Verilog-A resistor whose `r` is a *model* parameter (for the
  `@<model>[r]` case).
- `verify_sweep.py` — 11 checks against analytic responses, including a cross-check
  that `sweep R1` reproduces the built-in `.dc R1` exactly.
