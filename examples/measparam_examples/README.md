# measparam_examples — Enhancement-311

**`param` / `expr` measurements now work in a `.control` block.**

The `param` and `expr` measurement types are handled only by `do_measure()`'s second pass
(via `nupa_eval`), which the interactive / `.control` `meas` command bypasses — it calls
`get_measure2()` directly, and `get_measure2()` has no `param`/`expr` case. So the same
measurement that worked as a dot-card failed inside `.control`:

```
.meas tran pp param='a1-a2'      (dot-card)  ->  pp = 2
meas  tran pp param='a1-a2'      (.control)  ->  "no such function as ...", failed
```

Every form failed, down to a bare `param=a1`.

## The fix

A `param`/`expr` measurement is evaluated with the ordinary **vector expression evaluator**:
the prior results (`a1`, `a2`) are already single-valued ngspice vectors, so
`meas <an> <name> param=<expr>` is exactly `let <name> = (<expr>)`. The command is re-lexed
with `cp_lexer` so an expression containing spaces tokenises as the shell would.

Working forms in a `.control` block:

```
meas tran pp param=a1-a2                    $ unquoted
meas tran pp param='a1-a2'                  $ quoted, no internal spaces
meas tran pp param={sqrt(a1*a1 + a2*a2)}    $ braces -- spaces OK
meas tran pp expr='a1*a2'                   $ expr type
```

## Known limitation (not this fix)

`param='sqrt(a1*a1 + a2*a2)'` — a **single-quoted** expression with **internal spaces** — is
still broken, but by the `.control` shell's own quote pre-expansion, which mangles it
*before* `meas` ever sees it (the debug trace shows `sqrt(a1*a1` already replaced by an
internal temp). Use the **brace** form for spaced expressions. The dot-card `.meas`, which
does not go through the shell tokenizer, handles quoted spaces fine.

## Verify

```bash
python3 verify_measparam.py
```

8 checks under both solvers, all against closed-form values from a symmetric triangle
(max=+1, min=-1). Fails 7/8 on the pre-fix binary.
