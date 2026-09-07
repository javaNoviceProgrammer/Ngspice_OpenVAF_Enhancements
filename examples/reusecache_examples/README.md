# reusecache_examples — `.option osdicache` and `.option reusesetup`

A dig of 2026-09-07 into the two options, on the committed `openvaf-r` and `ngspice-46`,
both solvers. Six defects were found and fixed (Enhancement-573); this suite pins the fixes
and the behaviour that was already right.

## `.option osdicache` — `pre_osdi -va` skips an object that is up to date

| check | what it pins |
|---|---|
| [1] spellings | `osdicache` caches; `osdicache=0`, `osdicache = 0`, `osdicache=off` and `noosdicache` recompile, and none of them is called an unknown option (`noosdicache` was) |
| [2] `inc.va` + `body.inc` | an edit to a file the source `` `include``s rebuilds the object; the staleness test walks the includes the way the compiler resolves them, relative to the including file |
| [3] the compiler | an object older than `openvaf-r` is rebuilt and the run says so; with the compiler older again the object is up to date |
| [4] `a/m.va`, `b/m.va` | two sources with the same stem in different directories both load: a source with a directory names its object after it, `osdi/a_m.osdi` and `osdi/b_m.osdi`; a bare `rmod.va` still lands in `osdi/rmod.osdi` |

## `.option reusesetup` — a sweep keeps the circuit standing between points

Two device quantities were computed at setup only and went stale on every path that
changes a parameter without a setup: the reused sweep, `alter`, and the `.dc` that a
single-knob `op` sweep becomes (E-533/E-534).

| check | what it pins |
|---|---|
| [5] resistor | a noise sweep over `@r1[l]` matches a standalone run at every point with the setup reused (the tally says 2 of 3), and so does `alter @r1[l]` followed by `noise`; the flicker-noise area is now recomputed with the resistance |
| [6] BJT | `ise=2` is the SPICE2 c2 form, a multiplier of `is`; a sweep of `@qm[is]` as one `.dc`, per point with the setup reused, and per point with it rebuilt all match the standalone runs; `@qm[ise]` reads back 2 as given; an ordinary `ise` is unchanged |
| [7] `.ic` + `uic` | the initial condition is applied at every point of a transient sweep, reuse on and off alike |

## Run

```
python3 verify_reusecache.py
```

24 checks per solver, all PASS.
