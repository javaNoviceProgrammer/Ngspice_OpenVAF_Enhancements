# Enhancement-585: the OSDI nature-abstol report under `ngdebug` is one line per model and tolerance, not one per node

**Scope:** `src/osdi/osdisetup.c` (`flush_node_abstol`), `examples/abstolperf_examples/`
and `examples/lrmdisc_examples/` (the two checks that parsed the per-node lines).
**ngspice only.**

**Suites:** [`abstolperf_examples`](../examples/abstolperf_examples/) 4 of 4,
[`lrmdisc_examples`](../examples/lrmdisc_examples/) 34 of 34,
[`lrmio_examples`](../examples/lrmio_examples/) 17 of 17, per solver, both solvers;
full sweep 480 of 480.

## What was asked

A 1000-device OSDI Monte Carlo deck with `set ngdebug` in its control section
printed 2000 lines before the first sample:

```
OSDI: node 2 convergence abstol = 1e-06 (declared by its nature)
OSDI: node 3 convergence abstol = 1e-06 (declared by its nature)
...
OSDI: node 2002 convergence abstol = 1e-06 (declared by its nature)
```

They are E-539's report that a node's convergence tolerance was taken from the
Verilog-A nature of its unknown — one line per node the model touches, so a
1000-device ladder with an internal node per device gives 2000 of them. They read
as a flood of warnings, and they said nothing a count would not: every one carried
the same tolerance from the same `electrical` discipline.

## What changed

`flush_node_abstol`, the one walk of the node list that applies the tolerances a
model type collected, now tallies the nodes it changed by tolerance and prints,
under `ngdebug`, **one line per model type and distinct tolerance**:

```
OSDI: mcdev2: convergence abstol = 1e-06 on 2000 nodes (declared by its natures)
```

A model with several natures — a voltage and a current, a thermal node — gets one
line per tolerance (a two-terminal module on a custom `myvoltage` nature with
`abstol = 1u` reports `twonat: convergence abstol = 1e-06 on 2 nodes`, its terminal
and its internal node). The tally covers eight distinct tolerances per model type;
beyond that a closing line gives the count of nodes at further tolerances. Nodes an
earlier model type already set at a tighter or equal value are not counted again,
so the line says what this model type actually changed. The setup itself is
untouched: the same tolerances reach the same nodes, and without `ngdebug` nothing
is printed, as before.

Two suites parsed the per-node lines and now read the count: `abstolperf` sums the
nodes over the summary lines (≥ 200 on its ladder, in at most a few lines), and
`lrmdisc` reads "1e-09 on 2 nodes" where it counted two per-node lines. `lrmio`'s
regex already matched the summary form.

The `fast path armed` banner that the deck's README said needed `ngdebug` has been
unconditional since E-552; the only Monte Carlo line `ngdebug` still adds is the
setup-reuse tally.

## Verification

| check | result |
|---|---|
| the 1000-device deck under `ngdebug` | one line, `mcdev2: convergence abstol = 1e-06 on 2000 nodes`, instead of 2000; the run is otherwise identical |
| `abstolperf` | the summary reports ≥ 200 stamped nodes in at most four lines; setup still scales linearly |
| `lrmdisc` §9c | an overridden `potential.abstol` of 1e-9 reaches two nodes through the direct and the derived-nature route |
| `lrmio` | a declared nature abstol reaches the convergence test; an explicit `.option vntol` does not break the path |
