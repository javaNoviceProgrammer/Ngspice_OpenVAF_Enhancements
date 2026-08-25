# Enhancement-479 — a check that only ever saw a literal

Bug-hunt round 48, on openvaf-r. Every value guard in the compiler decided "is
this argument a number?" by looking at the *syntax* of the argument, so it
recognised a literal and nothing else. Naming the value made every guard skip.

## 1. `const_num` had no arm for a path

The same negative noise power, three ways:

```verilog
white_noise(-1e-12)                          // rejected
white_noise(-1e-12*1.0)                      // rejected -- folding IS applied
localparam real q = -1e-12; white_noise(q)   // ACCEPTED, silently
```

The third line is the damning one. A `localparam` is a compile-time constant the
LRM forbids from being overridden, so the compiler knows its value exactly — and
it demonstrably folds arithmetic, since the second line is caught. `const_num`
simply had arms for literals, unary minus and the four binary operators, and no
arm for `Expr::Path`.

One missing arm, eleven guard sites:

| guard | literal | localparam (before) |
|---|---|---|
| `$bound_step` | rejected | accepted |
| `@(timer)` start time | rejected | accepted |
| `@(cross)` direction | rejected | accepted |
| `transition` rise/fall/delay | rejected | accepted |
| `absdelay` delay/maximum | rejected | accepted |
| `zi_nd` sampling period | rejected | accepted |
| `last_crossing` direction | rejected | accepted |
| `white_noise` power | rejected | accepted |
| `flicker_noise` power | rejected | accepted |
| `analysis()` / `$simparam()` name | warned | silent |
| parameter range emptiness | rejected | accepted |

It is not academic — models name their constants. A negative `transition` time
supplied through a parameter drove a 0→1 signal to **−2.5 V and made it respond
before the input edge**, with `rc=0` and no diagnostic from the compiler or the
simulator.

`const_num` now follows a path to its `ParamId` and folds the value when the
parameter is a `localparam`, chasing chains of them.

**A `parameter` is deliberately not folded.** Its declared value is a *default*
the model card may override, so it is not what the model will run with, and
refusing a module because of its default would police a value no simulation need
ever use. That is the same rule under which a parameter's default is not checked
against its own `from`/`exclude` range.

## 2. The same assumption built the compile-time tables

`noise_table` and the inline `$table_model` are materialised when the model is
compiled. The reader folded only literals and unary minus, and its caller turned
"cannot fold" into `0.0` — so a *named* entry silently became a zero entry:

```verilog
localparam real v2 = 20.0;
$table_model(1.5, '{1.0,10.0, 2.0,20.0, 3.0,30.0}, "1L")   // 15
$table_model(1.5, '{1.0,10.0, 2.0,v2  , 3.0,30.0}, "1L")   //  5
```

Both tables hold the same numbers. Interpolating between 10 and 0 rather than 10
and 20 gives a smooth, plausible, wrong curve — nothing about the result looks
like a dropped value. `noise_table` failed more bluntly: the device became
noiseless and the noise analysis reported a confident total.

Only the *ordinate* column was affected. A named abscissa always worked, which is
why the symptom read as bad interpolation.

The reader now folds the binary operators and follows `localparam` references
into their own bodies, exactly as `const_num` does.

## 3. `abs(-0.0)`

`abs` lowers to `x < 0 ? -x : x`, and `-0.0 < 0.0` is false, so negative zero
passed through unchanged:

```
CONSTANT-FOLDED: abs=0  1/abs=inf      GENERATED CODE: abs=-0  1/abs=-inf
```

One expression, one input, and the two evaluators disagreed on the sign of
infinity. Adding `+0.0` in the else branch normalises it — `(-0.0) + 0.0` is
`+0.0` under round-to-nearest and `x + 0.0` is `x` for everything else, NaN and
the infinities included.

That required gating `x + 0 -> x` in the MIR simplifier: the fold is exact for
integers and for every float *except* negative zero, so it now sits behind the
`EXACT_ALGEBRA` flag the codebase already uses for unsound float rewrites.
Unlike `x * 0` — kept deliberately by Enhancement-337, because removing it moved
HiSIM2's DC drain current by 10× — adding a literal zero is not an idiom compact
models rely on, so the cost is a stray `fadd` in rare code rather than a changed
answer.

