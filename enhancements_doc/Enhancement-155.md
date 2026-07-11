# Enhancement-155 — RC network reduction (`reduce`, TICER)

The [gap analysis](../docs/internals/ngspice_internals/ngspice_gaps.md) listed
"RC reduction / model-order reduction" as ❌ in the post-layout section. Extracted
post-layout netlists carry enormous linear **parasitic RC networks** — thousands to
millions of interior resistor/capacitor nodes — that are impractical to simulate raw.
This enhancement adds a command that reduces such a network to a small, electrically
equivalent one.

## What it does

```
reduce <fmax> [factor <f>] [file <fname>] [name <subckt>] [keep <node> ...]
```

`reduce` collapses the circuit's linear R/C network into a much smaller network that
preserves the **port behaviour** over `DC..fmax`, and writes it as an ordinary
`.subckt` of R's and C's — ready to `.include` in place of the original parasitics.

## Method — TICER

The nodal admittance is `Y(s) = G + s·C`. **TICER** (Time-Constant Equilibration
Reduction) eliminates an interior node `n` by the Schur complement of `Y`, kept to
first order in `s` so the result is **realizable** as R's and C's (no model-order
black box, no passive-synthesis step). For every neighbour pair `(a,b)`:

```
G[a,b] -= G[a,n]·G[n,b] / G[n,n]
C[a,b] -= (G[a,n]·C[n,b] + C[a,n]·G[n,b])/G[n,n] − G[a,n]·G[n,b]·C[n,n]/G[n,n]²
```

The conductance update is the **exact** Schur complement, so **DC is preserved
exactly**; the capacitance update matches `Y` to first order in `s`. A node is
eliminated only when its self time-constant frequency `f_n = G_n/(2π·C_n)` lies well
above the band of interest (`f_n > factor·fmax`) — such a node is quasi-static in-band
and can be collapsed without losing in-band accuracy. `factor` is the accuracy/reduction
knob: smaller removes more nodes (more reduction, looser fit), larger keeps the in-band
poles (less reduction, tighter fit); the tradeoff is monotone.

## Ports (auto-detected)

Nodes that must be kept are found automatically: every node touched by a device that is
**not** a resistor or capacitor — a source, a transistor, an **OSDI Verilog-A** device —
plus ground and any user `keep` nodes. Those are exactly the terminals where the
parasitic network meets the real circuit; only interior RC-only nodes are removed. This
uses the generic `GENnode` / terminal-count device interface, so it works for built-in
and OSDI devices alike.

## Implementation notes

- **`spicelib/analysis/rcreduce.c`** (new): the `CKTreduceRC()` engine. It enumerates
  the built-in resistor and capacitor instances (`CKTtypelook("Resistor")`/`"Capacitor"`),
  builds the dense `G`/`C` over the RC-node set, auto-detects ports by walking every
  non-R/C device's terminals, runs the TICER elimination, and emits the reduced
  `.subckt` (using `CKTnodName` for node names).
- **`frontend/com_reduce.c`** (new): the `reduce` command — parses the arguments,
  resolves `keep` node names, and calls the engine. In the `optimize`/`sweep`/`montecarlo`
  command family; solver-independent (it reads devices and does its own dense solve).
- First cut is **dense** (node cap ~2500). Sparse TICER (fill-controlling elimination
  order) lifts that into the millions — a natural follow-up.

## Verification

`examples/reduce_examples/verify_reduce.py`, under **both** linear solvers:

- **identity** — a huge `factor` eliminates nothing and the emitted subckt reproduces
  the full network's AC response **bit-for-bit** (extraction + emission are exact);
- **reduction + accuracy** — a moderate factor cuts the node count (e.g. 25 → 6 nodes,
  4×) while the reduced network stays within tolerance of the full one across the band,
  with **DC preserved exactly**;
- the accuracy/reduction **tradeoff is monotone** in `factor`;
- **OSDI auto-port** — an OSDI device on a node makes that node a kept port with no
  `keep`.

`reduce_demo.cir` reduces a 24-section ladder and plots the reduced AC on top of the
full one.

## Scope and follow-ups

A correct, realizable, DC-exact TICER RC reduction with automatic port detection is
now available, moving the post-layout RC-reduction row to ✅. Follow-ups: a **sparse**
implementation (to lift the size cap to real extraction scale), optional **passivity
enforcement** (naive TICER can emit small negative elements — harmless for AC, worth
guarding for transient), and inductive (RLCk) reduction.
