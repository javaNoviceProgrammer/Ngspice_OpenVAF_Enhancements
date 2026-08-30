# Enhancement-511 — an option the run honours, reported as unknown

User-reported. `.option osdicache` printed

```
Warning: unknown option 'osdicache' on a .options card; ignored.
```

and then cached the compile anyway — the run said it was ignoring a setting it had
already acted on.

## Two enhancements colliding

[Enhancement-500](Enhancement-500.md) reads `osdicache` straight off the option
cards in `inp.c`, deliberately **not** through `cp_getvar`: `pre_osdi -va` runs
before any option has been published, so `cp_getvar` would answer for the previous
deck or for nothing at all — the trap
[Enhancement-464](Enhancement-464.md) recorded for `autobus`.

[Enhancement-438](Enhancement-438.md) later made an unrecognised name on a
`.options` card a warning, and for good reason: a misspelling used to be silently
inert, so `.options reltoll=1e-12` left `reltol` at its default while the user
believed the tolerance had been tightened.

`osdicache` never reaches the simulator option table at all, so E-438's check calls
it unknown — while E-500's own scanner has already honoured it.

That is precisely the failure the allow-list in `spiceif.c` exists to prevent, and
its own comment says so:

> a warning that fires on a setting the run then honours is worse than no warning:
> it teaches the user to ignore the check E-438 added.

`autobus`, `saveused`, `klu`, `reusesetup` and `noinit` are all listed there.
`osdicache` was simply never added.

## `seedinfo` had the identical defect

Found while checking whether `osdicache` was alone. It is read from the deck the
same way at `inp.c` and calls `setseedinfo()`, which makes `randnumb.c` print the
seed it chose — a setting that demonstrably works, reported unknown.

| | before | after |
|---|---|---|
| `.option osdicache` | `unknown option 'osdicache'` | accepted |
| `.option osdicache=0` | `unknown option 'osdicache'` | accepted |
| `.option seedinfo` | `unknown option 'seedinfo'` | accepted |
| `.option osdicaches` (misspelt) | warns | **still warns** |
| `.option reltoll=1e-12` (E-438's own example) | warns | **still warns** |

## The check still has to bite

A fix that silenced the warning generally would undo E-438. The change is two
names on an allow-list, nothing more: a genuine misspelling is still reported, and
checks [4] and [5] hold that line — [5] with E-438's own `reltoll` example.

## Not a defect, worth knowing

If a `.va` and its `.osdi` are written within the **same second**, the cache is
skipped and the model rebuilds. That is deliberate: `st_mtime` has one-second
granularity, so the staleness test is *strictly* newer. A tie costs one needless
recompile; the other way loads the object built from the previous text. It looks
like the cache failing, and it is the guard working. Check [8] pins the cache hit
outside that window.

Also observed while writing the suite, and left alone: `seedinfo` and `seed=` must
share one option card. Setting them on separate cards does not print the seed, so
the flag is evidently not in force when a separate `seed=` card is applied. That
is a pre-existing ordering question in the option scan, not something this
enhancement touches.

## Files

| file | change |
|---|---|
| `ngspice-46/src/frontend/spiceif.c` | `osdicache` and `seedinfo` added to `if_is_option`'s allow-list |
| `examples/optknown_examples/` | new suite |

## Verification

`optknown_examples` — **13 checks, both linear solvers**, of which **6 fail on the
shipped binaries** (measured: 7/13 pass before the fix, 13/13 after). Full
regression **425/425**.
