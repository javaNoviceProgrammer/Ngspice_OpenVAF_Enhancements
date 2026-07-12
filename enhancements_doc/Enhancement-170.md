# Enhancement-170 — Semantic syntax highlighting

[Enhancement-169](Enhancement-169.md) colored the interactive command line
*lexically* — the command word green/red, plus numbers, strings and options. This
extends it to *semantic* highlighting: it now checks whether the **signals** and
**expressions** you type actually exist and parse, and colors accordingly, and it
draws **error output in red**. New source in `src/frontend/syntaxhl.c`.

![semantic syntax highlighting](../examples/syntaxhl_examples/syntaxhl_semantic.png)

## What it adds

1. **Invalid signals turn red.** A signal reference `v(node)`, `i(source)` or
   `@device[param]` is looked up in the current plot (read-only, via
   `vec_fromplot`); if it exists it keeps the default color, if it does not it is
   **red**. So `plot v(out)` reads white once `out` is a real node with data, and
   `plot v(typo)` flags `v(typo)` red.
2. **An invalid signal inside a valid expression reddens only that signal.**
   `print v(a) + v(zzz)` colors just `v(zzz)` red — the rest of the expression,
   including the valid `v(a)`, stays default. Signals nested in functions
   (`sqrt(v(a)) - v(bad)`) are handled the same way.
3. **A malformed expression reddens as a whole.** If the argument of an
   expression command (`plot`/`print`/`gnuplot`/`asciiplot`) fails to parse — a
   genuine syntax error such as `v(a)*/v(b)` — the whole expression is red. The
   real parser (`ft_getpnames_from_string`) is used, with its output muted and its
   tree freed, so the check is silent and side-effect-free.
4. **Error output is red.** Everything ngspice writes to its error channel
   (`cp_err`) — `Error:`/`Warning:` messages — is drawn in red at an interactive
   terminal.

## Not flagged while you are still typing

A half-typed expression is **not** an error, so it stays neutral: a signal whose
parenthesis has not closed yet (`v(bP`), an expression with unbalanced parens
(`v(a)+v(b`), or one ending in an operator (`v(a)+`) are all left the default
color and produce no diagnostics. Only a *settled* malformed expression turns red.

This mattered in practice: the expression parser's error handler (`PPerror`)
writes straight to `stderr`, bypassing the `cp_err` muting, so an early version
spewed `syntax error in line segment ...` onto the prompt as you typed. The check
now also mutes fd 2 across the parse (restoring it afterwards), and skips
obviously-incomplete input entirely.

## Scope and safety

- **Signal validity is scoped to the unambiguous forms** `v(...)` / `i(...)` /
  `@dev[param]`. Bare words are left the default color, because a bare word could
  be a plot keyword (`vs`), a function (`sqrt`) or an option — validating those
  would produce false reds.
- **Signals are validated against the current plot**, so before you `run` a
  simulation (when no vectors exist yet) signal references read as red.
- Everything is **gated** exactly as in E-169: on only at an interactive TTY,
  disabled by `set no_syntax_highlight` and by `NO_COLOR`, and never emitted into
  a piped/redirected session. The error-stream coloring wraps `cp_err` via
  `funopen`/`fopencookie` and points `cp_curerr` at the wrapper too, so ngspice's
  per-command stream reset (`cp_ioreset`) keeps it in place.
- The parser and vector lookups run on every keystroke but are read-only and do
  **not** corrupt command execution — a subsequent `let z = v(a)+v(b)` still
  computes correctly.

## Verification

[`examples/syntaxhl_examples/verify_syntaxhl.py`](../examples/syntaxhl_examples/verify_syntaxhl.py)
— the E-169 lexical checks plus a semantic layer (driven through a pseudo-terminal
after simulating a small circuit so its signals exist):

- a valid signal `v(a)` is not red; an invalid `v(zzz)` is red;
- an invalid signal inside a valid expression reddens only that signal;
- a settled malformed expression reddens as a whole;
- a half-typed expression stays neutral with no parser-error spam;
- error/warning output is drawn in red; `NO_COLOR` suppresses it.

## Follow-ups

Bare vector names could be validated too if functions/keywords were excluded via
the interpreter's own tables; `let`/`define` right-hand sides could get the parse
check (skipping the `name =` prefix); and the palette could be made configurable
(`set syntax_colors=...`).
