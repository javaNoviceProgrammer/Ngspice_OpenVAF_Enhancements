# Enhancement-182 — pyplot: autoscale by default, pin axes only for explicit user limits

A user-experience refinement of the [E-94](Enhancement-94.md)/[95](Enhancement-95.md)/[98](Enhancement-98.md)/[99](Enhancement-99.md) `pyplot` matplotlib bridge: the generated script used to pin every axis with `set_xlim`/`set_ylim` taken from ngspice's internal plot machinery — grid-rounded ranges computed for ngspice's own renderer. Matplotlib frames data better on its own: the generated script now **relies on matplotlib's autoscaling plus `fig.tight_layout()`**, and emits `set_xlim`/`set_ylim` **only when the user explicitly asked for limits** (`xl`/`xlimit`, `yl`/`ylimit` on the command).

## The change

`plotit()` always fills its `xlims[]`/`ylims[]` arrays — from the user's `xlimit`/`ylimit` arguments when given, else from the data — so the back-end could not previously distinguish the two cases. The user-given case is exactly when the static `xlim`/`ylim` pointers (from `getlims`) are non-NULL; those statics are freed *before* the device dispatch, so `plotit` now captures `user_xlim`/`user_ylim` flags at that point and passes `NULL` limits to `ft_pyplot` unless the user provided them. `ft_pyplot` already handled NULL limits; the gnuplot and asciiplot back-ends are untouched.

```
pyplot rc v(out) v(in)                              -> autoscale + tight_layout
pyplot rc v(out) v(in) xlimit 0 1m ylimit -1 1      -> set_xlim(0, 1e-3), set_ylim(-1, 1)
```

## Verification

[`examples/pyplot_examples/verify_pyplot.py`](../examples/pyplot_examples/verify_pyplot.py) gains two checks (9 total × both solvers): the auto plot's script contains no `set_xlim`/`set_ylim` and keeps `tight_layout`; an explicit `xlimit 0 1m ylimit -1 1` command still emits both pins with the exact values and renders a valid PNG. The panel (E-98) and export (E-99) suites pass unchanged. Full example regression: 149/149.
