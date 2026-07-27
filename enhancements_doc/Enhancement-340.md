# Enhancement-340 — compiling the same source twice produced two different MIRs

`examples/lrm_examples/va/lrm_p150_1.va` compiled to **2 distinct MIRs**, and
`lrm_p209_1.va` to **8**, varying run to run on the same binary and the same input.

This was known and dismissed twice with the wrong cause attached to it. Both
earlier explanations were tested here and **disproved**:

| claimed cause | test | verdict |
|---|---|---|
| "multi-module dump ORDER varies" | the timing line accounted for it (E-338 era) | wrong |
| "parallel module compilation" | `RAYON_NUM_THREADS=1` — still 2 hashes | **wrong** |
| "hash-container iteration of implicit nets" | `implicit_nets` is only `get`/`insert`, never iterated | **wrong** |

## The actual root cause

Diffing two variants of the *unoptimised* MIR reduced it to four lines, the first
of which is the cause and the rest consequences:

```
< Spur(27) -> 'aa0'          > Spur(27) -> 'aa2'
< Spur(28) -> 'aa2'          > Spur(28) -> 'aa0'
< sim_node7: br[... node20 ...]   > sim_node7: br[... node21 ...]
< resist: v1748              > resist: v1757
```

Two strings are interned in a different order; node numbering and SSA value
numbering follow.

Both names are implicit nets introduced by **one** instance:

```verilog
comparator C1(.cout(aa0), .inp(in), .inm(aa2));
```

Enhancement-41 declares an undeclared connection actual implicitly, emitting the
declaration the first time it meets each name while walking the instance's port
bindings — in `hir/src/elaborate.rs`:

```rust
for (port_name, binding) in port_raw.iter_mut() {
    ...
    implicit_decls.push(format!("{discipline} {final_name}; // implicit net"));
```

`port_raw` is a `HashMap<Name, PortBinding>`. Rust seeds its hashers **randomly
per process**, so this walk visits the bindings in a different order on every
run. Whichever implicit net is met first is declared first, interned first, and
receives the lower `Spur`.

It takes **two implicit nets on one instance** to show. With one there is nothing
to reorder — which is why almost the whole corpus is unaffected.

`RAYON_NUM_THREADS=1` does not help because the randomness is in the hasher seed,
not in thread scheduling. That is what made the parallelism theory look plausible
and kept it alive.

## The fix

Walk the bindings in the **target's declared port order** — deterministic, and the
order a reader would expect — with the port name as a total tie-break for anything
not found there.

## Verified

- The reproducer and both corpus models now yield **one** MIR over 12 compilations
  each (`lrm_p209_1.va` went from 8 distinct to 1).
- **Corpus-wide: 488 models, 486 identical, 2 changed, `NONDETERMINISTIC 0`.** The
  two that changed are exactly the affected models, which now produce one canonical
  MIR instead of a random pick.
- **Not a behaviour change.** The sigma-delta model simulates byte-identically
  before and after — 417 transient rows, same hash, across four compilations with
  each binary.

## Why it mattered

It was never a miscompile: the permutation is consistent and the simulated output
is unchanged. But builds were not bit-reproducible, and it defeated MIR-diff
output-preservation checking — a change under test could not be distinguished from
the compiler disagreeing with itself. `VA_TEST/mir_oracle.py --stable` exists to
tolerate exactly this; with the cause gone, that flag is now a safety net rather
than a necessity.

## Files

- `OpenVAF-master-20260610/openvaf/hir/src/elaborate.rs` — deterministic
  port-binding walk order.
- `examples/vafdeterminism_examples/` — the same source compiles to the same MIR
  every time, both corpus models included (`verify_vafdeterminism.py`, 4 checks).
