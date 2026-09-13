# Enhancement-631: a `.func` shadows a built-in only for calls with its argument count — `limit()` works under KiCad's compatibility mode

**Scope:** `src/frontend/inpcom.c` — `inp_expand_macro_in_str()` leaves a call whose argument
count does not match the `.func`'s to the built-in of that name instead of the fatal
"parameter mismatch"; `inp_get_func_from_line()` takes whether the card is one ngspice
inserted itself (`linesource == "internal"`, the PSpice compatibility set) and does not
blame "your definition" for those; the user warning's text says what the definition now
covers. `examples/silentaccept_examples/` grows 42 → 44 checks per solver. **ngspice
only.** F14 of the
[2026-09-12 hunt](../docs/bug_hunts/2026-09-12_statistics-record-and-kicad-hunt.md).

**Suites:** [`silentaccept_examples`](../examples/silentaccept_examples/) 44 of 44 per
solver, both solvers; `numguard` green; full sweep 506 of 506.

## What was wrong

```
$ cat .spiceinit
set ngbehavior=kiltpsa            ; what KiCad sets
$ ngspice -b deck.cir             ; .param r1v = limit(1000, 100)
Warning: .func limit() redefines the built-in function 'limit'; every expression in this deck will use your definition instead of the built-in.
Warning: .func pwr() redefines the built-in function 'pwr'; ...
Warning: .func int() redefines the built-in function 'int'; ...
ERROR: parameter mismatch for function call in string limit(1000,100)
ERROR: fatal error in ngspice, exit(1)
```

The `ps` in `kiltpsa` turns on ngspice's PSpice compatibility pass, which inserts six
`.func` cards at the top of the deck — `limit(x, a, b)` (PSpice's clamp), `pwr`, `pwrs`,
`stp`, `if`, `int`. A `.func` replaces a built-in of its name for the whole deck, by
textual expansion, and the expansion of a call with the wrong number of arguments is
fatal: the random `limit(nom, avar)` — ngspice's own two-argument built-in, the
corner-style ± — was expanded against the three-parameter PSpice definition and ngspice
exited. And the three warnings said "your definition" of `.func` cards the user never
wrote. Every other statistical form (`agauss`, `gauss`, `unif`, `aunif`, `mvnorm`,
`osdimc`, `savemc`, `autobus`) was unchanged under the mode; `ngbehavior=ki` alone
gave 900 or 1100.

## What changed

- **A `.func` covers the calls of its own argument count.** When the count differs and
  the name is a built-in (`nupa_is_mathfunction`), the call is left as written for the
  built-in to evaluate — `limit(1000, 100)` is the coin, `limit(1500, 100, 1200)` the
  clamp, in one deck. A mismatched call of a name that is no built-in is still the error
  it was.
- **The compatibility set draws no warning.** A `.func` card ngspice inserted itself
  (`linesource == "internal"`) is not "your definition"; nothing is said. A user's
  `.func limit(x, a, b)` still warns, and the text now says what it covers: "every call
  with its argument count will use your definition instead of the built-in (a call with
  another count still reaches the built-in)".

```
@r1[resistance] = 1.100000e+03      ; limit(1000, 100) -- the coin
@r3[resistance] = 1.200000e+03      ; limit(1500, 100, 1200) -- PSpice's clamp
@r4[resistance] = 8.000000e+00      ; pwr(2, 3)
@r5[resistance] = 8.000000e+00      ; int(-2.7) + 10
```
under `set ngbehavior=kiltpsa`, with nothing else printed. The default mode is untouched
(`limit(nom, avar)` is the two-argument built-in there, as documented).

## Verification

| check | result |
|---|---|
| a user `.func limit(x,a,b)` beside `limit(1000, 100)` in one expression | 1200 + (900 or 1100); no exit; the warning says "every call with its argument count" |
| `set ngbehavior=kiltpsa` (a `.spiceinit`): `limit(1000,100)`, `limit(1500,100,1200)`, `pwr(2,3)`, `int(-2.7)` | 900 or 1100; 1200; 8; −2 — no fatal exit, no "redefines the built-in" |
| `.func sqrt(x)` (E-467's case), an ordinary name | still warns / still silent |
| the 42 existing checks; `numguard` | unchanged |
| `silentaccept_examples` | 44 / 44, both solvers |
| full sweep | 506 of 506 |
