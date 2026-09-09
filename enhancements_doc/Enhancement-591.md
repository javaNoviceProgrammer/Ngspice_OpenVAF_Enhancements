# Enhancement-591: `.option saveused` knows the accessor spellings of `v()`

**Scope:** `src/frontend/dotcards.c` (`e469_scan_refs`, the reference scan behind
the option), `examples/saveforms_examples/` (new, 16 checks per solver). **ngspice
only.** Finding F2 of the 2026-09-09 dig into `autobus`, `autoadapt`, `automc` and
`saveused`.

**Suites:** [`saveforms_examples`](../examples/saveforms_examples/) 16 of 16 per
solver, both solvers; `saveused_examples` and `autoopts_examples` unchanged; full
sweep 486 of 486.

## What was wrong

`.option saveused` (Enhancement-469) reads the control block and the deck's output
cards (Enhancement-572), collects every vector they mention and saves those alone.
The scan knew three forms: `v(...)`, `i(...)` and `@dev[param]`. ngspice's own
accessor spellings of `v()` — `vm()`, `vp()`, `vr()`, `vi()`, `vdb()` and `vg()`,
defined in `cpitf.c` as aliases of `mag(v(x))`, `ph(v(x))`, `real(v(x))`,
`imag(v(x))`, `db(v(x))` and the group delay, each also in the two-node form
`vdb(x,y)` — name the same vectors and were invisible to it:

| block | what happened |
|---|---|
| `print v(in) vdb(out)` after an `ac` | `in` saved, "vector out is not available" |
| `.meas ac gain find vdb(out) at=1k` beside a block printing `v(in)` | "no such vector as v(out)", the measure fails |
| `print vdb(out) vp(out) vm(out)` and nothing else | all print — by accident: the scan collected nothing, so the option stood down and every node was saved |

An ac deck is exactly where these forms are written, and the third row means the
option did not act on many of the decks it was set for.

## What changed

The scan recognises, after a non-identifier character, `v` or `i` followed by an
optional accessor suffix and `(`. The plain forms keep their verbatim registration
(`v(a,b)` as written, which `save` accepts). A suffixed form is registered as the plain
accessor of each node it names — `vdb(out)` as `v(out)`, `vm(a,b)` as `v(a)` and
`v(b)` — which is what `save` understands and what the option needs. `i()` has no
suffixed aliases in `cpitf.c`, so it takes none. Case does not matter, as before.

```
.option saveused
.control
ac dec 2 100 10k
print v(in) vdb(out)          ; out is now kept
.endc
.meas ac gain find vdb(out) at=1k
```

A block that uses only `vm(out)` now restricts the save set, keeping `out` and not
`in` — the option's purpose, where before it silently saved everything.

## Verification

| check | result |
|---|---|
| `print v(in) vdb(out)` | both print |
| `vm`, `vp`, `vr`, `vi`, `vdb`, `vg`, `VM`, `VDB` beside `v(in)` | `out` kept in each |
| `vdb(out,in)` | both nodes kept |
| `.meas ac gain find vdb(out) at=1k` and `.print ac vm(out)` beside a block printing `v(in)` | gain −1.4513 dB, the table filled |
| a block using only `vm(out)` | `out` kept, `in` not |
| `i(v1)` and `v(in,out)` beside `vm(out)`; `@n1[ir]` beside `vm(out)` in a transient | all work; saved per point |
| a node nobody names | still not saved |