## 4. Guards that did not exist at all

`$rdist_uniform`'s bounds were checked; the other six distributions were not, so
a degenerate shape argument returned a plausible finite number from a
distribution that cannot exist. `$rdist_exponential(s, -1.0)` handed back
**−1.735** — a negative sample from a distribution whose support is `[0, ∞)`.
LRM 9.13.2 requires each of these to be positive; all six are now checked.

Added with them:

- **`$vt(T)` for `T ≤ 0`.** It is `kT/q` at an *absolute* temperature.
  `$vt(-300)` returned a negative thermal voltage, so every current built on it
  came out sign-flipped; `$vt(0)` put a NaN straight into the solution, which the
  simulator then printed. The sibling constraint was already enforced for a
  `nature`'s `abstol`.
- **`ddt`/`idt` with a negative `abstol`.** A tolerance is a magnitude. The same
  quantity written as a `nature`'s `abstol` was already refused.
- **A `laplace_nd`/`laplace_zd` denominator whose highest-order coefficient is
  zero.** `'{1.0, 0.0}` is `1 + 0·s`, mathematically identical to `'{1.0}`, but
  the order is taken from the list *length*, so the realization divides through
  by that leading zero. The filter produced **no output at all** — gain 1 for
  `'{1.0}` and gain 0 for `'{1.0, 0.0}` across the whole sweep, after a burst of
  "singular matrix: check node n1#implicit_equation_0" that names an internal
  node rather than the call. Padding a coefficient vector to a fixed length is an
  ordinary thing to write when the top term is switched off. The z-domain twins
  are excluded: `lower_zi` pads both polynomials before the bilinear transform
  and `zi_nd`, `zi_zd` and `zi_np` all return the right gain for this input.

## 5. A build that defines no module

An unterminated `/*` swallows the rest of the file, module included. The compiler
printed *Finished building* in green, exited 0, and wrote a 35 KB `.osdi` holding
nothing — so the mistake surfaced much later and somewhere else, as the
simulator's "Unable to find definition of model", which points at the netlist.
A file with no module at all behaved the same way.

Having nothing to compile is now one line of error. (The lexer does produce an
"UnterminatedBlockComment", but comment tokens are trivia the preprocessor skips
without converting, so it never reaches a diagnostic; checking the result covers
that cause and any other.)

## What this deliberately does not change

Each of these was reported by the hunt and withdrawn on reading the code. The
suite pins them so a later round does not "fix" them:

- **`@(timer)` still accepts a period ≤ 0 and fires once.** LRM 5.10.3.3: it
  "shall trigger only once at the specified start_time". That is how a
  *computed* one-shot is written, and `limguard_examples` already pins it.
- **`noise_table_log` still refuses a negative power.** It takes the same
  **linear** (Hz, power) input as `noise_table` (LRM 4.6.4.4) and interpolates
  log-log, so a negative power has no logarithm. The hunt's premise that it takes
  dB was wrong. Only the diagnostic changed: it hardcoded the name
  `noise_table`, so a `noise_table_log` call was reported against a function the
  source does not mention.
- **`0.0 * NaN` still folds to 0** — Enhancement-337, above.
- **A real literal that underflows is still accepted.** `1e-324 → 0` is what IEEE
  754 defines, and `syntax/validation.rs` already records that decision.
- **A `parameter` default is still not policed**, nor is a `localparam` derived
  from one, whose value is not knowable at compile time.

## Verification

`examples/constguard_examples/verify_constguard.py` — **57/57**, both solvers.
Against the shipped pre-fix compiler the same suite scores **28/57**: 29 checks
discriminate, and everything that passes on both is either a pinned decision or a
valid value that had to keep compiling.

The checks target the *agreement* rather than the symptom — that a literal and a
named constant holding the same value are treated alike, and that a table entry
means the same thing however it is spelled.

All 40 models in `integration_tests/` compile with exit codes identical to the
shipped compiler, so no working model is newly rejected. Full regression 392/392,
both solvers. openvaf-r only.
