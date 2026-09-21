# openvaf-r bug hunt — the Laplace and z filters, `$table_model`, and the noise sources

**Date:** 2026-09-21, one hour (17:41–18:41; the probes ran until 18:06, the write-up
interleaved from 18:01 on), at head `c67b050c` (E-698, the simulator-side `transition` and `slew`).
**Binaries:** the repo's `OpenVAF-master-20260610/target/opt/openvaf-r` (built 15:15)
and `ngspice-46/build/src/ngspice` (built 15:37), both from the E-698 tree. **Method:**
187 small Verilog-A modules and about 190 decks written for the hour, compiled and run on
ngspice through a throw-away harness in the scratchpad (`hunt3/h3.py`, `pA.py … pP.py`),
each probe checked against the VAMS-2023 text (`pdftotext -layout docs/VAMS-LRM-2023.pdf`,
clauses 4.5.11–4.5.14, 4.6.4 and 9.21) or against the closed-form transfer function,
spline or table value computed beside it. Nothing was fixed; this is the list.
The ground chosen was the three areas the catalog is thinnest in and no hunt had
walked: every `laplace_*` and `zi_*` form with real, complex, origin and null roots,
the LRM's own filter examples, coefficient vectors as literals, `parameter` and
`localparam` arrays, improper and degenerate coefficient lists, the `abstol` argument,
step and cascade responses; `$table_model` with the LRM's `sample.dat` and its 9.21.5
array module verbatim, ragged isolines, every control code of Tables 9-30/9-31 including
`"C,,3"`, `"3,D,I,1;3"` and the dependent selector, the spline end conditions of 9.21.4,
data-file formats, duplicate and insufficient data, arrays filled at run time; and the
four noise functions with exponents, unsorted, duplicated and single-pair tables, files,
the 4.6.4.5 diode and 4.6.4.6 correlation examples verbatim, noise through a filter, and
the sources' silence in `op`, `ac` and `tran`.

## Summary

