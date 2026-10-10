# Enhancement-838: a voltage node whose row no value reaches is held with the dc-path conductance at the reorder — a model's internal node written only in an untaken branch failed every factorization

**Scope:** F1 of the
[robustness and correctness campaign of 2026-10-10](../docs/bug_hunts/2026-10-10_ngspice-openvaf-r-robustness-and-correctness-campaign.md),
with [Enhancement-836](Enhancement-836.md) and [Enhancement-837](Enhancement-837.md).

ngspice:
- `spicelib/analysis/cktsetup.c`: `CKTdeadHold`; the mode taken from `.option dcpath`; the hold
  in `CKTdcpathStamp`.
- `include/ngspice/cktdefs.h`: the dead-node list, and `notKcl` on a `CKTnode`.
- `osdi/osdisetup.c`: marks an OSDI implicit equation `notKcl`.
- `maths/ni/niiter.c`: the call before each reorder.

`examples/osdirows_examples/` (section [3]). **ngspice only.**

**Suites:**
- [`osdirows_examples`](../examples/osdirows_examples/): 20 of 20 per solver. 4 of the 7 checks in
  [3] fail on the E-835 binaries; the other three are controls or refusals that stand.
- The corpus campaign: HiSIM-SOI `hisimsoi_n4` and `_n5` (current release) converge again, to
  the version11 answer, −3.49636 µA.
- [`floatnode_examples`](../examples/floatnode_examples/): 16 of 16, with its OSDI BSIM4 open-gate
  check revised (below).
- [`paramrange_examples`](../examples/paramrange_examples/): 13 of 13, with check [4] revised
  (below).
- [`tranopdelay_examples`](../examples/tranopdelay_examples/): 11 of 11, unchanged. Its forced
  transient-op fallbacks are implicit equations, which this hold leaves alone.
- The full sweep: 548 of 548.

## What was wrong

HiSIM-SOI's current release declares a body-resistance network, nodes `db` and `sb`, and
writes them only when `COBCNODE == 1`. In its 4-terminal mode, `COBCNODE = 0`, nothing touches
them. The Jacobian pattern is fixed when the model compiles, so it still holds the junction and
body-resistance entries of the other branch, and every one of them is 0 here. The two rows
are empty in every analysis, at every bias.

Every way ngspice had of holding such a node read something else:
- **Enhancement-116** grounds a node with no pattern entry at all.
- **Enhancement-575's dc-path walk** reads the pattern, which shows `db` joined to the drain.
- **Enhancement-571** holds an all-zero row only in the `ac` load.

So every factorization of the operating point failed, and every homotopy with it. Until
Enhancement-734, source stepping left a 1e-12 S diagonal gmin on every node, and that leak held
them. The corpus campaign had counted both files OK since July for that reason.

`dead.va` is the ten-line shape: an internal node `x` written only when `mode = 1`.

| `mode = 0` | before | now |
|---|---|---|
| `op` | `singular matrix: check node n1#x`, every homotopy fails, refused | 3 iterations, `i(v1)` = −1 mA |
| message | — | `node 'n1#x' is dead at this point (its row is all zero: no current reaches it); 1e-12 S installed to hold it` |

## The change

A matrix with a row or a column of zeros cannot be factored, whatever the pivoting. Before a
reorder with no diagonal gmin in the matrix, `NIiter` asks `CKTdeadHold`:
- It runs E-571's `SMPzeroLines` over the loaded values.
- It holds every voltage node whose row or column holds no nonzero value with the dc-path
  conductance: gmin, or the `.option dcpath` value.
- It names each node, up to five.

The node stays on a per-setup list, stamped by every later load in every mode, like the walk's
always-held nodes.

Only a Kirchhoff node is held. An OSDI row whose unknown has no discipline is a compiler's
implicit equation, such as an `idt()` state or `absdelay`'s `implicit_equation_1`. Its own
equation defines it, so an all-zero row there means that equation says nothing at this point.
`idt(1.0)` with no initial condition reads 0 = 1 at dc, and a hold would answer 1/gmin for it.
`OSDIsetup` marks such a row (`notKcl`, by E-833's test), and it goes to the ladder as before.
`tranopdelay` forces its transient-op fallbacks that way, and the first cut, which held these rows
too, broke three of its checks.

Scope and cost:
- **Only failing decks change.** A deck whose matrix factors today never has such a line, so
  nothing in it changes.
- **The cost is one pass over the values per reorder.** Reorders are rare: an analysis's first
  iteration, and the retry after a singular refactor.
- **`.option dcpath` is honoured.** `warn` and `error` name the node without holding it, and
  `off`, `nodcpath` and `gshunt` leave it alone (`gshunt`'s diagonal gmin is there at every
  factorization anyway).

A dead group is a different matter: nodes joined to each other but to nothing else have rows
that are not empty, so it is not covered. `vbic_4T_et_cf.va` at its defaults is that case:
- **It writes every series resistor as an open circuit at R = 0.** `cx`, `bx`, `bp` and `si` are
  now named dead and held.
- **Its intrinsic nodes still float together.** `ci`, `bi` and `ei` are joined to each other only
  by junctions, so the operating point is refused. The device is open at those parameters.

## What else moves

An OSDI BSIM4 with an open gate (`floatnode_examples`) has the same shape. Its gate row
holds the gate-current partials in the pattern and, with no gate current in the model, no
value at all. After Enhancement-734 it went down the ladder to optran, which left the gate
wherever the ramp had put it: `v(g)` = 0.4324 V and `v(d)` = 1.0064 V, in about 400
iterations. Now the reorder finds the empty row and holds it with gmin, as the dc-path walk
holds the built-in level-1 twin's gate in the same suite: `v(g)` = 0 and `v(d)` = 1.2 V in 5
iterations, with the gate named. A floating gate's DC voltage is not defined by the circuit,
and this is the answer ngspice gives for every other node nothing conducts to.

HiSIM-SOI in `paramrange_examples` [4] is the rejected-configuration case: six terminals
connected with `COBCNODE = 0`, so the model prints its own `Fatal` line and contributes nothing.
Under E-571 its noise completed with the device absent; E-734 refused the point; now `db` and
`sb` are named and held and the noise completes again, on a point no leaked gmin produced.

## The checks

`osdirows_examples` [3], with `dead.va`:
- `mode = 0`: named, held, 3 iterations, `i(v1)` = −1 mA.
- `ac` and `tran` on the held node: |i| = 1 mA, −1 mA at the end.
- `dcpath=warn` and `dcpath=error`: named with "nothing installed", and refused.
- `dcpath=off`: silent and refused.
- `gshunt=1e-12`: silent, −1 mA (control).
- `mode = 1`: `x` is live, silent, −1.5 mA (control).
