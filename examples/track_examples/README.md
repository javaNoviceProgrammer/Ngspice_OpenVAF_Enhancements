# track_examples — `track`: every place a condition holds, as a plot

Enhancement-577, the implementation of `docs/proposals/2026-09-06_track-command.md`
with one extension: the command takes one or more expressions, one spec drives them
all, and each gets a vector in the plot.

```
track <expr> [<expr> ...] [-range x0 x1] [-spec <spec>] [-analysis <plot|type>]
      [-which all|first|last|N|-N] [-edge rise|fall|both] [-at entry|exit|mid]
      [-prominence p] [-raw] [-output name ...]
```

`track` is a vector-valued `meas`: the spec — a locator (`localmax`, `localmin`,
`globalmax`, `globalmin`, bare or on an expression), a crossing `lhs==rhs`, a region
`lhs<rhs`, or any boolean — becomes the set of x positions where it holds; every
expression is read there; both go into a plot `trackN` whose scale is named and typed
after the source scale. The locators are also `let` functions returning the positions.

| section | what it pins |
|---|---|
| [1] a sine's maxima | positions at (k+¼)T, `-range`, `-which -1`, `-raw` against the parabola-refined value, `let localmax(v(a))`, `print track1.time[2]` from another plot |
| [2] crossings | an RC step at τ·ln 2, a square wave's rise and fall counts, `-edge both` writing `edge` |
| [3] regions | `v(b)<=-1.0` on an amplitude-2 sine: width exactly T/3 with interpolated boundaries, `-at mid` reading −2; a boolean spec with sample-midpoint boundaries, said so |
| [4] several expressions | `value1..value3` under one spec, `-output pk vb` naming them, the summary's mapping line |
| [5] prominence, plateaus | a rippled sine: raw count far above the periods, `-prominence 0.1` one maximum and one minimum per period; a clipped sine: one maximum per plateau at its midpoint |
| [6] ac | `db(v(out))==-3.01` at the RC corner within 0.1 % through log-x interpolation; a complex spec refused with the `mag()` hint |
| [7] analysis and sweeps | `-analysis tran1` and `-analysis tran` while `ac1` is current, a wrong name listing the plots, `plot_cur` unchanged, a descending dc sweep with `-range` either way |
| [8] refusals | zero hits (no plot, `track failed!`), `-which` out of range, an unknown option, a locator on two samples, `-edge`/`-at`/`-prominence` on the wrong spec kind, a nested dc sweep; `define` composing; an unquoted `<=` spec parsing |
| [9] `$track_plot` and `$track_hits` (E-581) | six seeded trials of a ringing RLC with a prominence that makes some miss: both variables follow every trial, a hit names its `track` plot and a miss leaves an empty name and 0, the loop collects its counts through `$track_hits` with no plot-number drift, and a refusal after the loop leaves both cleared |

## Run

```
python3 verify_track.py
```

40 checks per solver, all PASS.
