# Enhancement-782: flattening an instance array was quadratic again — `%m`'s hierarchy lookup, the contribution map and the flow-probe statement search each scanned everything once per instance

**Scope:** OpenVAF: `openvaf/hir/src/elaborate.rs` (`AbsPrefixes::by_prefix`,
`hier_path_of_prefix`), `openvaf/hir/src/body.rs` (`ContributionMap`'s index and `BranchKey`,
`collect_flow_probes`). From the macOS Intel CI sweep, where vafhang [A] took 58 s for a
32,001-instance array against its 45 s bound.

**Suites:** vafhang (2 of 2), hierub, probeshort (48 of 48), diagslips, display, funclocal,
hunt3diag, lrmio, and the full sweep on macOS.

## What was wrong

E-264 made the flattening of a large instance array linear: a `u[0:N]` array, or a generate
loop, used to hang the compiler. vafhang [A] guards it with absolute bounds that assume a fast
machine, and on Apple Silicon the times still sat well inside them. On the macOS Intel runner
they did not: 7.0 s for 16,001 instances and 28.4 s for 32,001 run alone, four times the time for
twice the size, and 58 s inside the sweep. The arm64 times had the same shape:

| instances | before | after |
|---|---|---|
| 8,001 | 0.65 s | 0.72 s |
| 16,001 | 2.34 s | 0.57 s |
| 32,001 | 8.56 s | 1.10 s |
| 64,001 | (not run) | 2.68 s |

Three later additions each did a linear search once per instance:

1. **`%m`** (E-650): `hier_path_of_prefix` names an instance from its flattening prefix by
   scanning every entry of the hierarchy's prefix map -- one per instance -- for the shortest
   chain with that prefix. It is called once per instance.
2. **The contribution map** (E-400): a contribution's bucket was found by scanning the buckets
   with `same_branch`. Since E-757 each instance's contribution has its own named branch, so an
   array of N instances has N buckets; building the map was O(N^2), and every lookup the DAE
   build makes per branch (`check_discarded_contribution`, E-400) was O(N).
3. **The flow-probe sites** (E-406): each probe's lint anchor, the innermost statement containing
   it, was found by scanning every statement of the body: O(probes x statements).

## The change

1. `AbsPrefixes` keeps the inverse map, prefix to shortest chain (the smaller string on a tie,
   where the scan took whichever the hash map yielded first), built once with the map.
2. `ContributionMap` indexes its buckets by the key `same_branch` compares -- a named branch by
   identity, a node pair ground-free and looked up both ways round, so order-free -- and finds a
   bucket in O(1). A write whose nodes are all ground has no key, as `same_branch` matches nothing
   for it.
3. `collect_flow_probes` sorts the body's statement ranges once (by start, the longest first,
   the lowest id first among equal ranges) and finds a probe's statement by binary search and a
   short walk back: ranges nest, so the first statement containing the probe met walking back from
   the last one that starts at or before it is the innermost, as before.

After the change, the 64,001-instance compile spends its time in parsing and LLVM.

## Limits

- `ContributionMap::other_branch_over_same_nodes` (E-406) still scans the buckets, once per
  flow probe of a branch nothing contributes to: a large array of such probes stays quadratic in
  that check.
- vafhang's bounds stay absolute; the fix is measured above, not asserted as a ratio, because
  timing ratios under the sweep's parallel load are not stable enough to gate on.
