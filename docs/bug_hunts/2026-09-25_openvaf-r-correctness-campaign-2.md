# openvaf-r correctness campaign 2 — the compiler against itself, a hierarchy against its flattening, the operators against the simulator's own elements

**Date:** 2026-09-25, 09:00–10:00, at head `4bc5a0e7` (E-719). **Binaries:** the repo's
`OpenVAF-master-20260610/target/opt/openvaf-r` (built 08:20 on 2026-09-25, the E-718 tree; the E-719
change is simulator-side) and `ngspice-46/build/src/ngspice` (built 08:31 on 2026-09-25, E-719).
**Method:** seven throw-away harnesses in the scratchpad (`cc2/harnA.py` … `harnG`), about
90 compiles and 260 ngspice runs, each again an *oracle* rather than a list of cases. The
[first campaign](2026-09-25_openvaf-r-correctness-campaign.md) took the compiler's core —
folder, lowering, differentiation, operators, noise — and asked each to agree with a
Python model, a finite difference or a closed form. This one asks other questions: does
the compiler agree with *itself* at every optimisation level; does a hierarchy agree with
its hand-flattened twin; do the derivatives survive loops, arrays with run-time indices,
`while` loops with a data-dependent count, and analog functions with output arguments; do
the stateful operators survive timestep rejections under both integration methods; does a
Verilog-A inductor, mutual pair or `idt` capacitor agree with ngspice's own L, K and C;
is charge conserved; are instances independent; and what do the filters do where the LRM
leaves corners. Nothing was fixed; this is the list.

The ground, and what held:

- **The compiler against itself, -O0 to -O3** (harness A). One file of modules — 27
  integer overflow and shift probes (the UB an optimiser exploits when the IR carries
  `nsw` or an unguarded shift: `pbig + pone < pbig`, `pmin / pm1`, `abs(pmin)`, `-pmin`,
  `pone << 32`, `pm1 ** pbig`), 30 NaN and infinity probes (`inf - inf`, `sqrt(-x)`,
  `ln(-x)`, `0/0`, `pow(NaN, 0)`, `$rtoi` of ±inf and NaN), eight smooth nonlinear
  modules with `ddt`, and six deliberate cancellation shapes — compiled at each of the
  four levels. The integer probes are bit-identical at every level and equal to the
  32-bit wrap model; the NaN probes agree across levels (two literal-zero cases below);
  the smooth modules' op values and `.ac` Jacobians agree to 3e-16 and their transients,
  interpolated onto a common grid, to 4e-10 of full scale; the cancellation shapes give
  the same rounding at every level (a `ddx` of `(x·2⁵³ + x) − x·2⁵³` is 0, as the value
  is, and of `(x + 1e16) − 1e16` is 1).
