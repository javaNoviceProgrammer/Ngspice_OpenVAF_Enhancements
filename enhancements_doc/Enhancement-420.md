# Enhancement-420 — six things openvaf-r accepted and then quietly got wrong

A round-26 hunt over openvaf-r produced six findings and not one crash, hang or
ICE. Every one is the same shape: **the compiler accepted the source, the
simulator ran it, and the construct either returned a wrong number or did
nothing at all.** Nothing was reported at either end.

That shape is worth naming, because it is the one this project keeps finding and
the one users cannot search for. A crash tells you where to look. A model that
builds clean, simulates, and returns 1 where the standard says 0 tells you
nothing — you read the source, it says what you meant, and the answer is wrong.

Five of the six are compile-time checks. The sixth, `**`, is a wrong answer.

## The substantive one: `2 ** -1` was 1, and the standard says 0

`**` was typed **real unconditionally**. Both operands were promoted to float,
`llvm.pow.f64` ran, and the real result was rounded back **away from zero**
wherever an integer was wanted. So `2 ** -1` computed 0.5 and landed on **1**.

IEEE 1364-2005 §5.1.5 Table 5-6 defines integer `**` exactly:

| base | exponent > 0 | exponent = 0 | exponent < 0 |
|---|---|---|---|
| > 1 or < −1 | the power | 1 | **0** |
| 1 | 1 | 1 | 1 |
| −1 | ±1 by parity | 1 | ±1 by parity |
| 0 | 0 | 1 | `'x` (0 as an integer) |

and §5.1.5 also fixes the *type*: the result is real only if either operand is
real. Both integer, integer result. openvaf had neither half.

The fix is both halves, because either alone is wrong:

* `infere_bin_op` gives `Power` the two-candidate `NUMERIC_BIN_OP` instead of
  the single `REAL_BIN_OP`, so two integer operands now select `INT_OP`.
* `lower_bin_op` grows an `INT_OP` arm, `lower_int_pow`, implementing Table 5-6.

**A signature change alone would have left the same float `pow` sitting behind
an integer type.** That trap is already on record here: Enhancement-376 changed
`$dist_*` to integer and needed the lowering `ficast` too, or it read 0.

`lower_int_pow` is branchless. Every operand is a comparison or a multiply by
0/1, so the constant folder collapses the whole thing when the operands are
literals — but the reason it is written that way is sharper than tidiness:

> **The float path must never see the negative exponent.** `pow(0, -1)` is
> infinity, and `llvm.lround` of an infinity into an i32 is undefined. The
> exponent handed to `pow` is forced to 0 when it is negative, so the infinity is
> never *produced* rather than merely never *used*.

That mattered. The differential against the previous build turned up a **second
defect the hunt had not reported**: `0 ** -1` returned **2147483647** — exactly
`lround(inf)` saturating. Table 5-6 calls it `'x`, which is 0 in an integer
context, and that is what it returns now.

The real path is untouched: `2.0 ** -1` is still 0.5, and so are `2.0 ** -1.0`
and `2 ** -1.0`.

### The one further consequence, stated rather than discovered later

Making `**` integer-typed also changes what an expression *containing* it does:

```verilog
1 / (2 ** 3)     // was 0.125, is now 0
1.0 / (2 ** 3)   // 0.125, unchanged
```

This is not a side effect to apologise for — it is the same change. `1 / 8`
with two integer operands has always truncated to 0 in this compiler (round-26
re-verified `-7/2` as −3), so the old behaviour was `**` being the one
arithmetic operator that silently escaped integer arithmetic. The new behaviour
makes it agree with `/`, `*` and `+`.

It is nonetheless the only way an existing model can change answer, so it is
measured both ways in the example suite rather than left to be discovered. The
40-model corpus contains no `**` at all, and the 337-example regression is
unchanged.

## Five constructs that were accepted and then degenerate

All five are checked in `hir_ty/src/validation/body.rs`, beside the checks
Enhancement-396, -399 and -405 put there, and all five fold **literals only**
(`const_num`). A value computed at run time is the model's own business — that
narrowness is deliberate and shared with every neighbouring check.

### `laplace_*` with an identically-zero denominator

`laplace_nd(V(a,b), '{1.0}, '{0.0})` is the transfer function 1/0. It compiled
clean and then killed the operating point with

```
Transient op failed, timestep too small
```

which names neither the model nor the call, so the author debugs the netlist.

Rejected only when **every** coefficient folds to a literal zero, and only for a
**coefficient** list. Three legitimate things sit right next to it and all still
compile:

* `'{0.0, 1.0}` — the denominator `s`, a pure integrator.
* an all-zero **root** list (`laplace_np`, `laplace_zp`, `zi_np`, `zi_zp`) —
  poles at the origin, equally legitimate.
* a concatenation `{...}` — which `laplace_*` lowers correctly, as
  Enhancement-399 established when it declined to reject them here.

### `zi_*` with a zero sampling period

