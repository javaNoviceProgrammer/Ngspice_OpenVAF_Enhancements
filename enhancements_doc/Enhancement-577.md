# Enhancement-577: `track` — every place a condition holds, as a plot; one spec over one or more expressions

**Scope:** the implementation of the proposal in
[`docs/proposals/2026-09-06_track-command.md`](../docs/proposals/2026-09-06_track-command.md),
with one extension asked for at implementation time: the command takes one or more
expressions, one spec drives them all, and each gets a vector in the plot. New
`src/frontend/com_track.c` and `.h`; `src/maths/cmaths/cmath4.c` (the four locator
functions and their shared walk), `src/include/ngspice/fteext.h`, `src/frontend/parse.c`
(the function table), `evaluate.c` (the scale-aware call and the result's typing),
`commands.c`, `com_commands.h`, `control.c` (`noredirect`), `typesdef.c` (the plot
name), `frontend/Makefile.am`. **ngspice only.**

**Suites:** new [`track_examples`](../examples/track_examples/) (36 checks per solver,
both solvers); full sweep 476 of 476 on both solvers.

## What it does

```
track <expr> [<expr> ...] [-range x0 x1] [-spec <spec>] [-analysis <plot|type>]
      [-which all|first|last|N|-N] [-edge rise|fall|both] [-at entry|exit|mid]
      [-prominence p] [-raw] [-output name ...]
```

`track` is a vector-valued `meas`. The spec becomes the set of x positions where it
holds; every expression is read there; both go into a plot `trackN` of its own whose
scale is named and typed after the source scale, so `plot track1.value` draws against
time and a `meas` on the track plot is meaningful. `plot_cur` is not switched: the next
line of a script is usually another `track` or a `meas` on the same analysis. The
command prints one summary line, `track1: 5 hits of localmax on tran1 (applied to
v(a))`, and in batch mode one row per hit, capped at fifty, so a log can be grepped the
way `meas` output is. Zero hits creates no plot and prints `track failed!` —
[E-475](Enhancement-475.md)'s rule: a failed measurement leaves nothing stale behind.

| spec | what a hit is | x of the hit |
|---|---|---|
| *(none)* | every sample in the range — a crop into its own plot | the sample |
| `localmin`, `localmax`, `globalmin`, `globalmax` | an extremum of the **first** expression | the parabola through the three samples, unless `-raw`; a plateau's midpoint |
| `localmax(e2)` … | an extremum of `e2`; the expressions are read there | as above |
| `lhs==rhs` | a crossing: `d = lhs - rhs` changes sign, or is exactly zero | linear interpolation of `d`'s zero, in log x on a log grid (an ac decade sweep) |
| `lhs<rhs`, `<=`, `>`, `>=` | a region: a maximal run of samples where it holds | entry and exit interpolated like a crossing; `x_out` and `width` are written; `-at` picks where the expressions are read |
| anything else (`&`, `\|`, `~`, `!=`, two comparisons) | a region from the boolean vector the evaluator returns | entry and exit at sample midpoints, and the summary says so |

**Several expressions.** Every word before the first `-option` is an expression; quote
one that contains spaces. With one expression its vector is `value`; with several,
`value1`…`valueN`, in order; `-output a b c` names them instead, and fewer names than
expressions leaves the rest at their defaults. The summary carries the mapping,
`value1=v(a) value2=v(b) value3=v(s)`. A bare locator applies to the first expression,
and the summary says `(applied to v(a))`; a locator on another expression,
`localmax(v(a))`, is read on every expression at those positions.

**The locators are `let` functions first.** `localmax(v(a))` returns the x positions
of the maxima as a vector typed like the plot's scale; `globalmax` reports every sample
tied for the extreme value. A local maximum is `y[i-1] < y[i] >= y[i+1]` with the
plateau rule — a run of equal samples bounded by strictly lower ones on both sides is
one maximum, at the plateau's midpoint — and the first and last samples are never
extrema.

**Prominence.** A raw `localmax` on a waveform with sample-to-sample ripple returns
every ripple peak: fifty-one on a 1 kHz sine over three periods with 1 % ripple.
`-prominence p` applies the alternating hysteresis rule: walking the range, a candidate
of the wanted kind opens only once the signal has moved `p` away from the running
extremum of the other kind, and is confirmed only once the signal has moved `p` past it
again. Order N, deterministic, one maximum and one minimum per period on that sine. The
first version compared each ripple peak with the next candidate only, which confirmed
every peak on a descending flank by the drop to the trough; the alternating walk is what
the rule has to be.

## What was found on the way

* **The lexer splits the spec.** `<` and `>` are redirection characters everywhere
  else, so the lexer hands them over as words of their own, and `v(b)<=-1.0` arrives in
  pieces. The spec's words are joined *without* spaces — an expression needs none —
  and `track` is in `control.c`'s `noredirect` list so the pieces reach the command at
  all.
* **A quoted expression keeps its quotes.** The lexer hands `"v(a) * v(b)"` over as
  one word *with* the quote characters on it, which the evaluator cannot parse; the
  command strips a matching pair. Every other form — a `let` vector, an inline
  expression without spaces, functions, a `define`d function, a current, a cross-plot
  reference — evaluates as it would in `let`, on both the tracked expressions and the
  spec.
* **`ft_numparse` advances the pointer it is given.** Handing it the wordlist's own
  word for `-range` and `-prominence` moved that word's pointer into its middle, and
  the wordlist was freed from there after the command: a `pointer being freed was not
  allocated` abort on the first deck with a range. The command hands it a copy.
* **An ac plot's scale is complex.** `frequency` is stored as a complex vector with
  zero imaginary parts; the command takes the real parts and refuses only a scale
  whose imaginary parts are not all zero.
* **A nested dc sweep is one vector.** ngspice does not mark it multi-dimensional; its
  scale restarts at every outer step, so a scale that turns back on itself is the sign,
  and the refusal points at the per-point plots `sweep` keeps ([E-146](Enhancement-146.md)).
* **`track` is inside `ac`.** The plot-name table matches substrings, first match wins,
  and `{ "ac", "ac" }` sat before the new entry: the first track plot came out as
  `ac1`. The entry goes above the `ac` pair, with the reason beside it.

## Verification

[`track_examples`](../examples/track_examples/) — 36 checks per solver:

| section | checks |
|---|---|
| [1] a sine's maxima | positions at (k+¼)T within 1e-7 s, the refined value 1 within 1e-5; `-range` keeps three; `-which -1` the last; `-raw` below the refined value; `let localmax(v(a))` the same positions; `print track1.time[2]` from another plot |
| [2] crossings | an RC step at τ·ln 2 within 2 µs; five rising and five falling edges; `edge` = +1, −1, +1 |
| [3] regions | five regions of width T/3 within 0.2 µs with interpolated boundaries, `-at mid` reading −2; a boolean spec with the midpoint note |
| [4] several expressions, expression forms | `value1..value3` = 1, 2, 1 at the maxima; the mapping line; `-output pk vb`; a `let` vector, an inline and a quoted expression tracking alike; `deriv(v(a))==0` read on two expressions |
| [5] prominence, plateaus | raw count above thirty; one maximum and one minimum per period under `-prominence 0.1`; one maximum per plateau at its midpoint, value 0.5 |
| [6] ac | the RC corner at 1000 Hz within 1 Hz through log-x interpolation; the complex refusal with the `mag()` hint |
| [7] analysis, sweeps | `-analysis tran1` and `tran` while `ac1` is current; a wrong name lists the plots; `plot_cur` still `ac1`; a descending sweep with `-range` either way |
| [8] refusals, parsing | zero hits with no plot; `-which 9`; an unknown option; the three option-kind refusals; `define` composing; a two-sample locator; a nested dc; eight `track failed!` lines in all |

Full sweep 476 of 476 on both solvers.
