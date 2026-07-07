# legacygen_examples — the legacy `generate` statement (Enhancement-88)

The obsolete Verilog-A 1.0 `generate <id> (start, end [, incr]) body`
analog-block statement (LRM Annex C.4) — a compile-time loop-unroll where
the body is replicated with the index substituted by each successive
constant value.

`flashadc.va` is the LRM page-438 flash-ADC (with a constant bus width; the
parameter-dependent width is a separate limitation). `generate i (3, 0)`
unrolls MSB-first, and the body mutates `sample` across iterations, so both
the index substitution and the unroll order matter. For a 0.7 V DC input
(fullscale 1.0) the 4-bit code is `1011`:

| bit | out[3] | out[2] | out[1] | out[0] |
|---|---|---|---|---|
| V | 1 | 0 | 1 | 1 |

The verify script also checks that a legacy generate with a **parameter**
bound is rejected with the targeted "must be elaboration-time constants"
diagnostic (a runtime-bindable parameter cannot shape a compile-time
unroll — the same scope decision as `generate for`/`generate if`).

Run: `python3 verify_legacygen.py` (6 checks).
