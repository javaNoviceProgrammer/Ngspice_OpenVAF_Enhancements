# Proposal — `.option dcpath`: gmin installed where a node has no DC path to ground

*Scoped 2026-09-07, after the question "does `.option rshunt=1e12` engage automatically
like Spectre's gmin installation?" — it does not, and this is the enhancement that
would close the gap. Nothing here is implemented; the open item was recorded by
[E-569](../../enhancements_doc/Enhancement-569.md) as its follow-up.*

## The question

Spectre's topology check runs before Newton. For every node it cannot reach from
ground through a DC-conducting path it prints

```
No DC path from node <name> to ground, Gmin installed to provide path
```

and installs its `gmin` (1 pS by default) from that node to ground **permanently** —
for the operating point, the transient and the small-signal analyses alike. The
circuit then solves in a handful of iterations, and the user has been told which node
and why.

ngspice has every piece of that except the two that matter: the check that decides
*which* nodes, and a hold that stays.

## What exists, and what it lacks

**`.option rshunt`.** Off by default. When set, the operating-point ladder leaves
`1/rshunt` on the diagonal of **every** node for the rest of the run (`CKTdiagGmin =
CKTgshunt`, `cktop.c`). `rshunt=1e12` is Spectre's value at every node of the circuit,
including the ones with a perfectly good DC path, and it silences the diagnosis. E-569
measured it: every floating-node deck converges in three iterations under it, and no
node is named.

**The structural check ([E-566](../../enhancements_doc/Enhancement-566.md),
[E-569](../../enhancements_doc/Enhancement-569.md)).** At setup, a node whose matrix
row *or* column no device occupies gets a diagonal element and the warning
"connected to nothing that conducts; it is held only by gmin". The hold is not
installed: it is whatever the ladder leaves. Gmin stepping ramps its scalar diagonal
away before the final solve, the plain solve is singular, and the node lands in the
transient-based operating point, some 277 iterations later, held by the gmin that
`optran` runs with. Only a node that touches *nothing* is caught: a node reached only
through capacitors has matrix elements, zero-valued at DC, and is found late — by the
singular pivot ([E-570](../../enhancements_doc/Enhancement-570.md) names it) or by the
ladder.

**The small-signal hold ([E-571](../../enhancements_doc/Enhancement-571.md)).** `ac`,
`noise` and `sp` scan the complex matrix for all-zero rows and columns and add `gmin`
(or `gshunt`) to those diagonals, so a node the operating point held only by gmin is
held in AC too. It is a repair at the symptom: it does not know *why* the row was
empty, and it does nothing for the transient.

**Gmin stepping itself.** `LoadGmin` (`spsmp.c`, and its KLU twin) adds one scalar to
*every* diagonal; there is no per-node hold anywhere in the solver.

What is missing, then: a DC-path check rather than a touches-nothing check; a hold
that is per node, permanent and analysis-independent; one message that names the node
and the value; and a switch, including a mode that refuses to run.

## The design

### Detection — a DC-connectivity walk at setup

After the device setups have created their matrix elements and before the matrix is
sized (the point E-569 already uses), build the graph of nodes joined by a
DC-conducting device path and walk it from ground. Every node the walk does not reach
has no DC path.

Edges come from two sources.

* **Built-in device types**, from a table of DC-connected terminal groups, declared
  per type the way E-503 declares node-building parameters: resistor, inductor (a
  short at DC), voltage source, switches — both terminals one group; capacitor,
  current source — no edge; `E`/`G`/`F`/`H` — the output pair (and `F`'s input
  branch, which is a voltage source) but never the controlling pair; diode — both;
  BJT, JFET — every terminal; MOS levels — drain, source and bulk one group, the
  **gate isolated** (a MOSFET gate reached only through a capacitor is exactly E-570's
  singular case), unless the level models gate current. A type not in the table is
  taken as fully connected, which is the conservative reading: nothing is installed
  there, and the run behaves as it does today.
