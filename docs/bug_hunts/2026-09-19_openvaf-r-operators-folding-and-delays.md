# openvaf-r bug hunt — analog operators under every analysis, constant folding, derivatives at singular points, and the diagnostics around them

**Date:** 2026-09-19, one hour (06:08–07:08; the probes ran until 06:54, the hour was called at 07:08, the write-up
interleaved from 06:32 on), at head `6eb71d16` (after E-657…E-670, the corner and run-control
fixes of the 2026-09-18 hunt). **Binaries:** the repo's
`OpenVAF-master-20260610/target/opt/openvaf-r` and `ngspice-46/build/src/ngspice`,
both built the evening before from the E-670 tree. **Method:** ~350 small Verilog-A
modules and decks written for the hour, compiled and (where they compile) run on ngspice
through a throw-away harness in the scratchpad (`hunt/h.py`, `p1.py … p78.py`), each
probe checked against the VAMS-2023 text (`pdftotext -layout docs/VAMS-LRM-2023.pdf`)
or against the textbook response of the operator. Nothing was fixed; this is the list.
The ground chosen was what the earlier hunts had not walked: the analog operators
(`ddt`, `idt`, `idtmod`, the four `laplace_*` forms, `zi_nd`, `absdelay`, `transition`,
`slew`, `limexp`, `ac_stim`) under the operating point, `dc`, `ac`, `noise` and
transient analyses; automatic differentiation at the singular points of `abs`, `pow`,
`sqrt`, `min`/`max`, `floor`, `atan2` and `hypot`; constant folding against the same
expression computed at run time; the integer operators; strings, formats and the
file tasks; the preprocessor and the compiler directives; the parameter interface
(`aliasparam`, instance defaults, ranges, card spellings); contributions that read
their own branch; analog functions; the `case` forms; genvar loops; the `$simparam`
family; events per analysis; noise scaling and correlation. Areas the earlier hunts
covered in depth (parameters and arrays, events in transient, `$table_model`, the
corners, the loop commands, hierarchy) were only touched in passing.

## Summary

