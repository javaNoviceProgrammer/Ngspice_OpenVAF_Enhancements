# Enhancement-331 — `BitSet::contains` panicked outside its domain

Found while bounding the derivative order for Enhancement-330. Deeply nested `ddx`
crashed the **shipped** compiler:

```
thread 'main' panicked at lib/bitset/src/lib.rs:114:
  index out of bounds: the len is 1 but the index is 1
    bitset::BitSet<T>::contains
    bitset::hybrid::HybridBitSet<T>::contains
    mir_autodiff::…::populate_reachable
```

## Root cause — a representation leaking out as a panic

`BitSet::contains` indexed its backing storage with no bounds guard:

```rust
pub fn contains(&self, elem: T) -> bool {
    let (word_index, mask) = word_index_and_mask(elem);
    (self.words[word_index] & mask) != 0        // panics if the row is too short
}
```

A `HybridBitSet` stores a set either **sparsely** (a `Vec` of elements) or
**densely** (a bit array), switching as a size optimisation. Rows grow their domain
when something is inserted into them, so a row the traversal never inserts into
keeps whatever width it had when it went dense. Once the live-derivative universe
grew past 64 — **one word** — a query for a higher element indexed off the end.

The decisive detail is the asymmetry between the two representations:

| representation | `contains(elem)` beyond the domain |
|---|---|
| `SparseBitSet` | searches a `Vec` → returns **`false`** |
| `BitSet` (dense) | indexes `words[..]` → **panics** |

So the *same logical query* on the *same logical set* returned `false` while the
set happened to be sparse and crashed once it happened to be dense. The
representation — the very detail `HybridBitSet` exists to hide — leaked out as a
compiler crash.

## The fix

Make the dense query total, matching what the sparse one already does:

```rust
self.words.get(word_index).map_or(false, |word| (word & mask) != 0)
```

An element beyond the domain **cannot have been inserted** — `insert` grows the
domain — so "not contained" is the only correct answer. This is the one read-only
query that indexed unguarded; the remaining direct indexing sites are *mutating*
methods (`insert`, `remove`, internal helpers), where requiring the caller to
respect the domain is legitimate, so they are deliberately left alone.

## Verified

- The crash is gone across the word boundary and well past it. On the **release**
  build (what ships) 64, 65, 66, 80, 128, 129 and 200 nested `ddx` all compile —
  n = 200 in 1.8 s — where the shipped compiler previously panicked from 65 on. On
  the **assertions** build 64, 65 and 128 were verified to compile; n = 200 there
  had not finished after 300 s. That is the instrumented build's own cost (it runs
  the MIR validator over a function carrying a 200-deep derivative chain), not a
  regression from this change: before the fix that input panicked *early* instead
  of doing the work. It is called out here rather than glossed as "compiles on both".
- **Results are unchanged, not merely non-crashing.** A query that wrongly answered
  "absent" would silently drop a live derivative and corrupt the output, so
  higher-order derivatives are checked against the closed form: for `V³` at V = 2,
  `d/dV = 3V² = 12`, `d²/dV² = 6V = 12`, `d³/dV³ = 6` — measured `-12 mA`, `-12 mA`,
  `-6 mA` exactly.

## Output preservation

For any element **inside** the domain the expression is bit-identical to before —
`words.get(i)` returns `Some(&words[i])` and the mask test is unchanged. For an
element **outside** it, the previous behaviour was a panic, i.e. no output at all.
There is therefore no input for which behaviour changed from one valid result to a
different one. Confirmed against the corpus with the deterministic `--dump-mir`
oracle.

## A note on the threshold

The crash was first reported at 32 nested `ddx`. Re-verification put it at **65** —
the point at which the universe exceeds one 64-bit word, which is also what the
mechanism predicts. The example sweeps 64/65/128/129 rather than testing a single
depth, so it exercises the boundary itself rather than one lucky number.

## Files

- `OpenVAF-master-20260610/lib/bitset/src/lib.rs` — `BitSet::contains`.
- `examples/vafbitsetdomain_examples/` — 66 nested `ddx` compiles, the boundary
  sweep compiles, and higher-order derivatives stay exact
  (`verify_vafbitsetdomain.py`, 3 checks).
