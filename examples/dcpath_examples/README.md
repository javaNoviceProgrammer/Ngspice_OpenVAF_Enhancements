# dcpath_examples — `.option dcpath`: gmin installed where a node has no DC path to ground

Enhancement-575, the implementation of the proposal in
`docs/proposals/2026-09-07_dc-path-gmin.md`: Spectre's topology check for ngspice. At
setup the nodes are joined by every DC-conducting device path — built-in types from a
per-type table of DC-connected terminal groups, OSDI models from the non-zero resistive
entries of their Jacobian pattern (an entry and its transpose), XSPICE code models from
their port kinds — and the graph is walked from ground. A voltage node the walk does not
reach gets a diagonal and the circuit's `gmin` on it on every load of every analysis, and
the message names it:

```
Warning: no DC path from node 'x' to ground; gmin (1e-12 S) installed to provide one
```

| section | what it pins |
|---|---|
| [1] the floating shapes | a B-source's read node, a current source into a lone node (`I/gmin`), the capacitor-coupled node and MOS gate of E-570, an XSPICE input port, an OSDI probed port, an OSDI `ddt()`-only port — each named and found in three iterations, no singular report |
| [2] what stays silent | inductors, a source-held node, a switch, a gate resistor, JFET/BJT/diode, E and G sources, a lossless line; an OSDI resistive port; R‖C in one contribution; a matrix-less circuit keeps E-492's note |
| [3] modes and value | `gmin` (default), `<G>`, `warn`, `error`, `off`, `nodcpath`, a bare `dcpath`; `.option gmin=1n` moves the hold and a diode's leakage, `dcpath=1n` the hold alone; `dcpath=0` is taken as warn and says so |
| [4] transient | the held node leaks with `C/gmin` (2 pF, 1 pS: τ = 2 s); `dcpath=warn` keeps it flat |
| [5] ac and rshunt | ac on a held node runs; `.option rshunt` stands the walk down — every node has a path then |
| [8] OSDI voltage contributions | `V(out) <+ …` with nothing else on `out` is a branch to an implicit ground and a path (a port driven by a single-ended contribution and nothing else; nearly every node of a large deck was named before the rule); a chain of three is silent; `V(p,n) <+ 1` between two untouched nodes is a branch between them and both are named |
| [7] a thermal port | an OSDI thermal port with the model's own `rth` is a path; a pure power source is not held — its pattern is the `rth` one, the run stays singular and names the node as before |
| [6] the cap | seven floating nodes: five named, then a count |
| [11] an open OSDI terminal (E-719) | a `$port_connected`-guarded port left off the instance line: its node `n1#c` is flagged by the OSDI edge builder, joined to nothing, held in every mode and named as an unconnected terminal — three iterations where it went down the ladder to the transient operating point (277); `dcpath=off` is the old road; `silentports` installs the hold without a word and `=ground` has no node to hold; `warn` and `error` say what the node is; an unguarded resistor to the open port is held all the same and follows `v(a)`; the cap; a lone node beside a quieted one is still named |
| [10] a held node that diverges (E-679) | two delayed conductances in series: held by gmin in every mode, each one's current is the node's own past voltage over 1 kΩ, and the run stops as diverging at −1e18 V naming the node (it ran to 5.6e62 V, exit 0); the same chain around a child's internal node is singular and the "Timestep too small" line names the node (was "cause unrecorded"); a delay in series with a resistor is silent |

## Run

```
python3 verify_dcpath.py
```

69 checks per solver, all PASS (57 before [E-719](../../enhancements_doc/Enhancement-719.md), 52 before [E-679](../../enhancements_doc/Enhancement-679.md); this line had said 37 since E-575 while E-595's sections were added).

## Enhancement-595 — the hold outside DC

By default (`dcpath=dc`) a node the DC walk misses but a reactive walk reaches — a
node carried by a capacitor — is held at DC only and released in tran and ac, where the
capacitor carries it; nothing leaks. A node no walk reaches (a current source into a
lone node, an isolated transformer secondary) is held in every mode, and a released node
whose diagonal is still zero in tran (a zero-valued capacitor, `zddt.va` with `c=0`)
keeps the hold. `dcpath=all` is Enhancement-575's whole-run hold; `.option dcpathall`
combines it with a value (`dcpath=1n dcpathall`). Section [9] pins these, and the AC of
a capacitor-only node on both solvers, since Sparse read only the real part of the AC
row before (an Enhancement-571 slip fixed here).