- **The Jacobian through loops, arrays and functions** (harness B). Twelve modules whose
  contributions pass through a `for` loop over a parameter array, a `while` loop with a
  data-dependent count, an array filled in a loop and read with a parameter index, an
  analog function with an `output` argument, one with an `inout` argument, nested calls
  `fa(fb(x), fc(y))`, a piecewise function, the same function twice with a local, a
  `case` on `$rtoi` of a voltage, a 2-D array with parameter indices, a function with a
  loop inside, and contributions accumulated inside a loop: 48 Jacobian entries from
  `.ac` against central differences of the dc currents and against the analytic
  derivative, all within 1.2e-5 (the difference's own error); an element of the
  coefficient array moved on the card moves the polynomial and its derivative.
- **A hierarchy against its flattening** (harness C). A parent with two RC children and a
  diode child (series resistance, an internal node, shot and flicker noise), parameters
  passed by expression from the parent's, against the same equations written flat: op,
  `.ac` magnitude and phase over 1 kHz–10 MHz, the output noise spectrum, a 300 µs
  transient and a child's `@(cross)` counter (read as `r1__cnt`), plain and with `m=2`
  and `dtemp=30` — **bit-identical**, every number. Two same-named `white_noise` calls in
  two instances of one child are uncorrelated, as the flat twin's two names are.
- **The stateful operators under rejections** (harness D). `idt`, `ddt`, `absdelay`,
  `last_crossing`, a `cross` counter, a `timer` counter, `transition` and `slew` on a
  1 kHz sine and a pulse, with an ngspice diode rectifier on the pulse forcing the step
  control to reject 30 to 94 points per run, under trap and gear at reltol 1e-3 and
  1e-5: at every accepted point `idt` within 1.8e-5, `ddt` 5e-5, `absdelay` 6e-5 of
  amplitude; `idt(ddt(x))` returns x to 1e-9; the crossing and timer counts exact at every
  point; `last_crossing` within 1.4 ns; nothing goes backwards after a rejection; time
  strictly increasing (what read as repeated points was print precision).
- **Flow branches against the simulator's own elements** (harness E). `V(a,b) <+
  L·ddt(I(a,b))` against ngspice's L, a series RL, a mutual pair through two flow branches
  against `K`, and a capacitor written as `V <+ idt(I)/C` against `C`: `.ac` over four
  decades and a transient to 5e-16 — except the `idt` capacitor's `.ac`, F1 below. A
  nonlinear charge `q(V)` driven through four full cycles moves 7e-19 C net; the
  trapezoid of the current over the accepted points matches the exported charge to 5e-14
  of a 1.7e-9 swing; `ddt(x·y)` equals `x·ddt(y) + y·ddt(x)` to 3e-5, `ddt(idt(x))`
  returns x to 2e-13.
- **Instances are independent** (harness F). Six instances of one module — three
  `.model` cards with real, integer, array-element and string overrides, an instance
  parameter over a model one, `m`, `dtemp` and their combination — in one deck against
  each simulated alone: 36 values identical; a second module with the same parameter
  names beside them keeps its own.
- **The filters' corners** (harness G). A three-level `transition` input takes the
  full-swing rate and lands exactly at delay plus rise; `slew` with one rate limits both
  directions at it (the LRM's default), with two rates each at its own, with none is the
  input; a positive negative rate is refused at compile time; `absdelay` with a delay that
  itself varies in time (50 µs + 50 µs·V(c)) returns V(a)(t − td(t)) to 2e-6; a
  `transition` with a delay only reproduces the input's own 1 ns edge 15 µs later.

## Summary

| # | finding | kind |
|---|---|---|
| [F1](#f1--an-idt-asserted-on-analysisstatic-has-no-integrator-in-the-small-signal-analyses) | `V(a,b) <+ idt(I(a,b), 0, analysis("static"))/C` — the LRM's own idiom for an integrator that must be pinned at the operating point — is a **short** in `.ac` (\|i\| = 1/R, 158× off) and `I <+ k·idt(V, 0, analysis("static"))` an **open**; `if (analysis("static")) V <+ v0; else I <+ ddt(C·V)` is a short in `.ac` too; the same with `analysis("dc")`, `analysis("ic")` or no assert is right. ngspice's small-signal linearisation pass (`MODEINITSMSIG`) carries `ANALYSIS_STATIC`, so the model sees the LRM's AC-OP column where the sweep needs the AC column (static 0) | simulator side: a wrong small-signal model from a legal idiom |
| [F2](#f2--the-caret-label-of-every-argument-diagnostic-reads-invalid-the-argument-for-sqrt) | the caret label of every constant-argument diagnostic reads "invalid the argument for sqrt", "invalid the maximum negative rate for slew", "invalid the denominator for …": `format!("invalid {what} for {builtin}")` with a `what` that carries its own article, at 63 call sites | diagnostic wording |
| [F3](#f3--an-interrupted-transition-ramps-at-068-of-the-full-swing-rate) | *(fixed in [E-720](../../enhancements_doc/Enhancement-720.md): the source's 1 ns edge was a dozen accepted points, each a change, and the reversal took an intermediate value as the interrupted ramp's destination; every change after an edge's first now readjusts against the ramp the first found, and the edge's ramp gets its corners)* a `transition` interrupted half-way (rise 20 µs, a fall requested at 0.5) ramps down at 2.28e4 V/s and reaches 0 after 22.0 µs — neither the LRM's full time from the current value (30 µs) nor the full-swing rate (15 µs); with fall 20 µs, 14.67 µs: the same fraction 0.733 of the fall time either way | operator semantics at a corner the suites do not pin |

## F1 — an `idt` asserted on `analysis("static")` has no integrator in the small-signal analyses

**Observed.** `cc2/E/idtac.va`, a 1 kΩ resistor from the source into the module, `.ac` at
1 kHz, the analytic \|i\| = 1/\|R + 1/(jωC)\| = 6.283e-6 A:

| module | `.ac` \|i(v1)\| | phase |
|---|---|---|
| `V(a,b) <+ idt(I(a,b), 0.0, analysis("static")) / 1e-9` | **1.000e-3** (= 1/R: a short) | π |
| the same asserted on `analysis("dc")` | 6.283e-6 | −1.577 |
| the same asserted on `analysis("ic")` | 6.283e-6 | −1.577 |
| `idt(I(a,b))`, no assert | 6.283e-6 | −1.577 |
| `I(a,b) <+ 1e-3 · idt(V(a,b), 0.0, analysis("static"))` | **0** (an open; 1.59e-7 expected) | — |
| `I(a,b) <+ ddt(1e-9 · V(a,b))` | 6.283e-6 | −1.577 |
| `if (analysis("static")) V(a,b) <+ 0.3; else I(a,b) <+ ddt(1e-9·V(a,b));` | **1.000e-3** (a short) | — |
| the same on `analysis("ic")` | 6.283e-6 | — |

The transients of the same modules match ngspice's own capacitor to 1.4e-14, and the
operating points are right. A `$strobe` of the flags the model sees prints one line per
small-signal job: `static=1 dc=0 ac=1` for `.ac`, `static=1 dc=0 ac=0 noise=1` for
`.noise`.

**Where.** `ngspice-46/src/osdi/osdiload.c`, `OSDIload`: `is_dc` is `MODEDCOP |
MODEDCTRANCURVE`, and ngspice runs the small-signal pass (`MODEINITSMSIG`, the one
evaluation whose resistive and reactive Jacobians the whole `.ac` and `.noise` sweep
uses) with `MODEDCOP` set, so that evaluation gets `ANALYSIS_DC | ANALYSIS_STATIC`;
[E-53](../../enhancements_doc/Enhancement-53.md) and [E-684](../../enhancements_doc/Enhancement-684.md)
then replace the DC bit with the owning analysis's name and leave `ANALYSIS_STATIC`,
which is right for the *operating point* of the job (LRM Table 4-22's AC-OP column) and
wrong for the *sweep* (the AC column: static 0, ac 1). The compiler lowers `idt(x, ic,
assert)` as a select between `ic` and the integrator state, and a topology switched on
`analysis("static")` the same way, so with the static bit on, the linearisation has no
reactive part for them: the `idt` is the constant `ic`, the `V <+ v0` branch a short.

**Expected.** The linearisation pass carries the sweep's flags — `ANALYSIS_AC` or
`ANALYSIS_NOISE` and not `ANALYSIS_STATIC` — so that an integrator asserted on "static"
(the idiom of LRM 4.5.5's own example) is 1/(jω) in `.ac` and `.noise` exactly as one
asserted on "dc" or "ic" already is, and a model that switches its topology on "static"
linearises its dynamic branch. The operating point, `@(initial_step("ac"))`, the op
variables and the events keep the AC-OP flags they have. The suites that pin the phase
flags (`lrmnoise`, `lrmfuncs`, `analyses`, `finalstep`, `evtnoise`) pin op and tran
phases, not this pass.

**Kind.** Simulator side; a wrong small-signal model from a legal idiom, silent.

## F2 — the caret label of every argument diagnostic reads "invalid the argument for sqrt"

**Observed.**

```
error: sqrt: the argument is -1, which is outside the domain of sqrt (values >= 0); the result would be NaN
   |
88 |   r10 = max(V(a), sqrt(-1.0)) == ...
   |                        ^^^^ invalid the argument for sqrt
```

and `invalid the maximum negative rate for slew`, `invalid the denominator for %`,
`invalid the format for $strobe`, `invalid the degree for $discontinuity`.

**Where.** `hir_ty/src/validation.rs:1835`, the renderer of
`BodyValidationDiagnostic::InvalidBuiltinArg`: the headline is `"{builtin}: {what}
{why}"`, which reads well because the callers pass `what` as a noun phrase with its
article ("the argument", "the denominator", "the maximum negative rate" — 63 `bad_arg` /
`warn_arg` sites in `hir_ty/src/validation/body.rs`), and the caret label is `"invalid
{what} for {builtin}"`, which does not.

**Expected.** A label that takes the noun phrase as the callers write it — "the argument
is invalid for sqrt", or "not a valid argument" with the article dropped — at the one
renderer, not at 63 call sites.

**Kind.** Diagnostic wording.

## F3 — an interrupted `transition` ramps at 0.68 of the full-swing rate

**Observed.** `cc2/G/ti.va`: `transition(V(b), 0, 20u, 30u)` on a pulse that rises at
5 µs (the ramp would end at 25 µs) and falls at 15 µs, when the output is 0.5000:

| filter | slope after the interruption | reaches 0 at | LRM full time from 0.5 | full-swing rate |
|---|---|---|---|---|
| rise 20 µs, fall 30 µs | −2.277e4 V/s | 37.01 µs (22.0 after) | 45.0 µs (30 after) | 30.0 µs (15 after) |
| rise 20 µs, fall 20 µs | −3.415e4 V/s | 29.67 µs (14.67 after) | 35.0 µs | 25.0 µs |
| delay 10 µs, rise 20, fall 30 | −2.277e4 V/s | 46.96 µs | 55.0 µs | 40.0 µs |

The fraction is 0.733 of the fall time in every row, for a half swing. The output is
continuous throughout (no jump at the interruption; it overshoots the turn by 5e-5 while
the 1 ns input edge is in flight, which is the tracking loop [E-512](../../enhancements_doc/Enhancement-512.md)
made of the filter). A three-level input whose steps are not interrupted lands exactly.

**Where.** ngspice's transition scheduler (`src/osdi/osdiaccept.c`, the accept hook
[E-698](../../enhancements_doc/Enhancement-698.md) gave the operator when it made it the
simulator's; the compiler's tracking loop of [E-512](../../enhancements_doc/Enhancement-512.md)
is gone since then). The harness feeds the source's own 1 ns edge into the operator,
and the integrator resolves that edge with a dozen accepted points — the input read
0.99, 0.97, 0.935, 0.90, 0.893, 0.879, 0.851, 0.795, 0.683, 0.459, 0.2295, 0 inside it —
each of them a change of the input and a readjustment. A continuing direction takes
the interrupted ramp's origin, which stays the edge's level, so an uninterrupted edge
lands exactly; the reversal takes the ramp's *destination*, and by the first point
below the output (0.459) that is the previous point's value, 0.683: the ramp to 0 runs
at (0 − 0.683)/tf. The comparator form of the same edge (`V(b) > 0.5 ? 1 : 0`, the form
E-698's suite pins) changes once and runs at (0 − 1)/tf, 15 µs after.

**Expected.** One of the two readings of LRM 4.5.7 for an interrupted transition, stated
and pinned: the full transition time from the current value (Spectre's documented
behaviour is the rate of the original swing, ngspice's XSPICE `d_*` models take the
full time), the same for `slew`-like corner cases, and a suite check for it.

**Kind.** Operator semantics at a corner no suite pins; the value is continuous and lands.

*Fixed in [E-720](../../enhancements_doc/Enhancement-720.md).* The LRM's reading is
not in doubt — the slope of a reversed transition is `(v3 − v2)/tf3`, the original
destination over the new fall time, and E-698 had it — the corner was the edge's width:
a source's edge is a run of accepted points, and each point after the first readjusted
against what the previous point had made of the ramp. E-698 already told a change that
follows a change apart (it places no breakpoints for it); such a change now readjusts
against the ramp the run's first change found, on the direct path and behind a delay,
so the source's edge falls at 1/tf like the comparator, whatever its width, at 1 ns or
1 ps, at `reltol` 1e-3 or 1e-6. The edge's ramp gets its trailing corner breakpoint
once the input holds still, and behind a delay the edge's final due time gets one (its
ramp had started 0.19 µs late on a 1 µs step). `transedge` section 6, four checks: 30
of 30 per solver, 27 of 30 on the E-719 binaries.

