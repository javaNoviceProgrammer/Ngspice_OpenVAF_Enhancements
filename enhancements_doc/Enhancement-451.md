# Enhancement-451 — an option matched by substring, and three that worked while being called unknown

Two findings in option handling, both turned up by asking the question
[Enhancement-450](Enhancement-450.md) had just answered for `savecurrents`:
*which other options are decided by searching the line for a word?*

## `seed=` and `cshunt=` were found by substring

`eval_opt()` located them with a bare `strstr` over the option line, so any
option whose **name merely ended in the watched text** was taken as that option:

```
.options seed=7        sunif -> 4.3854057230e-01     (correct)
.options myseed=7                4.3854057230e-01     identical
.options noseed=7                4.3854057230e-01     the spelling that reads "off"
.options xseed=7                 4.3854057230e-01
   baseline, no seed set:        6.8709117128e-01
```

For `cshunt` the answer moves by six orders of magnitude:

```
baseline                    v(b)[10] = 1.0000000000e+00
.options cshunt=1e-6                 = 6.9209970972e-07
.options nocshunt=1e-6               = 6.9209970972e-07
.options mycshunt=1e-6               = 6.9209970972e-07
.options xcshunt=1e-6                = 6.9209970972e-07
```

Each of these **also** prints `Warning: unknown option 'nocshunt'`, which makes
it worse rather than better: the user is told the option was not recognised, and
it changes the answer anyway. For a Monte Carlo run the `seed` case means a
mistyped option name silently changes the random sequence while being reported
as ignored.

The boundary test is [E-450](Enhancement-450.md)'s: the character before the
name must not be part of an identifier, so `seed` matches and `myseed`, `noseed`
and `xseed` do not. `seedinfo` is matched as a whole token too, so `noseedinfo`
no longer switches it on, and `seed=` no longer sees the `seed` inside it.

### One thing this is NOT

The loop reads `for (card = deck; ...)` with no `.options` test, which looks as
though any deck line carrying `seed=` would hijack the generator. It does not —
the function's own comment says *"Input is the option deck (already sorted for
.option)"*, and measurement agrees: a `.param seed=7`, a model parameter named
`seed`, and a comment containing `seed=` all leave the sequence at baseline.
Recorded because it is the first thing the code reads like.

## Three options took effect while being reported unknown

Asking which flagged names *demonstrably change a run*:

```
.options scale=2      @m1[w]     1e-6 -> 2e-6      Warning: unknown option 'scale'
.options rseries=100  v(out)[10] moves             Warning: unknown option 'rseries'
.options autostop     tran rows  567  -> 2         Warning: unknown option 'autostop'
```

`autostop` is the clearest: it truncates a transient to a fortieth of its length
while being reported as a name ngspice does not know.

This is the case [E-447](Enhancement-447.md) fixed for `savecurrents`, `seed`
and `numdgt`, with three names it did not cover, and its reasoning applies
unchanged — a warning that fires on a setting the run then honours teaches the
user to ignore the check [E-438](Enhancement-438.md) added. `scale` and
`rseries` are read out of the deck's own option cards (`scale` by `inp.c` before
subcircuit expansion, `rseries` by `inp_add_series_resistor()`), so like `seed`
they never reach the `.options` parameter table the check consults.

**`scalm` is flagged too and is deliberately not registered.** It could not be
shown to change anything here, and this list is for options that demonstrably
take effect — adding a name on the strength of it appearing in the source would
be the same mistake in the other direction.

## Verification

**`examples/optname_examples` — 24/24, both solvers**, and **14/24 on the
previous binary**: the ten checks that fail there are exactly the defect-specific
ones, while every control passes on both.

* the option itself still applies — `seed=7`, `cshunt=1e-6`, the word beside
  other options on one line, and `seedinfo seed=7` still reporting the seed
* `my`/`no`/`x` prefixed forms of both leave the baseline untouched, and
  `noseedinfo seed=7` no longer reports
* `scale`, `rseries`, `autostop`, `savecurrents`, `seed`, `numdgt` are not
  flagged unknown
* a genuinely unknown name still is — `notanoption`, `bogusxyz`, and
  `myseed=7`, which must now be reported precisely because it no longer applies
* the two registered names that are easy to check really do move a run:
  `scale=2` doubles `@m1[w]`, `autostop` truncates 567 rows to 2

**Full regression 364/364**, both solvers.
