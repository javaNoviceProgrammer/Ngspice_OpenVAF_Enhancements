# Enhancement-404 — two quadratics behind one wide bus

A module that declares a wide bus and does almost nothing with it:

```verilog
module dut(a, b);
    inout [N:0] a;   inout b;
    electrical [N:0] a;   electrical b;
    analog I(a[0], b) <+ 1e-3;
endmodule
```

compiled in time that grew as **N²** — roughly 4× for every doubling of the bus:

| bus | before | | after | |
| --- | --- | --- | --- | --- |
| `[8191:0]` | 0.66 s | ×6.81 | 0.14 s | ×1.54 |
| `[16383:0]` | 1.95 s | ×2.97 | 0.19 s | ×1.38 |
| `[32767:0]` | 7.52 s | ×3.86 | 0.33 s | ×1.74 |
| `[65535:0]` | **31.50 s** | **×4.19** | **0.62 s** | **×1.89** |
| `[131071:0]` | — | | 1.24 s | ×2.00 |
| `[262143:0]` | — | | 2.80 s | ×2.27 |

51× at `[65535:0]`, and a bus four times wider than the largest that was measured
before now compiles in under three seconds. The scaling is linear.

This is a **low-severity** finding — no real compact model declares a bus at this
scale — and it was fixed on that basis: nothing here trades correctness or clarity
for speed, and the emitted `.osdi` is byte-for-byte what it was.

## The first quadratic, found by profiling rather than by reading

`sample` on a live `[65535:0]` compile put **9906 of 9912 samples** in
`Ctx::lower_port_decl`, with essentially nothing below it — a tight loop that fat
LTO had inlined into one frame. The loop is `find_node_for_decl`, called once per
declared bit:

```rust
if nodes.iter().any(|node| &node.name == name) {
    return nodes.iter_mut().find(|node| &node.name == name);
}
let base = merge_base.as_ref()?;
let node = nodes.iter_mut().find(|node| &node.name == base && node.decls.is_empty())?;
```

Up to **three** full scans of `nodes` per bit — the first two are one logical
lookup split in two to satisfy the borrow checker — while `nodes` itself grows to
N. The module-head port loop held a fourth, `nodes.iter().all(|node| node.name != name)`.

An `FxHashMap<Name, LocalNodeId>` now answers all of them in O(1), maintained by
a `push_node` helper so that every one of the five push sites keeps it in step.
The map holds the **first** node under each name, which is exactly what the linear
`find` it replaces would have returned.

Two details are worth stating, because they are where an index like this usually
goes wrong:

* **The merge path renames a node.** The first bit of a bus claims the module-head
  placeholder declared under the bare base name and renames it `a[0]`, so the index
  entry has to move with it. Subsequent bits then find no placeholder and push new
  nodes — the same sequence the scan produced.
* **The scan is kept as a fallback.** If a name's first node is already claimed,
  the old code went on looking for a later unclaimed one. Nothing well-formed can
  produce that — the head loop dedups by name and every other push carries a
  distinct bit name — so the fallback never runs, but the semantics are identical
  either way rather than identical-in-the-cases-considered.

## The bottleneck then moved, so the profile was taken again

That change alone took `[65535:0]` from 31.5 s to 2.4 s, but the top of the table
was still growing at ~3× per doubling. Re-profiling — against a temporary
debug-info build, since fat LTO had collapsed the frames — put **100%** of samples
in `sim_back`'s `build_jacobian`. Not bus elaboration at all, but the remaining
quadratic in this compile.

It builds each jacobian row densely and then sparsifies it:

```rust
self.system.jacobian =
    TiVec::with_capacity(self.system.unknowns.len() * self.system.unknowns.len());
let mut dense_row = TiVec::from(vec![(F_ZERO, F_ZERO); self.system.unknowns.len()]);
...
for (col, (resist, react)) in &mut dense_row.iter_mut_enumerated() { ... }
```

There are two costs. The reservation asks for a **dense** matrix that is never
built — 4.3 × 10⁹ entries for `[65535:0]`. And the sparsify scan walks every column
of every row: O(unknowns²), with one row per unknown.

Instrumenting the builder showed what that scan was actually looking at:

```
n=1023:   unknowns=1025   residual=1025   sim_unknown_reads=0
n=8191:   unknowns=8193   residual=8193   sim_unknown_reads=0
n=16383:  unknowns=16385  residual=16385  sim_unknown_reads=0
```

Every declared node becomes a simulation unknown before collapsing, so the matrix
is (N+2)×(N+2) — and with `sim_unknown_reads` empty, **the entire scan ran over
zeros**. The row build now records the columns it actually reaches and sparsifies
only those; the reservation drops to the diagonal.

**The sort is the part that matters.** The dense scan emitted a row's entries in
ascending column order; iterating touched columns in insertion order would not.
`SimUnknown` derives `Ord`, so a `sort_unstable` + `dedup` restores exactly the old
order — which is why this is a pure speedup and not a re-layout of the matrix.

## Verification

* **Byte-identical output, twice over.** Corpus differential over `VA_TEST` at the
  same `-o` path (an `.osdi` embeds its own output path): 124 models, **107
  compiled by both, 0 return-code differences, 0 byte differences.** Because no
  corpus model declares a wide bus, that was repeated on modules that do —
  `[15:0]`, `[255:0]`, `[1023:0]` and `[8191:0]`, plus `[7:0]`, `[63:0]` and
  `[255:0]` giving **every bit its own conductance** so a mis-mapped bit would
  change the bytes: **all seven byte-identical.**
* **Bit-to-node identity**, measured in the simulator rather than inferred: an
  8-bit bus whose bit *k* conducts (*k*+1) mA reads `i(v0..v7)` = −1.0e−3 …
  −8.0e−3 on both binaries.
* **Full regression 322/322.**
* **`cargo test --workspace --features llvm18` 210/0.**
* **No cost to real models**: bsim4 (9723 lines) compiles in 1.47 s before and
  1.48 s after, min of three.

## Found by

The second of the two round-13 findings that [Enhancement-399](Enhancement-399.md)
left open. The first is closed by [Enhancement-400](Enhancement-400.md). E-399
recorded this one as quadratic **and not a hang** — a distinction that came from
measuring the scaling rather than from watching a wide compile appear to stall,
and one that pointed straight at a linear scan per bit.
