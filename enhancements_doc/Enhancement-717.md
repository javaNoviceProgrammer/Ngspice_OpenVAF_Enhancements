# Enhancement-717: the automatic derivative of a quotient is formed over the divisor, not over its square, and its last division is emitted without the derivative fast-math flags — `x / (y + 1e-300)` at the V = 0 operating-point guess had the right value and a NaN Jacobian entry (0/0, the square underflowing), and so had `exp(−1/(x² + 1e-300))`; LLVM's instruction combiner had re-formed the square from the new shape until the flags came off

**Scope:** F3 of the
[correctness campaign of 2026-09-25](../docs/bug_hunts/2026-09-25_openvaf-r-correctness-campaign.md).
**Compiler only.** `mir_autodiff/src/builder.rs` (`gen_div_derivative`, the division's
cache entry, `keep_exact`); the expected derivative MIR of `mir_autodiff/src/builder/tests.rs`
and of `sim_back`'s diode snapshots refreshed to the new shape (a differentiated division is
four instructions shorter).
[`examples/hypotzero_examples/`](../examples/hypotzero_examples/) (section [4], 6 checks,
21 per solver). The hunt page.

**Suites:** `hypotzero` 21 of 21 per solver (17 of 21 on the E-714 binaries),
`vafautodiff` 18 of 18, `physcheck`, `stdaudit`, `vafcodegen`, `filterforms` 100 of 100,
`arrayscale` 38 of 38, `lrmfilters`, `complexpole` and `warmstart` unchanged; `osdilimit`
12 of 12 per solver with its legacy-path check re-pinned (below); the
campaign's own harnesses — `ddx` of 61 functions against finite differences, 84 Jacobian
entries against dc differences, the 22 singular-point derivatives — rerun with no
non-finite value left; the compiler workspace tests green apart from the three
pre-existing sourcegen drift failures (221 passed), no build warnings; full sweep, run
alone.

## What was wrong

At V(a) = V(b) = 0, the operating-point guess of every analysis (`cc/G/sing.va`,
`cc/K/q.va`):

| expression | value | ∂/∂V(a) | ∂/∂V(b) |
|---|---|---|---|
| `V(a) / (V(b) + 1e-300)` | 0 | 1e300 | **NaN** |
| `exp(-1.0 / (V(a)*V(a) + 1e-300))` | 0 | **NaN** | 0 |
| `V(a) / (V(b) + 1e-160)`, `1e-155`, `1e-150` | 0 | 1e160 … | 0 |

The autodiff formed `(f/g)' = f'/g − f·g'/g²`, caching `g·g` per division
(`mir_autodiff/src/builder.rs`, `inst_cache`, `Opcode::Fdiv`). For a divisor below the
square root of the smallest denormal, about 2.2e-162, `g·g` is 0, and with a zero
numerator the second term is `0 · 1 / 0`: NaN in a Jacobian entry whose value is 0. A
guard of 1e-160 or larger has a denormal square and was fine; the `1e-300` kind, and
the `1/(x² + tiny)` shape with such a `tiny`, were not. A NaN entry poisons the LU
factorisation, and the operating point fails on the first Newton iteration — the
same failure mode E-580 closed for `hypot` and `atan2` at the origin.

## What changed

**The quotient rule reuses the quotient** (`gen_div_derivative`):

```
(f/g)' = (f' − (f/g)·g') / g
```

`f/g` is the instruction's own result, already computed; every intermediate stays at
the quotient's scale and `g` is divided by once. A divisor constant in the unknown is
the plain `f'/g`, as before; the division's cache entry (`g·g`) is gone. The arithmetic
is the same derivative to rounding — the campaign's 61-function `ddx` sweep and its
84 Jacobian entries read as before, and an ordinary quotient's derivatives are the
analytic ones to 1e-9 in the suite.