`zi_nd(V(a,b), '{1.0}, '{1.0}, 0.0, 0.0)` compiled, ran, and returned the
**input unchanged** — y = 1.0 for a unit input. T is what the whole z-domain
filter is defined against; a filter with T = 0 is not a filter. A negative
period is no better defined, and both are now rejected.

### `last_crossing` with a direction that is not a direction

The LRM defines three: +1 rising, −1 falling, 0 either. `last_crossing(V(a,b) −
0.5, 7)` was accepted and behaved as **0**, returning the same 5.0e-07 the
`either` form gives. A direction is a spelled-out constant in every real model,
so the typo is catchable where it is written.

### `$discontinuity` with a degree below −1

The degree is the order of the derivative that jumps: 0 the value, 1 the slope.
`$discontinuity(-3)` names nothing and was silently handled as an ordinary
non-negative degree.

**The first version of this check was `require_non_negative`, and it was wrong.**
`$discontinuity(-1)` is the LRM's marker for a *limiting* discontinuity, written
inside a `$limit` function to say the iterate was moved — it appears verbatim in
the LRM's own page-261 `spicepnjlim` diode, and `lower_builtin` already routes
it to `LimDiscontinuity`. It is implemented, not merely tolerated.
`examples/lrm_examples` compiles that page and failed on the first regression
sweep. The check that ships rejects only what is **below** −1.

That is the second time in this release that the regression, not the reasoning,
set the boundary — see the note on scope at the end.

### `ac_stim` naming an analysis that can never match

The project's most repeated shape: **handled for one construct, silently not for
its sibling.**

| construct | unmatchable name | diagnostic |
|---|---|---|
| `analysis("nosuch")` | since E-399 | `L021` |
| `$limit(.., "nosuchlimit", ..)` | since E-396 | `L020` |
| `ac_stim("nosuch", 1, 0)` | — | **nothing** |

ngspice gates the stimulus on `strcmp(src->analysis, "ac")` in `osdiacld.c`, so
an unmatchable name leaves the source **permanently inactive**: the model has an
AC source that never sources anything. `ac_stim` now runs the same
`check_analysis_name` helper `analysis()` does, and the note the diagnostic
prints is specific to it — the consequence is an inactive source, not the dead
branch `analysis()` produces.

A warning rather than an error, for the same reason L020 and L021 are: the set
of analysis names is simulator-defined, and another OSDI consumer may match more.

The example suite does not take the diagnostic's word for the consequence. It
builds a one-terminal `V(out) <+ ac_stim(name, 1, 0)` and runs a one-point `.ac`:
`mag(v(out))` is **1.0** for `"ac"` and **exactly 0.0** for `"nosuch"`.

## Scope: two places the evidence, not the reasoning, drew the line

Both are recorded because a checker that rejects too much is worse than one that
rejects nothing — it breaks working models.

1. **`$discontinuity(-1)` is legal.** Covered above. `require_non_negative` was
   the obvious shape and it broke the LRM's own example.
2. **`ac_stim("tran")` is deliberately NOT warned.** ngspice's gate is `"ac"`
   alone, so `"tran"` is inactive there too — but the LRM lets a stimulus name
   any analysis, and another OSDI consumer may honour more than ngspice does.
   The claim the evidence supports is "this name can never match anywhere", so
   that is the only claim the check makes. A name that ngspice specifically
   ignores remains an open item, not a silent one.

## Verification

* **`examples/vafdegen_examples` — 91/91.** Roughly half is the *accept* half:
  every legitimate laplace denominator, all three legal `last_crossing`
  directions plus the no-direction form, all four legal `$discontinuity` degrees
  including −1 both bare and inside a `$limit` function, runtime-valued
  arguments in every checked position, and `ac_stim("ac")`.
* **Table 5-6 is measured, not asserted.** Twenty integer cases and five real
  ones are read back as opvars from a real ngspice operating point, plus eight
  more with the base and exponent supplied as **runtime parameters** rather than
  literals — so the lowering is exercised, not just the constant folder.
* **Full regression 336/336**, both solvers, plus the new example at 337.
* **40-model corpus differential.** Every model in `integration_tests/` compiled
  with the previous shipped binary and this one: **zero** changed diagnostics.
  (The corpus contains no `**` operator at all, so it bounds the validation
  changes, not the type change; `vafdegen` and `lrm` bound that.)
* **`cargo test --features llvm18`** clean — no MIR or OSDI snapshot moved.
* Every finding was reproduced on the **shipped** binary first: all five
  validation cases compile silently there, and `2 ** -1` returns 1.

## Found by

A round-26 hunt over openvaf-r, run against the shipped binary. The hunt also
withdrew six of its own expectations on evidence rather than reporting them, and
verified a large surface clean — the autodiff Jacobian across 14 functions
(matching a deck-perturbed finite difference to ~1e-10), integer overflow,
division and rounding semantics, both shift operators, `**` precedence against
unary minus, and the existing validation for parameter cycles, ranges, analog
functions, instantiation, events, branches and format strings.

The seventh defect in this release, `0 ** -1` returning `INT_MAX`, came from the
differential rather than the hunt — which is the argument for running one.
