# Enhancement-511 — an option the run honours, reported as unknown

```
python3 verify_optknown.py
```

13 checks, both linear solvers. 6 of them fail without the fix.

## What was wrong

`.option osdicache` printed `Warning: unknown option 'osdicache' ... ignored.` and
then cached the compile anyway. User-reported.

[Enhancement-500](../../enhancements_doc/Enhancement-500.md) reads `osdicache`
straight off the option cards, deliberately not through `cp_getvar` — `pre_osdi
-va` runs before any option has been published.
[Enhancement-438](../../enhancements_doc/Enhancement-438.md) later made an
unrecognised name on a `.options` card a warning, because a misspelling used to be
silently inert. `osdicache` never reaches the simulator option table, so the check
called it unknown while E-500's scanner had already honoured it.

The allow-list in `spiceif.c` exists for exactly this, and says so: *"a warning
that fires on a setting the run then honours is worse than no warning."*
`autobus`, `saveused`, `klu`, `reusesetup` and `noinit` are all on it. `osdicache`
was never added — and **`seedinfo` had the identical defect**, read from the deck
the same way and acted on by `setseedinfo()`.

## The check still bites

| | before | after |
|---|---|---|
| `.option osdicache`, `osdicache=0`, `seedinfo` | reported unknown | accepted |
| `.option osdicaches` (misspelt) | warns | **still warns** |
| `.option reltoll=1e-12` (E-438's example) | warns | **still warns** |

## Not a defect

If a `.va` and its `.osdi` are written within the **same second** the cache is
skipped — the staleness test is *strictly* newer because `st_mtime` has
one-second granularity. A tie costs one needless recompile; the other way loads
the object built from the previous text.

## Files

| file | what it holds |
|---|---|
| `cachemod.va` | a trivial model, compiled through `pre_osdi -va` so the cache decision is visible |
