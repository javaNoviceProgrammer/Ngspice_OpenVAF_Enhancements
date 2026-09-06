# Proposal — a `track` command: every place a condition holds, as a plot

*Written 2026-09-06, after Enhancement 565 and the `$port_connected` suite. Status:
proposal, not implemented. Everything below describes the tree as it stands at commit
5c81fedd.*

## The question

Add a post-processing command of the form

```
track <expr> -range x0 x1 -spec <spec> -analysis <analysis>
```

where `x0`/`x1` are values on the x-axis of the named analysis, `<spec>` is one of the
locators `localmin`, `localmax`, `globalmin`, `globalmax` or a user-written condition such
as `v(a)==2.0` or `v(b)<=-1.0`, the locators are also usable as functions on any
user-defined expression, a spec that matches several places in the range is handled
rather than being an error, and every call puts its result into a plot of its own,
`track1`, `track2`, …

## What exists, and what it lacks

* **`meas` returns one number.** `find`/`when` picks a single crossing chosen by
  `rise=`, `fall=`, `cross=` or `last` (the `riseCnt`/`fallCnt`/`crossCnt` walk in
  `ngspice-46/src/frontend/com_measure2.c`), interpolated between the two bracketing
  samples by `measure_interpolate`; the AC-margin path (E-203) interpolates in log
  frequency. `min`/`max`/`pp`/`avg`/`rms`/`integ`/`deriv` reduce a `[from,to]` window
  to one scalar. There is no "all crossings", no local extremum of any kind, and `when`
  accepts only `=`. Its contract — one scalar, `meas … failed!` and no stale value on
  failure (E-475) — is what hundreds of scripts test, which is the reason not to bolt
  vectors onto it.
* **`let` has no locators.** The vector-function table `ft_funcs` in
  `frontend/parse.c` (`interpolate`, `deriv`, `integ`, `group_delay`, `fft`, …) is
  applied by `apply_func_funcall` in `frontend/evaluate.c`; a short name list there gets
  the scale-aware calling convention (`v->v_plot`, `plot_cur`, `v_dims[0]`) and any
  function may return a vector of a different length. Nothing in the table finds an
  extremum or a crossing. Functions are unary: the evaluator has no two-argument
  function path.
* **Selecting by scale value exists.** `expr[[x0,x1]]` (`op_range`, `evaluate.c`) keeps
  the samples whose scale lies in the interval and ignores multi-dimensionality.
* **The option style exists.** E-146's `sweep` already takes `-analysis` and `-output`;
  `pyplot` takes `-hist`, `-fft`, `-bode`, … . A dash-option command is house style.
