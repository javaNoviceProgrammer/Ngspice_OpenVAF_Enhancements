# Enhancement-586: `alter` and `altermod` apply every `name=value` pair, a bare word reaches a string parameter, and a `$fatal` abort ends with its own message

**Scope:** `src/frontend/device.c` (the pair splitter in `com_alter_common`, the
string-first try in the worker), `src/frontend/spiceif.c` (the `doAnalyses` report),
`src/frontend/commands.c` (help), `examples/altermulti_examples/` (new, 14 checks per
solver). **ngspice only.** Hunt findings F1, F7b and F7c of 2026-09-07.

**Suites:** [`altermulti_examples`](../examples/altermulti_examples/) 14 of 14 per
solver, both solvers; the suites that `alter`/`altermod` one pair at a time pass
unchanged; full sweep 483 of 483.

## What was wrong

`alter n1 ga=5m gb=6m` set `ga` and dropped `gb`; `altermod mm ma=3 mb=4` set `ma`
only; built-in devices behaved the same (`alter r1 r=2k temp=50` left `temp` at 27,
`altermod dm is=2e-14 n=1.5` left `n` at 1). Nothing was said. The worker,
`com_alter_common_impl`, splits the *first* word carrying `=` into name, `=`, value,
`break`s out of that loop and reads whatever follows the value as more value; the
evaluator uses the first word of it. Its own "Only a single param - value pair
supported" error sits on the legacy `alter dev param value` path (no `=` anywhere)
and never fires for `a=1 b=2`.

Two smaller slips from the same hour: `altermod mm mode=quad` — a bare word for a
**string** parameter — went down the numeric path, evaluated `quad` as a vector and
said *no such vector quad*; and a `$fatal` raised during the operating point printed
its own clear two-line message and then E_PANIC's stock *doAnalyses: impossible error
- can't occur* after it.

## What changed

* **Every pair applies.** `com_alter_common` counts the assignments — a word
  `name=value`, `name=` or `=value`, or a bare `=` after a name — and, when there are
  several, hands the unchanged one-pair worker one `<target> name = value` list per
  pair, each with its own journal bracket (E-544). The target is the leading device or
  model name and is repeated for every pair; a pair written `@dev[param]=value` carries
  its own and gets none. The pair lists are built pre-split (name, `=`, value as three
  words), because the worker's own splitter, `wl_splice`, frees the node it splits — a
  list whose head it had split could not be freed afterwards. One pair, the
  `alter dev = value` form, the `@dev[param] = value` form, a `[ 0 5 1n ]` vector value
  and the legacy form reach the worker exactly as before, and the legacy form with two
  pairs is still refused with its old message. `==` inside a value is not counted as an
  assignment.
* **A bare word reaches a string parameter.** For a concrete device or model and a
  single-word value that starts like an identifier, the worker tries the string setter
  first; it reports "not string-typed" for a numeric parameter, and the numeric path
  then runs unchanged — a numeric parameter given a vector name still evaluates it, and
  an unknown name still reports the vector error.
* **The `$fatal` aftermath.** `spiceif.c` skips `ft_sperror` when `doAnalyses` returns
  E_PANIC and `CKTvaFatalRaised` is set: the cause has been named by `CKTop`, and the
  stock text only contradicted it.
* `help alter` and `help altermod` show the forms.

```spice
alter n1 ga=5m gb=6m
altermod mm ma=3 mb=4 mode="quad"
alter n1 ga=9m @n1[gb]=10m
alter r1 r=2k temp=50
altermod mm mode=quad
```

## Verification

| check | result |
|---|---|
| two instance pairs, two model pairs on an OSDI device | both applied (`ga=5m gb=6m`, `ma=3 mb=4`) |
| three pairs with a quoted string; pairs spaced `ga = 7m gb = 8m`; a plain pair beside an `@n1[gb]=` pair | all applied |
| built-ins | resistor `r=2k temp=50`, capacitor `c=2p m=3`, diode model `is=2e-14 n=1.5`: both of each |
| single-pair forms | `alter r1 = 3k`, `alter @r1[temp] = 40`, `alter @v1[pulse] = [ 0 5 1n ]` unchanged; the legacy two-pair form still refused, value unchanged |
| a bare word on a string parameter | `altermod mm mode=quad` applied (the current doubles); `ma=nosuchvec` still reports the vector error |
| `$fatal` during op | the `OSDI(fatal)` line and the abort message once, no *impossible error* |
