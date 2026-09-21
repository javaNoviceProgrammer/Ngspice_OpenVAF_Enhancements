# Enhancement-699: a z-filter root at the origin is the factor `z` of LRM 4.5.12 — the root expansion built the term 1, so a `zi_zp` pole at zero was a wire where the same delay as `zi_nd` coefficients was right

**Scope:** F1 of the
[bug hunt of 2026-09-21 on the filters, tables and noise sources](../docs/bug_hunts/2026-09-21_openvaf-r-filters-tables-and-noise.md).
openvaf: `hir_lower/src/expr.rs` (`lower_zi`: the origin roots are split off
before the product and applied as a power of `z`; the new helpers
`const_array_elems`, `zi_split_origin_roots` and `zi_apply_origin_roots`; the
`zi_roots_to_poly` doc comment that stated the opposite reading).
`examples/lrmfilters_examples/` (a fifth section, eight checks, 22 per
solver). Handbook [§2.4](../docs/handbook/02-verilog-a-language.md) row, the
compliance document, the suite README, the hunt page.

**Suites:** [`lrmfilters_examples`](../examples/lrmfilters_examples/) 22 of 22
per solver, both solvers (16 of 22 on the E-698 binaries: the five phase
checks and the transient one); `filterforms` 85 of 85, `filterslice`,
`lrmops`, `lrmfuncs`, `constguard`, `constfold`, `arraycast`, `deckdomain`,
`dropguard`, `nullarg`, `vaflaplace`, `complexpole`, `transedge`, `evtedge`
and `lrmnoise` both solvers, unchanged; the compiler workspace tests green
apart from the three pre-existing sourcegen drift failures; full sweep 531 of
531, run alone.

## What was wrong

LRM 4.5.12.1 defines the z-domain root forms as products of `(1 − z⁻¹ r)`
over the zeros and the poles and adds, for each of `zi_zp`, `zi_zd` and
`zi_np`: "If a root is zero, then the term associated with it is implemented
as z, rather than (1 − z⁻¹ r)". A pole at the origin is therefore `1/z`, a
delay of one sampling period, and a zero at the origin `z`, an advance —
the natural way to write a pure delay in root form, and a rule the clause
states although `1 − z⁻¹·0` divides by nothing.

The compiler's `zi_roots_to_poly` built exactly that `1`. Its doc comment
read the exception as a division guard: "The LRM's `(1 − s/r)` exception
exists because that form divides by the root; `(1 − rho·w)` does not, and at
`rho = 0` it is simply 1." So every root at the origin vanished from the
filter. On the unit circle `|z| = 1`, so the magnitude response of a filter
with a dropped origin root is the right one and only its phase — and its
transient — is wrong, which is why the magnitude checks of the E-514 audit
never saw it. At `ωT = 0.5` (phases in degrees, the bilinear image the
compiler documents for the z forms):

| call | `\|H\|` | phase got | phase LRM |
|---|---|---|---|
| `zi_zp(V(in), , '{0, 0}, 1u)` — a pole at the origin | 1.000 | **0.00** | −28.07 |
| `zi_np(V(in), '{1}, '{0, 0}, 1u)` | 1.000 | **0.00** | −28.07 |
| `zi_zd(V(in), '{0, 0}, '{1}, 1u)` — a zero at the origin | 1.000 | **0.00** | +28.07 |
| `zi_nd(V(in), '{0, 1}, '{1}, 1u)` — the same delay as coefficients | 1.000 | −28.07 | −28.07 |
| `zi_zp(V(in), '{0, 0}, '{0.5, 0}, 1u)` | 1.649 | **−22.83** | +5.24 |
| `zi_np(V(in), '{1, 1}, '{0, 0, 0, 0}, 1u)` | 1.940 | **−14.04** | −70.18 |

