# Enhancement-796: `altermod` and `alter` give an integer parameter what the card gives it — a warning when they round, -2.5 to -3, and a refusal for a value no integer holds

**Scope:** D1 of the
[ngspice + OSDI hunt of 2026-10-08](../docs/bug_hunts/2026-10-08_ngspice-osdi-hierarchy-sweeps-events-and-outputs.md).
ngspice:
- `frontend/spiceif.c`: `doset_user` (the wrapper every user write goes through) checks an
  integer value before it is applied; `doset` rounds an integer half away from zero.

`examples/osdislips_examples/` (new, section [1], six checks). **ngspice only.**

**Suites:** [`osdislips_examples`](../examples/osdislips_examples/) 56 of 56 per solver (5 of the
6 in [1] fail on the E-795 binaries); the full sweep, 538 of 538.

## What was wrong

A non-integral value for an integer parameter is rounded, by LRM 3.4.1's rule, and the card says
so:

```
.model ipm ip n=2.6
Warning: .model ipm: parameter (n) is an integer; the given non-integral value was rounded to the nearest integer.
```

The same value written by `altermod ipm n=3.7` or `alter n1 k=2.6` was rounded without a word.
The two routes also disagreed on more than the message:

| value | `.model` card | `altermod` / `alter` |
|---|---|---|
| 3.7 | 4, warned | 4, silent |
| -2.5 | -3 (half away from zero, E-399) | -2 (`floor(x + 0.5)`) |
| 1e300, 3e9 | refused, "does not fit an integer parameter" (E-509) | 2147483647, silent |

The last row is E-509's case: the saturated value can even pass a `from [0:2147483647]` range
check.

## The change

`doset_user` checks every element of an integer write (a scalar, or each entry of an integer
vector):

- A value whose rounding falls outside the `int` range is refused, and the parameter keeps its
  value:
  ```
  Error: value 1e+300 for integer parameter 'n' does not fit an integer; not applied.
  ```
- A non-integral one is applied rounded, with the value and the result named:
  ```
  Warning: model ipm: parameter (n) is an integer; the given non-integral value 3.7 was rounded to 4.
  Warning: n1: parameter (k) is an integer; the given non-integral value 2.6 was rounded to 3.
  ```

`doset` now rounds an integer with `round()`, as the card does since E-399, so -2.5 is -3 on both
routes. A flag keeps `floor(x + 0.5)`. The sweep machinery's per-point writes go through `doset`
directly, so they round the same way. They say nothing: a `dc` sweep of an integer parameter
already refuses a fractional step.

## The checks

osdislips [1]:

- `altermod ipm n=3.7`: the warning, and `@ipm[n]` is 4;
- `alter n1 k=2.6`: the warning naming n1, and k is 3;
- -2.5 gives -3 from `altermod` and from the card;
- `altermod ipm n=1e300` and `alter n1 k=3e9` are refused, and the old value stays;
- an integral value says nothing.

## Limits

- A wildcard write (`altermod @*:ipm[n]=3.7`) warns once per copy it reaches, as the
  non-finite-value refusal of the same wrapper does.
