# Enhancement-573: a dig into `.option osdicache` and `.option reusesetup` — a cache that watches its includes and its compiler, two sources that may share a stem, and two setup-time quantities that follow a swept parameter

**Scope:** a probe battery over the two options (both solvers), and what it found.
`src/frontend/com_dl.c` (the `pre_osdi -va` cache), `inp.c` and `spiceif.c` (the
`noosdicache` spelling), `src/spicelib/devices/res/restemp.c` (the flicker-noise
area), `src/spicelib/devices/bjt/bjtsetup.c`, `bjttemp.c`, `bjtdefs.h` (the c2/c4
leakage form). **ngspice only.**

**Suites:** new [`reusecache_examples`](../examples/reusecache_examples/) (24 checks per
solver, both solvers); `vacompile`, `reusesetup`, `reusestate`, `reusedev`,
`reuseloops`, `sweeptemp`, `mcarming`, `loopguard`, `optknown` pass; full sweep 473 of
473 on both solvers.

## The survey

`.option osdicache` ([E-500](Enhancement-500.md)) lets `pre_osdi -va` skip a Verilog-A
source whose object is already up to date. `.option reusesetup` ([E-471](Enhancement-471.md))
keeps the circuit standing between the points of a `sweep`, `optimize` or `montecarlo`
and runs `CKTtemp` in place of a setup. Both were read as designed and then pushed where
their own suites had not gone: every spelling of on and off, a source split across
files, a compiler rebuilt after the object, two model files with the same name, the
device quantities that ngspice computes at setup and nowhere else, and the paths that
change a parameter without a setup — the reused sweep, `alter`, and the `.dc` that a
single-knob `op` sweep becomes since [E-533](Enhancement-533.md). The two solvers agreed
on every value throughout; what follows is what the options themselves did.

| probe | before | now |
|---|---|---|
| `osdicache`: `body.inc` edited, `inc.va` that includes it untouched | "is up to date" — the object of the previous text, and the previous answer | rebuilt; the answer follows |
| `osdicache`: `openvaf-r` newer than the object | "is up to date" | "is older than the compiler …; rebuilding" |
| `pre_osdi -va a/m.va b/m.va` | one object `osdi/m.osdi`; the second "already loaded; skipping", its model never defined | `osdi/a_m.osdi` and `osdi/b_m.osdi`, both loaded |
| `.option noosdicache` | "unknown option 'noosdicache' … ignored" | the off spelling, accepted |
| `reusesetup`: `sweep @r1[l]` with a noise analysis | 169.7, **184.7, 171.7** — rising | 169.7, 130.6, 85.8, as three standalone runs |
| `reusesetup`: `sweep @qm[is]` with `ise=2` | second point 2 % off a standalone run, with the setup reused or rebuilt alike | matches |

Already right, and pinned: `osdicache=0`, `osdicache = 0` and `osdicache=off` all
recompile; `-f` still forces the rebuild; a bare `rmod.va` still lands in
`osdi/rmod.osdi`; an initial condition with `uic` is applied at every point of a
transient sweep; the reuse tally under `set ngdebug` counts what actually happened.

## What was wrong

**The cache watched one file.** The staleness test compared the object against the
source named on the `pre_osdi` line and nothing else. A model split into a header and a
body — a parameter list in one file, the equations in another, the textbook layout for
a compact model — kept loading the object of the previous text after an edit to the
included file, because the including file's timestamp had not moved.

**The cache trusted the compiler.** E-500 made the cache opt-in precisely because "a
`.va` timestamp says nothing about the compiler having changed", and left that hazard
to the user. While `openvaf-r` is under development it changes more often than the
models do, and an object built by a compiler that no longer exists is exactly what a
timestamp cache hands back.

**Two sources, one object.** The object was named after the source's stem alone, so
`a/m.va` and `b/m.va` — a vendor's model beside a local edit of it, say — compiled onto
the same `osdi/m.osdi`. The second compile overwrote the first's object while it was
loaded; the loader then reported the path "already loaded" and skipped it, so the
second model was never registered and the deck failed at its `.model` line. Under the
cache the surviving object was "up to date" for whichever source had been compiled
last.

