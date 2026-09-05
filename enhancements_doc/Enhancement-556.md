# Enhancement-556: an f-string after `name=` is evaluated, its result is plain text, and `pyplot` unquotes its name

**Scope:** F3, F4 and F5 of the
[bug hunt of 2026-09-05](../docs/bug_hunts/2026-09-05_strings-mcexpr-and-osdimc-distributions.md),
on the string forms of [E-553](Enhancement-553.md): the lexer's prefix
finder (`src/frontend/parser/lexical.c`), the glob skip
(`src/frontend/parser/glob.c`), the f-string pass (`src/frontend/control.c`),
the `if`/`while` condition path (`src/frontend/cpitf.c`) and `pyplot`'s name
argument (`src/frontend/com_pyplot.c`). **ngspice only; the compiler is
unchanged.**

**Suites:** [`rawfstring_examples`](../examples/rawfstring_examples/) 14 → 18,
[`pyplot_examples`](../examples/pyplot_examples/) 47 → 49, both solvers; the
thirteen neighbouring suites pass; full sweep 459 of 459. Handbook
[§3.10](../docs/handbook/03-ngspice-workflows.md), the pyplot reference
[§2.3](../docs/internals/ngspice_internals/ngspice_pyplot.md).

## What was wrong

* **F3.** The lexer accepted a string prefix at a word's start or after `=`,
  `(`, `,`; the glob skip and the f-string pass looked at the word's start
  only. The deck reader collapses `let z = f"{7}"` into `let z=f"{7}"` and
  `if f"{1+1}" = 2` into `if f"{1+1}"=2`, so in a deck an f-string after
  `name=` had its braces globbed away and was never evaluated: `let z=f"7"`
  was an *invalid RHS*, `set t=f"{1+1}"` stored `1+1`, and no `set` variable
  could take an f-string at all. Backquotes were no way round it either.
* **F4.** The substituted text was a quoted word, `"7"`, which `let`, `alter`,
  `setplot` and every numeric option refuse — so a formatted number could
  reach an `echo` and nothing else; `montecarlo … -max f"{1000+40}"` was
  *not a number*.
* **F5.** `pyplot` used a quoted name verbatim, quotes and all: `pyplot
  -export "sp dir/s1" v(out)` tried to open `"sp dir/s1".npy` and wrote
  nothing, and `pyplot -export f"run{$i}"` in a loop wrote `"run1".npy`.

## What changed

* `cp_string_prefix_at` finds a prefixed string wherever the lexer accepts
  one, with a tail after the closing quote kept and more than one per word
  allowed; `cp_doglob` skips a word carrying one; `cp_fstringsubst` rebuilds
  head + text + tail; `cp_istrue` — the `if`/`while` condition path, which
  never saw the pass — runs it.
* An f-string's result is **plain text**. A result with whitespace in it is
  quoted, so that a command which re-reads its arguments (`set u=rf"{x:.3f}
  V"`) still sees one word and unquotes it itself; a raw string keeps its
  quotes, like the plain quoted word it stands in for. `foreach x f"{3}"` now
  yields `x=3`, not `x="3"`.
* `pyplot` unquotes its name argument, the eye path included.

## Verification

| check | result |
|---|---|
| `let z = f"{7}"`, `let w=f"{2*4}"`, `set t=f"{1+1}"`, `alter r1 = f"{3*1000}"` in a deck | 7, 8, 2, 3000 |
| `set u = rf"{vecmax(v(out)):.3f} V"` | `0.756 V` |
| `if f"{1+1}" = 2`, `if f"{k*3}" = 6` after a `while` | both true |
| `setplot f"tran{1}"` | `tran1` |
| `montecarlo … -max f"{1000+40}"` | a yield |
| `wrdata f"wr{1+1}.txt"`, `write f"wr{2+1}.raw"`, `pyplot -export f"ex{4}"` | `wr2.txt`, `wr3.raw`, `ex4.npy`, no quotes |
| `set v=r"{1+1}"` | the braces kept |
| `pyplot -export "with space/exp" v(in)`, `pyplot "with space/img" v(in)` | written there, status 0 |
| `rawfstring_examples`, `pyplot_examples`; full sweep | 18 / 18, 49 / 49; 459 of 459 |
