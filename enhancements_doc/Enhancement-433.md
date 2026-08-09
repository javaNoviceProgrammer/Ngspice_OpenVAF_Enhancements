# Enhancement-433 — two spellings that worked everywhere except in one place

Two independent fixes with one shape: a thing that is written one way throughout
ngspice, and written another way — or not accepted at all — by a handful of
commands. Both were found by answering a question rather than by hunting.

```
sweep ... -analysis "tran 1n 20n"   ->  sweep: unknown command '"tran 1n 20n"'
wcd -metric v(d) -analysis tran 1n 20n
                                    ->  wcd: unknown option '1n'
montecarlo 2 -analysis disto lin 3 1e5 1e6 -0.5 ...
                                    ->  montecarlo: unexpected token '-0.5'
altermod @x1.rmod[res]=3000         ->  Error: no such device or model name x1.rmod
```

## Part 1 — quoting

ngspice's lexer treats the two quote characters differently, and says so in its
own comments (`parser/lexical.c`):

* `'...'` — *"read until next `'` is hit, will form a new word, **but without the
  `'`**"*. The quote characters go to the echo buffer and never into the word.
* `"..."` and `` `...` `` — *"will form a new word, **including the quotes**"*.
  `push(&buf, d)` runs before and after the loop.

A surviving double quote is not an oversight, it is the contract: the command is
expected to strip it with `cp_unquote()`, which removes exactly one enclosing
pair. Around seventeen frontend files call it — `com_echo.c` among them, which is
why `echo "a b"` and `echo 'a b'` print identically.

`com_sweep.c` and `com_optimize.c` called it **zero times**. So a double-quoted
argument arrived with its quotes attached and the command-name lookup failed on a
name no command has, while the single-quoted spelling worked. For `-output` the
residue was worse than an error: `-output "v(d)"` recorded a vector literally
*named* with quotes, and `-output "gain=v(d)"` split at the wrong `=` so nothing
resolved.

Tokens are unquoted **individually**, not after joining. Stripping one outer pair
from the joined `"tran" "1n" "20n"` would eat the wrong two characters.

### The same flag, three collectors

Five commands document `-analysis <cmd>` identically and collected it three
different ways. They now all use `is_flag()`:

| | before | after |
|---|---|---|
| `sweep`, `optimize` | `collect_until_flag()` | unchanged, plus unquoting |
| `montecarlo`, `highsigma` | stop at **any** leading `-` | `is_flag()` |
| `wcd` | `strncpy` of **one** token | the same collector as its siblings |

`is_flag()` is `-` *followed by a letter*, so an analysis argument that is
legitimately negative survives — `disto lin 3 1e5 1e6 -0.5` ended the list under
the old test and came back as an unexpected token. `wcd` was the only command
that *required* quoting, since it kept `tran` and rejected `1n`.

This is the same distinction Enhancement-432 had to draw for the `-output`
terminator, for the same reason: `-v(d)` and `-0.5` are values, not flags.

## Part 2 — a subcircuit-local `.model`

`modtranslate()` in `subckt.c` renames a model declared inside a subcircuit with
`tprintf("%s:%s", scname, model_name)`, where `scname` is the instance path. So a
model in `x1` becomes `x1:rmod`, and one in `x1/x2` becomes `x1.x2:rmod` — levels
joined with `.`, the model attached with `:`.

Nothing else in the hierarchy is spelled that way. Devices are `@x1.rx[p]`
(Enhancement-410) and nodes are `v(x1.mid)`, so the natural `@x1.rmod[res]` was
refused and the colon had to be discovered by reading the expansion code.

`if_find_model_hier()` maps the dotted spelling onto the real one by turning the
**last** `.` into `:` — exactly the instance-path/model boundary, at any nesting
depth. It is wired into both name funnels (`finddev`, `finddev_special`) *after*
the exact lookups and after Enhancement-410's instance fallback, so the rule can
only turn a former error into a hit; nothing that resolves today changes. A name
that already contains `:` is skipped, having been covered by the exact lookup.

Because all three paths resolve through those funnels, one fallback reaches
`altermod`, `optimize -mparam`, and `@`-readback together.

## Verification

* **`examples/sweepguard_examples` — 35/35** (was 23). All five commands × bare /
  single-quoted / double-quoted, plus the negative-argument case, plus `-output`
  in both quoted forms.
* **`examples/hierdev_examples` — 38/38** (was 32). The dotted model spelling
  resolves to the same model as the colon one, `altermod` drives it and the
  circuit follows (`v(out)` 0.5 → 0.25), `optimize -mparam` finds `res=3000`.
* **Both sets are positive-controlled.** With the sources reverted and rebuilt, 9
  of 12 quoting checks and 3 of 6 model checks fail. The ones that still pass are
  the deliberate no-regression controls — the bare and single-quoted spellings,
  the colon spelling, a nonexistent model, and a hierarchical *device*, which
  must keep resolving as a device rather than being captured by the new rule.
* **Full regression 345/345**, both solvers.

## Found by

Two questions, neither of them a bug report.

*"Does the `-analysis` flag require quoting for its argument?"* — answering it
honestly meant testing all three spellings rather than reading the parser, which
turned up the double-quote failure; and then asking whether the sibling commands
agreed, which turned up the other two collectors.

*"Does `optimize` work with hierarchical parameters?"* — device parameters and
node objectives already did, in both Enhancement-410 spellings and to the exact
analytic optimum. Models did not, and the failure was in `altermod` rather than
in `optimize`, which only a top-level-model control could establish.

Three method notes worth keeping, all the same mistake.

**A pass/fail filter keyed on error wording scored two real failures as "ok".**
`wcd: unknown option` and `montecarlo: unexpected token` did not match a filter
built from the errors seen earlier. The matrix looked clean when a fifth of it was
broken.

**A probe that cannot distinguish the two outcomes proves nothing.** Checking
`wcd`'s collector with a deliberately bad analysis name looked decisive and was
not: `sw_run_cmd` reports only the *first* word of the command string, so a
correctly collected `nosuch lin 3 1e5` and a truncated `nosuch` print the same
error. Its own `analysis '...'` echo settled it.

**`optimize` prints "converged" even when the knob never moved the metric.** A
`-dparam` run reported `converged, sum-sq residual = 0.0625` — exactly the square
of the untouched starting error, because the parameter being tuned was not used
by the circuit. Read the residual and the final value, not the word.
