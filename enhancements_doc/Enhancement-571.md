# Enhancement-571: a node the operating point holds only by gmin is held in the small-signal matrix too — `ac`, `noise` and `sp` run on it

**Scope:** `CKTacLoad()` in `src/spicelib/analysis/acan.c`, the shared load of every
AC-family analysis (ac, noise, sp, disto, pss), with a new `SMPzeroLines()` in
`src/maths/KLU/klusmp.c` (`SMPzeroLine()` of Enhancement-570 now sits on it), both
solvers. Noticed while folding Enhancement-570. **ngspice only.**

**Suites:** new [`acgminhold_examples`](../examples/acgminhold_examples/) (10 checks per
solver, both solvers); `paramrange` (E-56) has one check reworded, see below;
`solvercore` (E-566's rshunt-in-AC), `pzhb`, `lrmnoise`, `singularname`, `floatnode`,
`oprobust` pass; full sweep 470 of 470 on both solvers.

## What was wrong

A node nothing conducts to — a current source's only load, a controlled-current-source
output (Enhancement-566), a node only a B-source, an XSPICE input or a Verilog-A probed
port reads (Enhancement-569) — and an open MOSFET gate whose model has no capacitance
all get their operating point the same way: gmin stepping fails at its last step (the
node's row is zero without a diagonal conductance), source stepping fails, and optran
solves the point with `CKTdiagGmin` still at `gmin` on every diagonal, which is what
"held only by gmin" means in practice — the current-source node reads I/gmin.

The AC load then built the small-signal matrix with nothing on any diagonal. The same
node's AC row (or, for a current-source output, its column) was therefore all zero, and
`ac`, `noise` and `sp` ended in

```
doAnalyses: matrix is singular
```

under both solvers, right after an operating point that had just succeeded, with the
six "singular matrix: check node x" lines of the operating point above it for company.
Before Enhancement-569 two of those decks could not reach their AC at all; the others
had always failed there.

## What changed

After the device loads (and the `rshunt` shunt, if any), `CKTacLoad()` scans the loaded
matrix once for rows and columns whose values are all zero — `SMPzeroLines()`, the
complex-aware pass Enhancement-570 introduced for the singular report, now returning
every such line — and adds to the diagonal of each such node the conductance the DC
hold used: `gshunt` when the user set it, else `gmin`. Nothing else is touched: a node
with any admittance at all, a capacitor's jωC included, keeps its row as loaded, so no
AC result that exists today changes; the suite pins an RC low-pass at its corner and a
capacitor-only node to their old values. The scan is one pass over the values per
load, in the noise of the factorization that follows it.

The five decks above now run their AC under both solvers with the values the DC hold
implies: the AC-driven current-source node reads 1/gmin, and 1/gshunt when that is set;
the CCCS output reads |i(v1)|/gmin; the read-only node, the XSPICE input and the open
gate read zero; `noise` gives the 1 kΩ resistor's 4.07 nV/√Hz and `sp` its S₁₁.

One existing check moves with it. Enhancement-56's `paramrange` suite pinned that a
HiSIM-SOI whose configuration the model rejects in eval (`Fatal(HiSIM_SOI): 6 nodes are
connected but COBCNODE = 0`) no longer crashes the noise analysis but aborts it cleanly.
That deck's rejected device contributes nothing, so its nodes are held only by gmin in
the operating point — which succeeds, through optran, with the device absent — and the
small-signal matrix now holds them the same way, so the noise completes instead of
meeting the singular matrix E-56's abort was written for. The check now pins that the
model's Fatal line is printed and the noise completes; E-56's clean-abort path stays in
the code for a matrix that is singular without an all-zero line, which no corpus deck
reaches today. Whether a device that reports a fatal in eval should stop the run
outright, as Enhancement-378 does for `$fatal` in the operating point, is a separate
question and is left open here.

## Verification

| check | result |
|---|---|
| a current source's only load, AC-driven; the same with `.option gshunt=1e-9` | vm(x) = 1e12 = 1/gmin, vm(b) = 1; vm(x) = 1e9 — both solvers (were "matrix is singular") |
| a node only a B-source reads; an XSPICE input port; a MOS1 with an open gate and no capacitances | the AC runs, the held node and everything it drives read 0, the driven nodes are unchanged — both solvers (were "matrix is singular") |
| a CCCS output, the all-zero-column case | vm(b) = 0.5, vm(nx) = 5e8 = |i(v1)|/gmin — both solvers (was "matrix is singular") |
| `noise` and `sp` on the read-only deck | 4.07 nV/√Hz output density; S₁₁ printed — both solvers (were "matrix is singular") |
| an RC low-pass at its corner; a node whose only element is a capacitor | 0.70711 at −π/4; 1/(2πfC) = 1.5915e8 — unchanged |
| `paramrange`'s rejected HiSIM-SOI noise deck | the Fatal line is printed and the noise completes with the device absent, as its operating point already did (was E-56's clean abort) |
| `acgminhold_examples`; `paramrange`; `solvercore`, `pzhb`, `lrmnoise`, `singularname`, `floatnode`, `oprobust`; full sweep | 10 / 10 both solvers; all pass; 470 of 470 |