* **OSDI models**, from the Jacobian pattern the descriptor already carries: an entry
  flagged `JACOBIAN_ENTRY_RESIST` or `RESIST_CONST` joins its row and column; an entry
  that is `REACT`-only does not. A module whose only contribution to a port is
  `ddt(...)` therefore leaves that port unconnected, and a probed port
  (`V(out) <+ gain*V(in)`) has no resistive entry from `in` at all — which is the
  E-569 OSDI shape, recovered without a special case.
* **XSPICE**: an analog voltage-output port stamps a source branch and is a path; an
  input port is a probe and is not; a current-output port is not.

The structurally empty node of E-569 is the degenerate case — no edges at all — and
comes out of the same walk, so the two diagnostics merge into one.

### The hold

Every node the walk leaves unreached gets a diagonal element (created if it does not
exist, as E-569 does) and its number goes on a per-circuit list. `CKTload` adds
`CKTgmin` to each listed diagonal after the device loads, on every iteration of every
analysis; `CKTacLoad` does the same into the real part. That is the whole hold. It is
independent of the ladder's scalar `CKTdiagGmin`, which continues to ramp on top of it
during gmin stepping, and E-571's zero-row scan becomes a fallback for nodes the walk
did not see rather than the mechanism.

### The value

The default is the circuit's `gmin` — Spectre's choice, and already the value the
ladder leaves. It is changed the way it always has been:

```
.option gmin=1n
```

