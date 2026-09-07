# Enhancement-575: `.option dcpath` — gmin installed where a node has no DC path to ground, Spectre's topology check for ngspice

**Scope:** the implementation of the proposal in
[`docs/proposals/2026-09-07_dc-path-gmin.md`](../docs/proposals/2026-09-07_dc-path-gmin.md).
`src/spicelib/analysis/cktsetup.c` (the connectivity walk, the per-type table, the
option, the hold, the unsetup), `cktload.c` and `acan.c` (the stamp),
`src/osdi/osdisetup.c` and `src/include/ngspice/osdiitf.h` (the OSDI edges),
`src/include/ngspice/cktdefs.h`, `src/frontend/spiceif.c` (the known-option list).
**ngspice only.**

**Suites:** new [`dcpath_examples`](../examples/dcpath_examples/) (37 checks per
solver, both solvers); `floatnode` re-pinned to the new default, `singularname` and
`solvercore` carry `.option dcpath=off` where they pin the singular-matrix naming;
`acgminhold`, `ctrlnode`, `oprobust`, `warmstart`, `failacct`, `linesearch`,
`bsrcconv` unchanged; full sweep 475 of 475 on both solvers.

## What it does

Spectre's topology check runs before Newton: for every node it cannot reach from
ground through a DC-conducting path it prints "No DC path from node to ground, Gmin
installed to provide path" and installs its gmin there for the whole run. ngspice had
the diagnosis for a node that touches *nothing* ([E-566](Enhancement-566.md),
[E-569](Enhancement-569.md)) but no hold of its own — the gmin-stepping ladder ramps
its scalar away before the final solve, so such a node travelled the ladder to the
transient-based operating point, some 277 iterations, and was held there only by the
gmin optran runs with, and not at all in a transient. A node reached only through
capacitors was not even seen: its elements exist and are zero at DC, so it surfaced as
a singular pivot, which [E-570](Enhancement-570.md) names.

Now, after the device setups have created their elements, the nodes are joined by
every DC-conducting device path and the graph is walked from ground. Every voltage
node the walk does not reach gets a diagonal element and goes on a per-circuit list;
`CKTdcpathStamp` adds the conductance in force to those diagonals after the device
loads, in `CKTload` and `CKTacLoad` alike, so the hold is the same in the operating
point, the transient and the small-signal analyses. The message names the node and the
value:

```
Warning: no DC path from node 'g' to ground; gmin (1e-12 S) installed to provide one
```

Five are named, then a count.

| probe | before | now |
|---|---|---|
| a B-source's read node, a current source into a lone node, an XSPICE input port | "held only by gmin", ~277 iterations through optran | named, 3 iterations, the same values |
| a node reached only through capacitors; a MOS1 gate on a capacitor (E-570) | six "singular matrix: check node" reports, 289 iterations | named, 3 iterations, `v(g)` = 0, no singular report |
| an OSDI port the module only probes; an OSDI `ddt()`-only port | the first "held only by gmin", the second singular | both named, 3 iterations |
| the same capacitor-coupled node in a transient | held at whatever the operating point left | leaks with `C/gmin` — 2 pF against 1 pS is a two-second time constant |

## The edges

**Built-in types** come from a table of DC-connected terminal groups, in the style of
E-503's node-parameter table: resistor, inductor, voltage source, switches, VCVS and
CCVS join their first two terminals — the output pair of a controlled *voltage* source,
never its controlling pair; capacitor, current source, VCCS and CCCS join nothing — a
controlled *current* source is a current source at its output; a B-source decides per
instance from its type; diode, BJT, JFET, MESFET, HFET and the CIDER devices join every
terminal; the MOSFET levels join every terminal *except* one whose name contains "gate",
the gate being capacitive at DC unless a gate-current model connects it. A type in no
table joins every terminal, the conservative reading: nothing is installed there and
the run behaves as it did. The terminals are read generically through `GENnode()`, and
a device's *internal* node — `t1#int1`, a collector prime — is taken as reached, since
the device joins it to its terminals through series elements the table cannot see; one
that touches nothing at all is still caught by E-569's structural pass.

**OSDI models** come from the Jacobian pattern the descriptor already carries, through
`OSDIdcpathEdges`. Two things had to be got right, and the first attempt got both
wrong. An entry (i, j) says equation i *depends* on unknown j; a DC path between the two
nodes needs the current at both ends to depend on both — the symmetric pattern a
conductance stamps. A contribution `V(out) <+ 2*V(in)` has (out, in) and no (in, out),
so `in` is probed, not connected, exactly as E-569 treats it; taking the single entry as
a path had joined `in` to ground. And OpenVAF sets `JACOBIAN_ENTRY_RESIST` only when the
resistive part is non-zero, while `RESIST_CONST` says the part is *constant* and covers
a constant zero — a `ddt()`-only contribution carries `REACT|RESIST_CONST`, flags 9,
and had been read as resistive. The rule is now: an entry and its transpose both flagged
`RESIST`, decided once per device type. `set ngdebug` prints each entry's verdict.

