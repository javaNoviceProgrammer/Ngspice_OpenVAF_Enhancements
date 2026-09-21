# Enhancement-681: a netlist node spelled like a device's internal node is reported when the two become one — the adoption that E-608 added was silent about a device line

**Scope:** N1 of the
[bug hunt of 2026-09-21](../docs/bug_hunts/2026-09-21_ngspice-osdi-analyses-sens-and-events.md).
ngspice: `src/spicelib/analysis/cktmkvol.c` (`CKTmkSignal`: the adoption branch says so,
once, when the parse-time node it adopts was named by a device line).
`examples/internalnode_examples/` (five checks, 16). **ngspice only.**

**Suites:** [`internalnode_examples`](../examples/internalnode_examples/) 16 of 16 per
solver, both solvers (3 of the 5 new checks fail on the E-680 binaries: the warning, its
count across re-setups, and the branch-current wording; the merged values and the
silence of E-608's own cards pass on both); `sensrestore`, `sensstate`, `senscplx`,
`osdisens` unchanged; full sweep 531 of 531.

## What was wrong

A device builds its internal nodes at setup, after the deck is parsed, under the name
`<instance>#<node>`: `n1#mid` for a Verilog-A `electrical mid`, `q1#base` for a BJT
with `rb`, and the same convention names a source's branch-current unknown
`vin#branch`. [E-608](Enhancement-608.md) made `CKTmkSignal` **adopt** a parse-time node
of that name instead of building a second node beside it, because an analysis card may
legitimately name the node ahead of the device (`.tf v(n1#mid) v1`, whose node
`inp_analysis_node` creates with the `devRef` mark clear; a `.ic`/`.nodeset` is deferred
to setup and creates no node at all).

A **device line** that names such a node lands in the same branch, and nothing said so:

```
n1 in out mint r1=1k r2=1k c=1n        (internal node n1#mid)
vx n1#mid 0 dc 5
rx n1#mid 0 1k
op:   v(out) = 2.5   v(n1#mid) = 5   i(vx) = -11.5 mA
```

The 5 V source is wired to the model's internal node: `out` is the divider from the
forced 5 V, and the source delivers the internal current. A built-in BJT with `rb=100`
and a netlist node `q1#base` merges the same way (`vx#branch` = −1.2e35 A with the base
drawn to 3 V); a resistor on `vin#branch` is wired into the source's current equation.
The `#` namespace is not reserved, so a user who types the internal-node spelling to
probe the node — the spelling every `print`, `.save` and `.ic` uses — gets a circuit
that is silently different, with nothing in the output to say why.

## What changed

**The adoption says so, once.** In `CKTmkSignal`'s adoption branch, a parse-time node
that carries [E-429](Enhancement-429.md)'s `devRef` mark (set by `INPtermInsert` for
every node a device line names, cleared for a node an analysis card invented) and is
not yet `adopted` is reported before it is taken over:

```
Warning: node 'n1#mid' is named on a device line and is also the internal node 'mid' of instance n1;
         the two are one node -- whatever the netlist wires to 'n1#mid' is wired inside that model.
         Rename the netlist node unless that was intended.
```

and for a current unknown (`CKTmkCur`, the same routine):

```
Warning: node 'vin#branch' is named on a device line and is also the branch-current unknown of source vin;
         the two are one unknown -- whatever the netlist wires to 'vin#branch' is wired into that source's current.
```

The `adopted` mark E-608 sets keeps every later setup quiet (unsetup leaves a parse-time
node in place, so the next setup finds the same node again: `op; op; tran; sens` prints
the warning once). The merge itself is kept: E-608's adoption is what makes the analysis
cards work, and a deliberate connection to an internal node stays possible — the
message names the intent it assumes and the remedy.

## Verification

| check | result |
|---|---|
| `vx n1#mid 0 dc 0.5` beside an OSDI two-port with internal `mid` | the warning once, naming `n1#mid`, `mid` and `n1`; `v(n1#mid)` = 0.5, `v(out)` = 1/3 (the merge, pinned) |
| the same deck under `op; op; tran; sens v(out)` | one warning |
| `rz v1#branch 0 1k` | the branch-current wording, once |
| E-608's own cards: `.tf v(n1#mid) v1` ahead of the device, `.ic v(n1#mid)`, `.nodeset v(n1#mid)`, the diode's `.tf v(d1#internal) v1` | no warning; the suite's eleven E-608 checks unchanged |
| the hunt's BJT deck (`vx q1#base 0 dc 3`) | the warning names `base` and `q1` |
| the E-680 binaries on the suite | 3 of the 5 new checks fail (no warning was printed) |
| full sweep | 531 of 531 |

## What this does not do

- It does not refuse the connection. A netlist that means to reach an internal node by
  its name keeps working; only the silence is gone.
- A name used only by `.save`, `.print` or `.probe` creates no node and was never
  merged; nothing changes there.
- The `.ic`/`.nodeset` refusal on a *collapsed* internal node ("has no internal node")
  is the hunt's F6 and is not touched here.