**`noosdicache`.** The options scanner in `inp.c` matched `osdicache` and `osdicache=`;
the `no` prefix, which [E-572](Enhancement-572.md) had just made the accepted off
spelling for the other options, was reported unknown here.

**The resistor's flicker-noise area.** `RESsetup` computed the effective noise area
from `l`, `w` and the model's `lf`, `wf`, `short` and `narrow`, and no other routine
touched it. Every path that changes the geometry without a setup then ran the noise
analysis with the area of the first point: a noise sweep over `@r1[l]` rose where three
standalone runs fall, with the setup reused at 2 of 3 points as the tally reported.
`alter @r1[l]` followed by `noise` had the same defect, and so would a `.dc` over `l`
that fed a noise figure.

**The BJT's c2/c4 form.** An `ise` or `isc` above 1e-4 is the SPICE2 form, a multiplier
of `is`. `BJTsetup` resolved it in place — `ise = is * ise` — which destroyed the given
value. After any later change of `is`, the leakage stayed scaled by the old `is`
whether or not the setup was rebuilt: a rebuilt setup found a value already below 1e-4
and left it alone. So this one was not a reuse defect at all, though the reuse is where
it surfaced; `.dc @qm[is]` and a per-point sweep with `reusesetup=0` were wrong by the
same 2 %.

## What changed

**`com_dl.c`.** The staleness test now takes the newest timestamp among the source and
every file it `` `include``s, resolved the way the compiler resolves them — relative to
the including file's own directory first — and recursing to a fixed depth so an include
cycle terminates. A name found nowhere on that path, the compiler's own
`disciplines.vams` and `constants.vams`, is skipped rather than counted as missing. The
object must also be newer than the compiler `osdi_find_openvaf()` names; when it is
not, the run says which compiler it is older than and rebuilds. A compiler found on
`PATH` by bare name cannot be stat'ed and is not checked. The object's name folds in
the source's directory when it has one: `a/m.va` becomes `osdi/a_m.osdi`, `../lib/m.va`
becomes `osdi/up_lib_m.osdi`, a bare `m.va` is `osdi/m.osdi` as before.

**`inp.c`, `spiceif.c`.** `noosdicache` sets the cache off and is in the known-option
list.

**`restemp.c`.** The noise area is recomputed in `RESupdate_conduct`, the per-instance
parameter update that `REStemp`, `RESparam` and the `.dc` parameter sweep all run, from
the values as they stand. `RESsetup` keeps its copy of the computation; the two agree.

**`bjtsetup.c`, `bjttemp.c`, `bjtdefs.h`.** The given `ise`/`isc` are kept as given.
`BJTtemp` resolves the multiplier form every time it runs, into two new model fields,
and the temperature-scaled leakage currents read those. `@qm[ise]` now reads back the
value the model card gave rather than the resolved product.

## Verification

[`reusecache_examples`](../examples/reusecache_examples/) — 24 checks per solver:

| section | checks |
|---|---|
| [1] the spellings | `osdicache` caches; `osdicache=0`, `= 0`, `=off`, `noosdicache` recompile; none is an unknown option |
| [2] includes | `inc.va` + `body.inc` built once then up to date; `body.inc` edited alone rebuilds and the current halves |
| [3] the compiler | a compiler touched after the object rebuilds it and says so; older again, up to date |
| [4] the same stem | `a/m.va` and `b/m.va` both load (1k ‖ 2k gives 1.5 mA), as `osdi/a_m.osdi` and `osdi/b_m.osdi`; both up to date on a second cached run; a bare source is unchanged |
| [5] the resistor | three standalone noise totals fall with `l`; the reused sweep matches all three and the tally says 2 of 3; `alter` then `noise` matches |
| [6] the BJT | `ise=2` scales with `is` standalone; the sweep as one `.dc`, per point reused, and per point rebuilt all match; `@qm[ise]` reads 2; an ordinary `ise` is unchanged |
| [7] `.ic` + `uic` | the initial condition holds at every point, reuse on and off |

The include and compiler checks set timestamps explicitly rather than sleeping across a
second, and the compiler check runs a private copy of `openvaf-r` through the `OPENVAF`
environment variable, because a `set openvaf=` in the deck's control block runs after
the `pre_` commands it would have to precede. Full sweep 473 of 473 on both solvers.
