# plotcoord_examples — Enhancement-283

Plotting extreme data drives coordinate math through `mylog10()` (which returns
`+/-inf` for zero / denormal / overflowed values) and through divisions by a range
that can be zero, then casts the result to `int` -- undefined behaviour. Three sites,
all reached by ordinary plot commands:

- `agraf.c` -- the decade `(int) floor(mylog10(...))`, and the `lmt`/`hmt` limits
  `(int) floor(ylims[0] / tenpowmag)` (tenpowmag itself can be 0 or inf);
- `points.c` -- `ft_findpoint()`, whose fraction is `0/0` for a degenerate range;
- `display.c` -- the four screen-coordinate casts (log/linear, x/y).

Fix: bound the decade by `DBL_MAX_10_EXP`, sanitise + clamp the point fraction to
[0,1], and clamp screen coordinates into the viewport. Rendering for ordinary data is
byte-identical to before.

## Verify

```
python3 verify_plotcoord.py
```

Five checks: `asciiplot` of overflowing (-1e308), denormal and all-zero data, plus a
min/max over denormal data, are clean; an ordinary `asciiplot v(b)` still renders.
