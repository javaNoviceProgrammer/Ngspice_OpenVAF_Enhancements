# Enhancement-607: a `@dev[param]` vector keeps its name in a raw file

**Scope:** `src/frontend/outitf.c` (`fileInit_pass2`, the batch `-r` writer),
`src/frontend/rawfile.c` (`raw_write`, the `write` command; `raw_read` puts an old
file's `i(@...)`/`v(@...)` back), `examples/rawparam_examples/` (new, 7 checks per
solver). **ngspice only; every OSDI terminal current `.option savecurrents` records
was affected.** Finding N4 of the 2026-09-10 integration hunt
([`docs/bug_hunts/2026-09-10_ngspice-osdi-integration-second-hunt.md`](../docs/bug_hunts/2026-09-10_ngspice-osdi-integration-second-hunt.md)),
a stock ngspice defect.

**Suites:** [`rawparam_examples`](../examples/rawparam_examples/) 7 of 7 per solver,
both solvers; `rawtrip`, `rawfuzz`, `rawfstring`, `savecur`, `savecuroff` and the other
raw-file suites unchanged; full sweep 502 of 502 (one sweep, Enhancements 604–608 folded
together).

## What was wrong

The raw-file writers spell a node voltage `v(x)` and a branch current `i(x)` (with
`#branch` stripped), and a loaded file's `v(out)` and `i(v1)` resolve to `out` and
`v1#branch` again. But `@r1[i]` is current-typed, so it was written `i(@r1[i])` — a name
nothing reads back: after `load`, `@r1[i]` asks the (absent) device ("no such device
or model name r1"), and `i(@r1[i])` is the parser's i() of a name that is not a source.
`@n1[i_p]` under `.option savecurrents`, in `write` and in batch `-r` alike, was in
every raw file an OSDI deck produced and reachable in none of them.

## What changed

- A `@` name is a device parameter, never a node or a branch: both writers write it
  verbatim, whatever its type (`@r1[p]`, power-typed, was already verbatim; the
  current-typed ones join it).
- The reader puts an old file's `i(@...)` or `v(@...)` back to the `@` name, so files
  an earlier writer produced load addressable too.

## Verification

| check | result |
|---|---|
| `save all @r1[i] @r1[p] @r2[i]`, `write`, `remcirc`, `load` | `@r1[i]` 0.5 mA, `@r1[p]` 0.25 mW, `@r2[i]` 0.5 mA print; `v(out)`, `i(v1)` still do; the file names them verbatim |
| batch `-r` with `.option savecurrents` | `@r1[i]`, `@r2[i]` verbatim; a fresh session loads and prints them |
| a hand-written old file with `i(@r1[i])` and `v(@r1[v])` | loads as `@r1[i]`, `@r1[v]` |
| an OSDI device's `@n1[i_p]`/`@n1[i_n]` under `savecurrents` | verbatim, read back (0.5 mA, −0.5 mA) |
| the node voltage and the branch current | keep `v()`/`i()` |

Full sweep 502 of 502 on both solvers.
