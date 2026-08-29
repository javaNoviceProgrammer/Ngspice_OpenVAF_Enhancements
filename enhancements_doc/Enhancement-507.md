# Enhancement-507 — a format the compiler cannot read, and a value that was never read

Round 64's findings divide cleanly in two: a **format string** honoured only when
it is a literal, and a **value** that nothing checked had actually been read.

## 1. The scan format was read for one thing and ignored for the rest

`lower_scanf` reads a `$sscanf`/`$fscanf` format for exactly one purpose — picking
each field's integer base (Enhancement-105) — and then pulls **one
whitespace-delimited token per destination**. Enhancement-11 states that at the
site:

> The scanner is a simple whitespace-delimited tokenizer over a module-global
> cursor. It does not interpret the C format string.

Nothing, however, stated it to the **user**, and ignoring the rest of a C format
does not merely lose a feature — it returns the wrong field:

| call | before | C |
|---|---|---|
| `$sscanf("v=42", "v=%d", x)` | 0 conversions | 1, `x=42` |
| `$sscanf("1234", "%2d", x)` | **1234** | 12 |
| `$sscanf("12 34", "%*d %d", x)` | **12** | 34 |
| `$sscanf("A", "%c", x)` | 0 conversions | 1, `x=65` |

The third is the worst of them. `%*d` means *discard this field*, so the value the
model receives is the one the author asked to throw away — and the match count
agrees with it, so nothing looks wrong.

Each of these is now named at compile time, by the element that cannot be
honoured, rather than producing a plausible wrong number.

## 2. A run-time format silently changed the base

The conversion base is read when the model is **compiled**. A format that is only
a string at run time therefore fell back to `strtol`'s base-0 auto-detection:

| call | before | correct |
|---|---|---|
| `f = "%o"; $sscanf("777", f, x)` | **777**, reported as one success | 511 |
| `f = "%b"; $sscanf("101", f, x)` | **101**, reported as one success | 5 |
| `f = "%h"; $sscanf("ff", f, x)` | 0 conversions | 255 |

Every other builtin that needs a compile-time string already **refuses** a
run-time one — `white_noise`'s source name, `$test$plusargs`, `$value$plusargs`,
`$table_model`'s control string and `$limit`'s function name all answer
*"expected string literal"*. These two accepted it and misread it. They refuse it
now, for the reason the message states.

## 3. The display family had the same split, and keeps its fallback

`hir_lower::fmt` treats a string argument as a format only when it is a literal;
anything else is *printed by type* (Enhancement-453). That fallback is exactly
right for `$strobe(msg)`, which is how a model prints a message it built with
`$sformat`. It is exactly wrong when operands follow:

```
f = "MARK %g";  $strobe(f, 2.5);     ->  MARK %g 2.5
```

Because each conversion fixes its argument's **type** in the callback signature,
and that signature is built at compile time, a run-time format cannot be
honoured. So this is a warning (`L026`, `runtime_format_string`) naming the
fallback, not a refusal — and it fires only when at least one argument follows,
so the one-argument form stays silent.

## 4. A conversion that did not happen overwrote its destination

The scanner returned `0` / `0.0` / `""` when a field did not parse, and the store
was unconditional. So `$sscanf("abc", "%d", x)` set `x` to 0, and a partial parse
zeroed every destination past the last match. C leaves an unmatched argument
untouched and IEEE 1364 follows it — which is what makes the ordinary idiom work:

```verilog
x = fallback;
if ($sscanf(line, "%d", x) < 1)   // x is still fallback
```

The destination's current value is now passed **into** the scanner and handed
back when the field does not convert.

### Reading that value is the whole difficulty

A destination that has never been assigned has no `Place`, and declaring one
initialises it from `ParamKind::HiddenState` — persistent instance state the
backend does not provide for a scanf target. The generated module then segfaults
the simulator on its first evaluation. **Three** mechanisms hit exactly that:
`lower_expr` on the output reference, `use_place(PlaceKind::Var)`, and a `select`
on a separate *did-it-match* callback (which also added two blocks per
destination — Enhancement-505's lesson about control flow around a call whose
operands live elsewhere).

`get_place` distinguishes the two cases without guessing, and where there is no
prior definition the previous value **is** the implicit zero, so handing the
scanner a zero there is not an approximation. Passing the value as an argument
rather than branching keeps the callers branch-free.