| # | finding | kind |
|---|---|---|
| [F1](#f1--after-the-transient-op-fallback-every-delayed-output-is-lost-for-the-whole-transient) | after ngspice finds the operating point through the **"Transient op" fallback**, every `absdelay` and every `transition` with a delay in every loaded OSDI model loses its delay for the whole transient: read into a variable it is 0 at every point, contributed it passes the input through undelayed; an `idt` with an initial condition starts 1e-5 off. Gmin stepping and source stepping alone do not trigger it, `uic` avoids it | wrong result, silent |
| [F2](#f2--pow00-x-folds-to-0-for-every-exponent) | `pow(0.0, x)` and `0.0 ** x` with a literal zero base fold to 0 for every `x`: `pow(0.0, 0.0)` written out is 1, `pow(0.0, x)` at `x = 0` is 0; a negative `x` gives 0 where the same expression with a parameter base is the run-time domain `$fatal`; the derivative folds to 0 with it | wrong result, silent |
| [F3](#f3--l030-says-clipped-where-the-integer-default-wraps) | L030 says an integer default that overflows is "clipped to 2147483647" while the stored default wraps: `2147483647 + 1` is −2147483648, `100000 * 100000` is 1410065408, `-2147483647 - 2` is 2147483647, `2147483647 * 2` is −2; the lint evaluates the default as a real, the folder as a 32-bit integer; a real literal (`1e10`) really is clipped | wrong diagnostic |
| [F4](#f4--simparamstr-of-an-unknown-name-hands-strobe-an-invalid-string) | `$simparam$str("instance")` (or any name the simulator does not provide, no default) hands `$strobe` an invalid string — `instance=�` on stdout — before the run aborts with the run-time `$fatal`; the compile-time L025 warning is right, the value that reaches the model is garbage | memory hygiene |
| [F5](#f5--an-undeclared-macro-at-file-scope-still-raises-a-second-error-in-a-phantom-file) | an undeclared macro reference at file scope (outside any module) raises "has not been declared" and then a second error, "unexpected token integer; expected 'discipline', 'nature' or 'module'", at `/<file>__macro_synth.va:1:1` — a file that does not exist; E-665 removed the same knock-on in expression position only | diagnostic |
| [F6](#f6--last_crossing-returns-0-before-any-crossing-in-ac-and-noise) | `last_crossing` returns 0 before any crossing in an `ac` and a `noise` analysis, where LRM 4.5.10 requires a negative value; the operating point and `dc` return −1 as they should, transient returns the crossing time | conformance |
| [F7](#f7--the-fatal-label-in-a-dc-sweep-names-the-previous-sweep-point) | the `(at sweep value …)` label on a run-time `$fatal` in a `.dc` sweep names the **previous** sweep point (`over 0.5 (at sweep value 0)`), and the line is printed twice; `$error`, `$warning` and `$info` at the same point say `(at sweep value 0.5)` once; the transient and operating-point labels are right | diagnostic |
| [F8](#f8--a-node-joined-only-by-delayed-elements-diverges-to-1e62-in-silence) | a node whose every connection is a delayed element (two `absdelay` conductances in series) passes the operating point, then diverges once the first delayed edge arrives: −1e18, 1e27, 1e45, 5.6e62 over 73 accepted points, no warning, exit 0; the same circuit inside a child module prints six `singular matrix: check node n1#mid` and stops after the first point, also exit 0. Ill-posed for any Newton solver — the defect is the silence | silent divergence |
| [F9](#f9--idt-with-assert-relaxes-toward-the-initial-condition-instead-of-returning-it) | `idt(1e6, 0.5, V(a,b) > 0.5)` does not return the initial condition while `assert` is nonzero: the output relaxes from 1.5 toward 0.5 with a ~10 µs time constant (1.45, 1.41, 1.36, 1.32 …), and when the assert releases the integral resumes from the relaxed value, not from 0.5; independent of the timestep and of `method=gear`; LRM 4.5.4 says the ic is *returned* whenever assert is nonzero | wrong result, silent |
| [F10](#f10--option-interp-corrupts-integer-operating-point-variables-in-a-transient-print) | under ngspice's `.option interp`, an **integer** operating-point variable printed by `.print tran` is garbage: a constant 3 prints as 1.48e-323 (its bits read as a double) and then 1.25, and the next vector on the line shows the previous vector's values; without `interp`, and under `dc`, `op` and `ac`, the same integers print correctly; real opvars are unaffected | wrong output |

Dropped after checking the LRM or the code: the `laplace_zp` DC gain (the LRM's pole
form is a product of (1 − s/p) factors, so unity at DC is right; all four forms, a
zero and a pole at the origin and a complex pole pair match theory), the reduction
operators (`&5`, `|5`, `^5` are refused; LRM 4.2.10 forbids them in an analog block),
two `white_noise` sources with the same name (uncorrelated by LRM 4.6.4.6; the
name only groups the summary), an unsorted `noise_table` (LRM 4.6.4.3 defines the
interpolation by neighbours, not by position), `ddt` in a non-constant `if`
(refused, LRM 4.5.15), an analog function calling itself (refused, LRM 4.7), an
`idt(1.0)` with no initial condition at the operating point (LRM 4.5.4: undefined
unless a loop forces the argument to zero — the model's own fault; what it does to
the delays in the same run is F1).

## What was read and run

LRM sections read for the probes: 2.6 (strings and escapes), 3.4.7 (`aliasparam` is an
override spelling only), 4.2.2–4.2.11 (integer division and remainder, shifts, the
reduction operators, Table 4-1), 4.5.4–4.5.6 (`idt`, `idtmod`, the initial
condition at DC), 4.5.7–4.5.8 (`absdelay`, `transition`, `slew`), 4.5.10
(`last_crossing`: negative before the first crossing), 4.5.11 (the four Laplace forms
and their transfer functions), 4.5.12 (`zi_*`), 4.5.15 (restrictions on analog
operators), 4.6.4 (noise functions, tables, correlation), 4.7 (analog functions:
no recursion, no access functions), 9.15 (`$simparam`, `$simparam$str`, Table 9-27:
`tnom` in Celsius), 9.17 (`$discontinuity`, `$bound_step`), 10.4–10.7 (macros, `` `undef ``,
`` `line ``). Probe families: p1 `ddx` of 24 expressions across a `dc` sweep through
zero; p2 operating point convergence of twelve models with a singular derivative at
zero, driven by a current source; p3 the same integer and real expressions once through
parameters (run time) and once as literals (folded); p4 twenty analog operators under
`.ac`, magnitude and phase against theory; p5 the eleven Laplace forms; p6 domain checks
on node-dependent arguments; p7 algebraic folding with one literal operand, including
NaN and infinity operands; p8 strings, escapes, bit and shift operators, every format
specifier; p9 macro expansion, redefinition, recursion, argument count, `` `undef ``,
eleven directives alone and in pairs; p10 nine overflowing integer defaults under L030;
p11 the parameter interface on the card and on the instance line; p12 fifteen
contribution forms; p13 fourteen analog function forms; p14 the `$simparam` family
against `.option` values; p15 which events fire under each of five analyses; p16 ten
`case` forms; p19 eleven noise forms; p20 twelve transient operators on a step, on a
half-microsecond grid; p21 fifteen genvar loop forms; p22 the string, file and display
tasks; p25 contributions reading their own flow or potential; p27 integer division in
real contexts; p28–p31 the F1 bisection (thirty decks: opvar against contribution, with
and without the integrator, integrator in another instance, an ngspice inductor forcing
the same fallback, `uic`, `noopiter`, `gminsteps=0`).

## F1 — after the "Transient op" fallback, every delayed output is lost for the whole transient

This is the finding of the hour and it is on the ngspice/OSDI side. When the operating
point before a `.tran` cannot be found by plain Newton, ngspice tries dynamic gmin
stepping, true gmin stepping, source stepping and, last, the "Transient op" (`Note:
Transient op started` … `finished successfully`). After that last path every
`absdelay` and every `transition` that carries a delay, in every loaded OSDI model,
behaves as follows for the whole transient that follows:

- assigned to a variable (an opvar), the delayed value reads **0 at every point**;
- used directly in a contribution, the input passes through **undelayed**;
- an `idt(1.0, 0.5)` in the same module starts the transient at 0.50001 instead of 0.5.

Minimal reproduction (the deck's own inductor forces the fallback; the model has only
the delay):

```verilog
module m(a,b); inout a,b; electrical a,b;
(*desc="del"*) real del;
analog begin
 del = absdelay(V(a,b), 1u);
 I(a,b) <+ V(a,b)/1e3;
end
endmodule
```

```
v1 a 0 dc 0 pulse(0 1 1u 1n 1n 10u 20u)
n1 a 0 mm
.model mm m
l1 a 0 1m
.option interp
.tran 0.5u 4u
.print tran @n1[del]
```

Delayed output on the grid 0, 0.5 µs … 4 µs (the step is at 1 µs, so the delayed edge
belongs at 2 µs):

| deck | op path | `@n1[del]` |
|---|---|---|
| model alone | plain Newton | 0 0 0 0 0.696 1 1 1 1 |
| `l1 a 0 1m` added | gmin, source, **Transient op** | 0 0 0 0 0 0 0 0 0 |
| `.option noopiter` | dynamic gmin only | 0 0 0 0 0.696 1 1 1 1 |
| `.option noopiter gminsteps=0` | source stepping only | 0 0 0 0 0.696 1 1 1 1 |
| `l1` added, `.tran … uic` | no op | 0 0 0 0.696 1 1 1 1 |
| second instance of a module with `it = idt(1.0)` | Transient op | 0 0 0 0 0 0 0 0 0 |
| the same module with `it = idt(1.0)` (no ic) | Transient op | 0 0 0 0 0 0 0 0 0 |
| the same module with `it = idt(1.0, 0.5)` | plain Newton | 0 0 0 0 0.696 1 1 1 1 |
| the same module with `I(a,b) <+ absdelay(V(a,b),1u)/1e3` and `it = idt(1.0)` | Transient op | `i(v1)` is −1 mA from 1.5 µs: undelayed |
| `transition(V(a,b) > 0.5 ? 1.0 : 0.0, 0.5u, 1u)` with `it = idt(1.0)` | Transient op | 0 0 0 0 0 0 0 0 0 |
| `slew`, `laplace_nd`, `zi_nd`, `transition` without delay, with `it = idt(1.0)` | Transient op | correct |

Every delay form goes the same way under the fallback (an ngspice inductor forcing
it, the delay-only model): `absdelay` with `maxdelay`, a nested
`absdelay(absdelay(V, 0.5u), 0.5u)`, a delay from a parameter, `transition` with a
parameter delay, `absdelay(slew(V))` and `slew(absdelay(V))` all read 0 at every
point, and each is right under plain Newton.

So the trigger is exactly the Transient-op path, not the fallback in general (gmin and
source stepping keep the delay) and not the module (an integrator in another instance
suffices). A module whose only fault is a `laplace_nd(1.0, '{1.0}, '{0.0, 1.0})` (a
1/s integrator, also undefined at DC) triggers it the same way. The E-1 delay is a
synthetic-node DAE and the transition delay a queue; whichever state the Transient op
initialises, it leaves the delay line reading its input at the start of the transient
(contribution) or nothing at all (opvar) — the two spellings differ, which suggests the
opvar copy and the contribution value are taken from different states. The 12-operator
module of p20 (where this was first seen) had `it = idt(1.0)` among its opvars; every
delayed quantity in it was 0 for 4 µs while `slew`, `laplace_nd`, `zi_nd`,
`last_crossing` and the delay-less `transition` were right, and its `idt(1.0, 0.5)`
read 0.500010 at t = 0 against 0.500000 in a clean run.

An `idt` whose argument is a delayed signal needs no other device to reach this
state: `idt(absdelay(V(a,b), 1u), 0.0)` — initial condition given — is singular at
the operating point on its own (`singular matrix`, then the Transient op), and by the
rule above integrates 0 for the whole run; `idt(transition(…, 0.5u, 1n), 0.0)` the
same; `idt(V(a,b), 0.0)` and `idt(laplace_nd(V(a,b), …), 0.0)` find the operating
point (the latter through the fallback, and still integrates correctly, not being a
delay). Under `uic` the delayed integral is right (2e-6 after the 2 µs pulse).

The other stateful operators are untouched by the fallback: `zi_nd`, `idtmod`,
`last_crossing`, `slew`, and the `cross` and `timer` event counters read the same
under the Transient op as under plain Newton. F1 is the delay line, nothing else.

The small-signal side is untouched: under `.ac`, with the same second instance
forcing the Transient op, the phase of `absdelay(V, 250u)` is still −2πfτ.
`.option method=gear` and `maxord=1` change nothing.

Why it matters: a model with `absdelay` next to any device whose operating point takes
the Transient-op path (an ideal inductor across a source, an OSDI integrator without an
initial condition, a floating capacitor loop) simulates as if the delay were zero, and
nothing says so. The fix belongs where the Transient op hands over to the transient in
`ngspice-46` (the OSDI `init`/`eval` sequence under `MODETRANOP`), not in the compiler.

## F2 — `pow(0.0, x)` folds to 0 for every exponent

`mir_opt/src/simplify.rs`, `simplify_pow_inst`: after `rhs == 0 → 1` and the
constant-constant fold, `if lhs == F_ZERO { return Some(F_ZERO) }`. So a literal zero
base with a run-time exponent folds to 0 whatever the exponent:

```verilog
parameter real z = 0.0;
f = pow(0.0, V(a,b));  // 0 at V = -1, 0, 1
g = pow(z,   V(a,b));  // pow(0,0) = 1 at V = 0; pow(0,-1) is the run-time $fatal
```

Sweeping `V` over −1, 0, 1: `f` is 0, 0, 0; with the parameter base `g` is (fatal),
1, 0. `pow(0.0, 0.0)` written out is 1 (the `rhs == 0` rule runs first), so the fold
disagrees with its own literal case. `0.0 ** x` is the same instruction. The
derivative `ddx(pow(0.0, x), V(a))` is 0 as well (for x > 0 the true derivative is 0,
for x = 0 it is undefined). A NaN exponent gives 0 where C gives NaN. Low impact in
practice — a literal zero base is rare, a parameter base is a run-time value and
correct — but the rule is wrong for x ≤ 0 and the two spellings of the same call
disagree.

The companion rules `0.0 * x → 0` and `0.0 / x → 0` also hold when `x` is NaN or
infinite (IEEE gives NaN in both cases; `x - x` and `x / x` are not folded and keep
the NaN). That is the usual fast-math trade and is only listed under the smaller notes.

## F3 — L030 says "clipped" where the integer default wraps

`hir_ty/src/validation/body.rs`, the E-590 check: the default is evaluated by
`const_num_in` as an `f64`, and when it lies outside the 32-bit range the verdict is
formatted as `clipped to {i32::MAX or i32::MIN}`. The folder that produces the stored
default evaluates the integer-typed expression in 32-bit arithmetic, which wraps:

| default | L030 says | model card shows |
|---|---|---|
| `1e10` | clipped to 2147483647 | 2147483647 |
| `-1e10` | clipped to −2147483648 | −2147483648 |
| `2147483647 + 1` | clipped to 2147483647 | **−2147483648** |
| `100000 * 100000` | clipped to 2147483647 | **1410065408** |
| `-2147483647 - 2` | clipped to −2147483648 | **2147483647** |
| `2147483647 * 2` | clipped to 2147483647 | **−2** |
| `2 ** 31` | (no warning) | 2147483647 |

The real-literal rows are right. The four integer-expression rows name a value the
parameter never takes; the E-590 write-up's own motivating example (`= 3000000000`,
a literal) is a clipped one, so the lint was checked against literals and the
integer-expression path was never compared with the folder. `2 ** 31` gets no
warning because the folder's integer power saturates (the 2026-09-04 hunt's F5, still
open), so the real evaluation and the folded value agree by accident.

## F4 — `$simparam$str` of an unknown name hands `$strobe` an invalid string

```verilog
string sinst;
analog begin
 sinst = $simparam$str("instance");
 @(initial_step) $strobe("instance=%s", sinst);
 I(a,b) <+ V(a,b)/1e3;
end
```

Compile: `warning[L025]: $simparam$str names the simulator parameter "instance",
which this simulator does not provide` — correct. Run:

```
stdout:  OSDI n1: instance=�
stderr:  OSDI(fatal) n1: unknown $simparam$str "instance" (at the operating point)
         Error: a Verilog-A device raised $fatal during the operating point; aborting.
```

The fatal is right (LRM 9.15: no default, unknown name → error), but the eval that
raised it went on to the `$strobe` with whatever the failed lookup left in the string
slot — an invalid pointer or uninitialised bytes, printed as `�`. The same shape for
`"path"` and `"cktname"`. A numeric `$simparam("nosuch", -7)` returns its default and a
numeric one without a default was recorded last hunt (silent). The string case should
either abort before the value is used or return an empty string; reading past a failed
lookup is the kind of thing that turns into a crash on another allocator.

## F5 — an undeclared macro at file scope still raises a second error in a phantom file

E-665 fixed "an undeclared macro reference: *has not been declared* and then
*unexpected token ';'* about the hole it left" by leaving a synthesised `0` behind
and reporting one error. That holds in expression position (`` `A(1) `` after
`` `undef A ``: one error). At file scope it does not:

```verilog
`include "disciplines.vams"
`unknown_directive
module m(a,b); inout a,b; electrical a,b;
analog I(a,b) <+ V(a,b);
endmodule
```

```
error: macro '`unknown_directive' has not been declared
error: unexpected token integer; expected 'discipline', 'nature' or 'module'
  --> /p9f_unknown.va__macro_synth.va:1:1
  |
1 | 0
```

The synthesised `0` is a legal expression token but not a legal module item, so the
parser reports it — at a position inside `/<file>__macro_synth.va`, the virtual file
`preprocessor/src/processor.rs` creates for the substitute (the same phantom-file
shape as the 2026-09-08 hunt's F2). A misspelled directive (`` `timescal ``,
`` `defin ``) is the realistic way to hit this. One error, at the reference, is what
E-665 promised.

## F6 — `last_crossing` returns 0 before any crossing in `ac` and `noise`

LRM 4.5.10: "Before the expression crosses zero for the first time, the
`last_crossing()` function returns a negative value." A model that assigns
`tlast = last_crossing(V(a,b) - 0.5, 0)` and prints it at `final_step` reads:

| analysis | `tlast` |
|---|---|
| `.op` | −1 |
| `.dc` | −1 |
| `.ac` | **0** |
| `.noise` | **0** |
| `.tran` (edge at 2.15 µs) | 2.15e-6 |

0 is a valid time, so a model that tests `last_crossing(...) < 0` to mean "not yet"
takes the wrong branch under `ac` and `noise`. The small-signal analyses evidently
initialise the crossing state differently from the operating point that precedes them.

## F7 — the `$fatal` label in a `dc` sweep names the previous sweep point

```verilog
if (V(a,b) > 0.25) $fatal(1, "over %g", V(a,b));   // and the same with $error, $warning, $info
```

under `.dc v1 0 1 0.5`:

| task | message |
|---|---|
| `$fatal` | `OSDI(fatal) n1: over 0.5 (at sweep value 0)` — twice |
| `$error` | `OSDI(err) n1: over 0.5 (at sweep value 0.5)`, then `over 1 (at sweep value 1)` |
| `$warning`, `$info` | as `$error` |

The value the model prints (0.5) and the label (0) disagree; the label is the last
*completed* sweep point, read after the sweep loop has already recorded it. In a
transient every task says `(at t = 1.0003e-06)` and under `.ac` `(at the operating
point)`, both right. The doubled line is the same duplication as a domain `$fatal` for
a parameter argument (smaller notes): the fatal is reported once by the evaluation and
once by the abort path. Small, but the label exists to tell the user where the run
died, and in a `dc` sweep it points one step early.

## F8 — a node joined only by delayed elements diverges to 1e62 in silence

```verilog
module d(p, n); inout p, n; electrical p, n;
parameter real td = 1u;
analog I(p,n) <+ absdelay(V(p,n), td)/1e3;
endmodule
```

```
v1 a 0 dc 0 pulse(0 1 1u 1n 1n 10u 20u)
n1 a mid dd1
n2 mid 0 dd2
.model dd1 d td=1u
.model dd2 d td=0.5u
.tran 0.1u 5u
.print tran v(mid)
```

`v(mid)` is 0 through the operating point and the first 2 µs (the delayed values equal
their inputs at DC, so the op is a clean divider), then, once the first delayed edge
reaches the node: −1e18 at 2.6 µs, 1e27 at 3.4 µs, 1e45 at 4.2 µs, 5.6e62 at 5 µs.
73 accepted points, no `singular matrix` warning, no timestep failure, exit code 0.
With `.option gshunt=1e-9` the matrix is reported singular at once and the run aborts.
The same two elements as child instances of one module around an internal node
(`d #(.td(1u)) c1(a, mid); d #(.td(0.5u)) c2(mid, b);`) print `Warning: singular
matrix: check node n1#mid` six times and the transient ends after its first point —
one row, exit code 0, nothing else. A delay in series with a resistor, in either
order, at top level or in a child, is fine (73 points, the right waveform).

The circuit is numerically ill-posed for a Newton solver: each element's present
current is its *past* voltage over 1 kΩ, so the node has no conductance in the
transient and the matrix pivot is gmin. That is not the compiler's to fix. What is
a defect is that ngspice accepts 1e62 as a converged point and prints nothing, and
that the hierarchical spelling stops the analysis silently instead of failing it. The
2026-09-04 hunt's F3 (an internal node nothing contributes to) was the DC face of
the same class; this is the transient face.

## F9 — `idt` with `assert` relaxes toward the initial condition instead of returning it

LRM 4.5.4: "When specified with both initial conditions and assert, `idt()` returns
the initial conditions during DC and IC analyses, and whenever assert is nonzero.
Once assert becomes zero, `idt()` returns the integral of the argument starting from
the last instant where assert was nonzero."

```verilog
y = idt(1e6, 0.5, V(a,b) > 0.5);   // pulse on a: 1 V from 1 µs to 3 µs
```

| t (µs) | 0 | 0.5 | 1 | 1.5 | 2 | 2.5 | 3 | 3.5 | 4 | 4.5 | 5 |
|---|---|---|---|---|---|---|---|---|---|---|---|
| assert | 0 | 0 | 1 | 1 | 1 | 1 | 1→0 | 0 | 0 | 0 | 0 |
| LRM | 0.5 | 1.0 | 0.5 | 0.5 | 0.5 | 0.5 | 0.5 | 1.0 | 1.5 | 2.0 | 2.5 |
| openvaf-r | 0.5 | 1.0 | 1.5 | 1.45 | 1.41 | 1.36 | 1.32 | 1.82 | 2.32 | 2.82 | 3.32 |

While asserted the output is not 0.5; it decays from 1.5 toward 0.5 as
(1.5 − 0.5)·e^(−t/τ) with τ ≈ 10 µs (a 4 µs hold reaches 1.17), and on release the
integral resumes from 1.32 (or 1.17), so every later value is offset by the amount
that did not relax. The decay is identical with a 0.05 µs step and with
`method=gear`, so it is the realisation — the assert is a pull toward the initial
condition with a fixed rate, not a return of it. With a zero integrand
(`idt(0.0, 0.5, …)`) the output stays at 0.5 throughout, which hides the defect in
any test where the argument is small. A sample-and-hold or a reset integrator
written with `assert` — the LRM's own use case — holds the wrong value.

## F10 — `.option interp` corrupts integer operating-point variables in a transient print

```verilog
(*desc="k"*) integer k; (*desc="r"*) real r; (*desc="big"*) integer big;
analog begin
 k = (V(a,b) > 0.5) ? 7 : 3; r = k; big = 1000000;
 I(a,b) <+ V(a,b)/1e3;
end
```

`.print tran @n1[k] @n1[r] @n1[big]` on a pulse that rises at 1 µs:

| deck | t = 0 | 0.5 µs | 1.5 µs |
|---|---|---|---|
| `.tran 0.5u 2u` | k 3, r 3, big 1e6 | (accepted points, all right) | |
| `.option interp` + `.tran 0.5u 2u` | k **1.48e-323**, r 3, big **3** | k **1.25**, r 3, big **3** | k **1.25**, r 7, big **7** |
| `.dc`, `.op`, `.ac` | k 3 / 7, r 3 / 7, big 1e6 | | |

1.48e-323 is the 64-bit pattern of the integer 3 read as a double (1 reads as
4.94e-324, 2 as 9.88e-324, 4 as 1.98e-323 — seen on event counters in an earlier
probe), and `big` printing `r`'s values is the next vector being read one slot off.
So the `interp` resampling in `ngspice-46` treats every OSDI opvar vector as a double
vector: the integer ones are reinterpreted and the following vector is misaligned.
Real opvars are right with and without `interp`, and the integers are right on the
accepted points, and a control-block `print`, a `let` expression and `meas tran … find`/`max`
all read the integer vector correctly without `interp`, so this is the interpolation
path only. Many of this hunt's own
transient decks used `interp` for a readable grid; the delay values in F1 are real
and were cross-checked without it (`del_only`, `two_delays_toplevel`).

## Smaller notes (not pursued)

- `ddx(pow(x, 2), V(a))` at x = 0 is 2e-18 and `ddx(pow(x, 3.0), V(a))` is 3e-36:
  `mir_autodiff/src/builder.rs` guards the base of `pow` and `sqrt` derivatives with
  a = 1e-18 so that fractional exponents give a finite slope at zero (5e8 for
  `pow(|x|, 0.5)`, by design). For an integer-valued exponent ≥ 2 the true derivative
  at zero is exactly 0 and the guard perturbs it; `ddx(pow(|x|, x), V(a))` at zero
  reads ln(1e-18) = −41.4. Harmless in a Jacobian, surprising in a printed `ddx`.
- `0.0 * x` and `0.0 / x` fold to 0 even when `x` is NaN or infinite (F2's companion
  rules); `x - x`, `x / x`, `min(NaN, 1)`, `abs(NaN)`, `NaN == NaN` all follow IEEE.
- The compile-time help for a literal zero divisor says "the generated code would trap
  and take the simulator with it", but `mir_llvm/src/builder.rs` guards every integer
  division and remainder: a zero divisor yields 0 (remainder 0), `INT_MIN / -1` yields
  `INT_MIN`. A parameter divisor of zero therefore runs and gives 0 on every platform;
  the help text is stale.
- A run-time domain `$fatal` for a parameter argument (`sqrt(q)` with `q = -1`) is
  printed twice per violation — nine calls gave eighteen lines — presumably once in the
  setup pass and once in the first eval.
- An analog function `output` argument the function never assigns writes 0 back into
  the caller's variable (`r` went from 3 to 0) in silence; an analog function that
  never assigns its return value returns 0 (recorded last hunt). Both are lint
  material.
- Integer division in a real context is LRM semantics and unwarned: `parameter real
  half = 1/2` is 0, `x * (1/2)` is 0, `2 ** -1` is 0 (Table 4-6), `(n/2) * x` with
  `n = 3` is `x`. A lint on an integer-typed division whose result feeds a real would
  catch the classic mistake.
- A genvar loop bound must be a literal constant: `for (i = 0; i < n; …)` with a
  parameter `n`, a real bound (`2.5`) and a conditional bound are refused as "the loop
  condition is not a compile-time constant integer". Clear, and consistent with the
  compile-time flattening design, but LRM generate loops routinely use a parameter
  bound. A loop that expands to more than 4096 copies is refused with a count.
- `timer(0)` fires once in `op`, `dc`, `ac` and `noise` as well as in `tran`;
  `initial_step` without a qualifier fires in every analysis (LRM 8.7.1, right);
  `initial_step("ac")` and `final_step("tran")` are honoured.
- `acos(V(a,b))` driven past ±1 by Newton produces NaN and the operating point fails
  as a convergence failure; the run-time domain checks fire for parameter-derived
  arguments only (E-509/E-651's decision). A model with `x * ln(|x|)` fails the same
  way at x = 0 (0 × −∞), which is the model's own.
- `idtmod` with an offset lands in `[offset, offset + modulus)` as LRM 4.5.6 says
  (`idtmod(1.0, 0, 1u, 0.25u)` starts at 1.0 µs); with `.option interp` the row at
  the exact wrap instant is interpolated across the discontinuity (6.1e-7 between
  1e-6 and 0) — the deck's own artefact, noted so nobody chases it.
- `$simparam("tnom")` returns 30 for `.option tnom=30` — Celsius, as LRM Table 9-27
  specifies; `$simparam("iteration")` reads 3 at the operating point;
  `simulatorVersion` is 46.
- A model parameter and its `aliasparam` are refused on the instance line with the
  same message; the alias on the `.model` card sets the parameter and `$param_given`
  of the original reads 1; the alias inside the module body is refused with LRM 3.4.7
  quoted.
- `parameter real r = 1.0` set as `r=0x10` on the card reads 0: ngspice's own number
  reader stops at the `x`, as it does for every device.
- `-5 >> 1` is 2147483645 (logical, LRM 4.2.11) and `-5 >>> 1` is −3 with the
  "openvaf extension" warning; `1 <<< 31` is −2147483648; `~5` is −6; `5 ^~ 3` is −7.
- A `$strobe` `%m` prints the instance name (`n1`); `\101` prints `A`; `%%` prints `%`.
- `$bound_step(1n)` over a 3 µs transient gives 3009 accepted points (73 without), a
  parameter value of 5n gives 616, `if (analysis("tran")) $bound_step(2n)` 1512, a
  `$discontinuity(0)` inside a `cross` event 82: all as intended. The unconditional
  `$discontinuity` at 670,008 points is last hunt's note, unchanged.
- At the first point of a transient `analysis("static")`, `analysis("ic")` and
  `analysis("tran")` are all 1; from the next point only `"tran"`. Whether `"tran"`
  should already be true during the initial operating point is not something the LRM
  table settles; Spectre says yes.
- `$stop` in batch mode prints `pausing` and the run completes; `$finish(1)` prints
  the note with the sweep value and completes the sweep as well (the LRM's `$finish`
  ends the simulation — recorded last hunt as a withdrawn finding, see F6 there).
- A `.dc temp -25 75 50` sweep and `dtemp=10` on the instance reach `$temperature`,
  `$vt` and a temperature-dependent conductance exactly.
- `transition(x, 0, tr)` with `tr = -1u` from a parameter runs as a zero-time step in
  silence; the literal `-1u` is refused at compile time ("the rise time must not be
  negative"). The same for a negative fall time, and `idtmod(1e6, 0, m)` with
  `m = -1` from a parameter runs as a plain integrator (no wrap at all) while the
  literal is refused. This is the E-665 class (run-time domain silences) for the two
  operators it did not cover. A delay that depends on the node voltage or on
  `$abstime` (`absdelay(V, (1+V)*1u, 3u)`, `transition(x, V*1u, 1n)`) is evaluated
  instantaneously and gives the waveform that reading implies.
- `absdelay(V, td, 1u)` with `td = 2u` from a parameter is clamped to the 1 µs
  `maxdelay` in silence; the literal spelling gets the LRM 4.5.7 warning at compile
  time. Clamping is what the LRM prescribes, so this is only the run-time silence.
- `ddt(absdelay(V, 1u))` printed ±1e7 on a half-microsecond `interp` grid after the
  delayed edge; the delayed value itself is flat to 1e-12 (checked as
  `(absdelay(V, 1u) − 1)·1e6`), so the reading is the deck's interpolation between an
  accepted point on the 1 ns edge and the next one, not the model. Noted so nobody
  chases it; `ddt` of the source pulse shows the same on a coarser scale.
- Degenerate filter lists are refused with a reason: an identically zero
  `laplace_nd` denominator, an empty one, a numerator order above the denominator's,
  a `zi_*` period of 0 or negative. An all-zero numerator and a cancelling zero/pole
  pair compile; a coefficient that depends on the solution is warned ("will TRACK").

## Checked and clean, for the record

Derivatives at the singular points of `abs` (±1, 1 at zero), `max`/`min` ties,
`floor` (0), `atan2(x, 0)` (0), `hypot` (0 at zero, the 2026-09-07 F1 fix holds), the ternary,
`exp` and `limexp`; the operating point of `sqrt(|V|)`, `pow(|V|, 1.5)`, `|V|`,
`pow(V, 1/3)`, `V²`, `sqrt(V)`, `pow(V, 0.5)`, `ln(V + 1e-12)` and `tanh(1e6 V)`
driven by a current source (all converge within ngspice's `vntol`). Small-signal
magnitude and phase of `ddt`, `idt`, `idt` with ic, `idtmod`, `laplace_nd/zd/np/zp`
(pole, zero, two poles, complex pole pair, zero at the origin, pole at the origin),
`absdelay` (phase −2πfτ), `zi_nd`, `transition`, `slew`, `ac_stim`, `analysis("ac")`,
`$abstime`, `ddt(ddt())`, `V <+ ddt(I)`, `limexp`, a capacitor with a conductance,
`white_noise` and `ddt(white_noise)` under `.ac`. Transient responses of `transition`
(delay, rise, fall), `slew`, `idtmod` (with and without offset), `idt` with ic,
`laplace_nd` (first-order step response), `zi_nd`, `last_crossing`, and `absdelay`
whenever the op is found by Newton, gmin stepping or source stepping. The run-time
domain `$fatal` for parameter arguments of `sqrt`, `ln`, `log`, `asin`, `acosh`,
`atanh`, `pow` (negative base, fractional exponent; zero base, negative exponent) and
the compile-time refusal of the literal forms; `pow(0.0, 0.0)` = 1, `pow(x, 0.0)` = 1,
`pow(1.0, NaN)` = 1. Integer arithmetic: `-7 % 3` = −1, `7 % -3` = 1, `-7.5 % 2.0` =
−1.5, `7.5 % -2.0` = 1.5, `-7 / 2` = −3, `$clog2(0)` = 0, `abs(INT_MIN)` wraps the
same folded and at run time, shifts by 40 and by −1 warned and 0. Strings:
concatenation, replication, `==`/`!=`/`<`/`>`, the escapes, `$sformat`, `$swrite`,
`{s1, "/", s2}`, `$fopen`/`$fwrite`/`$fdisplay`/`$fstrobe`/`$fclose` (the file holds
the three lines), `$display`, `$write`, `$monitor`, `$debug`, `$info`; every format
specifier tried (`%5.2f`, `%-8.3e`, `%08.3f`, `%+d`, `%x`, `%o`, `%b`, `%c`, `%s`,
`%m`); a missing argument, `%g` of a string and `%s` of an integer refused at compile
time. Macros: textual precedence (`` `A(2)*3 `` = 5), nested, two-argument, multi-line,
a redefinition warned, recursion refused, a wrong argument count refused, `` `undef `` of
an undefined name warned, `` `__LINE__ ``, a string inside a macro body not substituted,
`` `ifdef``/`` `elsif``/`` `else``, nested `` `ifdef``/`` `ifndef``, a same-line
`` `ifdef … `endif``; `` `timescale``, `` `default_nettype``, `` `celldefine``,
`` `resetall``, `` `line`` (two and three fields, L033), `` `pragma``,
`` `begin_keywords`` (warned), `` `unconnected_drive`` accepted alone and in pairs.
Parameters: instance value over card value, an instance default that reads another
instance parameter, L028 on a model default that reads one, `exclude 0`, `(0:1]`
bounds at both ends, `n=1e3` out of `[0:3]` refused, `n=2.5` rounded, a quoted string
on the card, `1k`. Contributions: a named branch, a three-turn loop summing to one
conductance, opposite directions cancelling, `I(<a>)`, `ground`, the V-form resistor,
a cubic, an indirect assignment, an internal node, a switch branch, `V(a,b) <+ 0`
(singular against an ideal source, as it must be), `I(a,a)` refused with LRM 4.4
quoted, `ddt` under a non-constant `if` refused, both `I` and `V` on one branch warned
(L022); contributions that read their own flow (`I <+ 1m + 0.5 I(a,b)` gives 2 mA,
`I <+ V/1k + 0.5 I(a,b)` gives 2V/1k) and their own potential. Analog functions:
nested calls, `inout` write-back, a parameter shadowed by an argument, an integer
function rounding its real result, `$temperature`, `$param_given` and `$strobe`
inside, a local loop, recursion / `ddt` / `V(a,b)` / a keyword name all refused with
the LRM section. `case` on a real, `default` first, `case (1)` with comparisons, a
string, `casez` with `?`, multi-item, an integer against real items, nested, an empty
`case` refused, no default. Genvar loops: nested, shared genvar, index into an array
and a bus, step 2, downward, zero iterations, inner bound from the outer genvar,
multiplicative step, a genvar read after its loop refused with a hint. Events per
analysis: `cross` only in `tran` (both edges, direction +1 filtered), `above` from
`dc` on, `final_step` in all five analyses. Noise: `white_noise` power and its `m=3`
scaling (with the conductance scaling), `flicker_noise` exponents 0 and 1,
`noise_table` (also unsorted), a V-form noise source, sign, amplitude ×2 → power ×4,
two same-name and two different-name sources. `$simparam("gmin")`, `("scale")`,
`("sourceScaleFactor")`, defaults for unknown names, `$vt`, `$vt(350)`,
`$temperature` under `.option temp=40`, `$mfactor` under `m=3`,
`$simparam$str("analysis_name")`/`("analysis_type")`. Variable persistence across an
untaken branch in a downward `dc` sweep (E-7). `$error`, `$warning`, `$info`, `$fatal`
with 0, 1 and 2 as finish numbers, `$finish`, `$stop` under a `dc` sweep, a transient
and `.ac`. `transition` across the falling edge of a pulse with equal, unequal and
delayed rise/fall times (never below −1e-19), on a continuously varying input,
`slew` with asymmetric rates, `absdelay` inside a flattened child next to a resistor
child, and a delay and a resistor in series in either order at top level. The command
line: `-D NAME` (value 1) and `-D NAME=3`, `-I dir` for an `` `include ``, `-o` to a
file (a directory is refused), a missing input, a second positional file and an
unknown flag all refused with a usage line; `-E lint`, `-E warnings`, `-A all`, an
unknown lint name listed against the 32 known ones, `(* openvaf_allow="…" *)` on one
declaration. Model-card enforcement of a string `from {"lin","log"}` (case-sensitive),
an integer `from {1,2,4}`, `exclude [4:6]` at both closed ends, `exclude 5` against
5.0000001, and an instance range `(0:inf)` from the instance line and from the card's
instance default. `$param_given` of an instance parameter set on the card (1) and of
one never set (0). A V-form `white_noise` under `m=3` (three parallel copies, 4.33e-8
against 5e-8, right). `@(initial_step or final_step)` (2), `@(cross(…) or timer(2.5u))`
(3), `$mfactor` read inside a child instance under `m=2`, a 3-port module connected
with 2 ports (`$port_connected` 0, with ngspice's note) and with 4 (refused).
`$fopen` with `"a"` appends, `"w"` truncates a stale file from an earlier run, a
failed open returns 0 and its writes vanish, `$fwrite(1, …)` reaches stdout,
`$fclose(99)` is silent; a second `"w"` open of the same path inside one run continues
the stream, which is the 2026-09-08 hunt's F6, unchanged.

## Coverage, honestly

Not touched this hour: the `interp` path for integer opvars under `.dc` (F10 was
shown for `.tran` only), `idt` with `assert` under `.ac` and the four-argument
`idt(x, ic, assert, abstol)` beyond compiling, `$table_model`, the IHP library, KLU against Sparse, the RF
analyses, the corner and loop commands (as fixed yesterday), hierarchy and
instantiation, bus part-selects, `$bound_step` and `$discontinuity` in a transient,
`transition` with a non-constant delay argument, `absdelay` with `maxdelay` under the
Transient-op path (only the plain form was bisected), noise in a transient
(`trnoise`), the Windows and Linux binaries (F1 was reproduced on the macOS build only;
nothing in it is platform-specific). The F1 mechanism was bisected to the trigger
(the Transient-op path) and the two symptoms (opvar reads 0, contribution reads the
input); the ngspice source was not read, so the exact line is not named. The events
family (p15) was run under five analyses but only with the one pulse; `timer` with a
period and `cross` tolerances were left as last hunt recorded them.
