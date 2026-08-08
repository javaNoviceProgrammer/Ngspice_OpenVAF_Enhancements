# Enhancement-416 — the terminal current a node collapse hid

`if (rd == 0) V(d,di) <+ 0; else I(d,di) <+ V(d,di)/rd;` is how essentially every
compact model spells an optional series resistance, and **`rd = 0` is the shipped
default** (BSIM `rdsmod=0`, HICUM `re=0`). On that default path the terminal is
collapsed onto the internal node, so the model writes its current into `di`'s
residual and terminal `d`'s own residual slot stays zero.

`@n1[i_d]` read **exactly 0.0** for a terminal carrying the device's full current.

| `rd` | `i(vd)` — the truth | `@n1[i_d]` before | after |
| --- | --- | --- | --- |
| `0` — collapsed | −2.001 mA | **0.0** | −(−2.001 mA) ✓ |
| `1e-9` | −2.001 mA | 2.001 mA | unchanged |
| `0.001` / `1` / `10` | −2.001 mA | 2.001 mA | unchanged |

The reading is not merely imprecise, it is the wrong quantity, and it reaches the
user through three separate surfaces: `@dev[i_<term>]` (Enhancement-394), `show`,
and `.options savecurrents` (Enhancement-413).

## Why a Kirchhoff check did not catch it

With `rd = 0` **and** `rs = 0` — again, the default of a typical model — *every*
terminal read 0.0. The reported currents then sum to zero and a consistency test
passes on `0 = 0`, while the device carries 2.001 mA:

```
   rd  rs   i(vd)        i_d    i_g    i_s     KCL sum
   0   0    -2.001 mA    0.0    0.0    0.0     0.0     <- "consistent", and useless
   0   1    -1.999 mA    0.0    0.0   -1.999   -1.999
   1   1    -1.999 mA    1.999  0.0   -1.999    1e-15
```

## What was never wrong

The **solution**. `osdiload.c` stamps a collapse group into a single matrix row
(`CKTrhs[node_mapping[i]] -= …`), so the collapsed and uncollapsed forms of the
same model give the same node voltages and the same source currents. Only the
readback was wrong — which is exactly why it survived: nothing a user plots or
measures moved, so there was no symptom to chase.

That also fixes the meaning of the corrected value. The current into terminal `t`
is the quantity the loader puts into that row: the sum of the residuals of every
descriptor node in `t`'s collapse group. A group holds at most one terminal —
`collapse_nodes` refuses to merge two simulator-allocated terminals — so the
attribution is unambiguous, and an *un*collapsed terminal owns only itself, which
is why every uncollapsed number is bit-identical to before.

## The grouping has to be recorded during setup

The obvious implementation — group the descriptor nodes by the node index they
ended up on — is wrong, and wrong in a way that looks right on the headline test.
`collapse_nodes` builds a *local* mapping in which `node_mapping[i] ==
node_mapping[j]` means exactly "same group"; `write_node_mapping` then overwrites
that same array with **global** node numbers, and a global number cannot express
a group:

* two terminals wired to one net share a global number without being collapsed;
* ground (node 0) additionally collects grounded terminals, internal nodes
  collapsed to ground, Enhancement-116's structurally decoupled internal nodes,
  and Enhancement-401's dropped term-short flow nodes.

The second one bites in the common case: a source terminal tied to `0` alongside
an internal node the model grounded. `coll_chain.va`'s `tognd` knob is that
deck — terminal `c` on global node 0 beside a ground-collapsed internal node
carrying 0.1 mA. Grouped by global index, `|i_c|` reads 1.1 mA; the correct
answer, which the fix gives, is 1.0 mA.

So Enhancement-416 snapshots the ownership while it still exists, immediately
after `collapse_nodes` returns and before anything can renumber it, into one
`uint32_t` per descriptor node trailing `OsdiExtraInstData`. Entry `i` holds
`t + 1` when node `i` belongs to terminal `t`, and 0 for "no terminal" — the `+1`
because the instance block is `calloc`ed, so a device whose setup has not run
reads 0 everywhere and reports no current, exactly as before. A plain terminal
index could not tell "owned by terminal 0" from "never filled in".

Because the map records what the simulator *actually built*, the reported
currents cannot drift from the matrix even if the collapse machinery changes.

## The reactive half is load-bearing

The transient term is not a refinement. Driving 1 nF at 1 V/µs through the
collapsed path makes the terminal current ~1 mA of **pure displacement current**,
against a conduction term of a few µA; a fix that summed only resistive residuals
would be wrong by three orders of magnitude rather than slightly.

The walk in `OSDIask` therefore accumulates `CKTstate0[state+1]` for every
reactive node in the group — and, critically, keeps advancing `state` past
reactive nodes that are *not* in the group. That cursor is the same one
`osdiload.c` walks, where it steps on every node with a reactive residual
regardless of anything else; skipping a non-member would silently charge one
node's dQ/dt to another. The old code could `break` at the terminal because it
only ever wanted one node.

Measured over a 59-point transient: collapsed `i_d` was **0.0 at every timepoint**
before, and now tracks the uncollapsed reference to **4.5e-07** relative, with
`|i_d + i_s|` exactly 0.

