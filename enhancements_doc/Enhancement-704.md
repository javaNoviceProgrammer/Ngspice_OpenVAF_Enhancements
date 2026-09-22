# Enhancement-704: the cubic spline of `$table_model` takes LRM 9.21.4's end conditions — a `C` end pins the end derivative to zero, so the spline meets its constant extension with a continuous derivative; every spline was the natural one with the clamp bolted on outside the last knot, and the derivative that feeds the Jacobian jumped at the table edge

**Scope:** F3 of the
[bug hunt of 2026-09-21 on the filters, tables and noise sources](../docs/bug_hunts/2026-09-21_openvaf-r-filters-tables-and-noise.md).
**Compiler only.** `hir_lower/src/expr.rs`: `cubic_spline_moment_matrix` (was
`natural_cubic_spline_moment_matrix`; the two clamped-end rows), `interp_1d_spline`
(passes its ends), `interp_1d_spline_runtime` (the unknown range and the dead-row
rule of the unrolled Thomas solve), the run-time branch of `lower_table_model`.
`examples/cubic_table_examples/` (five modules in `cubic_demo.va`, section [5],
eleven checks), `examples/langguard_examples/` (section [4]: seven checks and one
expectation, 132 per solver). The handbook row, the compliance document, the hunt
page.

**Suites:** [`cubic_table_examples`](../examples/cubic_table_examples/) both
solvers (eight of the eleven new checks fail on the E-703 binaries: every value
whose spline has a clamped end, and the derivative at both edges);
[`langguard_examples`](../examples/langguard_examples/) 132 of 132 per solver, both
solvers (126 of 132 on the E-703 binaries); `tablearray`, `tablesrc` 57 of 57,
`vaftabledup` 20 of 20, `hunt3diag` 54 of 54, `lrmkernel` 44 of 44, `vafinstcheck`
41 of 41 and `tabledata` 60 of 60 unchanged; the compiler workspace tests green
apart from the three pre-existing sourcegen drift failures (219 passed), no new
build warnings; full sweep 532 of 532, run alone.

## What was wrong

LRM 9.21.4: "When formulating the cubic spline equations the desired derivative
of the interpolation function at both end points must be specified in order to
provide the complete set of constraints for the cubic spline equations. It is
convenient then that the table model function specifies end point extrapolation
behavior. If the user selects linear extrapolation this leads to a natural
spline. If constant extrapolation is specified the end point derivative is set
to zero thus avoiding a discontinuity in the first order derivative at that end
point." The clause before it says why: "the extrapolation option specified is
taken into account when generating the spline coefficients so as to avoid end
point discontinuities in the first order derivative of the interpolated
function."

The compiler built one spline whatever the ends asked for. `x²` sampled at
0…4, the natural and the zero-end-slope splines computed beside the run:

| control | point | got | natural | zero end derivative (9.21.4 for `C`) |
|---|---|---|---|---|
| `"3CC"` on `x²` | 1.5 | 2.23214 | 2.23214 | 2.33929 |
| `"3CC"` on `y = x` | 3.5 | 3.5 | 3.5 | 3.66071 |
| `"3CC"` on `y = x` | 3.9 | 3.9 | 3.9 | 3.98357 |
| `ddx` of `"3C"` on `x²` | 3.99 / 4.01 | **7.428 / 0** | 7.43 / 0 | 0.255 / 0 |

Under `C` the spline was the natural one — `M₀ = Mₙ₋₁ = 0`, the second
derivative zero at the ends — and the constant extension was selected outside
the last knot, so the derivative, the quantity that feeds the Jacobian, dropped
from 7.43 to 0 across the table edge. That is exactly the discontinuity the
clause's construction removes: the linear interpolation (`"1C"`: 7 then 0) is
allowed to have it, the cubic is not. `"3L"` was right — the natural spline,
its end tangent continued outside.

[E-22](Enhancement-22.md) built the natural spline when the only extrapolation
was "`L` or clamp"; the kernel audit ([E-562](Enhancement-562.md)) gave every
axis its per-end `C`/`L`/`E` and [E-390](Enhancement-390.md) solved the same
natural system at run time for the array form, but the spline's end conditions
never followed the control string. The defect was silent and reached every
`3C`, `3CC`, `3LC` and `3CL` table, in value near the edge and in derivative
across it, on the file, inline-array and run-time array forms alike, in every
dimension.

## What changed

