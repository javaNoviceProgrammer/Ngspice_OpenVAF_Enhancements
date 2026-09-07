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

## Run

```
python3 verify_dcpath.py
```

37 checks per solver, all PASS.
