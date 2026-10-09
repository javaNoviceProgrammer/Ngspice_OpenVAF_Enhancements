# Enhancement-819: `.ic`, `.nodeset`, `.save @...` and an early analysis command take the `x1.n1` spelling of a device inside a subcircuit

**Scope:** F3 of the
[ngspice + OSDI hunt of 2026-10-08](../docs/bug_hunts/2026-10-08_ngspice-osdi-hierarchy-sweeps-events-and-outputs.md),
with the analysis-command case found while fixing it. ngspice:
- `spicelib/parser/inppas3.c`: `INPinternalNodeCanon`, declared in `inpdefs.h`, gives an
  internal node's name as the circuit spells it. `.ic` and `.nodeset` defer that name.
- `spicelib/parser/inp2dot.c`: an analysis command's node, typed before or after the first
  setup, is retried by that name.
- `frontend/outitf.c`: `.save @x1.n1[p]` takes Enhancement-410's reconstruction whenever it
  finds the device.

`examples/subcktedit_examples/` (section [3], seven checks). **ngspice only.**

**Suites:** [`subcktedit_examples`](../examples/subcktedit_examples/) 16 of 16 per solver (6 of
the 7 checks in [3] fail on the E-816 binaries; the seventh is the typo control). `hiername`,
`hiernode`, `osdislips` ([12], E-806) and `savemiss` are unchanged within the full sweep, 542
of 542.

## What was wrong

A device `n1` inside `x1` is flattened to `n.x1.n1`, its internal node to `n.x1.n1#mid`.
Enhancement-410 lets `print`, `alter` and `show` write the shorter `x1.n1`, and
`.save v(x1.n1#mid)` and `.meas` took it too. Four constructs refused it:

| construct | `x1.n1…` |
|---|---|
| `.ic v(x1.n1#mid)=1.5`, `.nodeset v(x1.n1#mid)=0.3` | "IC on non-existent node … ignored" |
| `.save @x1.n1[pw]` of an operating-point variable | "no such device, so this vector will stay empty" |
| `tf v(x1.n1#mid) v1` as the first command | "simulation(s) aborted" |

- **`.ic` and `.nodeset`.** Enhancement-608 keeps an entry on an internal node until setup,
  when the part before `#` names an instance. It looked up an instance called `x1.n1`, which
  does not exist. A built-in BJT's internal node (`x1.q1#base`) was refused the same way.
- **The early analysis command.** It asks the same question (Enhancement-690), and got the
  same answer.
- **`.save @…`.** The save path already retried the reconstructed `n.x1.n1`, but kept it
  only when the parameter read back a value. An operating-point variable has none until an
  analysis has run (E-476), so the retry was discarded and the device reported missing.

## The change

- **`INPinternalNodeCanon`.** It returns the node's name with its instance part as the circuit
  spells it. The exact name is tried first, so every name that resolved still resolves as it
  did. Then comes Enhancement-410's `<type>.<path>`, the type being the local name's first
  letter (`x1.n1#mid` → `n.x1.n1#mid`).
  - `.ic` and `.nodeset` keep that name until setup.
  - Enhancement-806's spelling of a Verilog-A child's node composes with it:
    `x1.n1#c1.mid` → `n.x1.n1#c1.mid` → `n.x1.n1#c1__mid`.
- **Analysis commands.** An analysis command's node that is not found is retried by that
  name, before the first setup and after.
- **`.save @…`.** The save path takes the reconstructed device whenever the lookup finds it,
  whatever the parameter answers. The vector is recorded under the name the user wrote.

## The checks

`subcktedit_examples` [3]:
- `.ic v(x1.n1#mid)=1.5`: the node starts the `uic` transient at 1.5 V (it was ignored: 2 µV);
  `.nodeset v(x1.n1#mid)` is accepted.
- `.save @x1.n1[pw] @x1.n1[iop]`: no warning, and the vectors hold 4 mW and 2 mA.
- `tf v(x1.n1#mid) v1` as the first command and again after an `op`: 0.5 both times.
- `.ic v(x1.n1#c1.mid)=1.7` on a Verilog-A child's internal node: 1.7 V.
- `.ic v(x1.q1#base)` on a built-in BJT is accepted as the top-level `.ic v(q1#base)` is.
- `.ic v(x1.nosuch#mid)` is still refused.

## Limits

- With `uic`, a built-in BJT starts from its own `icvbe`/`icvce`, so an `.ic` on its internal
  base node is accepted but does not move its first point. The top-level spelling behaves the
  same; that is the device's convention, not the name's.