**The moment system takes the end conditions from the control string.** A cubic
spline through `n` knots is determined by its moments `M` (the second
derivatives at the knots), which solve a tridiagonal system whose interior rows
are `hᵢ₋₁Mᵢ₋₁ + 2(hᵢ₋₁ + hᵢ)Mᵢ + hᵢMᵢ₊₁ = 6(sᵢ − sᵢ₋₁)` with `sᵢ` the chord
slopes. The two end rows are the end conditions. A natural end pins `M = 0`
there. An end whose method is `C` now adds its moment to the unknowns with the
clamped row instead — `2h₀M₀ + h₀M₁ = 6s₀` at the bottom and
`hₗMₙ₋₂ + 2hₗMₙ₋₁ = −6sₗ` at the top — which is `S′ = 0` at that knot. An `L`
end keeps the natural condition, as the clause says; so does `E`, which has no
extension to meet. The extrapolation outside the table is unchanged: `C` holds
the endpoint value, which the spline now reaches with a zero derivative, and
`L` continues the end tangent of the spline the other end shaped (`"3CL"` above
the table follows the bottom-clamped spline's tangent, 720/97 on the `x²`
samples where the natural one's is 52/7).

**Both solves.** The compile-time matrix (`cubic_spline_moment_matrix`) builds
the system over the unknown moments — the interior ones plus each clamped end's
— inverts it once at compile time and lowers each moment as a constant-weighted
sum of the values, as before; a natural end's row of the operator stays zero.
The run-time array form solves the same system in MIR by the unrolled Thomas
algorithm ([E-390](Enhancement-390.md)); its unknown range now runs from the
bottom knot when that end is clamped to the top knot when that end is, and the
rows are written with a zero interval width and a zero chord slope past the
ends, so the clamped-end rows are the interior formula with one dead interval.
That is also what makes the [E-391](Enhancement-391.md) compaction come out
right: after the repeated abscissae are moved to the end and replicate the last
distinct knot, the last live knot's row has a zero-width interval after it — a
guarded zero slope — and is therefore the clamped row by construction, while
the replicated slots keep the identity row `M = 0`; with a natural top end the
last live knot keeps the identity row too, as it did. The `L` tangent formulas
are unchanged, since a linear end is a natural one and a clamped end's tangent
extension is overridden with the endpoint value.

**Where it applies.** Every 1-D spline step: the inline and file forms, the
column-array form, the run-time array form, each axis of an N-dimensional
table (the recursive 1-D scheme gives each axis its own ends) and each isoline
of a ragged data file.

## Verification

`cubic_table_examples` section [5], `x²` sampled at 0…4 as inline arrays:
`"3L"` still gives the natural spline's 125/56 at 1.5, `"3C"` 131/56, `"3LC"`
1799/776 and `"3CL"` 1751/776 (the exact fractions of the four moment systems);
`"3CL"` above the table continues the bottom-clamped spline's tangent
(16 + 720/97 at 5, the natural 16 + 52/7 before) and `"3LC"` below it the
top-clamped spline's (−48/97 at −1, −4/7 before); `"3C"` holds 16 above the
table; `y = x` under `"3C"` reads 5577/1400 = 3.98357 at 3.9, the spline bending
to meet the flat extension; the AC `gm` of the `"3C"` table is 0.2554 at 3.99
and 0 at 4.01 (it was 7.4284 and 0), 0.0172 at 0.01 and 0 at −0.01, while the
`"3L"` table's is 7.4284 and 7.4286 across the same edge. `langguard` section
[4], the run-time array form on (0,0), (1,1), (2,4): `"3CC"` and `"3C"` give
23/8 at 1.5 (the natural 37/16), `"3CL"` 131/56, `"3LC"` at −1 gives 0 (the
top-clamped spline's tangent at 0 is 0, the natural one's 1/2), `"3L"` 37/16
unchanged; `ddx` of the `"3C"` table is 0.1191 at 1.99, 0 at 2.01, 0.0003 at
0.01 and 0 at −0.01, and of the `"3L"` table 3.49985 then 3.5; the E-700 row
`"3CL"` at 3 moves from 7.5 to 4 + 24/7 = 7.4286, the tangent of the
bottom-clamped spline. By hand, the hunt's own probes: the four rows of the
table above now read 2.33929, 3.66071, 3.98357 and 0.255 / 0, on the file form
and on the run-time array form alike; `"3L"` and `"3"` are unchanged to the
last digit; a run-time table with repeated top knots under `"3C"` gives the
same value as the de-duplicated file. Seven table suites that never ask for a
clamped cubic pass unchanged.

## What this does not do

- The quadratic spline (`2`) is untouched: it chains from the first chord, and
  the LRM only says one "should attempt to avoid end point discontinuities,
  though it is not always possible in this case" — with one free parameter, a
  `C` at both ends cannot be met, and the clause names no rule for which end.
- Fewer than three knots is still a line, as documented since E-22; a two-knot
  `3C` table keeps the chord and the derivative jump at its ends.
- An `E` end is natural: the evaluation aborts outside the table, so there is
  no extension to meet.
- A clamped end's derivative is zero by construction. Data that really has a
  slope at the table edge — a line — is bent to meet the flat extension
  (`y = x` under `3C` reads 3.98357 at 3.9). That is the clause's own trade;
  `L` keeps the natural spline for such data.