That knob is **global**, and deliberately so: fifty device files add `CKTgmin` to
their own junction conductances (a diode's `gd = gdb + CKTgmin`), and the stepping
ladder ramps down to it. Spectre's `gmin` is global in the same way, so a deck that
raises it gets the same trade on either simulator: a firmer hold on the floating
nodes, and a little more leakage in every junction.

For the case where only the hold should move, `dcpath` itself takes a conductance:

```
.option dcpath=1n        install 1 nS on the nodes without a DC path; device gmin untouched
.option dcpath=gmin      install the circuit's gmin                                  (default)
```

so `dcpath=1n` on a deck with an awkward bootstrap node stiffens that node alone and
leaves every junction at its 1 pS. A value of zero is refused — that is `dcpath=warn`.

`dcpath` never touches the junction conductances: it is a topology check, and the
device loads keep adding `CKTgmin` across their junctions exactly as they do today.
The two meet only at the value, and the four combinations are:

| you write | across every junction | on a node with no DC path |
|---|---|---|
| nothing | 1 pS | 1 pS installed |
| `.option gmin=1n` | 1 nS | 1 nS installed |
| `.option dcpath=1n` | 1 pS | 1 nS installed |
| `.option gmin=1n dcpath=1p` | 1 nS | 1 pS installed |

That is Spectre's pairing — one `gmin` for both roles unless the deck splits them —
and it is why raising `gmin` is the blunt way to hold a floating node: it also adds
leakage to every reverse-biased junction in the circuit.

`rshunt` is not the knob for this. It stays what it is: a global shunt on every node
of the circuit, with or without a DC path, which this proposal does not touch.

### The switch and the message

```
.option dcpath=gmin      install gmin on every node without a DC path, and say so   (default)
.option dcpath=<G>       install the conductance G (e.g. 1n) there instead of gmin
.option dcpath=warn      say so, install nothing -- today's numbers
.option dcpath=error     refuse to run, naming every such node
.option dcpath=off       neither check nor message -- E-566's behaviour
```

The message, once per node, five per run then a count:

```
Warning: no DC path from node 'g' to ground; gmin (1e-12 S) installed to provide one
```

With `dcpath=1n` the message reads `1e-09 S installed`, so the value in force is
always on the screen.

E-569's "connected to nothing that conducts; it is held only by gmin" retires into it.
`dcpath=error` is the mode a PDK or a netlist checker wants: a floating node is a
mistake there, not a circuit.

### What changes in results, and for whom

A node with a DC path is untouched, bit for bit. A node without one:

* **operating point** — the same value the ladder finds today (`0` for a
  capacitor-coupled node with nothing injected, `I/gmin` for a current-driven one),
  reached in three iterations instead of some 277;
* **transient** — the node now leaks through gmin, with the time constant `C/gmin`
  (1 pF against 1 TΩ is one second). That is Spectre's behaviour and is the one
  place a user could see a difference from today: a bootstrap or charge-pump node held
  by a small capacitor over a long transient. `dcpath=warn` restores today's numbers in
  one line, and the message says which node to look at;
* **AC / noise / sp** — what E-571 gives today, from the same list.

### Interactions

* **Gmin and source stepping** — unchanged; the per-node hold sits under the scalar
  ramp.
* **`.nodeset` / `.ic`** on a held node — fine; the diagonal exists either way.
* **`sweep` with the setup reused (E-471)** — the walk runs at setup and again on any
  rebuild; an OSDI node collapse that changes the pattern already forces a rebuild.
* **KLU and Sparse** — the element is created through `SMPmakeElt` and stamped
  through the ordinary load path, so both solvers see the same matrix; the suite
  asserts it.
* **`rshunt`** — both apply when both are set; the message still names the node.

### Alternatives considered

* **Detect numerically** from the nonzero pattern of the first DC load: simpler, no
  per-type table. Rejected as the mechanism because a nonlinear device at its initial
  guess can stamp a zero conductance (not every level adds `gmin` to its own
  conductances), so a connected node could be misjudged; kept as a cross-check the
  suite runs against the walk.
* **Keep the ladder's hold** (today): correct in the end, 277 iterations to get there,
  and nothing holds the node in the transient.
* **Make `rshunt` automatic**: a global change to every node, and the diagnosis is
  lost.

## Verification to pin (the suite) — `dcpath_examples`, both solvers

* E-569's shapes — the B-source read, the XSPICE `gain` input, the current source
  into a lone node, the CCCS output, the OSDI probed port, BSIM4's open gate — solve
  in three iterations each, with the message and the same values E-569 pinned;
* E-570's capacitor-coupled gate: the message names `g`, `v(g)` = 0, and the singular
  message no longer appears;
* no message for a node between two inductors, a node held by a voltage-source
  branch, a node behind a closed switch, a MOSFET gate with a gate resistor, an OSDI
  port with a resistive contribution, an XSPICE voltage-output port;
* transient: a 1 pF node reached only through a capacitor decays with `C/gmin`, about
  90 % left at 0.1 s; `dcpath=warn` holds it flat, as today;
* `ac`, `noise` and `sp` on a held node (E-571's decks) still run and agree;
* `dcpath=warn` is bit-identical to today on the E-569 suite; `dcpath=error` refuses
  and names every node; `dcpath=off` is silent;
* `.option gmin=1n` moves the hold AND a diode's leakage; `dcpath=1n` moves the hold
  alone (the current-driven node reads `I/1n`, the diode's current is unchanged);
  `dcpath=0` is refused;
* the numerical cross-check agrees with the walk on every deck above;
* the canaries of the Newton-phase work — `oprobust`, `warmstart`, `failacct`,
  `linesearch`, `bsrcconv` — and `floatnode`, `singularname`, `acgminhold`,
  `solvercore` unchanged, then the full sweep.

## Where the code goes

* `src/spicelib/analysis/cktsetup.c` — the walk, after E-569's occupancy scan; the
  list on `CKTcircuit` (`cktdefs.h`); the message.
* a new `src/spicelib/analysis/dcpath.c` — the per-type table of DC-connected terminal
  groups and the union-find; the OSDI edges from the resistive Jacobian pattern
  (`osdi/osdisetup.c` exposes the flags); the XSPICE port classification (`xspice/mif`).
* `cktload.c` and `acan.c` — the per-node stamp; E-571's scan kept as the fallback.
* `frontend/spiceif.c` — the option and its four values in the known list.
* `examples/dcpath_examples/`, the handbook's operating-point section, and E-566's
  "held only by gmin" wording updated where the message changed.

Two stages, each shippable: **stage 1** installs the hold, the option and the message
on the nodes E-569 already finds (structurally empty), which turns their 277-iteration
points into three-iteration ones and holds them in the transient — a small change on
top of existing code; **stage 2** adds the connectivity walk, which is what reaches
the capacitor-coupled node. About four hundred lines of C between them, plus the
suite.
