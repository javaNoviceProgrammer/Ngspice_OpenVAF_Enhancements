# Enhancement-595: the `dcpath` hold is released outside DC — `dcpath=dc` is the default, `dcpath=all` keeps Spectre's rule

**Scope:** item 1 of the plan in
[`docs/bug_hunts/2026-09-10_dcpath-op-robustness-and-improvement-plan.md`](../docs/bug_hunts/2026-09-10_dcpath-op-robustness-and-improvement-plan.md).
`src/spicelib/analysis/cktsetup.c` (a second, reactive walk; the option words; the
stamp), `cktload.c` and `acan.c` (the stamp's mode), `src/osdi/osdisetup.c` and
`src/include/ngspice/osdiitf.h` (`OSDIdcpathEdges` learns the reactive entries),
`src/include/ngspice/cktdefs.h`, `src/frontend/spiceif.c` (the known-option list),
`src/maths/KLU/klusmp.c` (`SMPzeroLines`, a Sparse-only slip of Enhancement-571 found
on the way). `examples/dcpath_examples/` gains a section and a model. **ngspice only.**

**Suites:** [`dcpath_examples`](../examples/dcpath_examples/) 50 checks per solver, both
solvers (37 before; [4] re-pinned to the new default, [9] new); `floatnode`,
`acgminhold`, `ctrlnode`, `oprobust`, `singularname`, `solvercore`, `warmstart`,
`failacct`, `linesearch` unchanged; full sweep 489 of 489.

## What was wrong

Enhancement-575 installs gmin on a node the DC walk cannot reach from ground and, like
Spectre, keeps it there for the whole run. That is the one place the feature changes a
**result** rather than a message: a node reached only through a capacitor leaks with
C/gmin in a transient — 2 pF against 1 pS is a two-second time constant, and the suite
pinned 1.5 V falling to 1.1682 V at 0.5 s — and its AC response bends below gmin/C. A
switched-capacitor or charge-pump node simulated for a millisecond loses charge to a
conductance that exists only to make the operating point solvable.

The hold is needed only where the matrix is evaluated **at DC**. In a transient the
capacitor's companion conductance, 2C/h, carries such a node by many orders over gmin;
in AC it sees jωC. Neither needs the hold, and both are distorted by it.

Two things stood in the way of simply dropping the stamp outside DC:

- **Not every held node has a reactive path.** A current source into a lone node, a
  probed port, an isolated transformer secondary with a capacitor across it — the
  DC walk misses these and so does every frequency. `optran` finds the operating point
  by running a transient, so releasing them there would make the operating point
  itself singular on the shapes E-575 was written for.
- **A reactive element can be zero-valued.** A parasitic capacitor a parameter sets to 0,
  a `ddt()` whose coefficient is 0: the element is a path to the walk and nothing to
  the matrix, and a node it "carries" has an all-zero row in tran.

And one thing hid behind the AC half: under Sparse, `vm()` of a 1 pF node at 0.1 Hz
came out 0.391 whatever the mode, while KLU gave 0.500. Enhancement-571's all-zero-row
hold in the AC load reads the imaginary part only when the Sparse matrix is flagged
complex, and `spFactor` sets that flag *after* the load — so under Sparse a row holding
only jωC entries read as all-zero and was held with gmin in every AC analysis. KLU sets
its complex flag at conversion and was right.

## What changed

- **A second walk counts the reactive edges.** When a hold is to be installed at DC only,
  the walk runs again with a capacitor joining its pair, a MOSFET gate joining its
  terminals (its oxide capacitance carries it), and an OSDI entry flagged `REACT` joining
  its nodes under the same symmetry rule as `RESIST`. A current source and a mutual
  inductance still join nothing — coupling is not a path to ground. A node the DC walk
  missed and this walk reaches is **released outside DC**; one it also misses is **held in
  every mode**, as before. The list keeps the always-held nodes first, and
  `CKTdcpathAlways` counts them.
- **The stamp reads the mode.** In `CKTload` under any `MODEDC` bit (op, dc, the
  transient's and the ac's operating point) every listed node is held. In a transient a
  released node is stamped only if its diagonal is still exactly zero after the device
  loads — the zero-valued element, and nothing else, leaves it so. In `CKTacLoad` a
  released node is not stamped; an all-zero row there is Enhancement-571's to hold.
- **The message says which.** "…gmin (1e-12 S) installed to provide one; held at DC only
  -- tran and ac release it while a reactive path carries the node" for a released node;
  the E-575 text unchanged for one held in every mode.
- **The option words.** `dcpath=dc` (the default) and `dcpath=all` (Spectre's whole-run
  hold, E-575's form; `always` is accepted too). The option reader splits a value at a
  comma, so `dcpath=1n,all` cannot be one word; `.option dcpathall` is the whole-run hold
  as a word of its own and combines with a value: `dcpath=1n dcpathall`. The value words
  (`gmin`, a conductance) and the policy words (`warn`, `error`, `off`) are unchanged. An
  unknown word is refused by name: "…is not gmin, warn, error, off, dc, all or a
  conductance; using dcpath=gmin".
- **`SMPzeroLines` reads the imaginary part whether or not the Sparse matrix is flagged
  complex.** `Imag` is zero from allocation until a complex load writes it, and `spClear`
  zeroes it once the matrix has ever been complex, so an unflagged real matrix reads
  exactly as before. Sparse and KLU now agree on the AC of a capacitor-only node.

**Why `dc` is the default.** The plan proposed adding the mode first and flipping the
default later. With the always-held set and the zero-diagonal guard in place, the default
changes nothing on any shape the walk installs a hold for **except** the leak — every
operating point in the suites is identical, the AC of a held node is the exact divider
instead of a gmin-bent one, and the transient keeps its charge. The whole-run hold stays
one word away for anyone who wants Spectre's numbers.

## Verification

| check | default (`dcpath=dc`) | `dcpath=all` |
|---|---|---|
| 2 pF node from 1.5 V, `tran 0.5` (suite [4]) | flat at 1.5 V | 1.4268 V at 0.1 s, 1.1682 V at 0.5 s (τ = 2 s) |
| `dcpath=1n dcpathall`, the same, `tran 5m` | — | 0.9098 V at 1 ms, 0.5518 V at 2 ms (τ = 2 ms), no "held at DC only" |
| `vm(x)` at 0.1 Hz, both solvers | 0.500000 | 0.391239 |
| a current source into a lone node, tran | 1 pA into 1 pS: v(x) = 1 V, held, no suffix | the same |
| an isolated secondary with a capacitor across it | p and q named without the suffix; the transient runs, v(p) = −v(q) | the same |
| a zero-valued capacitor to a lone node, tran | no singular report, v(x) = 0 | — |
| an OSDI `ddt()` with a zero coefficient, tran | no singular report | — |
| every op of E-575's suite ([1], [2], [3], [7], [8], [6]) | unchanged | unchanged |
| `dcpath=bogus` | "is not gmin, warn, error, off, dc, all or a conductance" | — |

Full sweep 489 of 489 on both solvers.