In a transient the zp pole at the origin was a wire (1.0 at every point of a
step) while the nd delay traced the bilinear all-pass (−0.81 at 1.05 µs,
0.90 at 2.5 µs). The Laplace forms were right throughout: E-405's
`laplace_roots_to_poly` selects the `s` term at run time for a root at
zero, and every origin-root case of 4.5.11 gives the closed form.

## What changed

`lower_zi` splits the origin roots off before the product is built and
applies them afterwards as the power of `z` they are. With `a` origin zeros
and `b` origin poles the filter is `z^(a−b) · N'(w)/D'(w)` with `w = z⁻¹`, so
a surplus of origin poles multiplies the numerator by `w^(b−a)` and a surplus
of origin zeros the denominator by `w^(a−b)` — a shift of the ascending
coefficient vector by that many leading zeros (`zi_apply_origin_roots`).
Equal counts cancel, as `z/z` does. Every degree stays exact — no padded
state for the common all-constant filter — and the bilinear realization is
untouched: its leading denominator coefficient is `D(w = −1)`, which a
leading zero in `w` does not change, and its constant term `D(1)`, so the DC
gain `N(1)/D(1)` is the one at `z = 1` as before.

A root is at the origin when both its parts are known zeros when the model
is compiled (`const_array_elems`, element-aligned with the coefficient
lowering): a literal, an expression of literals, a `localparam`, an array
variable assigned constants once. A root the deck can set — an overridable
`parameter` anywhere in the pair — is never an origin root and keeps the
term `1 − z⁻¹ r`, whatever value the card gives it. That is a deliberate
reading of Table 4-20: the root vectors are constant-class arguments, the
filter's *order* is fixed when the model is compiled, and a run-time test
would have to pad every root form to the sum of its root counts to hold
both readings at once. A model that wants a delay it can switch from the
deck writes it as `zi_nd` coefficients, where a zero coefficient is simply
a zero coefficient.

The `zi_roots_to_poly` comment now records the rule and where it is applied,
so the next reader does not take the product's totality for the clause's
meaning.

## Verification

| check | new | E-698 binaries |
|---|---|---|
| `zi_zp(V(i), , '{0, 0}, 1u)`: phase at `ωT = 0.5` (rad) | −0.489957 (the `zi_nd` delay's) | 0.0 |
| `zi_np(V(i), '{1}, '{zr, 0})` with `localparam real zr = 0` | −0.489957 | 0.0 |
| `zi_zd(V(i), '{0, 0}, '{1}, 1u)` | +0.489957 | 0.0 |
| `zi_zp(V(i), '{0, 0}, '{0.5, 0}, 1u)`: `z/(1 − 0.5 z⁻¹)` | +0.091435 | −0.398522 |
| `zi_zp(V(i), , '{0, 0, 0, 0, 0.5, 0}, 1u)`: `1/(z² (1 − 0.5 z⁻¹))` | −1.378437 | −0.398522 |
| DC gains of the last two (`z = 1`) | 2.0, 2.0 | 2.0, 2.0 |
| step through the zp delay against the nd delay, 1.05 µs / 2.5 µs | −0.811536 / 0.900333 both | 1.0 / 1.0 against −0.81 / 0.90 |
| `filterforms` (every zi form with roots off the origin, 85 checks) | 85 of 85 | 85 of 85 |

The phase expectations are the bilinear image `z = (1 + sT/2)/(1 − sT/2)`
evaluated in the suite beside the run; ngspice prints `ph()` in radians to
six significant digits, the tolerance is 1e-5.

## What this does not do

It does not change what a z filter is between samples: the transient is
still the continuous bilinear image of `H(z)` the compliance document
records, so the delay a pole at the origin now adds is the all-pass
`(1 − sT/2)/(1 + sT/2)` the `zi_nd` spelling always gave, not a
sample-and-hold. It does not treat a parameter-valued root as the origin
when the deck sets it to zero (see above), and it does not warn about one —
the compiler cannot know the card's value. The Laplace forms are untouched.
