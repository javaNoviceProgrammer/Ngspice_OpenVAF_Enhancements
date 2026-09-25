# openvaf-r correctness campaign — the same answer three ways, derivatives against differences, operators against closed forms

**Date:** 2026-09-25, 04:40–06:10, at head `84893465` (E-714, the descriptor's -O1 middle
end). **Binaries:** the repo's `OpenVAF-master-20260610/target/opt/openvaf-r` (built 22:42 on
2026-09-24, the E-714 tree) and `ngspice-46/build/src/ngspice` (built 16:37 on 2026-09-22;
no simulator source has changed since). **Method:** about 110 compiles and 200 ngspice
runs from ten throw-away harnesses in the scratchpad (`cc/harnA.py` … `harnK`), each an
*oracle* rather than a list of cases: the question was "is the number right", and every
number was checked against something that could not share the compiler's mistake — a
Python model of the LRM's semantics, a finite difference, a closed form, ngspice's own
built-in device, or the same expression evaluated by a different path of the compiler.
Unlike the area hunts of September, which read the LRM clause by clause, this campaign
took the compiler's core — the constant folder, the run-time lowering, the automatic
differentiation, the time-domain and small-signal operators, the noise machinery — and
asked each to agree with the others. Nothing was fixed; this is the list.

The ground, and what held:

- **One expression, three paths, a fourth opinion** (harness A). 118 expressions over
  slots A, B (real) and I, J (integer) — every arithmetic, comparison, logical, shift,
  bitwise and ternary operator, the precedence traps (`-A ** 2`, `I & J == J`,
  `I << 1 + 1`), every math function, `$rtoi`/`$itor`, integer division, modulus and
  power with negative operands, shifts by 33 and by a negative count, 32-bit wrap,
  and the real-to-integer conversion on assignment — evaluated for six operand tuples
  (including 1e-300, 1e300, 0, 2³¹−1, −2³¹+1) from literals (the constant folder), from
  parameters (the run-time path) and from node voltages (the run-time path with
  derivatives), and compared with a Python model of IEEE 1364-2005 5.1 and the LRM's
  conversion rules: 695 expression-tuple pairs, 2 085 values, **no disagreement**. The
  integer `**` with a negative exponent follows 1364's table (0, or ±1 for a base of
  ±1), `>>` is logical and `>>>` arithmetic, a shift of 32 or more gives 0, the
  assignment of 2.5 gives 3 and of −2.5 gives −3, `$rtoi` truncates.
- **`ddx` against finite differences** (harness B). 61 functions of V(a) and V(b) —
  every transcendental, `pow` in three forms, `hypot`, `atan2`, `min`/`max`, `abs`,
  `%`, `limexp`, `floor`/`ceil`, ternaries, three user-defined analog functions, `$vt`,
  `$temperature`, a branch voltage — with both partial derivatives exported, swept over
  −1..1 V in 401 points: every derivative within the central difference's own error;
  the one flagged function is `$rtoi`, whose staircase makes the difference spike at
  each step while `ddx` is 0, which is right.
- **The Jacobian ngspice loads, against finite differences of the dc currents**
  (harness C). Twelve triples of `I(a) <+ f(V(a), V(b))`, `I(b) <+ g(…)` and `I(a) <+
  ddt(q(…))` with nonlinear f, g, q (exponentials, powers of two voltages, `atan2`,
  `hypot`, `limexp`, ternaries, `%`, `abs`, user functions, `$vt`): the four
  conductances and two capacitances of each read from a `.ac` with a unit source on a
  and on b, against central differences of `i(va)`, `i(vb)` and the exported charge from
  dc sweeps at `reltol=1e-9` — 84 entries, all within 2e-5. `$mfactor` triples the
  currents, conductances and capacitances; a voltage branch `V(a,b) <+ 10 I + 300 I³`
  reads dV/dI = 10 + 900 I² in `.ac`, and with `m=2` (10 + 900 (I/2)²)/2.