## How much of the corpus this was silently affecting

A differential over the 40 real compact models in `integration_tests/` (37 of
which reach an operating point) is the measure of how common the broken path is:
**23 bit-identical, 14 differ in terminal-current lines only, and nothing else
moved in any of them.** All 14 were reading all-zero terminal currents before:

> HICUM/L2, PSP103 (+`_nqs`, `103t`), ASMHEMT, BSIM3, BSIMBULK, BSIMSOI,
> HiSIM2, HiSIM-HV (n4, n5), DIODE, DIODE_CMC, BSIMCMG

At an operating point HICUM/L2's terminal currents now sum to exactly `0.0` and
`i_b` equals its base current exactly; PSP103's sum to 3e-21. The models that
were already correct — BSIM4 with `rdsmod=1`, MEXTRAM 505, VBIC 1.3, BSIM6,
PSP102, JUNCAP200, EKV, MVSG — are bit-identical, which is the expected result
of an uncollapsed terminal owning only itself.

## An unconnected terminal reports no current

Terminals past `connected_terminals` are deliberately left unowned, so
Enhancement-402's short instance line reports `0.0` (and still warns). The
justification is that such a terminal is not a circuit node at all, so there is
no external current to report — *not* that no current exists: a model can write a
contribution to the omitted terminal's own node and have that node collapsed to
ground, in which case the pre-416 code reported the internal figure. It is
reachable, it was never a current into anything connected, and reporting `0.0` is
the defensible reading.

## A signed zero lost its sign

`OSDIask` now accumulates into a `double cur = 0.0` instead of assigning the
residual directly, and `0.0 + (-0.0)` is `+0.0`. A terminal whose residual is
exactly negative zero therefore prints `0` where it used to print `-0`, in both
`print` and `show`. Numerically nothing changed (`-0.0 == 0.0`); it is recorded
because it is a visible text change, and a golden file containing a literal `-0`
would notice. Nothing in the regression suite does.

## Noted, and deliberately not changed

* ~~**A transient terminal current disagrees with the source current by ~2e-3
  relative.** … a plain two-terminal `R‖C` OSDI device with no collapse anywhere
  shows the same 2.1e-3 gap … and it does not shrink with `reltol` (so it is not
  Newton convergence).~~
  **CORRECTED by Enhancement-417 — both halves of that claim were wrong, and the
  measurement behind them was a harness error.** `.options savecurrents` on a
  *two-terminal* device saves only the bare `@n1[i]`, so `@n1[i_p]` was a
  length-1 **scalar** being compared against a waveform; that is where the
  "2.1e-3" came from. With the vector that is actually saved, the plain `R‖C`
  agrees to **1.31e-15**. The gap that does exist on a *multi-terminal* model
  **is** Newton convergence: on HICUM/L2 with proper 1032-point waveforms it goes
  from 4.73e-04 at the default `reltol=1e-3` to **7.9e-15** at `reltol=1e-6` —
  eight orders of magnitude. Enhancement-417 also removes the underlying
  inconsistency, so `savecurrents` now expands per-terminal names at every
  terminal count.
* **A collapse hint to ground on a node that a later hint also merges** is a
  shape the ordering logic in `collapse_nodes` handles by comparing a raw index
  against a mapped one. A deck built specifically to hit it produced physically
  correct answers in all four knob combinations, so nothing is claimed and
  nothing is changed.

## Verification

* **`examples/collapsecur_examples` 31/31**, and **13/31 on the pre-416 binary** —
  the suite discriminates rather than merely passing.
* The instance block grew, so the layout was checked rather than assumed: the
  size in `osdiinit.c` and the offset in `osdi_collapse_owner` were recomputed
  against **every `.osdi` in the repo — 386 files, 589 descriptors** — and the
  array fits and is aligned in all of them (widest: 80 nodes). The suites were
  then re-run under macOS guard malloc (`MALLOC_PROTECT_AFTER=1
  MALLOC_STRICT_SIZE=1`), which faults on any access past the allocation: clean.
* The owner map is rebuilt on every setup, so it cannot go stale: verified across
  `altermod` toggling the collapse on and off mid-session, `sens` (which calls
  `DEVsetup` a second time — Enhancement-351), `reset`, and reads taken after
  `.ac`/`.noise`/`pz`/`tf`.
* All four `rd`/`rs` combinations assert `i_d == -i(vd)` and KCL, so the
  uncollapsed rows are pinned as negative controls in the same run.
* A three-node collapse chain, a ground-collapsed internal node beside a grounded
  terminal, the capacitive transient, `show`, `.options savecurrents`,
  Enhancement-397's `temp`/`dtemp`/`dt` ids, Enhancement-402's short instance
  line, and rejection of an unknown terminal name.
* Both solvers (Sparse and KLU). **Full regression 333/333.**

## Found by

A one-hour hunt over ngspice + OSDI. The tell was arithmetic, not a crash: a
device whose source current was 2.001 mA reporting 0.0 into the terminal that
carried it — and the four-way `rd`/`rs` sweep, which showed the number switching
between correct and exactly zero at `rd == 0` and nowhere else.