## 5. A `{...}` that evaluates non-finite was applied as zero

numparam substitutes the **text** of an expression, and `{1/0}` substitutes `inf`,
which `INPevaluate` refuses. `INPgetValue`'s `IF_REALVEC` path honours that
refusal; its `IF_REAL` and `IF_INTEGER` paths took the same `error` and threw it
away, so the value landed as **0**:

```
.model nm nmos level=1 vto=0.5 kp={1/0}
   ->  i(vd) = -1.01e-12      (kp=100u gives -1.25e-4)
```

A transistor conducting nothing, eight orders of magnitude out, exit code 0, no
diagnostic. Writing `inf`, `nan` or `1e400` **directly** on the same card is
refused; so is `{1/0}` on an instance line, as a built-in device's value, in an
analysis argument, and through `altermod`. The `.model` card was the one path of
six that took it, for OSDI and built-in devices alike, and the conversion to zero
happened **before** the range check, so a `from` clause could not catch it either.

`INPgetValue` cannot simply return NULL for these types the way the vector path
does — none of its call sites test for NULL, so that would trade a wrong number
for a null dereference. The failure is recorded and the model-card path asks for
it, that being the one caller with no other way to find out. It reports and keeps
the parameter's **default**, which is what the surrounding `.model` conventions do
for an unknown or duplicated parameter.

## 6. Releasing a half-built expression announced an internal fault

`PT_PLACEHOLDER` is node type 0 and an ordinary leaf (`inpptree.h`: *"for
i(something)"*), but it was missing from the release switch, so freeing one fell
to the `default` arm and printed:

```
Internal error: unhandled parse-tree node type 0 while releasing an expression.
```

That reached users on an **error** path, where a partially built tree is released:
`B1 a 0 v={z}` with `.param z={1/0}` fails to parse, and the cleanup announced an
internal fault before the real, correct diagnostic. Like every other leaf it has
no child to release.

## 7. `save` called an operating-point variable a missing parameter

`INPaName` both **finds** a name and **asks** the device for its value, and any
failure of the second half arrived as the first half's message. An
operating-point variable is registered `IF_ASK` like any other askable parameter,
so the name resolves — but at `save` time no analysis has run, so the ask fails
and the user was told *"device has no parameter 'gv'"* about a name the device
does have and that `print` and `meas` both resolve. The netlist `.save` form
reported the same case correctly, so the two spellings of one request disagreed.
Only `E_BADPARM` now produces that message.

## Files

| file | change |
|---|---|
| `openvaf/hir_ty/src/validation/body.rs` | scan-format validation (`scanf_format_problem`), the `L026` check, `const_str`, `display_builtin_name` |
| `openvaf/hir_ty/src/validation.rs` | the `L026` report and lint arms |
| `openvaf/basedb/src/lints.rs` | `runtime_format_string` (documentation id 26) |
| `openvaf/hir_lower/src/expr.rs` | `lower_scanf` passes the destination's current value |
| `openvaf/hir_lower/src/callbacks.rs` | `Scan(kind)` takes one parameter |
| `openvaf/osdi/src/compilation_unit.rs` | the scan symbols' argument types |
| `openvaf/osdi/stdlib.c` | each scanner takes and returns a fallback |
| `ngspice-46/src/spicelib/parser/inpgval.c` | records a failed scalar conversion |
| `ngspice-46/src/spicelib/parser/inpgmod.c` | the `.model` path refuses a value that did not parse |
| `ngspice-46/src/spicelib/parser/inpptree.c` | `PT_PLACEHOLDER` is a leaf |
| `ngspice-46/src/frontend/outitf.c` | only `E_BADPARM` is "no such parameter" |
| `examples/scanfmt_examples/` | new suite |

## Verification

`scanfmt_examples` — **31 checks, both linear solvers**, of which **19 fail on the shipped
binaries**. Full regression **421/421**.

Every format the repository's own models use (`%d`, `%g`, `%s`, `%h`, `%o`, `%b`
and combinations) still compiles and scans identically;
`sscanf`, `stringio`, `fgetc`, `vafargcoerce`, `stresc` and `concat` were run
first, as the suites most exposed to these changes.
