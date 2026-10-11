# Enhancement-857: a sign after an operator in a `.param` is unary, as in the B-source — `{2*-p}` stopped the netlist, `{2*--2}` was −4 and `{2*-3^2}` 18

**Scope:** F2 of the
[third robustness and correctness campaign of 2026-10-10](../docs/bug_hunts/2026-10-10_ngspice-openvaf-r-third-robustness-campaign.md).

ngspice:
- `frontend/numparam/xpressn.c`: `unary_operand_end`; `formula` evaluates a sign after an
  operator as a unary one.
- `frontend/parse-bison.y`: `let` takes a unary plus (`%expect` 2 → 3).

`examples/unaryparam_examples/` (new). **ngspice only.**

**Suites:**
- [`unaryparam_examples`](../examples/unaryparam_examples/): 10 of 10 per solver. On the E-855
  binaries 9 fail; [9] is a control.
- The campaign's Family B, the 4 000 random expressions: the 114 refusals are gone. What is
  still flagged was flagged before: libm's sin and cos of arguments near 1e9 against Python's
  (the page's "Not defects"), and `let tan(0)` (F8).
- A table of 50 expressions with unary signs: `.param` and the B-source agree on every one
  (two, `2*-` and `2*-*3`, both refuse).
- The full sweep: 562 of 562.

## What was wrong

numparam read a minus after a binary operator by setting a flag, and only a NUMBER consumed it.
- **Before a name, a parenthesis or a function** the flag was left over. The formula ended
  "wrongly determined negation", a numparam error, and the netlist was not loaded: `{2*-p}`,
  `{2 * - p}`, `{1/-(2)}`, `{2^-(1)}`, `{2*-sin(1)}`. That was all 114 refusals among the
  campaign's 4 000 random expressions.
- **A second minus** set the flag again instead of clearing it, so one sign was lost without a
  word: `{2*--2}` was −4, `{0+--2}` −2, `{1/--2}` −0.5, `{2^--1}` 0.5, `{2---2}` 4.
- **A minus before a power** negated the number before `^` saw it: `{2*-3^2}` was 18,
  `{3*-2^2*2}` 24, `{1--2^2}` −3, `{2^-3^2}` 2⁻⁶. The B-source and `let` give −18, −24, 5 and
  2⁻⁹. The campaign's generator always bracketed its power chains, so this one surfaced in the
  dig.
- **A plus after an operator** was a misplaced operator: `{2*+3}`, `{2-+2}`.

`let` refused every unary plus: `let x = +2` and `let x = 2*+3` were syntax errors.

## The change

A sign that follows an operator (or `!`) is now unary. `unary_operand_end` finds the end of its
operand, which is what the B-source's grammar (NEG below `^` in `inpptree-parser.y`) and
`let`'s give it:
- a power chain, sign* primary (`^` sign* primary)*;
- where a primary is a number with its suffix, a name, a function call or a parenthesis.

`formula` evaluates that text recursively, negates it for a minus, and takes it as an atom. So
`2*-3^2` is 2·(−(3²)), `2^-3^2` is 2^(−(3²)), and every extra sign is applied in turn. The flag
and the "wrongly determined negation" message are gone. A sign with nothing after it is refused,
naming it: "Nothing follows the "-" in 2*-".

A sign at the start of a formula, or of a parenthesis, keeps its old reading, 0 − x, which
already agreed with the B-source.

`let`'s grammar takes `'+' exp %prec NEG`, the mirror of its unary minus. Like `exp1 '-' exp2`,
`exp1 '+' exp2` can be read as a list of two expressions, so the grammar expects 3 shift/reduce
conflicts instead of 2. The binary reading wins as before, so `print v(1) +v(2)` is still a sum.

A deck that relied on the old values changes. `{a*-b^2}` now follows the B-source, not
(−b)², and a doubled sign now counts.

## The checks

`unaryparam_examples`:
- **[1]** Before a name: `{2*-p}` and `{2 * - p}` are −6.
- **[2]** Before a parenthesis and a function: `{1/-(2)}`, `{2^-(1)}`, `{2*-sin(1)}`.
- **[3]** Two or three signs: 4, 2, 0.5, 2, 0, −2.
- **[4]** A sign before a power takes the chain: −18, −24, 5, 2⁻⁹, −18.
- **[5]** A unary plus after an operator.
- **[6]** A sign with nothing after it is refused, naming it.
- **[7]** The same through a subcircuit parameter and an element value.
- **[8]** `let` takes a unary plus.
- **[9]** (control) The forms that already worked: `{2*-3}`, `{-p*2}`, `{2*(-p)}`, `{-3^2}`, …
- **[10]** 34 expressions: the `.param` and the B-source agree on each.
