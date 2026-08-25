# Enhancement-480 — a check that could not fire where it mattered

Bug-hunt round 49, on ngspice and OSDI. Most of what follows is not a *missing*
check. The check was written, and something upstream of it made it unreachable.

## 1. The duplicate-parameter check on a `.model` card, twice over

**The list-full gate.** The test was written as

```c
if (mseen && nmid < n_mtrack) {      /* bound on the ARRAY, used as the gate */
    ...search mid[] for p->id, warn on a hit, otherwise record...
}
```

so once the list was full — every distinct model parameter seen once — a repeat
was never even **looked up**. A device with a single model parameter could
therefore never report one:

```
.model mm dut(r=1k r=4k)     ->  4k silently wins
```

for an OSDI model whose only model parameter is `r`. The instance-default branch
a few lines below has always had this right: it searches unconditionally and
bounds only the *insert*. It now reads the same way.

**The type token.** `.model` and the model name are consumed before the loop,
and for an OSDI card its type token too ("osdi models don't accept their device
type as an argument") — but a **built-in** card leaves the type in the line for
the parse. For most devices that is harmless here, because the type name is not
also a parameter name: `d` is not a diode parameter, which is exactly why
`.model dm d(is=1e-14)` was always clean. For `r`, `c` and `l` it is:

```
.model rmod r(r=1k)
Warning: Resistor: parameter 'r' is set more than once on this model card;
         only one value takes effect -- remove one.
```

on the most ordinary model card there is, telling the author to remove one of
the two things they wrote once. `r(res=1k)` collected the `aliasparam` wording
for the same reason. The type token is now skipped **for tracking only** — the
parse is untouched, so a genuine `r(r=1k r=4k)` still reports exactly once and
still takes 4k.

## 2. `.measure`'s edge count collided with a sentinel

The count is stored in a field whose sentinels are negative:

```c
#define MEASURE_DEFAULT          (-1)
#define MEASURE_LAST_TRANSITION  (-2)
```

so a number the user wrote was read as a request for something else. On a
triangle whose rising crossings are at 0.5 ms and 2.5 ms and whose falling ones
are at 1.5 ms and 3.5 ms:

| written | measured | why |
|---|---|---|
| `fall=1` | 1.5 ms | correct |
| `fall=-1` | **0.5 ms** | `-1` is "no fall given", so the first *crossing* is returned — a **rising** edge |
| `cross=-2` | 3.5 ms | `-2` is `CROSS=LAST` |
| `cross=-3` | fails | matches no crossing |

There is no reading under which a negative count means anything — crossings are
counted from one — so it is refused at the parse, before it can be mistaken for
a sentinel. The test is on the **token the user wrote**: by that point `LAST`
has already become `-2`, so testing the converted number would have let a
written `cross=-2` through as though it said LAST.

## 3. `%` disagreed with itself between evaluators

`.param` and a B-source both call `fmod`. The control-language `%` took
`floor(fabs())` of **both** operands and did an integer `%`, discarding the
fractional part and the sign of the dividend:

| | `.param` / B-source | `let` (before) |
|---|---|---|
| `(0.5) % 3` | 0.5 | **0** — the value vanished entirely |
| `(5.5) % 3` | 2.5 | 2 |
| `(5.5) % (2.5)` | 0.5 | 1 |
| `(-5) % 3` | −2 | 2 |

The manual lists `%` as "modulo" and gives a **separate** operator, `\`, for
"integer divide", so integer truncation was never what this one meant.

**Enhancement-273's range check is kept.** An operand beyond `INT_MAX` is still
refused with "argument out of range for mod", which `mathcast_examples` pins —
at that magnitude the spacing between representable doubles exceeds the divisor
and the answer would mean nothing. Only the `>= 1.0` floor on the divisor is
gone: it existed to stop `(int)0` dividing by zero, and `fmod` takes a
fractional divisor perfectly well. A zero divisor is still an error.

## 4. An unterminated control block was checked in the wrong place

`cp_evloop` is called once per **line** of a `.control` section, so its own
end-of-input check never saw the end of the *section*. An `if`, `while`,
`repeat` or `foreach` left open therefore swallowed every command after it —
they were collected into a block that never ran — and ngspice exited **0** with
no diagnostic, so a script that silently did nothing looked like one that
worked. A stray `end` has always been reported ("no block to end"); this is the
same imbalance seen from the other side.

The question is now asked once the section has been fed, by comparing the block
state **before and after**. Asking only afterwards was not enough: `reset`
inside a running `dowhile` re-enters the sourcing path, and at that moment a
block is legitimately open — the loop running the `reset` *is* that block. A
first version tore down the live structures there and `lhs_examples` hung on its
sampling loop. The report also does not call `cp_resetcontrol`, which left
`stackp` at 0 for a later `cp_popcontrol` and traded a silent failure for
"Internal Error: stack empty".

## 5. Guards that were genuinely absent

- **A transmission line's delay.** It is either given (`td`) or derived as
  `nl/f`, and nothing checked the inputs to that division. `f=0` made the delay
  non-finite and the AC analysis returned a table of `nan` — printed as an
  ordinary result, every row, rc 0, no diagnostic. A negative `z0` or `td` was
  taken at face value the same way. All three are refused at setup.
- **A switch's hysteresis.** `vh` sat beside `ron` and `roff` in the same model
  and was the only one of the three missing from the physics table. A negative
  hysteresis moves the switching point the *wrong way* — with `vt=0.5` the
  switch closed at 0.4 instead of 0.6. `vh` and `ih` are now listed.
- **The code-model PWL's breakpoint order.** It checked its array *lengths* and
  not the *order*, so `x_array=[0 2 1]` was accepted in silence and answered
  4.0, while the **source** `pwl` warns about exactly this mistake.
- **A duplicate parameter on a subcircuit call.** `X1 mid 0 s rv=4k rv=8k` took
  8k in silence, while an *unknown* name on the same line already warned
  (Enhancement-475).
- **A `.dc` step larger than its span.** `dc v1 0 0.1 1` printed an empty table
  and exited 0. A warning, not a refusal — the sweep is well-formed and the
  start point is arguably a legitimate sample.

## 6. A code-model message that could not fire in half the analyses

The limiter's reversed-limits message carried a guard borrowed from CLIMIT,
where it keeps a *signal-dependent* message quiet while the inputs are still
zero:

```c
if ((INIT != 1) && (0.0 != TIME))
    cm_message_send(limit_order_error);
```

`TIME != 0` is never true in an `op` or a `dc` sweep. So a limiter whose limits
were written the wrong way round said **nothing** there — producing the transfer
curve 5, 5, 5, 5, −5 in silence — and said it **214 times** in a transient, once
per timestep. Both faults are properties of the model card and cannot change
during a run, so they now fire at `INIT`: one message per instance, wherever the
instance is used.

## What this deliberately does not change

Each was reported by the round and withdrawn on reading the code; the suite pins
them so a later round does not "fix" them.

- **`vector(-4)` still equals `vector(4)`**, and `vector(0)` still yields one
  element. `cx_vector`'s own comment documents "a vector from 0 to the
  **magnitude** of the argument", and the `len==0 → 1` clamp beside it is
  explicit.
- **`pulse` with a negative `TR`/`TF`/`PW`/`PER`.** `vsrcload.c` documents "TR
  negative or 0 --> TR = CKTstep": negative means *use the default*.
- **`.dc` with `start == stop` computing no rows.** Enhancement-426 records that
  13 decks in `examples/` depend on that form being accepted, and this must not
  change what they do.
- **`ac lin 1`.** `span.c` records that nine cards use `lin 1` as a legitimate
  single frequency.

## And one fix built, measured, and reverted

The constant plot **is** writable: `let pi = 3` redefines π for the rest of the
session — `sin(pi/2)` becomes 0.9975 — while `destroy const` is refused on the
line before, so the plot is plainly meant to be protected.

The fix looked simple: send the write to the current plot instead, so the
constant keeps its value and the local name shadows it. It was built, and the
regression hung. **`run` is itself a built-in constant**, and `lhs_examples`
writes `let run = 0` and loops on it; with the shadow in place the write went to
a local while reads still resolved to the constant first, so the `dowhile` never
advanced. The two paths have to agree, and making them agree means changing name
resolution across the interpreter — far wider than the evidence here. Reverted,
with check [13] pinning the behaviour as it stands so a later attempt starts
from a recorded baseline rather than a rediscovery.

## Verification

`examples/gatecheck_examples/verify_gatecheck.py` — **47/47**. Against the
shipped pre-fix binary the same suite scores **24/47**: 23 checks discriminate,
and everything passing on both is either a pinned decision or a control that had
to keep working.

The checks target the *agreement* rather than the symptom — that a written
number is not read as a sentinel, that one operator means the same thing in two
evaluators, and that a parameter fault is reported the same way in `op`, `dc`
and `tran`.

Full regression, both solvers. ngspice-only.
