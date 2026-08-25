# Enhancement-480 — a check that could not fire where it mattered

```
python3 verify_gatecheck.py
```

47 checks. 24/47 against the pre-fix binary.

## The shape

Bug-hunt round 49. Most of these are not *missing* checks. The check was
written, and something upstream of it made it unreachable:

| the check | what stopped it |
|---|---|
| duplicate parameter on a `.model` card | gated on the tracking list not being **full**, so a device with one model parameter could never report a repeat |
| the same check | counted the model **type token** as a parameter, so `.model rmod r(r=1k)` was told to "remove one" |
| the limiter's reversed limits | gated on `TIME != 0`, never true in `op`/`dc` — silent there, 214 messages in a transient |
| an unterminated control block | tested per **line** of a `.control` section, never at the end of the section |
| `.measure`'s edge count | the struct's "not given" and "LAST" sentinels are `-1` and `-2`, so a written `fall=-1` *was* "not given" |

## The sentinel collision is the sharpest one

`.measure` stores its edge count in a field whose sentinels are negative:

```c
#define MEASURE_DEFAULT          (-1)
#define MEASURE_LAST_TRANSITION  (-2)
```

so on a triangle whose rising crossings are at 0.5 ms and falling at 1.5 ms:

| written | before | why |
|---|---|---|
| `fall=1` | 1.5 ms | correct |
| `fall=-1` | **0.5 ms** | read as "no fall given" → the first *crossing*, a **rising** edge |
| `cross=-2` | last crossing | read as `CROSS=LAST` |
| `cross=-3` | measure fails | matches no crossing |

A count is now refused before it can be mistaken for a sentinel, and the test is
on the **token the user wrote** — by the time the value is a number, `LAST` has
already become `-2`, so testing the number would have let a written `cross=-2`
through as though it said LAST.

## The false positive is the mirror image

`.model` and the model name are consumed before the parameter loop, and for an
OSDI card the type token too — but for a built-in the type token is left in the
line for the parse. For most devices that is harmless, because the type name is
not also a parameter name (`d` is not a diode parameter). For `r`, `c` and `l`
it is:

```
.model rmod r(r=1k)
Warning: Resistor: parameter 'r' is set more than once on this model card;
         only one value takes effect -- remove one.
```

on the most ordinary model card there is. The type token is now skipped for
tracking only — the parse is untouched, so a genuine `r(r=1k r=4k)` still
reports exactly once.

## `%` disagreed with itself

`.param` and a B-source both call `fmod`; the control-language `%` took
`floor(fabs())` of both operands and did an integer `%`:

| | `.param` | `let` (before) |
|---|---|---|
| `(0.5) % 3` | 0.5 | **0** — the value vanished |
| `(5.5) % 3` | 2.5 | 2 |
| `(-5) % 3` | −2 | 2 |

The manual lists `%` as "modulo" and gives a **separate** operator, `\`, for
"integer divide". Enhancement-273's range check is kept — an operand beyond
`INT_MAX` is still refused, which `mathcast_examples` pins, and at that
magnitude the spacing between doubles exceeds the divisor anyway.

## Guards that were genuinely absent

- a transmission line's delay is `nl/f`, and nothing checked either: `f=0` gave
  a table of `nan` printed as an ordinary AC result, every row, rc 0;
- a switch's `vh` sat beside `ron`/`roff` in the physics table and was the only
  one of the three not listed;
- the code-model PWL checked its array **lengths** but not the **order** of its
  breakpoints, while the *source* `pwl` warns about exactly that;
- a duplicate parameter on a subcircuit call, where an *unknown* one already warned.

## Deliberately NOT changed

Each was reported by the hunt and withdrawn on reading the code:

| | why it stays |
|---|---|
| `vector(-4)` == `vector(4)` | `cx_vector`'s comment documents "a vector from 0 to the **magnitude** of the argument"; the `len==0 → 1` clamp beside it is explicit |
| `pulse` with negative TR/TF/PW/PER | `vsrcload.c` documents "TR negative or 0 → TR = CKTstep" — negative means *use the default* |
| `.dc` with `start == stop` computing no rows | E-426 records that 13 decks in `examples/` depend on that form being accepted |
| `ac lin 1` | `span.c` records that nine cards use `lin 1` as a legitimate single frequency |

## And one fix built, measured, and reverted

The constant plot **is** writable: `let pi = 3` redefines π for the session while
`destroy const` is refused on the line before. Shadowing the write into the
current plot protects the constant — and breaks name resolution, because reads
still resolve to the constant first. `run` is itself a built-in constant, and
`lhs_examples` writes `let run = 0` and loops on it: with the shadow in place
its `dowhile` never advanced and the suite hung. Making this safe means changing
resolution across the interpreter, which is far wider than the evidence. Check
[13] pins the behaviour as it stands so a later attempt starts from here.
