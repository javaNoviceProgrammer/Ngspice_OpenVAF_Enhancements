# Enhancement-837: a model's terminal-to-ground short that another instance already makes is dropped, and one beside a voltage source is named — self-heating-off devices on one thermal net no longer leave a singular matrix

**Scope:** F1 of the
[robustness and correctness campaign of 2026-10-10](../docs/bug_hunts/2026-10-10_ngspice-openvaf-r-robustness-and-correctness-campaign.md),
with [Enhancement-836](Enhancement-836.md) and [Enhancement-838](Enhancement-838.md).

ngspice:
- `osdi/osdisetup.c`: `OSDIsetupPass`, the pass-scoped table of pinned nodes; `osdi_dup_shorts`,
  the decision and the warning; `collapse_nodes` takes the duplicates to drop.
- `osdi/osdidefs.h`: `dup_short_mask`, the decision kept per instance.
- `include/ngspice/osdiitf.h`.
- `spicelib/analysis/cktsetup.c`: the pass around the device loop.

`VA_TEST/correctness_campaign.py` and `.md`: the corpus harness connects such a terminal to
ground. `examples/osdirows_examples/` (section [2]). **ngspice only.**

**Suites:**
- [`osdirows_examples`](../examples/osdirows_examples/): 20 of 20 per solver. 5 of the 6 checks in
  [2] fail on the E-835 binaries; the other is a control.
- The corpus campaign: 90 of 92, with 11 of its 14 F1 models brought back by the harness rule
  and this change.
- The full sweep: 548 of 548.

## What was wrong

A self-heating model with the heating switched off ties its thermal terminal to ground:
- BSIM-BULK, BSIM-CMG and BSIM-IMG write `Temp(t) <+ 0`;
- HICUM writes `V(br_sht) <+ 0`.

The compiler makes that a real 0 V branch, with its own current unknown (`flow(t)`), and
Enhancement-401 drops it only when the terminal *is* ground. Two ways to put a second ideal
source on the same node:
- **two instances share their thermal net**, `n1 d g s b tn nch` and `n2 d g s b tn nch`, the
  same equation stamped twice;
- **a deck holds the net with a source**, `vt t 0 0`, the corpus harness's own way of holding
  a spare terminal at 0.

Either is a loop of voltage sources, which the manual rules out, and the matrix is singular. The
diagonal gmin that source stepping left behind had made it solvable. Under Sparse it also landed
on the branch rows. Enhancement-734 stopped that leak, and these decks stopped converging:
- **The two-instance deck failed outright.** Every homotopy failed and the transient op found a
  timestep too small.
- **11 of the corpus's 92 models went with them:** bsimbulk ×3, bsimcmg ×2, bsimimg, HICUM L0 ×2
  and HICUM L2 ×3. The singular-matrix message named an unrelated node (Enhancement-836).

Two corpus BSIM-CMG instances at their defaults (self-heating off), `d` = `g` = 1 V, sharing the
net `tn`:

| | E-835 | now |
|---|---|---|
| `op` | refused after 2215 iterations, `singular matrix: check node n1#di` ×6 | 4 iterations |
| `i(vd)` | — | −109.395 µA |

## The change

`CKTsetup` opens a table of circuit nodes around its device loop (`OSDIsetupPass`). It marks
every node a voltage source ties to ground, then frees the table after the loop. Before
`collapse_nodes`, each OSDI instance walks its terminal-to-ground shorts:
- **The node is already pinned by a model short:** this short is the same equation, so it is
  dropped (`drop_node`, as Enhancement-401 drops a redundant one). The first instance's branch
  carries the node's current.
- **Otherwise:** the node is marked pinned. If a voltage source also holds it, a warning names
  both, once per node. The run is still refused, because the source's value is the deck's: an
  `alter` or a sweep can move it. Dropping the model's short there would hide a contradiction
  rather than resolve one.

```
Warning: n1: the model ties terminal 't' (node 't') to ground with a 0 V branch, flow(t), and
voltage source 'vt' holds the same node: two ideal sources in parallel leave the matrix
singular. Leave the terminal unconnected or connect it to ground (0).
```

`sens` calls one model's `DEVsetup` a second time on the set-up circuit. It sees only that
model, so it could not decide again, and Enhancement-351 requires it to allocate nothing. The
decision is therefore kept per instance (`dup_short_mask`) by the setup that allocated the rows,
and a second pass reuses it.

Not covered:
- a terminal-to-terminal short duplicated across instances;
- Enhancement-532's synthetic 0 V sources between terminals.

Neither shape turned up in the corpus.

## The harness

The corpus harness holds every spare terminal with a 0 V source, so it built the voltage-source
loop itself. It now reads the warning and connects that terminal to ground (`correctness_campaign.md`,
"Terminals the model grounds itself"). The terminal carries power, not current, and leaves the
current sum.

## The checks

`osdirows_examples` [2], with `rth.va`, whose terminal `t` is tied to ground by `V(t) <+ 0`:
- Two instances on one lone net converge in 3 iterations: `i(v1)` = −1 mA, no singular matrix.
- Three instances with 1 mA into the net: exactly one `nX#flow(t)` carries it. That is the
  first instance set up; ngspice keeps instances last-parsed first.
- `vt tt 0 0`: still refused, with the warning above, and the singular row is `n1#flow(t)`.
- `sens v(p)` on the shared net: `d v(p)/d rs` = −2.5e-4 = −Rp/(Rp + rs)² with Rp = 1k, and no
  node allocated.
- A `dc` sweep and an `ac` on the shared net: −1 mA at 1 V, |i| = 1 mA at 1 kHz.
- `t` on ground for both instances: silent, Enhancement-401's path (control).
