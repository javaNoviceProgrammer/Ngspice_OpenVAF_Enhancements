# genvarloop_examples — Enhancement-407

A **`genvar` for-loop inside an `analog` block**, unrolled at elaboration.

The loop exists for one reason: a vectored net's bit-select must be a
**constant**, because each bit is its own simulator unknown. So this is rejected
outright —

```verilog
integer i;
for (i = 0; i < 4; i = i + 1) V(out[i]) <+ 1.0;   // bus bit-select index must be a constant
```

— and declaring `i` a `genvar` is how the LRM says *"unroll this at elaboration"*.
Until this release openvaf rejected that too, which left three examples taken
verbatim from the standard uncompilable.

```
python3 examples/genvarloop_examples/verify_genvarloop.py
```

## The oracle is the LRM's own

Page 117 ships the rolled `dac` **and** a hand-written `dac8` side by side — the
unrolled form *is* the specification. This example does the same: `rolled` and
`unrolled` are one weighted sum written both ways, and must agree exactly
(0.53125 = 0.8/2 + 0.4/4 + 0.2/8 + 0.1/16).

| module | what it shows |
| --- | --- |
| `rolled` / `unrolled` | the same sum, genvar loop vs hand-written — must be identical |
| `fanout` | a descending loop **contributing** per bit, which an `integer` loop cannot express at all |
| `sized` | the bound coming from a `parameter` frozen by shaping a declaration width (E-92) |

## What is and is not unrolled

Only a `for` whose index is a declared `genvar` and whose init, condition and
step all fold to integers. Everything else is untouched: an ordinary `integer`
loop stays a run-time loop, and a module-level `generate for` still elaborates
through its own path.

Bounds fold against the module's `localparam`s — including any `parameter` that
`fold_parameter_widths` has already **frozen** for shaping a declaration width
(E-92). That is exactly what the LRM examples rely on: `bits` sizes
`out[0:bits-1]`, so it is structural, frozen, and constant at elaboration.

Still rejected, each with its own message:

| shape | message |
| --- | --- |
| a genvar read as a value | *"cannot be used inside an analog block except as the index of a `for` loop…"* |
| bound is a settable `parameter` | *"the loop condition is not a compile-time constant integer"* |
| runaway loop | *"expands to more than 4096 statement copies"* |

## Acceptance

The three LRM examples — the page-91 ADC, the page-117 DAC and the page-134
genvar expression — move from `lrm_examples/limitations/` to `lrm_examples/va/`.
The ADC's output was checked bit-for-bit against a hand-unrolled copy, and the
page-117 DAC against the LRM's own `dac8`: both identical.
