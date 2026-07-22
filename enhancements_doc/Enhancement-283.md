# Enhancement-283 — ngspice: plot coordinate math no longer casts a non-finite double to `int`

The extreme-data output fuzz (the campaign that produced Enhancement-282) found three
more sites where a plot coordinate is computed through `mylog10()` — whose result is
`±inf` for zero, denormal or overflowed values — or through a division by a range that
can be zero, and then cast to `int`. That cast is undefined behaviour.

## The bug

All three are reached by ordinary plot commands on pathological data:

- **`agraf.c`** — the decade `mag = (int) floor(mylog10(...))`. Data that overflows
  (`-1e308 * 6` → `-inf`, so `-ylims[0]` is `+inf`), or is zero/denormal, makes the
  argument non-finite. The limits `lmt`/`hmt` = `(int) floor(ylims[0] / tenpowmag)`
  are equally exposed, since `tenpowmag = pow(10, mag)` can itself be `0` or `inf`.
- **`points.c`** — `ft_findpoint()` returns
  `(int)(((mylog10(pt) - tl) / (th - tl)) * (maxp - minp) + minp)`. For a degenerate
  range (`lims[0] == lims[1]`, or log endpoints sharing a decade) that is `0/0`.
- **`display.c`** — the four screen-coordinate casts (log and linear, x and y), e.g.
  `(int)((mylog10(y) - low) / (high - low) * height + …)`, with the same two failure
  modes.

## Fix

Per-site clamping, chosen so the result stays meaningful rather than merely defined:

- `agraf.c` — `agraf_decade()` bounds the exponent by `DBL_MAX_10_EXP` (the widest
  decade a `double` can represent) and maps `NaN` to 0; `agraf_int()` clamps the
  `lmt`/`hmt` ratios into `int` range.
- `points.c` — the fraction is computed in `double`, a `NaN` (degenerate range) maps
  to 0, and it is clamped to `[0, 1]` before scaling, so the result always lands in
  `[minp, maxp]`.
- `display.c` — `disp_clamp_coord()` clamps each coordinate into the viewport,
  mapping `NaN` to the low edge.

## Verification

`examples/plotcoord_examples/verify_plotcoord.py` (5 checks): `asciiplot` of
overflowing (`-1e308`), denormal, and all-zero data, and a min/max over denormal data,
are each clean where they previously invoked UB; and an ordinary `asciiplot v(b)` still
renders. Rendering was additionally diffed against the pre-fix binary and is
**byte-identical** for ordinary data.

## Scope

Three source files (`agraf.c`, `points.c`, `display.c`), guard-only. No change to any
rendered plot.
