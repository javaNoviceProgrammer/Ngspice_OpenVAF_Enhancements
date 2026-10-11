# Enhancement-859: the front end reads a scale factor after an exponent — `let x = 1.5e2u` was 150 where an element value 1.5e2u is 1.5e-4

**Scope:** F4 of the
[third robustness and correctness campaign of 2026-10-10](../docs/bug_hunts/2026-10-10_ngspice-openvaf-r-third-robustness-campaign.md).

ngspice: `frontend/parser/numparse.c`: `scale_factor`, taken out of `ft_numparse`, follows an
exponent too.

`examples/letsuffix_examples/` (new). **ngspice only.**

**Suites:**
- [`letsuffix_examples`](../examples/letsuffix_examples/): 6 of 6 per solver. On the E-857
  binaries 4 fail; [5] and [6] are controls.
- 316 suffixed spellings through four routes (an element value, a `.param`, a B-source and
  `let`): every one is the same double in all four. On E-857 `let` differed on every spelling
  with an exponent and a suffix.
- The full sweep: 564 of 564.

## What was wrong

`ft_numparse`, the front end's number reader, took "the scale factor or the exponent (can't have
both)":

| text | element value, B-source | `let` on E-857 |
|---|---|---|
| `1.5e2u` | 1.5e-4 | 150 |
| `1e3meg` | 1e9 | 1000 |
| `1e-3k` | 1 | 0.001 |
| `3.3e2mil` | 8.382e-3 | 330 |

The netlist's reader, `INPevaluate`, and numparam apply both. A control script that computes a
value from a netlist's text got a different number, silently: a number in a `let`, `print` or
`plot` expression is read by `ft_numparse`.

## The change

The scale-factor table is now its own function, `scale_factor`. After an exponent it is
consulted too, and its power of ten is added to the exponent's, with `mil`'s 25.4. The sum goes
to `INPdecimal` as one exact decimal, as [Enhancement-643](Enhancement-643.md) made it, so the
value is `INPevaluate`'s to the bit.

An `e` with no digits after it is still not an exponent: `1em` is 1 and `2ex` is 2, the
netlist's reading ([Enhancement-426](Enhancement-426.md)).

## The checks

`letsuffix_examples`:
- **[1]** `let x = 1.5e2u` is 1.5e-4, the element value (150 on E-857).
- **[2]** 1e3meg, 1e-3k, 4.7e3p, 2.2e-1u, 3.3e2mil.
- **[3]** 300 spellings with an exponent and a suffix: `let` is the element value to the bit.
- **[4]** Inside an expression: `v(1) * 1e-3k` and `2e1u + 0`.
- **[5]** (control) An `e` that is not an exponent is trailing text: `1em` is 1, `2ex` is 2.
- **[6]** (control) Plain numbers and suffixes.
