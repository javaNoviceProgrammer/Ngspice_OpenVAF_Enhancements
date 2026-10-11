# Enhancement-858: a `.param` reads a suffixed number as the netlist does, and passes it on with every digit — `{1mil}` was 1e-3 where `1mil` is 25.4e-6

**Scope:** F3 of the
[third robustness and correctness campaign of 2026-10-10](../docs/bug_hunts/2026-10-10_ngspice-openvaf-r-third-robustness-campaign.md).

ngspice: `frontend/numparam/xpressn.c`:
- `fetchnumber` reads `mil`, and folds a mantissa's own exponent with the suffix's
  (`decimal_parts`);
- `double_to_string` writes 17 significant digits.

`examples/milparam_examples/` (new). **ngspice only.**

**Suites:**
- [`milparam_examples`](../examples/milparam_examples/): 6 of 6 per solver. On the E-857
  binaries 5 fail; [6] is a control.
- 316 suffixed spellings through four routes (an element value, a `.param`, a B-source and
  `let`): every one is the same double in all four.
- The campaign's Family B, the 4 000 random expressions: the one where `.param` was an ulp
  from the B-source (its 16 digits) now matches it, and `let`, to the bit. The "digits" flag
  left there is Python's reference, which rounds a suffixed number twice.
- The full sweep: 564 of 564.

## What was wrong

**`mil`.** numparam's suffix table ([Enhancement-643](Enhancement-643.md)) had no `mil`. It read
`m` and let "il" go as decoration, so `{1mil}` was 1e-3. `r1 1 0 1mil`, a B-source and
`let x = 1mil` give 25.4e-6, the manual's scale-factor table (§2.1.3.2). The same text came out
39 times apart in one netlist, without a word. That held for every spelling: `{2.5mil}`,
`{1MIL}`, `{10mils}`, `{3.3e2mil}`, and `wid=4mil` on a subcircuit instance.

The dig found two more ways a `.param` drifted from the netlist's reading of the same text:
- **An exponent and a suffix.** E-643 folds a suffix into the number's text, so `1.1u` is the
  double nearest 1.1e-6. A mantissa with its own exponent kept the multiplication, a second
  rounding: `{66.5e4u}` was 0.6649999999999999 where the netlist reads 0.665, and 37 of 300
  random such spellings landed an ulp off.
- **16 digits.** A `{...}` value goes back into the deck as text, and that text had 16
  significant digits (`% 23.15e`). A double does not always survive that: `{0.1+0.2}` reached
  the element as 0.3, and `{sin(45f/7.1f)}` an ulp from the B-source's value. So `{1mil}`, once
  read as 25.4e-6, still reached the element as 2.54e-05, an ulp from what `1mil` is.

## The change

- **`mil`.** A suffix that begins `mil`, in any case, is 25.4 times 10⁻⁶, as in `INPevaluate`.
- **Exponent and suffix.** `decimal_parts` splits a plain decimal into its mantissa and its
  exponent. The exponent and the suffix's power are added and the mantissa is read with the sum
  in one `strtod`, which is the exact decimal `INPevaluate` reads. `mil` multiplies that by 25.4,
  as `INPevaluate` does. A hex float keeps the multiplication.
- **17 digits.** The value is written `% 24.16e `, 17 significant digits in the same
  25-character placeholder (the comment there always counted 17 characters for precision).

A `.param` built from a suffixed number is now the double the netlist reads from the same text.
A deck that wrote `mil` in a `.param` meaning milli changes by a factor of 39; `m` is milli as
before.

## The checks

`milparam_examples`:
- **[1]** `{1mil}` is `1mil` to the bit (1e-3 on E-857).
- **[2]** `mil`'s spellings: 2.5mil, 1MIL, 10mils, 3.3e2mil, 1e-3mil.
- **[3]** `mil` in an expression, and through a subcircuit parameter.
- **[4]** 300 spellings with an exponent and a suffix: each `.param` is the element value to
  the bit (65 differed on E-857, 37 by an ulp).
- **[5]** 17 digits reach the element: `{0.1+0.2}` is 0.30000000000000004, and
  `{sin(45f/7.1f)}` is the B-source's value.
- **[6]** (control) Plain suffixes, and `m` still milli.