- **Statements, arrays, conversions, parameters, contributions** (harness D, 40
  probes): loops with literal and parameter bounds, `repeat` of a real (rounded),
  `case` on reals and on integers with lists and a leading `default`, nested ternaries,
  arrays indexed by parameters, 2-D arrays, saturating real-to-integer conversion of
  ±1e10 and of NaN (0), rounding of an integer parameter given 2.7 on the card (with a
  warning), a saturated one refused, real modulus by a card zero a fatal, real
  division by a card zero ±∞, `1/(−0.0)` = −∞ and `atan2(0, −0.0)` = π at run time and
  folded (the 2026-09-07 F3 is fixed), string parameters compared and overridden on
  the card, `$param_given` (and through an alias), parameter default chains and
  `localparam` at run time, range and `exclude` refusals at setup with the value and
  range named, an instance parameter on the instance line, `$mfactor`, `$temperature`,
  `$vt` and `$vt(T)` against CODATA 2018, `analysis` strings, `$abstime` and
  `$simparam("gmin")` at the op, port-current probes, contributions summed across
  `if` paths and loops and both branch orientations, a node collapse, a switch branch.
- **Noise against closed forms** (harness E, 12 spectra): a Verilog-A resistor's
  thermal noise equals ngspice's own resistor's to 3e-7 in the same divider; white and
  flicker current noise with exponents 1 and 1.5; `noise_table` and `noise_table_log`
  interpolation; the thermal noise across a `ddt` capacitance; a voltage-branch noise
  source; a noise power computed from the operating point; two same-named white
  sources sum as powers (the E-528 reading of 4.6.4.6, correlation keyed on the call)
  and two differently named ones likewise; `m=2` doubles the power and the
  conductance.
- **The time-domain operators on analytic waveforms** (harness F, 13 quantities over
  4 065 accepted points of a 1 kHz sine and a pulse): `ddt` within 3e-4 of the
  amplitude and `idt` within 3e-6, `idt` with an initial condition, `idtmod`, `idt`
  asserted on `analysis("static")`, `absdelay` of 100 µs, `transition` with separate
  rise and fall, `slew` with separate rates, `last_crossing` (a one-step detection
  lag, −1 before the first crossing), `$abstime`, `ddt` of a constant and of a square.
  At a well-posed operating point `absdelay`, `transition` and `slew` return their
  input, `idt(x, ic, 1)` its `ic`, `laplace_nd` its dc gain; an *unasserted* `idt` of
  a nonzero constant has no dc solution, and ngspice's gmin and source stepping then
  produce values for every other operator of the same module that mean nothing — the
  campaign's first "finding" was that and is withdrawn.