* **The own-plot pattern exists.** `fft`/`spec` (`frontend/com_fft.c`) do
  `plot_alloc("spectrum")`, `plot_new` (E-345's single insertion point), copy the source
  title, set `pl_name`, `vec_new` each result, and switch `plot_cur` to the new plot.
  `plot_alloc` (`frontend/vectors.c`) numbers plots through the abbreviation table in
  `frontend/typesdef.c`; a name missing from that table comes out as `unknown1`, the
  lesson `sweep` taught (E-146) and `hbosc` repeated (E-487).
* **Cross-plot references exist.** `tran1.v(a)` is resolved in `vec_get`
  (`frontend/vectors.c`) by a typename-prefix search over `plot_list`; `meas` refuses a
  named analysis that does not match the current plot (`frontend/measure.c`).
* **Three hazards are already in the tree.**
  `<` and `>` on a control line are I/O redirection unless the command is in the
  `noredirect[]` list of `frontend/control.c` (`stop`, `define`, `circbyline`), so an
  unquoted `v(b)<=-1.0` never reaches the command. The comparison operators on complex
  vectors (`cx_eq`, `cx_gt`, … in `maths/cmaths/cmath3.c`) compare real *and*
  imaginary parts, so `v(out)>1` on an AC vector is not a magnitude test. And the names
  `cross` (gather the n-th element of several vectors, `frontend/postcoms.c`), `where`
  (convergence-failure locator) and `find` (a `meas` keyword) are taken; `trace` exists
  but command matching is exact, so `track` is free.
* **`define` composes.** User functions are substituted at parse time (`ft_substdef`,
  after the built-in table is searched), so any new built-in accepts them as arguments —
  and shadows a user function of the same name.

## The design

**Principle.** `track` is a *vector-valued `meas`*: it turns a spec into a set of hits
on the x-axis, reads the tracked expression there, and packages both into a plot. The
locators are ordinary `let` functions first, so they are useful without the command; the
command adds the range, the analysis, the crossings and regions, the multi-hit policy
and the plot.

### Grammar

```
track <expr> [-range x0 x1] [-spec <spec>] [-analysis <plot|type>]
      [-which all|first|last|N|-N] [-edge rise|fall|both] [-at entry|exit|mid]
      [-prominence p] [-raw] [-output name]
```

`<expr>` is any expression the plot can evaluate. Words after `-spec` up to the next
`-option` are joined, so `v(a) == 2.0` with spaces works as well as `v(a)==2.0`.

### The locators (stage 1, no command needed)

`localmin(e)`, `localmax(e)`, `globalmin(e)`, `globalmax(e)` join `ft_funcs` and the
scale-aware name list in `apply_func_funcall`. Each returns the **x positions** of its
hits as a real vector — typed like the source scale (`SV_TIME`, `SV_FREQUENCY`,
`SV_VOLTAGE`), so `plot` and `print` label them correctly — of length equal to the number
of hits; zero hits gives a zero-length vector and a message, not an error.

* A local maximum at sample `i` is `y[i-1] < y[i] >= y[i+1]` with the plateau rule: a
  run of equal samples bounded by strictly lower ones on both sides is *one* maximum,
  reported at the plateau's x midpoint. The first and last samples are never extrema.
  Minimum symmetric.
* `globalmax`/`globalmin` report every sample tied for the extreme value, which is
  normally one.
* Unary only, because the evaluator's function path is unary: prominence and
  refinement live in `track`. A `let` user filters by hand.

### Specs

| spec | meaning | x of a hit |
|---|---|---|
| *(none)* | every sample in the range — `track` as a crop into its own plot | the sample |
| `localmin` … `globalmax` | applied to `<expr>` itself | see below |
| `localmax(e2)` … | applied to another expression; `<expr>` is read at the hits | see below |
| `lhs==rhs` | a **crossing**: `d = lhs - rhs` changes sign between samples `i-1` and `i`, or is exactly zero | linear interpolation of `d`'s zero; log-x when the plot's scale carries a log grid type (AC decades), the E-203 rule |
| `lhs<rhs`, `<=`, `>`, `>=` | a **region**: a maximal run of samples where it holds | entry and exit interpolated from `d`'s crossing of zero, like `==` |
| anything else (`&`, `\|`, `~`, function-wrapped) | a region from the boolean 0/1 vector `ft_evaluate` returns | entry and exit at the midpoint between the last false and first true sample; the summary line says so |

`track` splits the top-level comparison operator itself before evaluation, so `==`
means *crossing* here rather than the evaluator's exact equality, and a single-comparison
region gets interpolated boundaries. `-edge` filters crossings by the sign of the change
(default `both`, and an `edge` vector of +1/−1 is written when both are kept). `-at`
chooses where `<expr>` is read inside a region (default `entry`); `x_out` and `width`
are always written for regions.

**Extrema on sampled data.** By default a local extremum is refined with the parabola
through samples `i-1, i, i+1`, giving x and y between samples — the same courtesy
crossings already get from interpolation. `-raw` reports the sample. Plateaus are never
refined.

**Prominence.** Real transient data carries sample-to-sample ripple, so a raw
`localmax` on a waveform returns hundreds of spurious peaks. `-prominence p` (y units,
default 0) applies the hysteresis rule: walking the range, a candidate maximum is
confirmed only once the signal has fallen `p` below it, a candidate minimum once it has
risen `p` above it. Order-N, deterministic, and it merges noise into the peak it rides
on rather than dropping small genuine peaks arbitrarily.

**Complex values.** If `<expr>`, `d`, or the boolean spec evaluates complex, `track`
refuses: *"the spec is complex-valued; wrap it in mag(), db(), ph() or real()"*. No
hidden magnitude default — an AC spec must say what it compares.

### Range and analysis

* `-range x0 x1` is inclusive, in the scale's units, with engineering suffixes
  (`1u 30u`), either order (a descending DC sweep). The search runs over the samples
  inside the interval **plus one bracketing sample on each side**, so a crossing whose
  interpolated x lies just inside the range is found even when its bracketing sample
  lies outside. Default: the whole axis.
* `-analysis` names a plot (`tran2`) or a type (`tran`, `ac`, `dc`, `sp`, `sweep` — any
  typename prefix, the `vec_get` rule), meaning the most recent plot of that type;
  default is the current plot. `<expr>` and the spec are evaluated in that plot by
  swapping `plot_cur` for the duration and restoring it on every exit path. A name that
  matches nothing is a refusal that lists the plots there are.
* Multi-dimensional vectors (a nested `dc` sweep, `v_numdims > 1`) are refused in the
  first version with a pointer to the per-point plots `sweep` keeps (E-146). A later
  stage tracks each segment separately and adds a `run` vector.

### Multiple hits

Several hits are the normal case, not the exception. Default `-which all`, ordered by x;
`first`/`last`/`N`/`-N` (1-based, negative from the end) select one, and an out-of-range
selector is a failure, not a silent clamp. A single hit is a plot of length one; nothing
about the output shape depends on the count.

### Output

* A new plot from `plot_alloc("track")` — with a `{ "track", "track" }` entry added to
  the abbreviation table in `typesdef.c` so the plots are `track1`, `track2`, … .
  `pl_title` is copied from the source plot; `pl_name` is `Track: <spec> on <typename>`;
  `pl_date` is stamped by `plot_alloc` (E-371).
* Vectors: the **scale**, named and typed after the source scale (`time`, `frequency`,
  `v-sweep`) and installed as `pl_scale`, so `plot track1.value` draws against time and
  a `meas tran` on the track plot is meaningful; **`value`** (or the `-output` name,
  `sweep`'s clean-name trick) holding `<expr>` at the hits; **`index`**, the bracketing
  sample index; for regions **`x_out`** and **`width`**; for `-edge both` the
  **`edge`** vector.
* `plot_cur` is **not** switched to the new plot — unlike `fft` — because the next line
  of a script is usually another `track` or a `meas` on the same analysis. The command
  prints one summary line, `track1: 3 hits of v(out)==1.2 on tran1 in [0, 5e-06]`, and in
  batch mode one row per hit, so a log can be grepped the way `meas` output is.
* **Zero hits creates no plot** and prints `track failed!` — E-475's rule: a failed
  measurement leaves nothing stale behind for the next read.

### Redirection

`track` joins `noredirect[]` in `frontend/control.c` beside `define`, so `-spec
v(b)<=-1.0` is parsed as an expression and not as an input redirection. A quoted spec
works too. The cost, as for `define`, is that `track … > file` no longer redirects;
`set` or `wrdata` cover that.

### Refusals

No current plot or no scale; `<expr>` or the spec not evaluable in the chosen plot; a
spec of a different length than the scale; a complex-valued spec; an unknown `-option`;
a non-numeric `-range`; `-which` out of range; `-analysis` matching no plot; a
multi-dimensional vector (first version); a locator on a vector shorter than three
samples; `-edge`/`-at` given for a spec kind they do not apply to. Every refusal ends in
`track failed!` so the same test a script has for `meas` works here.

### Alternatives considered

* **Extend `meas` with `cross=all`.** Breaks the one-scalar contract that E-475 and every
  script rely on; a second output shape inside one command is worse than a second
  command.
* **Locator functions only, no command.** Covers the extrema, but not crossings,
  regions, the range, the analysis, or the packaging; users would rebuild `track` by
  hand in every script.
* **Calling it `where`, `find` or `cross`.** All taken.
* **A `.track` netlist card.** `.meas` has one because it predates control blocks; a
  `.control` line suffices here, and the card can be added later if a batch flow wants
  it.

## Verification to pin (the suite)

* A transient sine: `localmax` positions at `(k + 1/4)·T` within interpolation error,
  the count equal to the periods in `-range`, `-which -1` the last one, `-raw` the
  sample and the refined value closer to the amplitude than the sample.
* An RC step with `v(out)==0.5`: one hit at `τ·ln 2`; a square wave with `-edge rise`
  and `-edge fall` giving the two counts; `-edge both` writing `edge`.
* A sine of amplitude 2 with `v(b)<=-1.0`: one region per period of width exactly
  `T/3`, `x_in` and `x_out` interpolated, `-at mid` reading `-2`.
* A compound spec `v(a)>0 & v(b)>0` giving sample-midpoint boundaries and the summary
  line saying so.
* The same sine plus small ripple: raw `localmax` count far above the period count,
  `-prominence` restoring exactly one per period; a clipped signal reporting one maximum
  per plateau at its midpoint.
* AC: `db(v(out))==-3` on an RC giving the corner frequency within 0.1 % through
  log-x interpolation; `v(out)>0.5` on the complex vector refused with the `mag()` hint.
* A descending DC sweep with `-range` given in either order.
* `-analysis tran1` while the current plot is an `ac` plot; a type prefix picking the
  latest plot; a wrong name refused with the list; `plot_cur` unchanged afterwards.
* `define hp(x) x - 0.5` composed as `-spec localmax(hp(v(a)))`; a `let` of
  `localmax(v(a))` giving the same positions as the command.
* An unquoted `-spec v(b)<=-1.0` parsing (the `noredirect` entry).
* `print track2.value`, `plot track1.value` against time, a nested `dc` refused with the
  `sweep` pointer.
* Zero hits: `track failed!`, no plot created, the plot counter not advanced.
* Both solvers through `check_both_solvers`, as every suite does.

## Where the code goes

| side | files | work |
|---|---|---|
| ngspice, locators | `maths/cmaths/` beside `cx_interpolate`/`cx_deriv` (four functions plus the shared extremum walk with plateau handling); `frontend/parse.c` (`ft_funcs` entries); `frontend/evaluate.c` (the scale-aware name list in `apply_func_funcall`) | a few hundred lines |
| ngspice, command | new `frontend/com_track.c` (+ `.h`): option parsing, the spec splitter, crossing/region/extremum walks, prominence, refinement, plot assembly, summary and refusals; `frontend/commands.c` (both command tables) and `com_commands.h`; `frontend/Makefile.am`; `frontend/control.c` (`noredirect`); `frontend/typesdef.c` (the `track` entry) | somewhat more |
| compiler | none | |
| docs | handbook control-language chapter, `docs/change_log/ngspice_changes_full-report.md`, the enhancement doc, a new `examples/track_examples/` suite | |

It fits one enhancement in three steps, each testable on its own: the locator
functions with the plateau rule (usable from `let` at once); the command with crossings,
regions, the range, the analysis, `-which`, the plot, the summary lines and the
refusals; then multi-dimensional segments with a `run` vector.