## Observations, not findings

- **A literal zero factor annihilates NaN and infinity**: `0.0 * xinf`, `xinf * 0.0`,
  `0.0 * sqrt(-x)`, `0.0 / (x − x)`, `(1.0 − 1.0) * xinf` all read 0 at every
  optimisation level, where a parameter zero (`pz * xinf`) reads NaN. This is
  [E-337](../../enhancements_doc/Enhancement-337.md)'s documented exception in
  `mir_opt/src/simplify.rs`: the `x * 0 → 0` fold is kept because `flag * term` with a
  zero flag is how compact models disable a term that is non-finite when disabled, and
  removing it changed HiSIM2's drain current tenfold. Recorded as verified, not reopened.
- **`min` and `max` with a NaN operand depend on the operand order**: `max(x, NaN)` is
  NaN and `min(NaN, x)` is x — they are `x > y ? x : y` and `x < y ? x : y`, the
  second-operand tie rule the first campaign recorded. The LRM gives no NaN rule; C's
  `fmax` returns the number. Left as is.
- **A `ddt` assigned to a variable is timestep-controlled like a 1 F capacitor**: `c =
  ddt(V(a))` on a smooth sine costs nothing alone, but once a rectifier elsewhere in the
  deck forces 1e-11 s steps at its edges, that "charge" of 1 C scale takes the transient
  from 2 359 accepted points to 6 265 with 3 151 rejections at reltol 1e-5 (steps to
  1.3e-14 s). ngspice's own `C2 a 0 1` does exactly the same (6 225 and 3 110), and
  `chgtol=1e-9` cures both: it is the simulator's LTE control on a large charge with a
  wildly non-uniform step history, not the compiler's. At the default reltol the effect
  is 1747 points against 1735.
- **A charge that jumps inside an `if`** (`q = 1e-9·V + 3e-10` above 0.5 V) stops the
  transient at the crossing with "timestep too small", with or without a
  `$discontinuity(0)` announced from a `@(cross)`: the current is a delta; a current that
  steps inside the same `if` is taken in stride. A model-side rule, worth a line in the
  handbook.
- **A child instance's variables are exported as `<child>__<name>`** (`r1__cnt` in
  `show n1`), which nothing documents.
