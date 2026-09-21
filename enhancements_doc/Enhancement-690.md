# Enhancement-690: an internal node can be the output of `sens`, `pz`, `tf` and `noise` typed as the first analysis of a session — and a collapsed one is bound to the node it collapsed into

**Scope:** F8 of the
[bug hunt of 2026-09-21](../docs/bug_hunts/2026-09-21_ngspice-osdi-analyses-sens-and-events.md).
ngspice: `src/spicelib/parser/inp2dot.c` (`inp_analysis_node`: a declared OSDI internal
node entered before the first setup, a collapsed one resolved after it, the hint for a
built-in device's), `src/spicelib/parser/inppas3.c` (`INPinternalNodeName` exported),
`src/include/ngspice/inpdefs.h`, `src/osdi/osdisetup.c` (`OSDIdeclaredInternalNode`; the
analysis-invented twin of a collapsed node shorted to its target),
`src/include/ngspice/osdiitf.h`, `src/spicelib/analysis/cktsens.c` and `pzan.c` (a phantom
output refused). `examples/internalnode_examples/` (seven checks, 26). **ngspice only.**

**Suites:** [`internalnode_examples`](../examples/internalnode_examples/) 26 of 26 per
solver, both solvers (all 7 new checks fail on the E-680 binaries, beside E-681's three and
E-688's three); `inputguard`, `teardown`, `dcpath`, `osdireload`, `lifecycle`, `netinit`,
`sweepparam`, `mcfastpath`, `sensrestore`, `analyses`, `finalstep`, `senscplx`, `sensstate`,
`osdisens` unchanged; full sweep 531 of 531.

## What was wrong

```
sens v(n1#mid)                       Error: no such node: n1#mid   sens simulation(s) aborted
pz in 0 n1#mid 0 vol pz              Error: no such node: n1#mid   pz simulation(s) aborted
tf v(n1#mid) vin                     Error: no such node: n1#mid   tf simulation(s) aborted
noise v(n1#mid) vin lin 2 1k 2k      Error: no such node: n1#mid   noise simulation(s) aborted
```

— as the **first** analysis of a session. A device builds its internal nodes at setup and
`IFnewUid` enters them in the parser's node table then; typed after an `op`, every one of
the four commands found `n1#mid` and ran. Typed first, nothing was set up, the table did
not have the name, and Enhancement-426's rule for a card synthesised from a command —
"deck parsing is over, an unknown name is a typo" — refused it. The rule was right about
typos and wrong about this: an OSDI compact model's interesting nodes are often internal
(the intrinsic drain, the junction temperature), and the first thing a user does with a
fresh circuit is ask for one.

Two neighbours found on the way. An internal node the model **collapses** (`V(a, ai) <+ 0`
with `rs = 0`) is never built, so it was "no such node" even after an `op`, and a `.tf
v(n1#ai)` *card* invented a node nothing connects to — it floated in every analysis of the
session (singular-matrix warnings, an operating point that needed the transient fallback)
and E-429 refused the output. And a mistyped suffix in a `.sens` or `.pz` card (`v(n1#mdi)`)
made the same floating node and was **not** refused: E-429's phantom check covered `tf`
and `noise` only, and the `sens` printed a table of −0.0 sensitivities.

## What changed

- **Before the first setup**, a command's `<instance>#<suffix>` whose instance is an OSDI
  device and whose suffix that module **declares** (`OSDIdeclaredInternalNode`, answered
  from the descriptor alone) is entered as a parse-time node — the node E-608's adoption
  makes the device's own at setup, exactly as a `.tf` card ahead of its device has always
  been handled. A suffix the module does not declare is refused as before and nothing is
  created (a phantom would float for the rest of the session). A built-in device declares
  its internal nodes nowhere the parser can see, so `sens v(q1#base)` as the first command
  keeps the refusal, and the message now says what makes the node visible: run an `op` or
  any analysis first, or put the card in the deck.
- **After a setup**, a name that is a collapsed internal node (`OSDIcollapsedNode`, E-688)
  resolves to the node it collapsed into, with a Note — as a `.ic` on it does since E-688.
- **At setup**, a parse-time node named after an internal node the model collapsed, which
  only an analysis card or command ever referred to, is shorted to the node it collapsed
  into by one of E-532's synthetic 0 V sources (a branch equation, as a collapse merge is),
  said once. The deck form `.tf v(n1#ai)` and the first-command form both measure at the
  merged node, `v(n1#ai)` reads it, and nothing floats.
- **`sens` and `pz` refuse a phantom** output (or, for `pz`, input) node — "does not exist
  (no device connects to it)" — as `tf` and `noise` have since E-429.

## Verification

| check | result |
|---|---|
| `sens`, `pz`, `tf`, `noise` on `n1#mid` as the first commands | the same numbers as after an `op` (0.75, 375 Ω, the pole at −1.5e6, onoise 3.2e-8) |
| a mistyped suffix as the first command (`v(n1#mdi)`) | "no such node: n1#mdi"; the `tf v(n1#mid)` right after it gives 0.75; no floating node |
| the BJT's `q1#base` as the first command | refused, with the hint; runs after an `op` |
| a collapsed `n1#ai` as the first command's `tf` output | 1000 (dv(a)/di1), the Note, no floating-node or singular warning; `v(n1#ai)` = `v(a)` |
| the same typed after an `op` | resolved to `a` with a Note, 1000 (was "no such node") |
| a mistyped suffix in a `.sens` and a `.pz` card | both refused as a node no device connects to (the `sens` printed −0.0) |
| the E-680 binaries on the suite | all 7 new checks fail |
| E-608's suites, the analysis suites; full sweep | unchanged; 531 of 531 |

## What this does not do

- A built-in device's internal node as the first command is still refused — the parser has
  no list of what a BJT builds; the hint says to run an analysis first or use the deck.
- A declared internal node that the instance's parameters collapse is bound by a short: a
  branch-current unknown (`n1#cshort0` in the operating-point listing) is added for it.
- Branch-current unknowns (`n1#flow(p,n)`) are not offered as outputs, and an instance
  inside a subcircuit is reached as before, by its hierarchical name.
