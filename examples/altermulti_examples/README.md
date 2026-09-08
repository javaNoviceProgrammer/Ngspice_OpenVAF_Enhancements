# altermulti_examples — every `alter`/`altermod` pair applies (Enhancement-586)

```
python3 verify_altermulti.py
```

14 checks, both solvers.

## The need

`alter n1 ga=5m gb=6m` set `ga` and silently left `gb` alone; `altermod mm
ma=3 mb=4` set `ma` only; built-in devices did the same (`alter r1 r=2k
temp=50` left `temp` at 27, `altermod dm is=2e-14 n=1.5` left `n` at 1). The
worker split the first word carrying `=` and read everything after the value
as more value; its "only a single param-value pair supported" error lived on
the legacy `=`-less path and never fired for `a=1 b=2`.

## What changed

- The front end counts the assignments and hands the one-pair worker one
  `<target> name = value` list per pair, each with its own journal bracket.
  The target is the leading device or model name and is repeated for every
  pair; a pair written `@dev[param]=value` carries its own. One pair,
  `alter dev = value`, `[ ... ]` vector values and the legacy form are untouched.
- `altermod mm mode=quad` — a bare word for a **string** parameter — said
  "no such vector quad". A bare identifier is now tried on the string setter
  first; it reports "not string-typed" for a numeric parameter and the numeric
  path then runs exactly as before.
- A `$fatal` during the operating point printed its own clear message and then
  the stock "doAnalyses: impossible error - can't occur"; the stock line is
  skipped when the cause has already been named.

```spice
alter n1 ga=5m gb=6m
altermod mm ma=3 mb=4 mode="quad"
alter r1 r=2k temp=50
altermod mm mode=quad
```
