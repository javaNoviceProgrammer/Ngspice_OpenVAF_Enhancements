# Enhancement-479 — a check that only ever saw a literal

```
python3 verify_constguard.py
```

75 checks, both solvers. 28/57 of the original set against the pre-fix compiler;
the last eighteen (Enhancement-544) crash the compiler it fixed.

## The shape

Bug-hunt round 48. Every value guard in openvaf-r decided "is this argument a
number?" from the *syntax* of the argument, so it recognised a literal and
nothing else. A `localparam` is a compile-time constant the LRM forbids from
being overridden — the compiler knows its value exactly — yet naming one made
every guard skip.

The same negative noise power, three ways:

| spelling | before | after |
|---|---|---|
| `white_noise(-1e-12)` | rejected | rejected |
| `white_noise(-1e-12*1.0)` | rejected (folding **is** applied) | rejected |
| `localparam real q = -1e-12; white_noise(q)` | **accepted, silently** | rejected |

`const_num` had arms for literals, unary minus and the four binary operators —
and no arm for a path. One missing arm, eleven guard sites: `$bound_step`,
`@(timer)`, `@(cross)`, `transition`, `absdelay`, `zi_nd`, `last_crossing`,
`white_noise`, `flicker_noise`, the `analysis`/`$simparam` name checks and the
parameter-range emptiness check.

It is not academic. Models name their constants, and a negative `transition`
time supplied that way drove a 0→1 signal to **−2.5 V and responded before the
input edge**, with `rc=0` and no diagnostic from either the compiler or the
simulator.

## The same assumption in the table builder

`eval_const_real` folded only literals and unary minus, and its caller turned
"cannot fold" into `0.0`. So a table entry that was *named* became a zero entry:

```verilog
localparam real v2 = 20.0;
$table_model(1.5, '{1.0,10.0, 2.0,20.0, 3.0,30.0}, "1L")  // 15
$table_model(1.5, '{1.0,10.0, 2.0,v2  , 3.0,30.0}, "1L")  //  5   <- v2 read as 0
```

Interpolating between 10 and 0 instead of 10 and 20 gives a smooth, plausible,
wrong curve. `noise_table` lost its noise entirely the same way — the device
became noiseless and the analysis reported a confident number.

Only the *ordinate* column was affected; a named abscissa always worked, which
is why the failure looked like bad interpolation rather than a dropped value.

## `abs(-0.0)`

Lowered as `x < 0 ? -x : x`, and `-0.0 < 0.0` is false, so negative zero passed
through unchanged. `1.0/abs(-0.0)` gave **−inf** from generated code and **+inf**
from the compiler's own constant folding — the two disagreed on the sign of
infinity. Adding `+0.0` in the else branch normalises it; that required gating
`x + 0 → x` in the MIR simplifier on the existing `EXACT_ALGEBRA` flag, since
the fold is exact for integers and for every float *except* negative zero.

Unlike `x * 0` (Enhancement-337, kept deliberately because removing it moved
HiSIM2's DC drain current by 10×), adding a literal zero is not an idiom compact
models rely on.

## Guards that did not exist

`$rdist_uniform`'s bounds were checked; the other six distributions were not, so
a degenerate shape returned a plausible finite number from a distribution that
cannot exist — `$rdist_exponential(s, -1.0)` handed back **−1.735**, a negative
sample from a distribution whose support is `[0, ∞)`. Added here, with `$vt(T≤0)`
(a negative absolute temperature returned a sign-flipped thermal voltage;
absolute zero put a NaN straight into the solution), `ddt`/`idt` negative
`abstol`, and a `laplace_nd`/`laplace_zd` denominator whose highest-order
coefficient is zero — its effective order is lower than its length, the
realization divides by that zero, and the filter produced **no output at all**.
`zi_nd`/`zi_zd`/`zi_np` already handled the same padding correctly, and [23d]
pins that they still do.

## A build that defines nothing

An unterminated `/*` swallows the rest of the file, module included. The compiler
printed *Finished building* in green, exited 0, and wrote a 35 KB `.osdi`
containing no module — the failure surfaced much later as the simulator's
"Unable to find definition of model", pointing at the netlist. A compilation
with no module is now an error that says so.

## Deliberately NOT changed

Pinned here so a later round does not "fix" them — each was reported by the hunt
and withdrawn on reading the code:

| | why it stays |
|---|---|
| `@(timer)` period ≤ 0 | LRM 5.10.3.3: "shall trigger only once at the specified start_time". That is how a *computed* one-shot is written. [26] |
| `noise_table_log` refusing a negative power | its input is the same **linear** (Hz, power) as `noise_table` (LRM 4.6.4.4), interpolated log-log, so a negative power has no logarithm. Only the diagnostic changed — it used to name `noise_table`. [27][28] |
| `0.0 * NaN → 0` | Enhancement-337 keeps that fold deliberately. [29] |
| a real literal that underflows | `1e-324 → 0` is what IEEE 754 defines. [31] |
| a `parameter` DEFAULT | the model card may replace it, so the declared value is not what the model runs with — the same rule under which a default is not checked against its own range. [30] |

## Enhancement-544 — simulation state in a constant

`parameter real t0 = $temperature;` crashed the compiler (mir_llvm
builder.rs: "attempted to read undefined value"). A parameter default or
range is validated in the constant context, where `analysis()` was already
refused but the simulation-state functions and the random draws were not, so
they reached codegen of the setup functions with nothing to read; `$mfactor`
— a hierarchical parameter with its own lowering — folded to a placeholder 1
instead, and `$random` to one fixed number shared by every instance. The
eighteen checks pin twelve refused forms (`$temperature`, `$vt`, `$abstime`,
`$port_connected`, `$mfactor`, `$random`, `$rdist_normal`; in a default, a
range bound, an array default, an instance-typed default, an expression),
the two help notes, and four controls: `$param_given` and `$simparam` stay
legal in a default, the same functions compile and read live values in the
analog block, and `analysis()` keeps its own message.
