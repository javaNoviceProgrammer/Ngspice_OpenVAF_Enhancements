# Enhancement-833: an OSDI module's internal node with no DC path gets the dc-path gmin, as a built-in device's twin does

**Scope:** F17 of the
[ngspice + OSDI hunt of 2026-10-08](../docs/bug_hunts/2026-10-08_ngspice-osdi-hierarchy-sweeps-events-and-outputs.md).

ngspice:
- `osdi/osdisetup.c`: `OSDIdcpathEdges` marks the nodes an instance created for itself.
- `include/ngspice/osdiitf.h`: the new argument.
- `spicelib/analysis/cktsetup.c`: the dc-path walk checks such a node instead of passing it by.

`examples/seedac_examples/` (section [2], four checks); `dcpath_examples` [10] follows the
change. **ngspice only.**

**Suites:**
- [`seedac_examples`](../examples/seedac_examples/): 20 of 20 per solver. 1 of the 4 checks in
  [2] fails on the E-831 binaries; the other three are controls.
- [`dcpath_examples`](../examples/dcpath_examples/): 84 of 84, with one check of [10] revised.
- The full sweep: 547 of 547.

## What was wrong

```verilog
module fl(a, b); ... electrical mid;
  I(a,b)   <+ V(a,b)/1k;
  I(a,mid) <+ ddt(1p*V(a,mid));
  I(mid,b) <+ ddt(1p*V(mid,b));
```

The `op` went like this:
- `singular matrix: check node n1#mid`, six times;
- dynamic gmin, true gmin and source stepping all failed;
- the transient operating point answered `v(n1#mid)` = 0.5 V, after 277 iterations.

The built-in twin, an external node reached only through two capacitors, was named at once
(`no DC path from node '2' to ground; gmin installed`) and held at 0.

Enhancement-575's walk joins the nodes by every DC-conducting device path and holds each node
it cannot reach. It passes by any node whose name carries a `#`. That is how ngspice names a
built-in device's internal nodes (`q1#collector`), which the device's own series elements join
to its terminals in a way no terminal table can see. An OSDI module's internal nodes are named
the same way (`n1#mid`). Its Jacobian pattern, which the walk already reads, says what joins
them. An external node reached only through OSDI capacitors was handled, and
`.option rshunt=1e9` worked around the internal one.

## The change

`OSDIdcpathEdges` now marks, for the DC walk, every node an instance created for itself:
- a node it does not share with one of its terminals;
- not ground;
- a Kirchhoff node: its unknown's nature is its discipline's potential.

A branch's flow unknown and the compiler's implicit equations (`absdelay`'s
`implicit_equation_1`, which has no discipline) are not marked. Their own equations define
them, not KCL. A first cut marked them too, and dcpath's delayed conductance beside a resistor
was named "no DC path from node 'n1#implicit_equation_1'". A descriptor without nature data
marks nothing, the old behaviour.

The walk's `#` rule passes by a node only when it is unmarked. A marked node reached through
the module's resistive entries is reached. One reached only through `ddt()` gets what a
built-in node in its place gets:
- the dc-path gmin, with the message;
- held at DC only: Enhancement-595's reactive walk finds the capacitors, so a transient and an
  ac analysis release it.

| | before | now |
|---|---|---|
| `op` iterations | 277 | 3 |
| messages | `singular matrix` ×6, three failed homotopies | `no DC path from node 'n1#mid' to ground; gmin (1e-12 S) installed …; held at DC only` |
| `v(n1#mid)` | 0.5 V (transient operating point) | 0 (as the twin's `v(2)`) |

## The checks

`seedac_examples` [2]:
- The `op`: `n1#mid` named and held, no singular matrix, no stepping, `v(n1#mid)` = 0, at most
  5 iterations (was 277).
- The built-in twin (control): the same message for node `2`, `v(2)` = 0.
- A 0 → 1 V step: the node is released in the transient and divides as the twin does, 0.5 V.
- An internal node with a resistive path to a terminal is not named (control).

`dcpath_examples` [10] (Enhancement-679) had pinned the old behaviour for a chain of two
delayed conductances around a child module's internal node: singular, with the
"Timestep too small" line naming the node. The node is now held by the installed gmin, and
the transient stops as diverging, naming `n1#mid`, exactly as the same chain at the top level
does. The check says so, and `vdelay2.va`'s comment with it.

## Limits

- A node the pattern joins only through an asymmetric (controlled) entry stays unreached, as an
  external node would. That is Enhancement-569's rule for a probed input.
