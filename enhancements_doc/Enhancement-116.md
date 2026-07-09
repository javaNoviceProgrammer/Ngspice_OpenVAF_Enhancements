# Enhancement-116 — KLU wrong-DC fix for decoupled OSDI nodes (2 of 3 XFAILs)

Three examples produced a **different, wrong result under KLU** than under Sparse
1.3 — genuine numerical discrepancies (not refusals), tracked as `KLU_XFAIL` in the
[dual-solver harness](../examples/_setup.py):

- `groundcontrib` — a node-to-ground voltage contribution read **`v(p)=0`** under
  KLU instead of `1.5`.
- `hierbranch` — hierarchical branch-**current** probes read **`0`** under KLU
  (the node voltages were correct).
- `opamp741` — the transistor-level µA741 **transient diverges** at the slew edge
  under KLU.

This enhancement fixes the **first two** (which turned out to share one root cause);
`opamp741` is a separate KLU factorization-robustness limit, discussed at the end.

## Root cause (groundcontrib + hierbranch)

Both models use a **voltage contribution** (`V(a,b) <+ expr`), which OpenVAF lowers
to a synthesized branch-current unknown plus a branch equation. The key detail is
the **ground reference**: a contribution such as `V(p, gnd) <+ 1.5`, where `gnd` is
an explicit `ground` net, has the branch equation `V(p) − V(gnd) = 1.5`. Because
`gnd` is ground, OpenVAF correctly **omits the `∂/∂V(gnd)` partial** — so the `gnd`
net appears in **no Jacobian entry at all**.

But `OSDIsetup` (ngspice side) still allocated `gnd` its **own solver row**
(`node_mapping` gave it a real matrix node). With no Jacobian coupling, that row
**and** column are entirely zero:

```
   [ 1/Rl   1  ] [ V(p) ]   [  0  ]        row/col for gnd is all-zero
   [  1     0  ] [  i   ] = [ 1.5 ]   +    -> structurally singular under KLU
```

Sparse 1.3 tolerates the decoupled all-zero row (it solves to `V(gnd)=0`, the rest
is unaffected). **KLU's factorization sees a structurally singular matrix and
returns a wrong solution** (`v(p)=0`). This is not specific to a "degenerate
single-node" topology as previously thought — it affects *any* OSDI voltage-branch
contribution against a `ground` reference (verified with series resistors and
multiple instances). `hierbranch` hits the same issue through its `top`-module
`ground gnd` and the synthesized ammeter branches its current probes read.

## The fix

In [`src/osdi/osdisetup.c`](../ngspice-46/src/osdi/osdisetup.c), when allocating an
instance's internal nodes, first build the set of node indices that appear in **any**
Jacobian entry (as equation row or unknown column). An internal node that appears in
**none** is structurally decoupled from the matrix; instead of allocating it a solver
row, **map it to ground (node 0)**:

```c
/* build "used" set from descr->jacobian_entries (mapped through node_mapping) */
for (i = connected_terminals; i < num_nodes; i++) {
    if (!node_used[i]) { node_ids[i] = 0; continue; }   /* decoupled -> ground */
    ... CKTmkVolt / CKTmkCur as before ...
}
```

This matches how OpenVAF already treats such a net (no coupling), removes the
all-zero row/column, and fixes **both** solvers (Sparse is unchanged in result; KLU
now matches it). Terminals are never ground-tied — only internal nodes.

Verified: `groundcontrib` → `v(p)=1.5` under KLU (was `0`); `hierbranch` → 6/6
checks under KLU including the branch-current probes (was 4/6). The full example
suite is **101/101 under both solvers** with no regressions — the node-allocation
change touches every OSDI model, and every one still agrees across solvers.

## opamp741 — a genuine KLU robustness limit (unchanged)

The stiff transistor-level µA741 follower, driven with a large square wave, **slews**
its output. At the slew edge (t ≈ 2.03 µs) output-stage transistors switch off, their
transconductances collapse, and the Jacobian becomes ill-conditioned. **KLU declares
the matrix singular** (nodes `x1.o1`/`o2`/`b34`/`cm`) and the timestep collapses,
where **Sparse's dynamic Markowitz threshold pivoting** re-orders and completes the
run (KLU aborts at ~133 rows, Sparse at 4058).

This is the classic KLU-vs-Sparse tradeoff: KLU's fill-reducing symbolic ordering is
computed **once** and `klu_factor` can only pivot *within* it, whereas Sparse
re-orders **every** factorization. It was confirmed not fixable with the available
knobs — full partial pivoting (`tol = 1.0`), disabling BTF and re-analyzing a fresh
ordering, and the gmin-loading path (identical to Sparse — both skip absent
diagonals) all left the abort unchanged. A real fix would require a **hybrid solver**
that falls back to Sparse when KLU's factorization fails, i.e. maintaining both matrix
representations in sync — a large architectural change disproportionate to one stiff
example. `opamp741` therefore remains the single documented `KLU_XFAIL`.

## Files changed

| File | Change |
|---|---|
| `ngspice-46/src/osdi/osdisetup.c` | ground-tie internal OSDI nodes that appear in no Jacobian entry (decoupled `ground`-reference nets), instead of giving them an all-zero solver row that makes the KLU matrix structurally singular |
| `examples/_setup.py` | `KLU_XFAIL` reduced from `{opamp741, groundcontrib, hierbranch}` to `{opamp741}` |

## Scope

KLU now matches Sparse across the suite for **DC, DC-sweep, AC, transient, noise,
S-parameters, single-ended pole-zero, sensitivity, and distortion**, plus the two
formerly-wrong OSDI voltage-branch cases. The remaining differences under KLU are:
**balanced-output pole-zero** (Sparse-only by construction — see
[Enhancement-113](Enhancement-113.md)) and the **`opamp741` stiff transient**
(robustness, above). Sparse 1.3 remains the default and runs everything.
