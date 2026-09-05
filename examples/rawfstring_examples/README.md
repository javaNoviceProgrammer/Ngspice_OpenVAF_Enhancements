# rawfstring_examples — raw strings and f-strings in control scripts (Enhancement-553)

```
python3 verify_rawfstring.py
```

18 checks, both solvers.

## The need

A deck is folded to lower case as it is read, and the fold reached the text a
control script hands to a command: `pyplot … title "RC Low-Pass"` printed
`rc low-pass`, `set t="ABC"` stored `abc`. The fold was command-specific and
uneven — `echo` lines and `gnuplot`'s title tokens were exempt, `pyplot`'s were
not — and the same reading pass dropped the spaces around an `=` inside a
quoted string. There was no way to say *this text, as written*, and no way to
put a computed, formatted value into a string at all.

## What changed

| form | meaning |
|---|---|
| `r"…"` / `r'…'` | a **raw string**: copied through the deck reader as written, case and spaces kept (also `R`) |
| `f"…"` / `f'…'` | an **f-string**: every `{expression}` is evaluated with the control-language evaluator when the command runs and replaced by its text; `{expr:.3f}`, `{expr:.4g}`, `{expr:e}`, `{expr:d}` format it; a scalar prints with `%g`, a vector as its elements, a complex value as `re,im`; `\{` and `\}` are literal braces. Since E-556 the result is plain text (quoted only when it has whitespace, so it stays one word), so `let`, `set`, `alter`, `if`, `setplot`, a file name and a numeric option all take it |
| `rf"…"` / `fr"…"` | both |

The prefix counts at a token start or after `=`, `(`, `,` inside a token
(`set t=r"…"` and `let z=f"{7}"` — the deck reader's form of `let z = f"{7}"`
— have one; a device `r1`, a variable `f` and the words `r`, `rf` do not;
E-556 closed the gap where only the lexer knew the second rule). An expression that resolves to
nothing, an unbalanced brace or a bad format is an error naming the string,
and the command is not run. `{{ }}` is not an escape: it belongs to the
netlist's `.for` construct (E-474), and the suite pins that the two coexist.
`pyplot` now keeps the case of its `title`/`xlabel`/`ylabel` tokens the way
`plot` and `gnuplot` always did.

```spice
set title=r"RC Low-Pass, Corner Case"
echo f"yield {100*montecarlo_yield:.2f} %, corner {mean(fc):.4g} Hz"
pyplot fig v(out) title rf"RC low-pass, Vmax = {vecmax(v(out)):.3f} V"
```

Where it lives: `prefixed_span_end` / `raw_span_end` in
`src/frontend/inpcom.c` (the deck reader's case folding and whitespace pass
skip a prefixed literal), `cp_string_prefix_len` and the quote cases of
`cp_lexer` in `src/frontend/parser/lexical.c` (a prefixed `'…'` becomes the
double-quoted form; a backslash inside a prefixed string is kept), `cp_unquote`
in `src/frontend/quote.c` (the prefix is stripped with the quotes), `cp_doglob`
in `src/frontend/parser/glob.c` (a prefixed word is not brace-expanded) and
`cp_fstringsubst` in `src/frontend/control.c` (the evaluation, after globbing).
