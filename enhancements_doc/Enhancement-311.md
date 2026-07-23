# Enhancement-311 — ngspice: `param`/`expr` measurements now work in a `.control` block

Found while oracle-checking the less-common `.meas` modes. The `param` and `expr`
measurement types worked as a `.meas` dot-card but **failed** from an interactive/`.control`
`meas` command, with `no such function as '...'`.

## The gap

`.meas` cards are processed by `do_measure()`, which runs **two passes**: the second pass
handles `param`/`expr` specially, evaluating the expression through the numparam machinery
(`nupa_eval`). The interactive `meas` command (`com_meas`) skips `do_measure` entirely and
calls `get_measure2()` directly — and `get_measure2()` has no `param`/`expr` case. So

```
.meas tran pp param='a1-a2'      -> pp = 2      (dot-card, works)
meas  tran pp param='a1-a2'      -> failed      (.control, no param case)
```

Every `.control` form failed, down to a bare `param=a1`.

## The fix

In a `.control` block the prior results (`a1`, `a2`) are already single-valued ngspice
**vectors** (`com_meas` stores each with `com_let`). So a `param`/`expr` measurement is just
`let <name> = (<expr>)` evaluated by the ordinary vector-expression evaluator. `com_meas`
now detects a `param`/`expr` measure type, before its single-valued-vector substitution loop
(which would otherwise mangle the expression), reassembles the expression from the tokens
after `param=`/`expr=`, strips the delimiter single quotes, and re-lexes the whole `let`
command with `cp_lexer` so an expression with spaces tokenises exactly as the shell would.

Working forms: `param=a1-a2` (unquoted), `param='a1-a2'` (quoted, no internal spaces),
`param={sqrt(a1*a1 + a2*a2)}` (braces, spaces OK), and the `expr=` type. Normal measurement
types (`max`/`min`/`avg`/`when`/…) are untouched — they still route through `get_measure2()`,
byte-identically.

## Known limitation left in place

`param='sqrt(a1*a1 + a2*a2)'` — a single-quoted expression with **internal spaces** — is
still broken, but by the `.control` shell's own quote pre-expansion, which evaluates and
mangles the quoted string *before* `meas` is invoked (the reassembled command comes through
as `pp = ( vexprint1 + a2*a2) )`). That is upstream of `com_meas` and out of scope here; the
**brace** form is the spaced-expression path, and the dot-card handles quoted spaces because
it does not pass through the shell tokenizer.

## Verification

`examples/measparam_examples/verify_measparam.py` — 8 checks under both solvers, all against
closed-form values from a symmetric triangle (max=+1, min=-1): the four practical `param`
forms, `expr`, a brace function call, and a check that the normal `max` path is unchanged.
The suite scores **7/8 failing on the pre-fix binary** (only the normal-path check passes),
so it is a real regression guard.

## Scope of change

`src/frontend/measure.c`, `com_meas` only.
