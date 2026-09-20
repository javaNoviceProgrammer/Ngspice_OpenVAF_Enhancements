# Enhancement-679: a node held only by the DC-path gmin that diverges in the transient stops the run and says why — and a singular transient names its node

**Scope:** F8 of the
[bug hunt of 2026-09-19](../docs/bug_hunts/2026-09-19_openvaf-r-operators-folding-and-delays.md).
ngspice: `src/spicelib/analysis/dctran.c` (the divergence guard at the
accepted point, `DCPATH_DIVERGE_V`), `src/maths/ni/niiter.c` (the singular
row recorded as the trouble node, Sparse and KLU branches).
`examples/dcpath_examples/` (`vdelay.va`, `vdelay2.va` and five checks, 57).
**ngspice only.**

**Suites:** [`dcpath_examples`](../examples/dcpath_examples/) 57 of 57 per
solver, both solvers (4 of the 5 new checks fail on the E-670 binaries; the
control passes); full sweep 531 of 531.

## What was wrong

```
v1 a 0 dc 0 pulse(0 1 1u 1n 1n 10u 20u)
n1 a mid dd1          .model dd1 vdelay td=1u     I(p,n) <+ absdelay(V(p,n), td)/1e3
n2 mid 0 dd2          .model dd2 vdelay td=0.5u
.tran 0.1u 5u
```

```
Warning: no DC path from node 'mid' to ground; gmin (1e-12 S) installed to provide one
v(mid): 0 ... -1e18 at 2.6 us, 1e27 at 3.4 us, 1e45 at 4.2 us, 5.6e62 at 5 us
No. of Data Rows : 73                                              (exit 0)
```

[E-575](Enhancement-575.md)'s walk found no DC path to `mid`, and
[E-595](Enhancement-595.md)'s reactive walk found no capacitance either, so
the node is held by the installed gmin in every mode — by design: a current
source into a lone node reads 1 pA / 1 pS = 1 V in the transient too, and the
suite pins it. A delayed conductance stamps nothing: its present current is
its *past* voltage over R. Two in series make the node's own past its
present current, and each delay multiplies the voltage by 1/(gmin·R) = 1e9.
Every point "converged" (the system is linear in the present unknowns), the
run finished, and nothing after the setup warning said a word.

The same chain around a child module's internal node — which carries the
instance's `#` and is left out of the walk — was singular instead: six
`singular matrix: check node n1#mid` warnings and `Timestep too small;
initial timepoint: cause unrecorded`. The hunt read that as a silent stop;
through a control block ngspice prints the abort line and exits 0, its
convention. What was missing was the cause.

## What changed

**A held node that diverges ends the transient.** At each accepted point
the always-held list is checked; a node past 1e15 V stops the run:

```
doAnalyses: TRAN:  time = 2.54429e-06: the solution is diverging -- node 'mid' has reached -1e+18 V.
    The node has no path to ground through any conductance or capacitance; only the 1e-12 S installed for its DC path
    holds it (the warning at setup), so every current into it -- a delayed element's, a source's -- is divided by that
    conductance. Give the node a path (a resistor, a capacitor), or `.option dcpath=error` to refuse such a node at setup.
tran simulation(s) aborted
```

No circuit puts 1e15 V on a node nothing constrains: at the default 1e-12 S
that is a kiloampere into a node with no path, and a delay chain passes it
within one delay of its onset. The guard reads only the nodes the simulator
itself knows nothing holds, so it cannot fire on a node any element
constrains.

**The singular row is the trouble node.** `NIiter` records the row
`SMPgetError` names, in the Sparse and the KLU branch, so `CKTtrouble`'s
line reads `trouble with node "n1#mid"` — the idiom the non-convergent-node
case already used — instead of `cause unrecorded`.

## Verification

| check | result |
|---|---|
| two delayed conductances in series at top level, `.tran 0.1u 5u` | held by gmin; the run stops as diverging, naming `mid`, the 1e-12 S and the remedy; `tran simulation(s) aborted` (was 73 rows to 5.6e62, exit 0) |
| the points stored | 47, within one delay of the onset (was 73) |
| a delayed conductance in series with a resistor (control) | no message, 73 points, the delayed toggle 1 / 0 arrives |
| the chain around a child's internal node | `trouble with node "n1#mid"` (was `cause unrecorded`) |
| the chain under `.option gshunt=1e-9` | the walk stands down; `trouble with node "mid"` |
| a current source into a lone node in the transient (E-595's check) | 1 V, unchanged |
| the E-670 binaries on the suite | 4 of the 5 new checks fail; the control passes |
| full sweep | 531 of 531 |

## What this does not do

- The held-node semantics are unchanged: a node with no path in any mode is
  I/gmin in the transient ([E-595](Enhancement-595.md)), and a bounded one
  runs as before. Only a runaway ends the run.
- A node not on the always-held list is not watched. The guard is for the
  nodes the simulator knows nothing constrains; a runaway elsewhere is the
  circuit's own and still shows in the waveform.
- `.option dcpath=warn` installs nothing: the chain is then singular and
  gets the named "Timestep too small" line; `dcpath=error` refuses the node
  at setup, as before.
