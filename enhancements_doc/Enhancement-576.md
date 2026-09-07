# Enhancement-576: `run_regression.py --jobs N` — the sweep runs suites in parallel, 1391 s to 316 s

**Scope:** `examples/run_regression.py` only. **Harness; no simulator or compiler
change.**

**Suites:** the full sweep, 475 of 475 under `--jobs 8` in 316 s and 475 of 475
sequentially in 1391 s on the same tree, the same day.

## What it does

```
python3 run_regression.py --jobs 8      # eight suites at a time
NG_JOBS=8 python3 run_regression.py     # the same through the environment
```

`--jobs N` runs N suites at once on a thread pool, each suite in its own subprocess as
before. The per-suite lines then come in completion order, each numbered by how many
have finished; the summary and the `NOT OK` list are unchanged. The default stays
sequential — a sweep on a shared or noisy machine is easier to read that way — and
`-j N`, `--jobs=N` and `-jN` are accepted spellings.

## Why it is safe

Every verify script runs from its own directory and cleans its own scratch files, and
a search of all 475 found none that writes outside it: the six that reach into another
directory (`dynphys`, `paramrange`, `physcheck`, `plotorder`, `rfanalyses`,
`tempphys`) only read model sources there. The harness settings that
[E-574](Enhancement-574.md) hands every child — a dumb terminal, `NO_COLOR`, the
resolved compiler — are per process and unaffected.

Three suites are the exception, and they are held back to run alone after the parallel
batch: `benchmark` (an OSDI-against-built-in speed ratio), `nested_cond` (compile time
against nesting depth) and `reusesetup` (check [26], the setup reuse against a rebuild)
each assert a ratio *measured on the machine*, which a loaded machine would move. They
are the `SERIAL` set at the top of the runner, with the reason beside each.

## What it is worth

| | wall time | result |
|---|---|---|
| sequential | 1391 s | 475 of 475 |
| `--jobs 8` | 316 s | 475 of 475 |

The remaining wall time is the longest suites, not the count: `lrmfuncs` alone takes
207 s under load (137 s alone), `rtdomain` 135 s. More jobs would not shorten those.
The machine this was measured on has 16 performance cores and idles through a
sequential sweep at one busy core, which is why its fans never noticed one.
