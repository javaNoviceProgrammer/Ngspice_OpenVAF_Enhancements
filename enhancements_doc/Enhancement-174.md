# Enhancement-174 — `help all` crash fix (help string used as printf format)

Running **`help all`** (or `help montecarlo`) in the interactive shell crashed
the shipped ngspice with:

```
Error: tvprintf failed
ERROR: fatal error in ngspice, exit(-1)
```

## Root cause

ngspice's help printer uses each command's help text **as a `printf` format
string**. In [`com_help.c`](../ngspice-46/src/frontend/com_help.c) (and the
parallel `com_ahelp.c`):

```c
out_printf(ccc[i]->co_help, cp_program);   /* co_help IS the format */
```

Only one argument is ever passed (`cp_program`, the program name, meant to fill
a single `%s` — as in the legitimate `"Report a %s bug."`). Any other `%` in a
help string is an invalid/incomplete conversion specifier, so `tvprintf` fails
and ngspice calls a fatal `exit(-1)`.

The `montecarlo` command's help (added in
[Enhancement-151](Enhancement-151.md)) read:

> `… reports the yield with a Wilson 95% CI and per-spec violations …`

The `% ` (percent-space) in *95% CI* is that invalid specifier. `help all`
walks the command table alphabetically and died the moment it reached
`montecarlo`; `help montecarlo` crashed directly too. The bug was present in
both command tables (`spcp_coms` for ngspice, `nutcp_coms` for nutmeg).

It is not X11/terminal/solver specific — it is plain format-string handling, so
it reproduced on every build. (It was invisible in headless CI because
`help all` is an interactive command not exercised by the batch example decks —
now it is; see below.)

## Fix

Escape the literal percent as `%%` (printf convention), in both tables:

```
… a Wilson 95%% CI …      →  renders as "95% CI"
```

One character; the help line now prints the literal `95% CI` and `help all`
completes.

## Regression guard

New [`examples/helpcmd_examples/verify_helpcmd.py`](../examples/helpcmd_examples/verify_helpcmd.py)
with two layers:

- **Runtime** — drives an interactive ngspice on a pseudo-terminal and asserts
  `help`, `help all`, and `help montecarlo` each run to completion (no crash, no
  `tvprintf failed`), and that the montecarlo line renders a literal `95% CI`.
- **Static class-guard** — scans `commands.c` and fails if *any* command help
  string carries a format hazard: a `%` that is not `%s` or `%%`, or more than
  one `%s` (only one argument is passed, so a second `%s` would read a garbage
  pointer). This catches a future unescaped `%` even when that specific command
  is never exercised at runtime — the actual class of bug, not just this
  instance.

The static guard flags the pre-fix string and passes the fix; the runtime guard
crashes on the pre-fix binary and passes on the fixed one. Full example
regression: 137/137.