| # | finding | kind |
|---|---|---|
| [F1](#f1--a-z-filter-root-at-the-origin-is-dropped) | *(fixed in [E-699](../../enhancements_doc/Enhancement-699.md): the origin roots are split off when the model is compiled and applied as the power of `z` they are — a shift of the coefficient vector in z⁻¹ — so a zp/zd/np pole at zero is the one-period delay and a zero the advance of 4.5.12, exactly the `zi_nd` spelling; a root the deck can set stays `1 − z⁻¹ r`)* a `zi_zp`/`zi_zd`/`zi_np` root at the origin contributes **1** where LRM 4.5.12 implements it as **`z`**: a pole at zero (the zp spelling of a one-sample delay) is a wire, and the same delay written as `zi_nd` coefficients is right | wrong result, silent |
| [F2](#f2--e-extrapolation-aborts-on-the-first-newton-iterate) | the `E` extrapolation error is judged on every Newton iterate, so a table whose domain excludes the zero initial guess aborts before the first solve — the LRM's own `sample.dat` under `"1L,1E"` cannot evaluate its Figure 9-2 point | abort where the solution is inside the table |
| [F3](#f3--a-cubic-spline-under-c-keeps-the-natural-end-condition) | `3C` builds the natural spline and clamps outside it, so the first derivative jumps at the table edge (7.43 to 0 on the `x²` samples); LRM 9.21.4 sets the end derivative to zero under `C` precisely to avoid that | deviation, silent, reaches the Jacobian |
| [F4](#f4--a-trailing-comment-on-a-data-line-makes-the-file-unusable) | a `#` comment after the numbers on a line makes the whole file "missing, unreadable, or contains no usable table data" for `$table_model`, `noise_table` and `noise_table_log`; 9.21.1 allows comments anywhere, 4.6.4.3 before or after any pair | refusal of legal input |
| [F5](#f5--the-data-errors-of-921-are-not-raised) | one isoline in a 2-D table, an isoline with a single point, and two rows with the same coordinates and different values are all accepted — the last with a warning that says the LAST value anchors when the FIRST is kept; a dependent selector outside 1..M picks a column in silence | silence, one slip |
| [F6](#f6--a-run-time-array-table-follows-the-solution) | the 1-D array form whose data the body computes is rebuilt at every evaluation; 9.21.1 captures the data on the first call and ignores later changes, and the analogous `laplace_*` policy at least warns | deviation, silent |
| [F7](#f7--diagnostic-slips) | a file with too few columns for its inputs is reported as unreadable; a null denominator draws a type error spelt `_[0:0]` beside the real one; a negative or zero Laplace `abstol` passes where `ddt`'s is refused; the run-time array form refuses `"1E"` as "unsupported" while its own note lists `E` as supported | diagnostic slips |

Dropped after checking the LRM, the code or the numbers: every `laplace_*` form with a
real, complex, null and origin root gives the closed-form response (the null zeros
argument `laplace_zp(x, , p)`; a zero at the origin is `s`, a pole at the origin `1/s`,
both at once `s/s = 1`, `laplace_nd` with `d0 = 0` is the same integrator); the LRM's
examples 4.5.11.5 (the `zp` pair, `s/(s²−1)`, and the band-limited noise source, which
the compiler builds from the four poles it lists — the clause's prose `k/(s²−1)²`
describes two, the example is inconsistent with itself); an improper filter (`'{0,1}`
over `'{1}`, an odd zero count, `'{}` poles) is refused with a diagnostic that says why
and points at `ddt` — the LRM formula admits it, Spectre refuses it the same way; a
trailing zero denominator coefficient refused; the `abstol` argument as a real and as a
nature; a `localparam` vector built from card scalars retunes from the deck (`wc=2e3`),
while an array `parameter` is not a card parameter at all (ngspice: "unrecognized
parameter (d)") — the OSDI card has no arrays; the lone complex root still builds a
different real filter in silence (0.894 against 1.0), which the compliance document
already records as open; `zi_*` AC and transient are the continuous bilinear image
(documented: 1.649 against the true 1.639 at `ωT = 0.5`, a ramp through a unity filter
is a wire), `T` from a card parameter retunes, a zero transition time in the 6-argument
form draws 4.5.12's "shall not be assigned to a branch" warning; the four noise functions
match every closed form tried (flicker exponents 0, −1, 1, 2.5; an unsorted table is
sorted; a duplicated frequency refused by name; a single pair is a constant; the
same label twice in one instance combines into `onoise_n1_th`; the 4.6.4.5 diode and
the 4.6.4.6 partially-correlated example, whose common source cancels through the load
at `corr = 1`, to 1e-10; a noise source in a filter is shaped by `|H|`; `op`, `ac` and
`tran` see zero); a string parameter as a noise label is refused ("expected string
literal") — Syntax 4-4's `string` is the literal token; an overridable `parameter
string` as a file name or control string is refused with a pointer to `localparam`
(documented); `$table_model` with the LRM's `sample.dat` and its 9.21.5 array module
gives the Figure 9-2 value 2.0 and extrapolates on each ragged isoline as the clause
describes; `"C,,3"` equals `"1CC,1LL,3LL"`, `"3,D,I,1;3"` selects, ignores and interpolates
as Table 9-32 says; `D` snaps away from zero on a tie; the quadratic spline is a C¹
forward-chained parabola (2.0 at 1.5 on `x²`); `3L` extrapolates with the spline's own
end slope; `C` clamps per isoline on ragged data; shuffled rows are sorted; an exact
duplicate row is dropped with the warning 9.21.1 permits; `ddx` of a table is the
segment slope; `ddt` of a table is a charge; a 4000-row table compiles in 5 s and a
60×60 cubic grid in 7 s; twelve coincident poles written as roots and as binomial
coefficients agree to 1e-6; the noise summary of a flattened hierarchy combines
same-labelled sources of two child instances into one entry (`onoise_n1_kid` is
their power sum) — 4.6.4.1's "same instance" rule applied after elaboration, with
the totals right; the integrated `onoise_total` over a decade sweep is the rms of
the closed-form integral.

## What was read and run

LRM sections read for the probes: 4.5.11 (the four Laplace forms, the null zeros
argument, the origin-root rule, the 4.5.11.5 examples), 4.5.12 (the four z forms, `T`,
τ and `t0`, the origin-root rule "implemented as z"), 4.5.13, 4.5.14 (Table 4-20),
4.6.4 (Syntax 4-4, the four sources, the file format of 4.6.4.3, the 4.6.4.4 formula,
the 4.6.4.5 diode, the 4.6.4.6 correlation examples), 9.21 (Syntax 9-16, the data
requirements, 9.21.1's file format and "captured on the first call", 9.21.2, Tables
9-30 to 9-32, 9.21.4's spline end conditions, the 9.21.5 modules).

Compiler source read: `hir_lower/src/expr.rs` (`zi_roots_to_poly` at 4921 and
`laplace_roots_to_poly` at 4820, `lower_zi` at 5087, `lower_laplace` at 4664;
`parse_table_ctrl_cols` at 128, `split_table_dep` at 103, `build_tbl_tree` at 80,
`natural_cubic_spline_moment_matrix` at 196, `read_noise_table_file` at 1308,
`read_table_tokens` at 1364, `read_table_lines` at 1405, `read_table_isoline_tree` at
1443, `interp_tbl_tree` at 1465, `apply_end_extrap` at 1614, `interp_1d_spline_runtime`
at 1966, `interp_1d_spline` at 2380, `lower_table_model` at 2526,
`lower_table_model_arrays` at 2686), `hir_lower/src/ctx.rs` (`runtime_fatal` at 258,
`runtime_warn` at 287, `make_select` at 415), `hir_ty/src/validation.rs`
(`table_file_is_usable` at 2480, the `TableFileUnusable`, `TableFileDupKnot` and
noise-table reports at 372–460).

Probe families, in the order they ran (`hunt3/pX.py`):

- **pA** — Laplace: null zeros; a zero and a pole at the origin, both; the three
  4.5.11.5 examples; a `parameter` vector and its card override; an odd pair count;
  `d0 = 0`; a trailing zero; `'{0,1}` over `'{1}`; a biproper filter; the step response
  at τ and 3τ; a cascade; `abstol` as a real and a nature; a `'{}` vector; `'{0}`
  numerator; `ddt` of a filter; a null argument in the other positions. z: a zero at the
  origin, `T` as a parameter and overridden, `d0 = 0`, `z⁻¹`, more zeros than poles,
  `2*T`, null zeros, a ramp through a unity filter.
- **pB, pK** — noise: the spectrum unit; `ac`/`op` with a 1e6 source; flicker
  exponents 0, 2.5, −1, 1 and from the card; an unsorted, a duplicated, a single-pair
  table; a file with comments, tabs and integers; a missing file; `noise_table_log`
  with a zero power and a zero frequency; the same label twice; the 4.6.4.5 diode
  verbatim; `abs`, `exp` and the product of noise sources; parameters inside the inline
  vector; a string parameter label; `4kT/R`; flicker of a zero current; the 4.6.4.4
  formula; the 4.6.4.6 Example 2 at `corr` 0, 0.5, 1; a filter fed signal plus noise.
- **pC, pE, pG, pH, pI, pJ** — tables: `sample.dat` at seven points including the
  ragged extrapolations; the 9.21.5 array module verbatim; `"C,,3"` against its
  expansion on a 3-D file; `";2"`, `"1L;2"`, `";5"`, `";0"`; shuffled rows; a one-point
  isoline; a one-isoline 2-D file; `2`, `3`, `3L`, `3C`, `3CC`, `2L`, `2C`, `3LC` on
  `x²` and `x` samples against natural and clamped splines computed beside them;
  `E` in `op`, in a `dc` sweep, on the outer axis, on the inner axis of ragged and
  regular tables, over `[1,4]` with and without `.nodeset`/`.ic`/`uic`; inline `'{}`
  arrays; a file with tabs, inline comments, integers and blank lines and its nine-way
  bisection; a string-parameter file name; `ddx` and `ddt` of a table; a two-point
  cubic; the `D` tie rule at ±1.5 and 0; `";2"` on the array form; exact and
  conflicting duplicate rows; `"1L,1L"`, `"1LLL"`, `"Q"`; a 2-D file with one input and
  with `"I,1L"`; `"3,D,I,1;3"`; data computed from `V(a,b)`; two inputs on a two-column
  file; `"1E"` on the run-time array form.
- **pD** — the array-override route on the card, model and instance.
- **pL, pM** — origin roots in every z form by magnitude and phase, and the step
  response of the zp delay against the nd delay.
- **pN, pO, pP** — 200/1000/4000-row and 60×60 tables (compile time, `.osdi` size);
  eight and twelve coincident poles as roots and as coefficients; `abstol` negative,
  zero and from a parameter across `ddt`, `idt` and the Laplace forms; the integrated
  noise summary; `"1L,I"`; a z accumulator; noise labels under instantiation.

## F1 — a z-filter root at the origin is dropped

**Observed.** LRM 4.5.12.1: "If a root is zero, then the term associated with it is
implemented as z, rather than (1 − z⁻¹ r)". A pole at the origin is therefore `1/z`, a
one-sample delay, and a zero at the origin a one-sample advance; the same clause's
numerator-denominator spelling of that delay is `zi_nd(x, '{0, 1}, '{1}, T)`. At
`ωT = 0.5` (`hunt3/pM.py`; phases in degrees, the bilinear image the compiler documents):

| call | `\|H\|` got / expected | phase got / expected |
|---|---|---|
| `zi_zp(V(in), , '{0, 0}, 1u)` — a pole at the origin | 1.000 / 1.000 | **0.000** / −28.07 |
| `zi_np(V(in), '{1}, '{0, 0}, 1u)` | 1.000 / 1.000 | **0.000** / −28.07 |
| `zi_zd(V(in), '{0, 0}, '{1}, 1u)` — a zero at the origin | 1.000 / 1.000 | **0.000** / +28.07 |
| `zi_nd(V(in), '{0, 1}, '{1}, 1u)` — the same delay as coefficients | 1.000 / 1.000 | −28.07 / −28.07 |
| `zi_zp(V(in), '{0, 0}, '{0.5, 0}, 1u)` | 1.649 / 1.649 | **−22.83** / +5.24 |
| `zi_zp(V(in), , '{0, 0, 0.5, 0}, 1u)` | 1.649 / 1.649 | **−22.83** / −50.91 |
| `zi_np(V(in), '{1, 1}, '{0, 0, 0, 0}, 1u)` | 1.940 / 1.940 | **−14.04** / −70.18 |

On the unit circle `|z| = 1`, so every magnitude agrees and only the phase shows the
missing factor — which is why a magnitude-only check never saw it. In transient
(`tran 0.01u 3u`, a step at 1 µs) the zp pole at the origin is a wire (1.0 at 1.05 µs,
1.0 at 2.5 µs) while the nd delay is the bilinear all-pass the compiler documents
(−0.81, then 0.90).

**Expected.** A pole at the origin delays by one period, a zero advances by one; the
zp/zd/np spellings and the nd spelling of one filter agree.

**Where.** `hir_lower/src/expr.rs`, `zi_roots_to_poly` (4921). Its doc comment states
the choice: "There is deliberately no zero-root special case. The LRM's `(1 − s/r)`
exception exists because that form divides by the root; `(1 − rho·w)` does not, and at
`rho = 0` it is simply 1." That reads the exception as a guard against a division by
zero. The z clause has no division and still states the rule, because a root at the
origin of the z-plane is a pure delay or advance — the term `1 − z⁻¹·0 = 1` is not
degenerate, it is simply not the filter the LRM defines. `laplace_roots_to_poly` (4820,
Enhancement-405) selects the `s` term at run time for the Laplace forms; the z forms
need the same select building `z` (a shift of the coefficient vector by one, the
denominator's shift being the numerator's in the bilinear map), which is what the nd
spelling already gets from its coefficients. The 09-19 hunt's filter checks and the
`lrmfilters` suite exercised origin roots only in the Laplace forms.

**Kind.** Wrong result, silent; every `zi_zp`, `zi_zd` and `zi_np` with a root at
the origin — the natural way to write a pure delay in root form. Not platform-specific.

*Fixed in [E-699](../../enhancements_doc/Enhancement-699.md).* `lower_zi` now splits the roots at the origin off before the
product is built (a root is at the origin when both its parts fold to zero at
compile time: a literal, an expression of literals, a `localparam`) and applies
them as `z^(a−b)` with `a` origin zeros and `b` origin poles — a surplus of
origin poles shifts the numerator by `w^(b−a)`, a surplus of origin zeros the
denominator by `w^(a−b)` — so every degree stays exact and the bilinear
realization is untouched. The seven probes above read their expected phases to
the printed digits, and the zp pole at the origin traces the `zi_nd` delay's step
response point for point. A root the deck can set (an overridable `parameter`)
is never an origin root: Table 4-20 fixes the root vectors, and with them the
filter's order, when the model is compiled.

## F2 — `E` extrapolation aborts on the first Newton iterate

**Observed.** A one-dimensional table over `x ∈ [1, 4]` under `"1E"`, evaluated at
`V(in) = 2.5` from a voltage source (`hunt3/pJ.py`):

```
OSDI(fatal) n1: $table_model: the evaluation point is below the table and the control
string requests an error there ('E', LRM 9.21.2); it is 0 (at the operating point)
Error: a Verilog-A device raised $fatal during the operating point; aborting.
```

The same deck with `.nodeset v(in)=2.5` or `.ic v(in)=2.5` runs and prints 2.5; `tran …
uic` aborts the same way. The LRM's own `sample.dat` (x from 1 to 6) under `"1L,1E"`
aborts at (3.5, 0.25) — the Figure 9-2 point, inside every isoline — and at every other
point tried, always naming 0. The first Newton iteration of an operating point starts
with every node at zero, so the device is evaluated at `x = 0` once before the source's
equation has been solved; the `E` check fires on that iterate and raises the abort flag.
A table whose domain excludes zero — a temperature table over 250–400 K, an I-V table
over 1–6 V, a normalised bias from 0.5 up — can never start under `E`, whatever the
solution is.

**Expected.** LRM 9.21.2: "an extrapolation error is reported if the $table_model
function is requested to evaluate a point beyond the interpolation region" — the point
the simulator asks the model about is the solution, not the iterates on the way to it.
Every other run-time check of this family compares a converged quantity: `$error` and
`$warning` defer to the accepted iteration (E-541), E-651's deck-domain warnings are
"deferred to the accepted iteration like `$warning`", and the abort-at-once
`runtime_fatal` was reserved (E-504/E-506) for constants — a sampling period, a leading
coefficient — that no iteration can change. The extrapolation check is the one
solution-dependent user of it.

**Where.** `hir_lower/src/expr.rs`, `apply_end_extrap` (1614): the below/above selects
call `ctx.runtime_fatal(…, Some(x))` (`ctx.rs` 258), whose `CallBackKind::Print` is
`immediate: true` followed by `SetRetFlag(Abort)`, so the first iterate that lands
outside the table ends the run. The regular-grid path (`interp_nd`) and the 1-D path
share it. The fix is the deferral `runtime_warn` already has — evaluate on the accepted
iteration, or at least not before the first solve — with the fatal kept for a converged
point outside the table.

**Kind.** Abort where the answer exists; every `E` table whose domain excludes the
initial guess. Not platform-specific.

## F3 — a cubic spline under `C` keeps the natural end condition

**Observed.** LRM 9.21.4: "When formulating the cubic spline equations the desired
derivative of the interpolation function at both end points must be specified … If the
user selects linear extrapolation this leads to a natural spline. If constant
extrapolation is specified the end point derivative is set to zero thus avoiding a
discontinuity in the first order derivative at that end point." On `x²` sampled at
0…4 (`hunt3/pE.py`, `pG.py`), the natural and the zero-slope (clamped) splines computed
beside the run:

| control | point | got | natural | clamped ends (LRM for `C`) |
|---|---|---|---|---|
| `"3CC"` on `x²` | 1.5 | 2.23214 | 2.23214 | 2.33929 |
| `"3CC"` on `f = x` | 3.5 | 3.5 | 3.5 | 3.66071 |
| `"3CC"` on `f = x` | 3.9 | 3.9 | 3.9 | 3.98357 |
| `ddx` of `"3C"` on `x²` | 3.99 / 4.01 | **7.428 / 0.000** | 7.43 / 0 | 0 / 0 |

Under `C` the spline is the natural one and the constant extrapolation is bolted on
outside the last knot, so the derivative — the quantity that feeds the Jacobian — drops
from 7.43 to 0 across the table edge. That is the discontinuity the clause's
construction removes; the linear interpolation (`"1C"`: 7 then 0) is allowed to have
it, the cubic is not. `"3L"` is right: its extrapolation continues the spline's own end
slope (23.43 at 5, the chord would give 23).

**Expected.** With `C` on an end, the spline's end condition is `S'(x_end) = 0` (a
clamped condition at that end, natural at the other if it is `L`), so the value is
`C¹` across the edge into the constant extension. `"3CC"` on `f = x` at 3.9 is 3.98357,
not 3.9.

**Where.** `hir_lower/src/expr.rs`, `natural_cubic_spline_moment_matrix` (196) builds
only the natural system ("M[0] = M[n−1] = 0 for a natural spline", `interp_1d_spline`
at 2380); `interp_1d_spline_runtime` (1966) is the same for the run-time array form;
`apply_end_extrap` then clamps the finished spline. The moment matrix needs the two
end rows of the clamped system (`2h₀M₀ + h₀M₁ = 6(s₀ − 0)`, and its mirror) selected
per end by `ctrl.lo`/`ctrl.hi`.

**Kind.** Deviation, silent; every `3C`/`3CC`/`3LC`/`3CL` table, in value near the
edge and in derivative across it. Not platform-specific.

## F4 — a trailing comment on a data line makes the file unusable

**Observed.** LRM 9.21.1: "Comments begin with '#' and continue to the end of that
line. They may appear anywhere in the file." LRM 4.6.4.3: "comments may be inserted
before or after any frequency / power pair." A nine-way bisection of one file
(`hunt3/pD.py`), `x` and `x²` on 0…4, evaluated at 2.5 (expected 6.5):

| file variant | `$table_model` | `noise_table` (same rows as `f`, `p`) |
|---|---|---|
| `0 0 # zero` on the first line | **refused** | **refused** |
| `4 16 # last` on the last line | **refused** | — |
| `0 0   #zero` | **refused** | **refused** |
| tabs between the columns | 6.5 | right |
| leading spaces and tabs | 6.5 | — |
| blank lines | 6.5 | — |
| whole-line `#` comments before, between, after | 6.5 | right |
| integers only, no trailing newline | 6.5 | right |
| CR LF line ends | 6.5 | — |

The refusal is the generic one: "cannot use 'fb_inl.dat' as $table_model data —
missing, unreadable, or contains no usable table data", with notes about non-finite
values and the path; nothing names the `#`. `noise_table_log` shares the reader.

**Expected.** `#` to end of line is a comment wherever it stands; `1.0e0 1.657580e-23
# thermal floor` is a legal row in both clauses.

**Where.** `hir_ty/src/validation.rs`, `table_file_is_usable` (2480): "Whole-line
comments only, exactly as all three readers in `hir_lower` do it. Inline comments are
deliberately NOT stripped here: no reader strips them either" — the validator and the
readers were kept in agreement (E-396) on a rule that is half the LRM's. The readers
are `read_table_lines` (`hir_lower/src/expr.rs` 1405, "a line with any unusable token
is skipped whole"), `read_table_tokens` (1364) and `read_noise_table_file` (1308); each
tests `line.starts_with('#')` and never truncates a line at a `#`. Cutting the line at
its first `#` before tokenising, in the validator and the three readers alike, keeps
the invariant E-396 relied on.

**Kind.** Refusal of legal input, at compile time, with a message that does not name
the cause; every data file with a trailing comment — the natural way to annotate a
measured row. Not platform-specific.

## F5 — the data errors of 9.21 are not raised

**Observed.** LRM 9.21: "The minimum data requirement is to have the product of at
least two points per dimension (2^N for N dimensions). In addition, the result of the
bracketing to produce intermediate points … must also produce at least two points per
subsequent lower dimension. … If there are two or more data points with the same
independent values but different dependent values then an error is generated."
(`hunt3/pC.py`, `pE.py`)

- A two-dimensional file holding **one isoline** (`0 1 1 / 0 2 2 / 0 3 3`) compiles
  and evaluates: `f(2.5, 0.5) = 2.5`, constant in `y`.
- A file whose `y = 1` **isoline has one point** (`1 2 5`) between full isolines at
  `y = 0` and `y = 2` compiles and evaluates: `f(2.5, 1.0) = 5.0`, constant in `x` on
  that isoline, and `f(2.5, 0.5) = 3.75` blended from it.
- Rows `(1, 1)` and `(1, 5)` in one file draw a **warning** — "table file 'dup2.dat'
  repeats the abscissa 1; the duplicated knot makes a zero-width segment … interpolation
  anchors on the LAST value at the repeated knot" — and then `f(1.5) = 1.5`, `f(1.0) =
  1.0`, `f(0.5) = 0.5`: the **first** row is what the table keeps (with the last, 3.5,
  5 and 2.5). `build_tbl_tree` (80) says so in its own comment: "a repeated full
  coordinate keeps its FIRST row". The exact duplicate `(1, 1)` twice draws the same
  warning, which 9.21.1 permits ("the duplicates shall be ignored and the tool may
  generate a warning").
- The dependent selector `";5"` on a file with two dependent columns selects column 2
  and `";0"` selects column 1, in silence; 9.21.2: "This number runs 1 through M".
  `split_table_dep` (103) does `parse().unwrap_or(1).max(1)` and the callers
  `(dep − 1).min(width − ndim − 1)` (1456, 2719).

**Expected.** The first three are errors by the clause's wording ("an error is
generated"; the two-points-per-dimension minimum), the conflicting-value case with the
values named; the selector outside 1..M is at least a warning naming M. Where the
warning stays, its label must describe what the table does.

**Where.** `hir_ty/src/validation.rs` 415–435 (`TableFileDupKnot`, the "LAST value"
label — the 1-D inline path's `dedup_by` at `expr.rs` 2664 keeps the first too); the
isoline tree builder `build_tbl_tree` (80) groups without counting; `read_table_isoline_tree`
(1443) returns a tree for any width above `ndim`.

**Kind.** Silence where the LRM mandates an error, and one label that says the opposite
of the code. Not platform-specific.

## F6 — a run-time array table follows the solution

**Observed.** LRM 9.21.1: "The state of the data source is captured on the first call
to the table model function. Any change after this point is ignored." A 1-D table whose
value array the body computes from the solution (`hunt3/pF.py`, `pG.py`):

```verilog
xs[0] = 0.0; xs[1] = 1.0; xs[2] = 2.0;
ys[0] = 0.0; ys[1] = 1.0 + V(a,b); ys[2] = 4.0;
I(a, b) <+ $table_model(V(a,b), xs, ys);
```

compiles without a word and, over `dc vb 0.5 1.5 0.5`, gives 0.75, 2.0 and 3.25 — the
knot `ys[1]` re-read at every evaluation (`1 + V`), so the table is a different table
at each sweep point. Captured on the first call it would be one table for the whole
sweep. The 2-D array form (the LRM's 9.21.5 module, its arrays filled in
`@(initial_step)`) is compile-time constant (`const_array_values`, 2735) and gives the
clause's 1.75 — the run-time behaviour is the 1-D two-array form only.

**Expected.** Either the clause's freeze at the first call (the analog of 4.5.14's
"the value of the dynamic expression at the start of the analysis defaults to the
constant value"), or — if tracking is the intended extension, as the compliance
document records for a solution-dependent `laplace_*` coefficient — a compile-time
warning saying so, which that case draws and this one does not.

**Where.** `hir_lower/src/expr.rs`, `lower_table_model` (2526), the `runtime_1d` branch
(Enhancement-389: "the data arrives as two array variables filled in by the body")
lowers `lower_array_elems_impl` values straight into `interp_1d_runtime` /
`interp_1d_spline_runtime` / `interp_1d_quad_runtime`, so the knots are ordinary
solution-dependent MIR values. A freeze would store them as instance state on the first
evaluation, as the delay operators store their arguments; a warning would sit where
the Laplace one does.

**Kind.** Deviation, silent; only tables whose array data depends on a circuit quantity
(the parameter- and `initial_step`-filled idioms are unaffected). Not
platform-specific.

## F7 — diagnostic slips

- `$table_model(0.5, V(in), "two_col.dat")` — two inputs on a two-column file — is
  refused as "cannot use 'two_col.dat' as $table_model data: missing, unreadable, or
  contains no usable table data", with the non-finite-value and path notes. The file
  is readable and its numbers are fine; what is missing is a column (N inputs need
  N + 1 columns, 9.21.1). `read_table_isoline_tree` (1443) returns `None` when
  `width <= ndim`, and the validator's `TableFileUnusable` report (validation.rs 437)
  is the only message for `None`.
- `laplace_nd(V(in), '{1}, )` — a null argument where only zeros may be null — draws
  two errors: "type mismatch: expected real value but found _[0:0] value" (an internal
  spelling of the empty array type) and then the one that matters, "the denominator is
  an empty coefficient list; it needs at least a constant term". One message, saying
  that the null argument is allowed for zeros only (4.5.11: "The zeros argument may be
  represented as a null argument"), would do.
- The `abstol` argument of the Laplace filters is not checked: `laplace_nd(V(in),
  '{1}, '{1, 1e-3}, -1e-9)` and `laplace_zp(V(in), , '{-1e3, 0}, 0.0)` compile in
  silence, where `ddt(V(in), -1e-9)` and `idt(V(in), 0, 0, -1e-9)` are refused with
  "the absolute tolerance must be greater than zero" (the tolerance is unused by the
  OSDI route either way, which is documented; the inconsistency is the slip).
- `$table_model(V(b), xs, ys, "1E")` on the run-time array form is refused as
  "unsupported $table_model control string "1E"", and its own note lists "'E' (error)"
  among the supported codes. The restriction is the form's ("validation restricts
  runtime-array controls to the shapes they can express", `lower_table_model` 2555), not
  the string's; the message should say the form does not support `E` (or `E` should be
  implemented there, which F2's deferral would make straightforward).