- **Small-signal transfer of the operators** (harness G): `ddt`, `idt`, `idtmod`,
  `absdelay` (e^{−jωτ}), `transition` and `slew` (unity), `laplace_nd` and
  `laplace_zp`, `ddt` of `ddt`, `idt` of `ddt`, all exact to 1e-9 over 1 kHz–10 MHz;
  a `$table_model` conductance in `.ac` against the dc difference, linear (1e-13) and
  cubic (1e-5, the difference's own term). Derivatives at the singular points
  (V = 0): `pow(x, 0.5)` gives 5e8 (the E-489 clamp at 1e-18), `abs` gives +1,
  `hypot(0, 0)` 0 (the 2026-09-07 F1 is fixed), `atan2(0, 0)` 0, `min`/`max` choose
  the second operand, `pow(0, x)` at 0 the clamp's −41.4, a `$table_model` its
  segment's slope. Analog functions with `output` and `inout` arguments write back;
  the current of a collapsed branch is the current through the short; a NaN as an
  `if` condition is false (the x-is-false reading).
- **Events, hierarchy, ports, temperature** (harnesses I and J): `initial_step`,
  `initial_step("dc"/"ac"/"tran")`, `final_step`, `cross`, `timer` and `above` fire
  the LRM's number of times in `op`, a dc sweep, `ac` and `tran`; a child instance
  reads `#(.r(pr / 2), .k(pk))` from the parent's parameters and the parent's `m`
  scales the subcircuit; `$port_connected` sees an open port; `$simparam` for
  `gmin`, `tnom`, `iteration`, `sourceScaleFactor`; `$temperature` follows
  `.options temp`, `.temp`, an instance `temp` and `dtemp` and their combination;
  `ddx` with respect to a branch current; a branch collapse chosen by `r=0` on the
  card against `r=500` and `r=1e3` with the same `.osdi`; integer parameter defaults
  wrap as E-675 says; `$strobe` formats (`%5.2f`, `%10.3e`, `%-6d`, `%+d`, `%08.3f`,
  `%x`, `%o`, `%b`, `%c`, `%%`, `%r` in SI form). A flat sum of 800 literal terms
  folds to the Python value to the last bit, as does its loop form.

## Summary

| # | finding | kind |
|---|---|---|
| [F1](#f1--an-array-parameters-element-is-not-found-in-the-current-scope-in-any-constant-context) | *(fixed in [E-715](../../enhancements_doc/Enhancement-715.md): the inference finds the module's arrays through the body owner's scope, so a parameter's default, a range bound, a localparam and an array literal read `pa[k]`, with the card override and the range check following; a forward reference to an element is refused naming it, not crashed)* an array parameter's element — `pa[1]` — is "'pa' was not found in the current scope" in another parameter's default, in a range bound, in a `localparam` and in another array parameter's literal, while the analog block reads `pa[pi]` and `pa[2]` without a word | wrong refusal of legal code |
| [F2](#f2--integer-division-by-a-card-supplied-zero-is-0-in-silence-the-modulus-by-the-same-zero-is-a-fatal) | `pi / pz` with `pz=0` on the card evaluates to 0 without a message; `pi % pz` with the same zero is `OSDI(fatal) … the second operand (the modulus divisor) is zero, which LRM 4.2.4 makes an error`; a real `px / pz` is ±∞ | silent wrong number, inconsistent with the sibling operator |
| [F3](#f3--the-derivative-of-a-quotient-is-formed-over-the-squared-denominator-and-is-nan-below-2e-162) | the automatic derivative of `x / y` is `x'/y − x·y'/(y·y)`: for `V(a) / (V(b) + 1e-300)` at the V = 0 initial guess the value is 0 and ∂/∂V(b) is NaN (0/0, the square `1e-600` underflowing to 0), likewise `exp(−1/(x² + 1e-300))`; a guard of 1e-160 or larger is safe (its square is a denormal), the equivalent `(x/y)/y` form never underflows | NaN in a Jacobian at the operating-point guess |
| [F4](#f4--a-flat-sum-or-product-of-a-thousand-terms-is-refused-as-nesting-too-deeply) | `r = 1.0/1 + 1.0/2 + … + 1.0/999` is "expression nests too deeply": the E-148 parser guard (`MAX_EXPR_DEPTH = 1000`) counts a left-associative chain as nesting; 800 terms compile, 511 nested parentheses and 600 unary minuses compile, the same 1 500 terms in thirty parentheses compile | refusal of legal input, misleading diagnostic |
| [F5](#f5--an-unconnected-port-guarded-by-port_connected-leaves-ngspice-a-floating-node) | a three-terminal module instantiated with two terminals, its third branch guarded by `if ($port_connected(c))` as the LRM's `$port_connected` intends, warns "1 of the 3 terminals … are not connected" and then "singular matrix: check node n1#c" twice, runs gmin stepping (277 iterations) and converges; the open port's node has nothing on it | simulator side: a floating node from the LRM's own idiom |

## F1 — an array parameter's element is "not found in the current scope" in any constant context

**Observed.** With `parameter real pa[0:2] = '{1.5, 2.5, 3.5};` every one of

```
parameter real pb = pa[1];
localparam real lq = pa[0] * 2;
parameter real pb = 1.0 from [pa[0]:pa[2]];
parameter integer pb = pa[0] + pa[1];        (integer array)
parameter real pq[0:1] = '{pa[0], pa[1]};
```

is refused with `error: 'pa' was not found in the current scope`, the caret under
`pa` (`cc/D2/v1.va` … `v5.va`); a scalar parameter in the same places is fine (`v6`:
`parameter real pa[0:1] = '{ps, ps * 2};` with `ps` a parameter compiles), and the
analog block reads `pa[pi] + pa[2]` (`v9`, `apb.va`). The array parameter is
declared; only the constant contexts cannot see it.

**Where.** A parameter's default and range are lowered by their own query
(`hir_def/src/body.rs`, `param_body_with_sourcemap_query`), not with the module
body; an array parameter is one item per element since E-14 (`nameres/collect.rs`,
"every array element of the same `InstanceUnit` shares …"), and the module body's
resolution of `pa[k]` reaches those elements where the parameter body's does not —
the path resolver reports `NotFound` (`nameres/diagnostics.rs`). E-713 touched the
default of an array *element* (`array_literal_leaf`) but not a reference *to* one
from another parameter.

**Expected.** LRM 3.4: a parameter's default is a constant expression, and a
parameter (array or not) is a constant; `from [pa[0]:pa[2]]` is the ordinary way to
range one parameter by another. A model that derives a scalar from a table-shaped
parameter (`parameter real vth0 = vth[0];`) is legal and cannot be written today
except by moving the derivation into the analog block.

**Kind.** Wrong refusal of legal code; the workaround changes the model's structure.

*Fixed in [E-715](../../enhancements_doc/Enhancement-715.md).* `find_param_array` answered only for the module's own body; it now finds the module through the body owner's scope, so every form of the table compiles and follows the card, and the declaration-order check covers element reads — a forward reference to `pa[1]`, which crashed the compiler once the element resolved, is refused like a scalar's.

## F2 — integer division by a card-supplied zero is 0 in silence; the modulus by the same zero is a fatal

**Observed.** `parameter integer pi = 7; parameter integer pz = 1;` and on the card
`pz=0`:

| expression | result |
|---|---|
| `r1 = pi / pz;` | `r1 = 0`, no message (`cc/D2/idz.va`) |
| `r2 = pi % pz;` | `OSDI(fatal) n1: %: the second operand (the modulus divisor) is zero, which LRM 4.2.4 makes an error`, the op aborted (`cc/D/int_div_zero_runtime`) |
| `px / pz` (real) | `+inf`, `-px / pz` `-inf` (`real_div_zero_runtime`) |
| `px % pz` (real) | the same fatal (`real_mod_zero_runtime`) |

**Where.** E-518 closed the LLVM-level undefined behaviour of `sdiv` and `srem` by a
zero or by `INT_MIN / -1` with explicit selects (`mir_llvm/src/builder.rs`, the
`Opcode::Idiv | Opcode::Irem` arm: "x / 0 ⇒ 0, x % 0 ⇒ 0"), and separately gave the
`%` operator E-509's run-time `$fatal` for a *card-supplied* zero
(`hir_lower/src/expr.rs`, `"%%: the second operand (the modulus divisor) is zero"`,
`hir_ty/src/validation/body.rs:2377`), citing LRM 4.2.4; the division was left with
the silent guard only. The E-518 write-up says a *genuinely* run-time divisor (one
computed from a solution variable) is deliberately unguarded; a card value is not
that, and the modulus already treats it as a fatal.

**Expected.** The same LRM clause governs both operators: whatever the compiler does
for `%` by a card zero, `/` by the same zero should do — a fatal naming the
operator, or at the least a message. A silent 0 is a wrong number a model then
multiplies into a current. (On x86 the same division would trap; the 0 is the
AArch64 behaviour E-518 made portable.)

**Kind.** Silent wrong number, inconsistent with the sibling operator.

## F3 — the derivative of a quotient is formed over the squared denominator, and is NaN below 2e-162

**Observed.** At V(a) = V(b) = 0 (`cc/G/sing.va`, the operating-point guess of every
analysis):

| expression | value | ∂/∂V(a) | ∂/∂V(b) |
|---|---|---|---|
| `V(a) / (V(b) + 1e-300)` | 0 | 1e300 | **NaN** |
| `exp(-1.0 / (V(a)*V(a) + 1e-300))` | 0 | **NaN** | 0 |
| `V(a) / (V(b) + 1e-160)`, `1e-155`, `1e-154`, `1e-150` | 0 | 1e160 … | 0 |
| `exp(-1.0 / (V(a)*V(a) + 1e-155))` | 0 | 0 | 0 |

The value is right in every row; the derivative is `0 / 0` whenever the denominator's
square underflows to zero — below the smallest denormal, so for |y| under about
2.2e-162 — and the numerator is 0 (`cc/K/q.va`).

**Where.** `mir_autodiff/src/builder.rs`: for `Opcode::Fdiv` the cached
sub-expression is `fmul(arg1, arg1)` (line 444) and the derivative is assembled as
`f'/g − f·g'/g²` (the `// f*g'/g^2` arm, about line 700). `x · y' / (y·y)` with
`y = 1e-300` is `0 · 1 / 0`.

**Expected.** Mathematically the same derivative as `(x/y)·(y'/y)`, which is
`0 · 1e300 = 0` here, or `(x'·y − x·y')/y` divided by `y` — either form keeps the
intermediate at 1e300 and never at 1e-600. The guard-by-epsilon idiom `x / (y +
tiny)` is common in compact models; with `tiny` at 1e-30 or larger the square does
not underflow, so the exposure is to guards below about 2e-162 — the `1e-300`
kind — and to `1/(x² + tiny)` shapes with such a `tiny`.

**Kind.** A NaN in a Jacobian entry at the operating-point guess for an expression
whose value is finite; low frequency in practice, cheap to close.

## F4 — a flat sum or product of a thousand terms is refused as nesting too deeply

**Observed.** `analog r = 1.0/1 + 1.0/2 + … + 1.0/N;` (`cc/K/sumN.va`):

| N | result |
|---|---|
| 800 | compiles (and folds to the Python value to the last bit) |
| 999 | `error: expression nests too deeply` |
| 1 000, 1 200, 1 500 | the same |

The same for a product of N factors. The same 1 500 terms in thirty parenthesised
groups of fifty compile; 1 500 statements `s = s + 1.0/k;` compile; 511 nested
parentheses and 600 stacked unary minuses compile.

**Where.** `parser/src/grammar/expressions.rs`, `MAX_EXPR_DEPTH = 1000`, checked
through `expr_depth` (`parser.rs`) on every binary-expression recursion — E-148's
guard against a genuinely nested input (its message was written for "a file that
includes itself?"). A left-associative chain `a + b + c` recurses once per operator
in this parser, so a *flat* expression of a thousand terms reads as a thousand-deep
one.

**Expected.** A generated model — a polynomial fit, a table written out as a sum of
products — can easily carry a thousand terms on one line; the LRM has no such limit,
and the compiler's own MIR handles it (the statement form is fine). Either the chain
is parsed iteratively (the depth then measures real nesting), or the message says
what happened ("an expression of more than 1 000 operators on one line; group it or
split it").

**Kind.** Refusal of legal input with a misleading diagnostic.

## F5 — an unconnected port guarded by `$port_connected` leaves ngspice a floating node

**Observed.** `module pc(a, b, c)` with `I(a,b) <+ 1e-3 V(a,b); if ($port_connected(c))
I(c,b) <+ 1e-3 V(c,b);` instantiated as `N1 a 0 mm` (`cc/I/pc.va`): ngspice warns
`instance n1: 1 of the 3 terminals of model type 'pc' are not connected.`, then
`Warning: singular matrix: check node n1#c` twice and `Dynamic gmin stepping …`; the
op converges after 277 iterations (`$simparam("iteration")`), `$port_connected(c)`
reads 0 and `$port_connected(a)` 1, as they should.

**Where.** `ngspice-46/src/spicelib/parser/inp2n.c:1189` issues the warning and
creates the internal node `n1#c` for the missing terminal; nothing is attached to
it, the module's guarded branch being — correctly — absent, so the node's row is
empty and the matrix singular until gmin stepping fills it.

**Expected.** `$port_connected` exists exactly so that a module can leave an open
port without a contribution; the simulator should then not solve for that
node — ground it, tie it with the gmin it later adds, or drop it from the matrix —
rather than take the failed-op route to the same answer. The compiler's side is
right; the cost is the warnings and the 277 iterations on every op.

**Kind.** Simulator-side; a clean LRM idiom produces failure-path warnings.
