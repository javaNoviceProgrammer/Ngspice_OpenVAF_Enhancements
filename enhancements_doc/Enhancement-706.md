# Enhancement-706: `0.0/0.0` is a compile error, `1.0/0.0` folds to the infinity it is, and a constant call that overflows is named — the undefined quotient folded to NaN in silence and the NaN then passed every constant-argument check, an infinite delay was "not a constant" to the delay check, and `exp(1000.0)` and `pow(10.0, 400.0)` folded to infinity without a word

**Scope:** F6 of the
[robustness campaign of 2026-09-23](../docs/bug_hunts/2026-09-23_openvaf-r-robustness-campaign.md)
(and the literal half of the last bullet of its F10). **Compiler only.**
`hir_ty/src/validation/body.rs`: the `/` arm of `validate_expr` (the undefined
quotient), the `exp`/`sinh`/`cosh` arm and the overflow branches of the `pow` and `**`
arms (a finite constant whose result is past the largest double), `require_positive`
and `require_non_negative` (a non-finite constant is named as one), and `const_num_in`
(a non-zero constant over a constant zero folds to IEEE's infinity).
[`examples/powguard_examples/`](../examples/powguard_examples/) (19 checks, 37 in all).
The handbook's operators row, the compliance document's domain paragraph, the hunt
page.

**Suites:** `powguard` 37 of 37 (25 of 37 on the E-704 binaries), `vafdivzero` 5 of 5
(E-333's contract — `1.0/0.0` is IEEE arithmetic and compiles — is kept), `deckdomain`,
`constguard`, `domainrt`, `rtdomain`, `mathguard`, `hunt13slips` (E-640), `fmtdiag` 40
of 40, `constfold`, `intrange`, `lrmexpr`, `lrmfilters`, `langguard` 132 of 132,
`diagslips` 46 of 46 and `multimod` 28 of 28 unchanged; the compiler workspace tests
green apart from the three pre-existing sourcegen drift failures (221 passed), no
build warnings; full sweep 532 of 532, run alone.

## What was wrong

The campaign wrote every constant expression that produces a NaN or an infinity and
read what the compiler said:

| expression | before | now |
|---|---|---|
| `ln(0.0)`, `sqrt(-1.0)`, `pow(0.0, -1.0)`, `asin(2.0)` … | compile error naming the domain (E-455, E-489) | unchanged |
| `1/0`, `1.0 % 0.0` | compile error (E-333, E-578) | unchanged |
| `0.0/0.0` | **NaN, silent** | error: the quotient is undefined; the result would be NaN |
| `1.0/0.0` | **+∞, silent, and not a constant** | IEEE's infinity, folded; legal on its own, refused by a consumer that needs a finite number |
| `exp(1000.0)`, `sinh(1000.0)`, `cosh(1000.0)`, `pow(10.0, 400.0)`, `10.0 ** 400.0` | **+∞, silent** | error: exceeds the largest double; the result would be infinite |
| `1e400` | lexer error, "too large to represent" | unchanged |
| `absdelay(V(p,n), 1e308*10)` | "the delay must not be negative, but is inf" | "the delay must be a finite number, but is inf" |

The NaN then travelled: `absdelay(V(p,n), 0.0/0.0)`, `transition(V(p,n), 0.0/0.0)`,
`slew(V(p,n), 0.0/0.0)`, `$bound_step(0.0/0.0)`, `$limit(V(p,n), "pnjlim", 0.0/0.0,
0.7)`, `$rdist_normal(s, 0.0, 0.0/0.0)`, `flicker_noise(1e-12, 0.0/0.0)`,
`white_noise(0.0/0.0)`, `parameter real q = 0.0/0.0 from [0:1]`, `parameter real q = 1
from [0.0/0.0:1]`, `parameter real q = 1 exclude 0.0/0.0` and `laplace_nd(V(p,n), '{1},
'{1, 0.0/0.0})` all compiled in silence, where the same argument written as `-1` is
refused ("the delay must not be negative, but is -1"). At run time, measured on a 1 V
pulse: a NaN delay is a zero delay, a NaN `maxdelay` holds the output at 0 for the whole
run, a NaN transition time is the default ramp, a NaN slew rate is no limit, a NaN
`$bound_step` is ignored, a NaN Laplace coefficient is refused as "zero" and a NaN
standard deviation, `idt` initial condition or parameter default fails the operating
point with "timestep too small".

**Where.** `const_num_in` — the constant evaluator every argument check reads — leaves a
zero divisor unfolded on purpose, "so the division checks report it themselves"; but
only the integer division (E-333, in inference) and the modulus (E-578) had a check, and
the real `/` had none. So `0.0/0.0` was "not a constant" to every argument check and
reached the MIR folder, which folds `fdiv` to the IEEE result; and `1.0/0.0` was not
folded either, so `absdelay(V(p,n), 1.0/0.0)` slipped past `require_non_negative`
although that check refuses a non-finite constant it can see. `exp`, `sinh`, `cosh` and
the real `pow`/`**` are not folded by `const_num_in` at all, and no check judged their
overflow; `1e308*10` is folded, and the checks that saw it called the infinity "negative".

The hunt page wrote that the run-time projections of E-651 test `x < 0` and so pass a
NaN. Reading them, they were already written the other way round (`fge`/`fgt`, false
for NaN, with a comment saying so at each site): the NaN delay became a zero delay
because that IS the projection — a run-time quantity is projected onto its domain in
silence, by E-651's rule — and the literal reached it only because the compile-time check
never saw it. The whole gap is at compile time.

## What changed

1. **The undefined quotient is refused where it is born.** In `validate_expr`, a real
   division whose operands are both constants, the divisor 0 and the dividend 0 (or
   NaN), is an error at the division: "/: the operands are both 0, so the quotient is
   undefined; the result would be NaN". A `localparam` is folded like any constant; an
   overridable `parameter` is not, so `parameter real z = 0.0; … V(p,n)/z` compiles as it
   always did.
2. **An infinity is a value, and its consumer judges it.** A non-zero constant over a
   constant zero now folds in `const_num_in` to ±∞ (IEEE 754, and Enhancement-333's
   deliberate contract: `vafdivzero_examples` writes `f = 1.0/0.0` and compares against
   it). A plain use stays legal. A consumer that needs a finite number now sees the
   value and says so: `absdelay(V(p,n), 1.0/0.0)` and `absdelay(V(p,n), 1.0/z)` with a
   `localparam` zero are "the delay must be a finite number, but is inf", `$bound_step`
   and a `maxdelay` likewise, and `parameter real q = 1.0/0.0` is Enhancement-640's "the
   default of parameter 'q' overflows to infinity", reached at last. The integer division
   by zero stays unfolded (E-333 reports it) and so does `0.0/0.0` (this reports it), so
   neither produces a second complaint downstream.
3. **A finite constant whose result is past the largest double is refused.** `exp`,
   `sinh` and `cosh` with a constant argument, and `pow`/`**` with two constant operands
   inside the domain, are errors when the result is infinite: "exp: the argument is
   1000, for which exp exceeds the largest double (about 1.8e308); the result would be
   infinite"; "pow: the base is 10 with the exponent 400, for which pow exceeds …".
   `exp(700.0)`, `pow(10.0, 300.0)` and `exp(-1000.0)` (0) compile.
4. **A non-finite constant is named as one.** `require_positive` and
   `require_non_negative` — the delay, the step bound, the standard deviation, the noise
   power, the event tolerances and their kin — say "must be a finite number, but is inf"
   where they said "must not be negative, but is inf".

## Verification

`powguard_examples` (Enhancement-489's constant-domain suite) gains checks [19]–[37]:
`0.0/0.0` refused with its sentence; `exp(1000.0)`, `cosh(1000.0)`, `pow(10.0, 400.0)`
and `10.0 ** 400.0` refused as exceeding the largest double while `exp(700.0)` and
`pow(10.0, 300.0)` compile; `1.0/0.0` in an expression and `V(a,b)/0.0` legal;
`absdelay(V, 1.0/0.0)` and `absdelay(V, 1.0/z)` with a `localparam` zero refused as an
infinite delay, the `parameter` form accepted, `parameter real q = 1.0/0.0` refused by
E-640's rule; `absdelay(V, 1e308*10)` named finite-not-negative; `absdelay(V,
0.0/0.0)`, a `from [0.0/0.0:1]` bound and a `'{1, 0.0/0.0}` Laplace denominator refused
before any run time; and `1/0` and `1.0 % 0.0` keep E-333's and E-578's sentences.
Twelve of the nineteen fail on the E-704 binaries (25 of 37). By hand: the campaign's
F6 probe set, every row of the table above.

## What this does not do

- `*`, `+` and `-` on constants are folded but not judged at the operation: `x =
  1e308*10;` compiles and `x` is +∞ (IEEE). Enhancement-640 judges the value in a
  parameter default and the argument checks judge it as an argument, which is where it
  does harm.
- A deck-fixed real division by zero has no run-time guard (`parameter real z = 0.0;
  … 1.0/z` runs as IEEE arithmetic); Enhancement-509's run-time guard covers `%`. A
  run-time NaN reaching a projection is projected in silence, as Enhancement-651
  designed.
- `ln(0.0)` is −∞ and stays Enhancement-455's domain error; the new overflow arm covers
  the functions whose domain is the whole real line.
- The message names the operation and the value; it does not cite an LRM clause,
  because LRM 4.2.4 makes only the modulus by zero an error and says nothing of a real
  division by zero.