The third thing came from a real deck. A voltage contribution is a *branch*: `V(x) <+
f(...)` adds a flow unknown with the symmetric pair (x, br), (br, x), and its other end
— ground — is implicit, in no entry at all. Joining x to the branch alone left the pair
adrift, and on a large deck whose every port is driven that way, nearly every node
came out "without a DC path". So a flow node coupled
symmetrically to exactly one voltage node is a branch to ground and that node is joined
to ground; coupled to two, `V(p,n) <+ ...`, it joins them to each other, which the
symmetric rule already does, and the pair floats or not with the rest of the circuit.
That deck then runs with no warning and results byte-identical to `dcpath=off`.

The same deck found the walk's one performance trap: the node's name was fetched with
`CKTnodName`, which walks the node list, for every unreached node before the
internal-node test — quadratic on a deck with thousands of unreached device-internal
nodes, seven seconds of setup. The node carries its own name; the walk now costs a
third of a second there, and the deck's run time is unchanged.

**Where the pattern cannot tell.** An OSDI thermal port is the case that shows the
walk's limit. A model with its own `rth` — `Pwr(dt) <+ Temp(dt)/rth - P` — gives the
node a real conductance to ground; a pure power source, `Pwr(dt) <+ -V*I`, gives it
none. Both produce the same Jacobian pattern, because the power depends on the
temperature through the current and the current on the temperature through the
mobility, so the entries (dt, p) and (p, dt) are there either way. The walk therefore
takes the pure power source as connected and installs nothing: the run stays singular
and names the node as it did before. That is the honest outcome — installing gmin would
"solve" it at P/gmin, some 1e9 K — and the fix belongs in the model or the netlist. Both
shapes are pinned. A thermal terminal omitted from the instance line lands on the
device-internal node E-402 makes for it, and follows the internal-node rule above.

**XSPICE code models** come from their port kinds: an analog output port of a voltage
kind (`v`, `vd`, `h`, `hd`) stamps a source branch between its nodes and is a path; an
input port is a probe, a current output a current source, and neither is.

## The option

```
.option dcpath=gmin      install the circuit's gmin, and say so   (default)
.option dcpath=<G>       install the conductance G instead (dcpath=1n)
.option dcpath=warn      say so, install nothing -- Enhancement-569's numbers
.option dcpath=error     refuse to run, naming every such node
.option dcpath=off       neither check nor message -- Enhancement-566's run
.option nodcpath         the same off
```

Read the way E-471 reads `reusesetup`: a number before a string before a bool.
`dcpath=0` installs nothing and says it is taken as `warn`. The value is `gmin` unless
`dcpath=<G>` gives one: `.option gmin=1n` therefore moves the hold *and* every
junction's leakage, `dcpath=1n` the hold alone — the pairing the proposal's table lays
out, and the suite pins on a reverse-biased diode beside a floating node.

Two cases stand the walk down. With `.option rshunt` (or `gshunt`) every node has a
conductance to ground, so no node lacks a DC path: nothing is installed and nothing is
said, and the global workaround keeps its own numbers, including E-571's AC hold that
follows `gshunt`. And a circuit with no matrix at all — a current source into a lone
node and nothing else — keeps E-492's single note, as E-569's structural pass does; the
walk runs only in an otherwise connected circuit.

## What moved in the suites, and why

`floatnode` pinned E-569's message and the trip through optran; it now pins the new
message and a point found within five iterations, and E-569's message is what
`dcpath=off` still prints. `singularname` pins E-570's *naming* of a vacuous node and
`solvercore` E-566's, which needs the node left unheld: their decks carry
`.option dcpath=off`, and the naming is what a user sees under `off` or `warn`.
`acgminhold`'s "the AC hold follows `gshunt`" check is what found that `rshunt` has to
stand the walk down, and `ctrlnode`'s E-492 check is what found the matrix-less case.

## Verification

[`dcpath_examples`](../examples/dcpath_examples/) — 37 checks per solver:

| section | checks |
|---|---|
| [1] the floating shapes | a B-source's read node, a current source into a lone node (`I/gmin`), the capacitor-coupled node and the MOS gate of E-570, an XSPICE input port, an OSDI probed port, an OSDI `ddt()`-only port — each named, three iterations, no singular report |
| [2] what stays silent | inductors, a source-held node, a switch, a gate resistor, JFET/BJT/diode, E and G sources, a lossless line; an OSDI resistive port; R‖C in one contribution (flags `RESIST|REACT`); a matrix-less circuit |
| [3] modes and value | `gmin`, `<G>`, `warn`, `error`, `off`, `nodcpath`, a bare `dcpath`, `dcpath=0`; `gmin=1n` against `dcpath=1n` on a diode beside a floating node |
| [4] transient | the held node leaks with `C/gmin`: 1.4268 V at 0.1 s and 1.1682 V at 0.5 s from 1.5 V, τ = 2 s; `dcpath=warn` keeps it flat |
| [5] ac and rshunt | ac on a held node gives the capacitor divider's 0.5; `rshunt` stands the walk down |
| [8] OSDI voltage contributions | `V(out) <+ …` with nothing else on `out` is a branch to an implicit ground and a path (a port driven by a single-ended contribution and nothing else); a probe-and-drive chain of three is silent; `V(p,n) <+ 1` between two untouched nodes is a branch between them and both are named |
| [7] a thermal port | the model's own `rth` is a path (silent, four iterations, T = P·rth); a pure power source is not held and the run names the node as before |
| [6] the cap | seven floating nodes: five named, then "and 2 more" |

Full sweep 475 of 475 on both solvers.
