# Enhancement-628: `.probe alli` on a bus device — KiCad's default probe no longer floats a bus port

**Scope:** `src/frontend/inpc_probe.c` — the `alli` pass over the deck read leaves OSDI
lines and subcircuit calls to a second pass, `inp_probe_osdi()`, that runs from
`inp_spsource` once the `pre_` commands have loaded the objects and `.option autobus` is
resolved; there a shorthand OSDI line is written out against its model's ports
(`probe_expand_bus_line`), every terminal gets its own measuring source under the model's
terminal name, and a subcircuit call gets one source per bit for each formal that is a bus
base inside (`probe_formal_bits`, through nested calls; `probe_splice_x`); the splice
itself is factored into `probe_splice`, used by both passes. `src/frontend/subckt.c` /
`subckt.h` — E-464's model → ports lookup exported as `inp_osdi_port_widths` (on any
deck) with `inp_model_of_line`, and `inp_get_autobus` reads back what `inp_set_autobus`
published. `src/frontend/inp.c` / `inp.h` — `inp_autobus_of_deck` (the option and its
spelling off the deck's own cards) and the call to the second pass before subcircuit
expansion. New suite [`probebus_examples`](../examples/probebus_examples/) (6 checks per
solver). **ngspice only.** F11 of the
[2026-09-12 hunt](../docs/bug_hunts/2026-09-12_statistics-record-and-kicad-hunt.md).

**Suites:** `probebus_examples` 6 of 6 per solver, both solvers; `probeblock`, `namelookup`,
`savekw`, `silentloss`, `autobuskicad`, `autobus`, `autoopts`, `busmixed`, `busname` green;
full sweep 505 of 505.

## What was wrong

The 4-bit `va_res` cascade of `KiCad/example5`, with the one card KiCad's simulator adds
to every run:

```spice
.option autobus=kicad
.probe alli
V1 /in_0_ 0 DC 1u  ...  V4 /in_3_ 0 DC 4u
N1 /in /mid vares
N2 /mid /out vares
RL0 /out_0_ 0 1k   ...  RL3 /out_3_ 0 1k
```
```
Warning: instance n2: 'probe_int_/out_n2' was expanded to the 4 bus bits probe_int_/out_n2_0_ .., but the deck
         also uses 'probe_int_/out_n2' as a plain node -- a different node from every bit.
Warning: no DC path from node 'probe_int_/mid_n1' to ground; gmin (1e-12 S) installed to provide one
...  (10 warnings)
v(/out_3_) = 0.000000e+00        <- 4 V is right
```

The pass counted the line's node tokens — two, for two 4-bit bus ports in autobus
shorthand — took the device for a two-terminal one and spliced its measuring source into
the second token: `n2 /mid probe_int_/out_n2 vares` plus a source from
`probe_int_/out_n2` to `/out`. Autobus then expanded the base the pass had invented into
four bits nothing else touched; the source sat on the plain node; the bits floated. Under
KiCad every bus device read 0 V, and the workaround was a script that stripped the probe.
A subcircuit call whose formal is a bus base inside (`.subckt va_res_block in out` with
`N2 /mid out vares` in it, called as `X1 /in /out va_res_block`) failed the same way
through the X line.

It could not be fixed where it stood: the pass runs during the deck read, before the
`pre_` commands load the `.osdi` objects, so no model could be asked its ports.

## What changed

- **OSDI lines and subcircuit calls are probed in a second pass**, run from
  `inp_spsource` after the `pre_` commands and after `.option autobus` is resolved,
  before subcircuit expansion — the point where `pre_osdi` has registered the modules and
  the deck's `.model` cards name them (E-464's lookup, now on any deck). The first pass
  only notes that `alli` met such a line.
- **A shorthand OSDI line is written out against its model's ports** — each token becomes
  its bits, in the deck's spelling (`/out_0_ .. /out_3_` under `autobus=kicad`,
  `/out[0] ..` otherwise, E-572's one-bit rule included) — and every terminal gets its own
  source, so autobus finds nothing left to expand. Each terminal current is a vector named
  by the model's terminal: `n2:p_0_#branch .. n2:n_3_#branch` (`[k]` spelled `_k_` in a
  vector name, whatever the node spelling). A line already written out gets the terminal
  names too (they were all `nn`); a two-terminal scalar device keeps `<inst>#branch`.
- **A subcircuit call keeps its base token and gets one source per bit.** The width a
  formal is used with is found inside the subcircuit — an OSDI shorthand line that puts it
  on a bus port, or a nested call that passes it on (`probe_formal_bits`, eight levels) —
  and each bit is bridged, `/out_k_` to `probe_int_/out_x1_2_k_`, while the X line still
  passes the base, which the subcircuit expands into exactly those bits:
  `x1:out_0_#branch .. x1:out_3_#branch`. A call whose formals are all plain nodes is
  spliced as before (`x3#branch` for two, `x1:<formal>#branch` otherwise); the KiCad
  `unconnected` shunt and `probe_alli_nox` are honoured in the new pass as in the old.

```
v(/out_0_) = 1.000000e+00     v(/out_3_) = 4.000000e+00
n2:n_0_#branch = -1.00000e-03  ...  n2:n_3_#branch = -4.00000e-03
n2:p_0_#branch = 0             ...
x1:out_3_#branch = -4.00000e-03      (through va_res_block)
```
No warning of any kind.

## Verification

| check | result |
|---|---|
| the example5 cascade, `autobus=kicad`, `.probe alli` | 1, 2, 3, 4 V; no warning; `n2:n_k_#branch = -(k+1) mA`, `n2:p_k_ = 0`, `n1` alike |
| through `va_res_block` (`X1 /in /out`) | 4 V; `x1:out_k_#branch = -(k+1) mA`, `x1:in_k_ = 0`; no `x1#branch` |
| the default bracket spelling; `outer` → `inner` two deep | `out[3]` = 4 mV, `n1:n_3_#branch`; `x2:b_3_#branch = -4 µA` |
| a scalar OSDI device; a two-formal plain subcircuit; a written-out OSDI line | `n5#branch`, `x3#branch` as before; `n6:n_0_#branch` by terminal name |
| the same deck without `.probe alli` | the same outputs |
| `probeblock`, `namelookup`, `savekw`, `silentloss`; the five bus suites | unchanged |
| `probebus_examples` | 6 / 6, both solvers |
| full sweep | 505 of 505 |