**The last division is emitted without the derivative fast-math flags**
(`keep_exact`). The first cut of the rewrite still read NaN: `mir_llvm` gives every
instruction the autodiff inserts the `Partial` fast-math flags — `reassoc`, `nnan`,
`arcp` — read off the sign of its source location, and with `reassoc` and `arcp` on
the outer division LLVM's instruction combiner rewrote `(f' − (f/g)·g') / g`, where
the numerator is `−(x/g)·g'` at f' = 0, back into `−x·g' / (g·g)` — the square the
form exists to avoid, visible in `--dump-ir` as `fmul %g, %g` feeding the `fdiv`. The
autodiff now gives that one instruction the magnitude of its location, so the code
generator emits it with no flags and the two divisions stay two divisions
(`fdiv %19, %17` after `fdiv reassoc nnan arcp %18, %17`); the diagnostics' file
position is unchanged. One unflagged instruction per differentiated division costs
nothing measurable.

## Verification

`hypotzero` section [4]: `x*y/(y*y + 1e-300)` solves at (0, 0) with a zero
small-signal conductance and a zero dI/dV(b) — the entry that was NaN — and a
transient sweeping V(a) through the origin runs; `exp(-1/(x*x + 1e-300))` solves at
0 with a zero conductance; an ordinary quotient `(x+0.3)/(y+0.7)` at (0.3, 0.4) has
dI/dV(a) = 1e-3/1.1 and dI/dV(b) = −1e-3·0.6/1.21 through the rewritten rule. The 15
checks of E-580 unchanged; on the E-714 binaries the four underflow checks fail with
"op failed", the two ordinary ones pass.

By hand: the table above on the new compiler (−0, 0, and the unchanged rows); the
same four forms as `ddx` of a variable and of the expression itself, with and without
a following reassignment (the shape that had exposed the reassociation); the
optimised IR of the derivative before and after `keep_exact`; the campaign's
harnesses B, C and G; the nine suites; the workspace tests; the sweep.

**The one sweep failure, and what it was.** `osdilimit`'s check that the *un-limited*
Newton path (`.option noosdilim`, E-543's opt-out to the path its limiting replaced) reaches the same
operating point as the limited one on a 100-stage BSIM4 inverter chain failed under KLU
on this build: the legacy path ran off to 7e54 V. BSIM4's small-signal Jacobian differs
between the E-714 compiler and this one by one unit in the last place (3e-16 relative)
and its currents not at all; the un-limited path on that chain turns out to sit on a
knife edge on *both* compilers:

| chain, KLU, un-limited | E-714 model | this model |
|---|---|---|
| 100 stages, as the suite runs it | converges, 139 iterations | 7.5e54 V |
| the same with `vin = 1e-9` V | 8.6e28 V | converges, 138 |
| the same with `vdd = 1.2000001` | converges | converges |
| 50 stages | 6.5e63 V | converges |
| 50 stages, `vin = 1e-9` V | converges | 3.9e59 V |
| 20 stages, `vin = 1e-9` V | 1.1e22 V | converges |

— a nanovolt at the input, or the last bit of a conductance, decides between two
singular-matrix fallbacks. The limited path (the default) converges in 8 iterations on
every one of these. The check now asserts what holds: when the legacy path converges it
reaches the limited op to 1e-9 V, and when it diverges that is recorded as the knife
edge rather than counted against the compiler; the "> 100 iterations, gmin stepping"
check that it *returns* is unchanged.

## What this does not do

- It does not change the derivative fast-math policy. The `Partial` mode's bits are
  `0x01 | 0x02 | 0x10` — LLVM's `AllowReassoc`, `NoNaNs` and `AllowReciprocal` — while
  the comment beside them says "Reassoc | Reciprocal | Contract" (`AllowContract` is
  `0x20`): the derivative code has carried `nnan` since the first import, not
  `contract`. A NaN that does reach derivative code is undefined under `nnan` rather
  than a NaN; whether the mode should be what its comment says, or drop reassociation
  altogether, is a separate decision with a numerical footprint on every model, and
  is recorded here and on the campaign page rather than made in passing.
- A divisor that is exactly zero is still a division by zero; the rewrite changes
  nothing at a true singularity.
- The E-489 clamps of `pow` and `sqrt` at zero are as they were.
