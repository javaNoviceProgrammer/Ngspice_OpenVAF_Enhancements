# Enhancement-630: a `/name` is a vector name wherever an operand is expected

**Scope:** `src/frontend/parse.c` — `PPlex` remembers the token it returned last
(`PPlex_prev`, reset at the top of each `ft_getpnames_from_string`) and reads a `/`
followed by a name character as the start of a vector name wherever an *operand* is
expected: the start of the expression, after `(`, `,`, `[` or an operator; the name runs
on through further `/` (`/sheet1/out`) to the next special. A `/` after an operand is
still a division. `examples/track_examples/` grows 40 → 45 checks per solver.
**ngspice only.** F13 of the
[2026-09-12 hunt](../docs/bug_hunts/2026-09-12_statistics-record-and-kicad-hunt.md).

**Suites:** [`track_examples`](../examples/track_examples/) 45 of 45 per solver, both
solvers; full sweep 506 of 506 (the lexer serves every expression in the program).

## What was wrong

| accepted `v(/out)` | did not |
|---|---|
| `print v(/out)`, `let x = v(/out)`, `meas … v(/out)`, `montecarlo -expr/-spec/-writemc`, `writemc`, `highsigma -metric`, `wcd -metric`, `sweep -output` | `track v(/out) …`, `montecarlo -track "v(/out) …"` ("cannot parse expression"), `print vdb(/out)`, `vm`, `vp`, `vr`, `vi`, `ph(/out)`, a bare `/out` (PPerror) |

A schematic tool spells every net `/name`. Enhancement-611 taught `print`/`plot`'s
quoting pass, and a string form of it for the commands that evaluate their own text,
to wrap a `v()`/`i()` argument holding a `/` in quotes — so `v(/out)` parsed there. But
`vdb(/out)` and its siblings are `define`d functions whose argument is parsed *before*
the substitution (`vdb(x)` → `db(v(x))`), `ph(/out)` takes a vector expression, `track`
parsed with the plain parser, and a bare `/out` is an expression in its own right: in
every one of those the lexer met `/` and returned the division operator, with nothing to
its left. The workarounds were `vdb("/out")` and `db(v(/out))`; `track` had none.

## What changed

- **The lexer reads `/name` as a name where an operand is expected.** `PPlex` now knows
  the token it returned last; at the start of an expression, after `(`, `,`, `[` or any
  operator, a `/` cannot be a division (nothing stands to its left), so `/` followed by a
  letter or `_` begins a vector name, read on to the next special — a further `/` included,
  so a hierarchical `/sheet1/out` is one name. After an operand (`2/v(/in)`, `v(/out) /
  v(/in)`, `a/b`) a `/` is the division it always was.
- Everything that parses an expression follows: `track v(/out) -spec localmax`,
  `-spec v(/out)>0.5`, `montecarlo -track "v(/out) …"`, `print vdb(/out) vm(/out)
  vp(/out) vr(/out) vi(/out) ph(/out)`, `print /out`, `-/out`, `(/out)/2`, `/out*2`,
  `let y = /out + v(/in)`, `plot /out`. E-611's quoting stays for the names it was made
  for (`v(2p)`, a digit-led node).
- Two things to know: a `/` *inside* a name continues it, so `/sheet1/out/2` is one name —
  divide a `/name` with a space or parentheses, `(/sheet1/out)/2`; and a `print` list is
  one expression string whose items are told apart only by the grammar (as `print a -b`
  has always been `a-b`), so `print v(1) /out` reads as `v(1)/out` — give a bare `/name`
  item its own `print`, or write it as `v(/out)`.

```
track1: 5 hits of localmax on tran1 (applied to v(/out))
vdb(/out)[3] = -1.68155e-01     vp(/out)[3] = -1.96137e-01     ph(/out)[3] = -1.96137e-01
/out = 1.000000e+00   -/out = -1.00000e+00   (/out)/2 = 5.000000e-01   /out gt 0.5 = 1
```

## Verification

| check | result |
|---|---|
| `track v(/out) -spec localmax` on a 1 kHz sine over 5 ms | 5 hits; `-spec v(/out)>0.5` finds its regions |
| `vdb/vm/vp/vr/vi/ph(/out)` on the ac plot | all evaluate; `vdb` = 20 log₁₀ `vm`, `vp` = `ph` |
| a bare `/out`, `-/out`, `(/out)/2`, `/out*2`, `let y = /out + v(/in)` | the expected values |
| `v(/out)/v(/in)`, `v(/out) / v(/in)`, `2/v(/in)` | still divisions |
| `montecarlo -track "v(/out) -spec localmax" -expr pk=maximum(v(/out))` | hits on both samples, `pk` recorded |
| `/sheet1/out` (a hierarchical net) in `v()`, bare, `vdb`, `let` | one name throughout |
| the 40 existing checks | unchanged |
| `track_examples` | 45 / 45, both solvers |
| full sweep | 506 of 506 |
