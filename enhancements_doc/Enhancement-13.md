# Enhancement-13 — `limexp()`: investigation, kept stateless

This document records an investigation into the Verilog-AMS `limexp()` limited
exponential in **OpenVAF-r** (`version11/`), and the deliberate decision to
**keep its existing stateless implementation** rather than adopt a stateful
prev-iteration step-limiting one. **No functional change was made** (only an
explanatory code comment was added at the `limexp` lowering site); this doc
exists so the decision and its rationale are not lost.

## 1. Current (kept) implementation — stateless cutoff linearisation

`limexp(x)` is lowered in `hir_lower/src/expr.rs` to:

- `exp(x)` for `x <= ln(1e30)`;
- above that, the exponential is continued along its **tangent line**
  (`1e30 * (1 + (x - ln(1e30)))`), so the value and derivative stay finite.

This is a pure function of the current argument, so it is **exact and correct in
every context** (DC sweep, operating point, AC/noise, transient). It provides the
practical benefit of `limexp` -- bounding the derivative and preventing overflow
of the exponential nonlinearity -- and matches what a number of simulators ship.
A diode `I(a,c) <+ Is*(limexp(V(a,c)/Vt) - 1)` reproduces the analytic
`Is*(exp(V/Vt)-1)` curve across the operating range.

## 2. Why the stateful step-limiting version was NOT adopted

The LRM describes `limexp` as keeping the argument's previous value and limiting
its change between iterations (pnjlim-style). That version was implemented and
tested, and then **reverted because it produces incorrect DC values**:

- The step-limited value is `exp(x_lim)`, where `x_lim` is derived from the
  *previous evaluation's* argument (held in a per-`eval()` `EventState` slot,
  gated by `EnableLim`).
- But the simulator judges convergence from the **node voltages**, not from
  `limexp`'s internal `x_lim`. When the circuit converges while `x_lim` still
  lags `x` -- e.g. an ideal voltage source fixes the argument, so there is no
  Newton loop to unwind the limiting -- the returned current is
  `exp(x_lim) != exp(x)`. A diode I-V sweep came out wrong at roughly half the
  bias points, including high-current ones. A DC characterisation sweep is a
  first-class use case, so this is disqualifying.

The **only** way to step-limit while keeping the converged value exact is SPICE's
limiting-RHS correction, `lim_rhs = J(x_lim)·(x_lim - x)` (it cancels at
convergence). OpenVAF *has* this machinery (`sim_back/src/dae/builder.rs`,
`build_lim_rhs`), but it only applies the correction to values registered as
circuit **unknowns** (node voltages / branch currents) -- the same reason
`$limit`/`start_limit` require their probe to be a bare voltage/current.
`limexp`'s argument is a **derived** quantity (e.g. `V/Vt`), which is not an
unknown, so the correction is silently skipped and the DC value is wrong.

## 3. What a correct version would require (not done)

Extending `build_lim_rhs` (and the derivative tracking) to limit **derived**
arguments -- applying the chain rule from the limited quantity back to the
underlying node/branch unknowns so the RHS correction is emitted. That is real,
higher-risk surgery in `sim_back`'s DAE builder + autodiff, and was judged out of
scope; the stateless version is correct in the meantime. Reusable primitives
identified if it is ever pursued: `new_event_state()` (a per-`eval()`-persisted,
zero-derivative scalar) and `ParamKind::EnableLim` (set by ngspice for DC/tran
loads but not for small-signal AC/noise).

## 4. Diff summary

| File | Kind of change |
|---|---|
| `openvaf/hir_lower/src/expr.rs` | Added an explanatory comment at the `limexp` arm documenting that it is intentionally stateless and why the stateful version is not correct here (§2). No behavioral change. |
