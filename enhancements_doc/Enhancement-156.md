# Enhancement-156 — Sparse RC reduction (scalable `reduce`)

[Enhancement-155](Enhancement-155.md) added the `reduce` command — TICER RC-network
reduction — but with a **dense** `N×N` implementation capped at ~2500 nodes. Real
extracted post-layout parasitic networks have 10⁵–10⁶ nodes, so the dense version
could only reduce toy blocks. This enhancement makes the engine **sparse and
scalable**, lifting the cap into the millions, and fixes a terminal-ordering pitfall.

## What changed

The RC network is sparse — each node touches only a few neighbours — so the engine now
stores it as **per-node adjacency lists** (not a dense matrix) and eliminates interior
nodes in a **minimum-degree** order, exactly like sparse LU factorization. That keeps
**fill-in** tiny: a degree-2 chain node merges two series elements with *zero* fill, a
degree-1 dangling node with none. A **fill guard** (`maxdeg`, default 12) refuses to
eliminate a node once its degree has grown past the threshold — so a dense mesh core
(whose boundary Schur complement is inherently dense) is left intact instead of
blowing up. The TICER Schur-complement math, the DC-exact conductance update, the
frequency criterion, and the automatic port detection are all unchanged from E-155.

```
reduce <fmax> [factor <f>] [maxdeg <d>] [file <fname>] [name <subckt>] [keep <node> ...]
```

`maxdeg` is the new knob: lower it to force sparser output (leave more of a dense core
in place), raise it to reduce more aggressively at the cost of possible fill.

## Why minimum-degree + a fill guard

Reducing a network to its ports is a Schur complement, and its cost/fill depend
entirely on the **elimination order**. Eliminating a degree-`d` node turns its `d`
neighbours into a clique (up to `d²/2` new edges), so eliminating **low-degree nodes
first** minimises fill — the classic minimum-degree heuristic (here via a lazy binary
heap keyed on current degree). On tree-like parasitics (the common case) fill is
essentially zero and reduction is near-linear. On a 2-D mesh the boundary Schur
complement is unavoidably dense; the `maxdeg` guard caps the damage by declining to
eliminate a node once its degree is large, leaving a small dense core rather than
densifying the whole network. Measured: on a 2-D mesh, unguarded elimination created
up to **3308** fill edges in a single step; with the guard, **9**.

## The terminal-order fix

The reduced `.subckt`'s terminals are emitted in internal-node-index order, which need
not match the order the user typed the `keep` nodes. Instantiating with the wrong
order silently swaps ports (and, on an asymmetric network, changes the response). The
command now **prints the correct instantiation** so it can't be gotten wrong:

```
reduce: RC network 65017 nodes -> 16886 nodes (3.9x), 18710 R + 32599 C written to bigred.sp
reduce: instantiate as  x1 out in big
```

## Implementation notes

- **`spicelib/analysis/rcreduce.c`** rewritten around a sparse `RCadj` adjacency (a
  growable per-node edge list of `{neighbour, g, c}`), a minimum-degree binary heap
  with lazy stale-entry skipping, and the `maxdeg` fill guard. Ground is node 0 (a
  permanent port); in the edge representation the diagonal is implicit, so eliminating
  a node just adds Schur edges among its neighbours and the self-conductance
  bookkeeping is automatic. Node cap raised to 5,000,000.
- **`frontend/com_reduce.c`** gains the `maxdeg` option; **`cktdefs.h`** the extra
  parameter. The command prints the instantiation line.

## Verification

`examples/reduce_examples/verify_reduce.py`, under **both** linear solvers, keeps the
E-155 checks — **identity is bit-exact** (0.00 dB), a moderate factor gives ~4× fewer
nodes at <0.25 dB in-band with **DC exact**, the tradeoff is monotone in `factor`, and
OSDI auto-port works — and adds:

- **scale** — a network of **8001 nodes** (well past the old ~2500 dense cap) reduces
  successfully. Interactively, a **65,017-node** network reduces in ~4 s.

## Scope and follow-ups

The reducer now scales to real extraction sizes. Remaining follow-ups: optional
**passivity enforcement** (naive TICER can emit small negative elements — harmless for
AC, worth guarding for transient) and inductive (RLCk) reduction.
