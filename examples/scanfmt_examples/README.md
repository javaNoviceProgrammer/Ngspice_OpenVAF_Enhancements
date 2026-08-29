# Enhancement-507 — a format the compiler cannot read, and a value that was never read

```
python3 verify_scanfmt.py
```

31 checks, both linear solvers. 19 of them fail without the fix.

## What was wrong

### The scan format was read for one thing and ignored for the rest

`lower_scanf` reads a `$sscanf`/`$fscanf` format for exactly one purpose — picking
each field's integer base
([Enhancement-105](../../enhancements_doc/Enhancement-105.md)) — and then pulls
**one whitespace-delimited token per destination**.
[Enhancement-11](../../enhancements_doc/Enhancement-11.md) says so at the site;
nothing said it to the *user*, and ignoring the rest of a C format returns the
wrong field:

| call | before | C |
|---|---|---|
| `$sscanf("v=42", "v=%d", x)` | 0 conversions | 1, `x=42` |
| `$sscanf("1234", "%2d", x)` | **1234** | 12 |
| `$sscanf("12 34", "%*d %d", x)` | **12** | 34 |
| `$sscanf("A", "%c", x)` | 0 conversions | 1, `x=65` |

`%*d` means *discard this field*, so the third gives the model the value the
author asked to throw away — and the match count agrees, so nothing looks wrong.

### A run-time format silently changed the base

The base is read when the model is **compiled**, so a format that is only a string
at run time fell back to base-0 auto-detection: `%o` on `"777"` returned **777**
instead of 511 and reported one successful conversion; `%b` on `"101"` returned
**101** instead of 5.

Every other builtin that needs a compile-time string already refuses a run-time
one (`white_noise`'s name, both plusargs, `$table_model`'s control string,
`$limit`'s function name). These two accepted it and misread it.

### The display family keeps its fallback

A non-literal format is *printed by type*
([Enhancement-453](../../enhancements_doc/Enhancement-453.md)) — right for
`$strobe(msg)`, wrong when operands follow: `$strobe(f, 2.5)` printed
`MARK %g 2.5`. That is a warning (`L026`), not a refusal, and it fires only when
at least one argument follows.

### A conversion that did not happen overwrote its destination

The scanner returned `0`/`0.0`/`""` on a failed field and the store was
unconditional, so a failed or partial scan **destroyed** values the model had set.
C leaves an unmatched argument untouched, which is what makes the ordinary idiom
work:

```verilog
x = fallback;
if ($sscanf(line, "%d", x) < 1)   // x is still fallback
```

Reading that previous value is the whole difficulty: a destination never assigned
has no `Place`, and declaring one makes it `ParamKind::HiddenState` — persistent
instance state the backend does not provide for a scanf target, which segfaults
the simulator. `get_place` distinguishes the two cases, and where there is no
prior definition the previous value **is** the implicit zero.

### And three on the simulator side

- A `{...}` that evaluates non-finite is substituted as the text `inf`, which
  `INPevaluate` refuses — and `INPgetValue`'s scalar paths threw that refusal away
  where its vector path honours it. `.model nm nmos ... kp={1/0}` built a
  transistor conducting **1e-12 instead of 1.25e-4**, exit 0, no diagnostic.
- Freeing a partially built B-source expression announced
  `Internal error: unhandled parse-tree node type 0`, because `PT_PLACEHOLDER` —
  an ordinary leaf — was missing from the release switch.
- `save @dev[opvar]` said *"device has no parameter"* about a name the device has
  and that `print` and `meas` both resolve.

## Files

| file | what it holds |
|---|---|
| `scanok.va` | every format the scanner honours, plus the destination-preserving rule |
| `bad_literal.va`, `bad_width.va`, `bad_suppress.va`, `bad_conv.va` | one refused format element each — these are expected **not** to compile |
| `bad_runtime.va` | a format known only at run time |
| `fmtwarn.va` | the display warning, alongside the two forms that must stay silent |

## What is deliberately unchanged

The scanner is still a whitespace-delimited tokenizer — this enhancement makes
its limits **visible**, it does not rewrite it into a C `scanf`. A non-literal
format is still *printed* by the display family, because that is what a
one-argument `$strobe(msg)` wants; only the operands-follow case warns. And a
`.model` card whose value did not parse keeps that parameter's **default**, which
is what the surrounding conventions already do for an unknown or duplicated
parameter.
