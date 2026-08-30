# Enhancement-510 — an LRM function that crashed the compiler

```
python3 verify_lrmintrin.py
```

21 checks, both linear solvers. On the shipped binaries only **13 can run at all**
— the compiler crash prevents the rest — and 4 pass.

## What was wrong

Round 66 fuzzed 2089 constant-folded expressions. Exactly two crashed, for *every*
argument:

```
internal error: entered unreachable code: intrinsic log1p not found
```

`ln1p`/`expm1` lower to the libm routines of those names — the LRM lists them
apart from `ln`/`exp` for their precision near zero — and the builder asks for
them by name. The intrinsic registry declared neither, so codegen hit its own
`unreachable!`. Both spellings, every context.

**It survived because the suite that added them writes `$ln1p(0.5)`** — a
literal, which folds before codegen, so the intrinsic is never emitted. A
parameter or a probe reaches codegen; a literal does not. Checks [3]–[8] use both.

## Also fixed

| | before | after |
|---|---|---|
| a 32-link `localparam` chain in a compile-time table | refused as *"not a compile-time constant"* | builds |
| `atanh(-0.9999999)` folded vs run time | 1.3e−10 apart | identical, both exact |
| `pre_osdi -va` reporting a compiler exit of 101 | `exit 25856` | `exit 101` |
| any resistor `.model` card | `Error on .model mm : parameter (r) is not a number` | clean |

The resistor one is the oldest trap in this file: the first token of a `.model`
card is the model **type**, ngspice's resistor model has a parameter named `r`, and
`first_tok` already existed to handle that collision — the value checks just never
consulted it. A genuinely unparsable value is still refused; check [21] holds
[Enhancement-507](../../enhancements_doc/Enhancement-507.md)'s contract.

## Recorded, not fixed

Constant folding **loses the sign of zero** (`1.0/ceil(-0.5)` is +inf folded,
−inf at run time). The interner is bit-exact and `eval_unary` folds correctly, so
the loss is further down the constant emission path. Rewriting `Fneg` as `0 - x`
was tried and reverted — a constant operand never reaches that arm, so it fixed
nothing and only removed an optimisation.

## Withdrawn at fix time

A run-time out-of-range array index returning element 0 is documented at the
lowering site as *"DELIBERATE and load-bearing"* — the select chain exists so such
an index can never read out of bounds, and both NaN and splitting the parameter
case from the variable case were explicitly considered and rejected there.

## Files

| file | what it holds |
|---|---|
| `lrmi.va` | `ln1p`/`expm1`, both spellings, parameter and probe arguments |
| `deepchain.va` | a 40-link `localparam` chain feeding a compile-time table |
