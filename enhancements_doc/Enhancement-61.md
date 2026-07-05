# Enhancement-61 — operator-argument audit: `slew` sign-convention fix (version11)

This document describes the changes made to **OpenVAF-r** in the `version11/`
directory following a full-argument-form audit of the analog operators
(LRM 4.5) and events (LRM 5.10). Front-end only — no OSDI/ngspice change.

## The audit

22 probe forms covering every optional-argument spelling: `cross` 3/4-arg
(`time_tol`, `expr_tol`), `above` 2/3-arg, `timer` 2/3-arg (period +
tolerance), `absdelay` 3-arg (`maxdelay`), `transition` 5-arg (trailing
tolerance), `slew` 2/3-arg, `ddt` 2-arg (abstol), `idt` 4-arg, `idtmod`
5-arg, `last_crossing` 1/2-arg, `laplace_*`/`zi_*` trailing
tolerance + full `zi` arg lists (T, τ, t0), `$bound_step`, `$limit`
(built-in `"pnjlim"` string, user functions, user functions with extra
arguments), and `ac_stim` with magnitude and phase.

**One real defect found (and fixed); everything else verified working at
runtime**, not just parsing:

| verified working | evidence |
|---|---|
| `timer(start, period[, tol])` | fires exactly 5× at 0.1/0.3/0.5/0.7/0.9 µs |
| `$bound_step(5n)` | eval count 120 → 416 over a 1 µs transient |
| `$limit` `"pnjlim"` + user fn (+ extra args) | stiff 5 V/1 Ω diode converges **directly** (raw diode needs gmin stepping); exact op 0.9345 V |
| `ac_stim("ac", 2.0, π/2)` | V = j1000 exactly (magnitude AND phase honored) |
| `ddt(x, abstol)` | −j2πfC to 10 digits at AC |
| `idt(x, ic, assert, abstol)`, `idtmod(x, ic, mod, off, abstol)` | +j1e-6 exactly at ω = 1000 |
| toleranced `cross`/`above` | fire correctly (tolerances are step-control hints) |
| `transition` 4/5-arg | linear ramp, exact midpoint (first runtime pin ever) |
| `absdelay(x, td, maxdelay)` | 1.5e-5 max error vs the analytic delayed sine |
| `laplace_*`/`zi_*` trailing ε | accepted; realization exact (documented no-op) |

(Also confirmed: an empty `{}` vector for "no zeros" is rejected — correct,
Verilog-A has no empty array-literal syntax; E-34's `EmptyConcat` diagnostic
stands.)

## The defect: `slew` ignored its input

**Before:** `slew(V(in), 1e6, -1e6)` — the LRM-conformant spelling
(4.5.15: *max_pos_slew_rate shall be greater than zero,
max_neg_slew_rate shall be less than zero*) — produced an output that
**ignored the input entirely**: it ramped at +1e6 V/s from t = 0 (while the
input was still 0) and sailed unboundedly past the target (2.0 V at 2 µs
for a 1.0 V input).

**Root cause:** `lower_slew` fed the bounds to the shared
`lower_rate_limited_track` loop (`dy/dt = clamp(K·(x−y), lo, hi)`) after
`fneg(neg_max)` — assuming a *positive magnitude* third argument. An
LRM-conformant negative value was double-negated into a **positive lower
clamp bound** (+1e6), so the clamp forced `dy/dt = +1e6` regardless of the
input: a positive-feedback runaway disguised as a ramp. (`transition`,
which converts rise/fall *times* to always-positive rates before calling
the same helper, was unaffected — which is why it worked while `slew`
didn't.)

**Fix** (`hir_lower/src/expr.rs`): bound with `|max_pos|` / `−|max_neg|`
via a new `lower_fabs` helper (neg/lt/select — MIR has no fabs
instruction). Exact for LRM-conformant inputs and tolerant of the legacy
positive-magnitude spelling; the single-rate form keeps its LRM "absolute
value bounds both directions" behavior.

**After:** the output holds at the input, ramps at exactly the bound when
the input outruns it (asymmetric rates verified: rise 1e6, fall 0.25e6 —
both edges exact), and stops at the target.

## Examples (`opargs_examples/`, 16 checks, ALL PASS)

`verify_opargs.py`: [1] the fixed `slew` defect (holds before the step,
rate-limited rise, **stops at the target**, asymmetric fall); [2]
toleranced events + `timer` period (5 fires exact); [3] `$limit` pnjlim +
user fn converge directly to the exact op with no gmin fallback; [4]
`$bound_step` honored; [5] `ac_stim` magnitude and phase exact; [6]
`ddt`/`idt`/`idtmod` trailing tolerances numerically exact at AC; [7]
`transition` ramp semantics. Items [1] and [7] are the first runtime
verification the `slew`/`transition`/`absdelay` operator family has had
(the old `slew_examples`/`transition_examples`/`absdelay_examples` folders
have no verify scripts).

## Regression

All version11 example verify suites pass; crate tests (hir_lower,
sim_back, osdi, mir_autodiff) pass; VA_TEST corpus compiles 92/92.
