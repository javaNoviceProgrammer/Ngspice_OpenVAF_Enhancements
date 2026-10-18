# Enhancement-900: `compose … values` reads a signed word as a new value — `1 -2 3` made [−1, 3], without a word

**Scope:** F6 of the
[analyses correctness campaign of 2026-10-16](../docs/bug_hunts/2026-10-16_ngspice-openvaf-r-analyses-correctness-campaign.md).

ngspice:
- `frontend/com_compose.c`: the values of `compose name values …` are parsed in runs of words,
  split before a signed word that follows a complete value.

**ngspice only.**

**Suites:**
- [`composevalues_examples`](../examples/composevalues_examples/), new: 8 of 8 per solver; on
  the E-899 binaries 5 of 8 fail.
- The full sweep: 594 of 594.

## What was wrong

`compose name values v1 v2 …` builds a vector from a list of values, each of which may be an
expression. The command flattened its words into one string and handed it to the expression
parser, whose list is a run of juxtaposed expressions. In that grammar `1 -2` is the expression
1 − 2, so a negative value was subtracted from the one before it:

```
compose a values 1 -2 3        -> [-1, 3]
compose a values 1, -2, 3      -> [-1, 3]
compose a values 1 +2 3        -> [3, 3]
compose a values x -x          -> [0]
```

The shell's lexer turns a comma after a word into a word break, so the comma form was the same
list. Nothing was printed. A program that writes its numbers with `%g` gets a shorter vector of
sums: eleven random values in [−5, 5] came out as three. The manual asks for negative values in
parentheses, `(-2.364)`, but a script that writes values does not do that.

## The change

A word that starts with `-` or `+` begins a new value when:
- it has more than the sign;
- it follows a word that ends an operand, that is, not an operator, `(`, `[`, `,`, or one of the
  word operators `gt`, `lt`, `ge`, `le`, `ne`, `eq`, `and`, `or`, `not`;
- it is outside parentheses and brackets.

This is MATLAB's rule for a row. Each run of words is parsed on its own, and the lists are joined
as the grammar joins them.

| | before | now |
|---|---|---|
| `1 -2 3` | [−1, 3] | [1, −2, 3] |
| `1 -2*3 4` | [−5, 4] | [1, −6, 4] |
| `x -x` | [0] | [5, −5] |
| `1 - 2 3` | [−1, 3] | [−1, 3] |
| `(1 -2) 3` | [−1, 3] | [−1, 3] |
| `2 * -3 4` | [−6, 4] | [−6, 4] |

Values in parentheses, complex values `(1, -2)`, and the error messages are unchanged.
`print`, `plot` and the other commands that take expression lists are not changed: they label
each expression as they parsed it, so `print 1 -2` shows `1 -2 = -1`.

## The checks

`composevalues_examples`:
- **[1]** `1 -2 3` is [1, −2, 3]. E-899: [−1, 3].
- **[2]** `1, -2, 3` and `1,-2,3` likewise. E-899: [−1, 3].
- **[3]** `1 +2 3` is [1, 2, 3]. E-899: [3, 3].
- **[4]** Signed expressions start new values: `1 -2*3 4`, `x -x`, `sin(0) -cos(0)`,
  `1 -(2+3) 4`, `3 -2 +1`, `-1 -2 -3`, `1e-3 -1e-3`. E-899: every one wrong.
- **[5]** Eleven random values in [−5, 5], written with `%g`: the same eleven. E-899: 3.
- **[6]** The binary forms are unchanged: `1 - 2 3`, `1-2 3`, `(1 -2) 3`, `2 * -3 4`,
  `2 ^ -1 4`, `x gt -1 7`.
- **[7]** `1 (-2) 3` and the complex `(1, -2) (3,4)` are unchanged.
- **[8]** `1 -` is still a syntax error, `1 -foo` names the missing vector, an empty list warns,
  and none makes a vector.
