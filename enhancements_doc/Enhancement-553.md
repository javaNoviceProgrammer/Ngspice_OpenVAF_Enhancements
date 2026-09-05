# Enhancement-553: raw strings `r"…"` keep their case through the deck reader, f-strings `f"…{expr:.3f}…"` evaluate in a control script

**Scope:** the deck reader's case folding and whitespace pass
(`src/frontend/inpcom.c`), the command lexer, unquoter and glob
(`src/frontend/parser/lexical.c`, `quote.c`, `parser/glob.c`) and the command
loop (`src/frontend/control.c`). Prompted by the `pyplot` review of
[E-547](Enhancement-547.md): its titles came out in lower case.
**ngspice only; the compiler is unchanged.**

**Suites:** [`rawfstring_examples`](../examples/rawfstring_examples/) (new, 14
checks, both solvers); the pyplot family, `forloop` and `mcrecord` pass; full
sweep 457 of 457. Handbook [§3.10](../docs/handbook/03-ngspice-workflows.md)
(new) and [§4.5](../docs/handbook/04-limitations-and-gotchas.md), the
[commands table](../docs/internals/ngspice_internals/ngspice_commands.md), the
pyplot reference [§5](../docs/internals/ngspice_internals/ngspice_pyplot.md).

## What was wrong

A deck is folded to lower case as it is read, and the fold reached the text a
control script hands to a command: `set t="ABC"` stored `abc`, `pyplot … title
"RC Low-Pass"` printed `rc low-pass`. The fold was command-specific and
uneven — `echo` lines and the `title`/`xlabel`/`ylabel` tokens of `plot` and
`gnuplot` were exempt, `pyplot`'s were not — and the same reading pass dropped
the spaces around an `=` inside a quoted string, `"A = B"` becoming `A=B`.
There was no way to say *this text, as written*, and no way to put a computed,
formatted value into a string at all.

## What changed

Two string forms, after Python's:

| form | meaning |
|---|---|
| `r"…"` / `r'…'` | a **raw string**: copied through the deck reader as written, case and spaces kept (also `R`) |
| `f"…"` / `f'…'` | an **f-string**: every `{expression}` is evaluated with the control-language evaluator when the command runs and replaced by its text; `{expr:.3f}`, `{expr:.4g}`, `{expr:e}`, `{expr:d}` format it; a scalar prints with `%g`, a vector as its elements, a complex value as `re,im`; `\{` and `\}` are literal braces |
| `rf"…"` / `fr"…"` | both |

```spice
set title=r"RC Low-Pass, Corner Case"
echo f"yield {100*montecarlo_yield:.2f} %, corner {mean(fc):.4g} Hz"
pyplot fig v(out) title rf"RC low-pass, Vmax = {vecmax(v(out)):.3f} V"
foreach x f"{2*n}" f"{3*n}"
  ...
end
```

* The prefix counts only at a token start: `set t=r"…"` has one; a resistor
  `r1`, a variable `f`, `set r=…` and the words `r`, `rf` do not.
* An expression that resolves to nothing, an unbalanced brace or a format
  that is not one is an error naming the string, and the command is not run:
  an empty substitution would be a silent zero.
* `$variables` are substituted before the braces are evaluated, so
  `{$&v * 2}` works. `{{ }}` is not an escape: it belongs to the netlist's
  `.for` construct ([E-474](Enhancement-474.md)), and the two coexist.
* Interactive input was never folded; there the prefixes are simply
  accepted. A plain string folds exactly as before.
* `pyplot` keeps the case of its `title`/`xlabel`/`ylabel` tokens the way
  `plot` and `gnuplot` always did.

Where it lives: `prefixed_span_end` / `raw_span_end` in `inpcom.c` (the
control-line fold and the whitespace pass skip a prefixed literal);
`cp_string_prefix_len` and the quote cases of `cp_lexer` (a prefixed `'…'`
becomes the double-quoted form, a backslash inside a prefixed string is kept);
`cp_unquote` strips the prefix with the quotes; `cp_doglob` leaves a prefixed
word out of brace expansion; `cp_fstringsubst` in `control.c` evaluates after
globbing, in the command loop and in `foreach` lists.

## Verification

| check | result |
|---|---|
| `set a=r"ABC Def"`, `set b=R'Mixed Case'`, `set c="ABC Def"` | `ABC Def`, `Mixed Case`, `abc def` |
| `pyplot … title "Plain Title Kept" xlabel r'My Time' ylabel R"Quoted Volts"` | all three kept |
| `set d=r"A = B raw"`, `set e="A = B plain"` | `A = B raw`, `a=b plain` |
| `f"vmax {vecmax(v(out)):.3f} V default {vecmax(v(out))} int {length(v(out)):d} vec {vector(3)}"` | `vmax 0.756 V default 0.75611 int 112 vec 0 1 2` |
| `f"complex {v(out)[0]}"` on an ac plot | `0.999999,-0.000999025` |
| `rf"Kept Case {2*3} and \{literal\} braces"` | `Kept Case 6 and {literal} braces` |
| `echo f"bad {v(nosuch)} here"` | `Error: f-string f"bad {v(nosuch)} here": {v(nosuch)} does not evaluate to a value …`; not run |
| `f"open {2*3"`, `f"stray } here"` | `'{' without a closing '}'`, `a '}' without a '{'`; the script goes on |
| `{vecmax(v(out)[0])}`, `{max(1,2)}`, `{v(out)[1]:.2e}` | a colon inside brackets or parentheses is not a spec; a real one after it works |
| `foreach x f"{1+1}" f"{2+2}"` | `x="2"`, `x="4"` |
| `let r = 3`, `let f = 4`, `set rf=plain`, `print @r1[resistance]` | untouched |
| interactive `echo r"ABC Def" f"{1+1}" rf"Kept {3*3}"` | `ABC Def 2 Kept 9` |
| `.for i in range(1,3)` with `rl{{i}}` beside an f-string | both work |
| `title rf"RC low-pass, Vmax = {vecmax(v(out)):.3f} V"` | `RC low-pass, Vmax = 0.756 V` |
| `rawfstring_examples` | 14 / 14, both solvers |
| full sweep | 457 of 457 |
