# Enhancement-86 — hierarchical branch probes

This document describes Enhancement-86: the LRM page-119 hierarchical
branch reference forms — `V(top.a1.b)`, `V(top.d1.branch(a, b))`, and
`I(top.d1.branch(<p>))` — implemented end-to-end, plus the two
pre-existing DAE defects and two elaboration bugs the work uncovered
and fixed. The second scope item the user requested, named part-select
connections (`.out(out[3:2])`), had already shipped in E-85; this
enhancement adds the missing runtime pin for the output-direction named
form (a 2-bit output bus sliced onto a caller bus, 13 V exact).

## The three probe forms

**Named branch of an instance** (`V(top.a1.b)`): free once absolute
paths resolve — branches rename like every other child item
(`a1__b`), so E-49's member rewrite produces exactly the right name.
The missing piece was scope: E-49's absolute aliases (`<top>.<chain>`,
`$root.`) existed only for the top module's own body text. `ElabCtx`
now carries the top's unambiguous absolute map (`abs_prefixes`) and
every inlined child's scope merges it, so SIBLING bodies resolve
absolute references too.

**Unnamed branch** (`V(top.d1.branch(va, vb))` / `branch(a)`): after
flattening, the child's unnamed branch (va, vb) IS the flattened node
pair (d1__va, d1__vb) — the reference expands textually to that pair,
so `V(...)` and `I(...)` of it are exactly the child's branch
quantities. The path grammar swallows the `.branch(...)` tail into the
path node (`paths.rs`) so the enclosing item's CST stays whole — the
E-49 hole scanner then rewrites the reference (a parse-shredded item
was the original failure mode); an unresolvable chain fails name
resolution as a normal error.

**Port branch** (`I(top.d1.branch(<p>))`): the child's current into
its port is not a node quantity, so flattening synthesizes a 0V
ammeter: the child's body sees a fresh internal net, and a named
branch from the caller's net to it carries exactly the instance
current (positive into the child, matching E-29's `I(<p>)` sign). A
pre-scan over every module's text (`find_port_branch_probes`) records
which instances need one, and a child's own `branch (<p>) pb;`
declarations alias the same ammeter — fixing a blind spot where port
branches inside flattened children were broken (bound to a top port:
silently read the NODE total; bound to an internal net: hard error).

Modules holding absolute references anchored at another module (the
LRM's monitor idiom) are **hierarchy-bound**: their standalone
flattened copies are omitted (a comment marks the omission) since only
inlined copies can resolve.

## The two DAE defects (pre-existing, exposed by the ammeter)

1. **Voltage-source branches feeding internal nodes were open circuits
   at DC.** The small-signal (noise/ac_stim) pruner registers a node's
   drives keyed on the branch's LIVE voltage unknown — a pure
   `V(a, f) <+ expr` whose `V(a,f)` is never read registered nothing,
   so an internal node fed only by such a source plus linear conduction
   was classified as a zero-DC small-signal node and its conduction
   silently moved to the AC-only residual. Any voltage-capable branch
   now disqualifies its nodes from pruning regardless of liveness
   (`small_signal_network.rs`). `V(port, internal) <+ 3.0` with a 1k
   to ground now conducts exactly 2 mA.

   *Behavior change:* a collapsible branch whose current the model
   references (MVSG_CMC's access resistances carry noise on
   `flow(d,drc)`) now stays a real 0V source instead of collapsing —
   electrically identical, two extra matrix rows, and the branch-current
   references stay meaningful (the `mvsg_cmc` descriptor snapshot
   updated accordingly).

2. **A probed `V(x,y) <+ 0` branch was collapse-hinted away.** Node
   collapse eliminated the very unknown `I(branch)` reads — the probe
   silently returned zero. `NodeCollapse::new` now skips hint pairs
   whose branch current is an actual DAE unknown (the unprobed
   collapse idiom is untouched), and `hint()` tolerates suppressed
   pairs (it used to `unwrap_index` — a panic). Pinned by the
   permanent `vsrc_internal_node` sim_back snapshot test.

## Also fixed

- **`ground gnd;` inside flattened children** lost its keyword during
  net-declaration re-rendering (` a1__gnd;` — a parse error); the
  net-type token is preserved now.

## Verification

- `hierbranch_examples` 6/6: all three probe forms runtime-exact
  (1.34 V / 2.5 V / 5 V), the discriminating check that the port-branch
  probe reads the instance's 5 mA and not the 10 mA node total, total
  source current pinning both DAE fixes, and the unresolvable-chain
  diagnostic.
- `partselect_examples` extended to 6/6 (output-direction named slice,
  13 V exact).
- LRM suite: `lrm_p119_1` graduates (40 compile / 19 limitations / 21
  AMS, verify 7/7).
- Full regression: all version11 verify suites + 28 integration tests;
  sim_back/mir_opt/hir_lower snapshot tests green (including the new
  `vsrc_internal_node` pin).

## Gotchas recorded

- The E-49 hole scanner operates per-ITEM on the CST: a construct that
  shreds the parse (the `branch` keyword in path position) fragments
  the item and the scanner sees truncated text — grammar must swallow
  such tails even when elaboration consumes them.
- Absolute-path references from siblings need the top's alias map
  merged into every child render — per-child chain maps only cover the
  child's own subtree.
- ngspice caches nothing across processes, but STALE .osdi artifacts
  during compiler debugging absolutely do (two rounds of confusion in
  this enhancement — recompile before every ngspice probe).
