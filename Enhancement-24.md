# Enhancement-24 — `$discontinuity(n)` simulator support (version11)

This document describes the changes made to **OpenVAF-r** *and* **ngspice-46** in
the `version11/` directory to give real effect to **`$discontinuity(n)`** (for
n ≥ 0). Previously `$discontinuity` compiled but was a no-op except for the
internal `$discontinuity(-1)` used by device limiting (which sets the OSDI `LIM`
eval flag); every other form hit a `// TODO implement support for discontinuity?`
branch and generated nothing.

## Semantics

`$discontinuity(n)` (n ≥ 0) announces a discontinuity of degree *n* in the branch
constitutive relations at the current point. A transient simulator should limit
the timestep there — placing a fine timepoint and not extrapolating a large step
across the event — rather than trusting its truncation-error estimate through the
discontinuity. It affects **only timestep control**, never the computed solution.

## Implementation: via the `bound_step` output

The natural vehicle would be an OSDI eval **return flag** (like `$finish`/`$stop`),
but that path is **not honoured by ngspice's timestep control** (ngspice acts on
`FATAL`/`LIM`/`STOP` during load, but nothing routes a flag into `OSDItrunc`).
The **`bound_step` eval output**, on the other hand, *is* honoured: `OSDItrunc`
already clamps the next timestep to it (it defaults to `+INFINITY`).

So `$discontinuity(n)` is lowered exactly like `$bound_step`, but writing a
**negative sentinel** (`-1.0`) to `PlaceKind::BoundStep` instead of a real bound.
`OSDItrunc` interprets a negative `bound_step` not as a literal step limit but as
"a discontinuity occurred here": it clamps the next timestep to the last accepted
step (`CKTdeltaOld[0]`), so the step cannot grow across the event. A positive
`bound_step` keeps its original meaning (an explicit `$bound_step` bound). Because
`bound_step` defaults to `+INFINITY` and real bounds are positive times, a
negative value is an unambiguous sentinel.

This required no OSDI ABI change (the `bound_step` slot already exists) and only a
few lines in each of OpenVAF and ngspice.

### Files changed

- **OpenVAF** `hir_lower/src/expr.rs` — `$discontinuity(n)` for n ≥ 0 now
  `def_place(PlaceKind::BoundStep, -1.0)` (the `$discontinuity(-1)`-inside-`limit`
  case is unchanged).
- **ngspice** `src/osdi/osditrunc.c` — a negative `bound_step` clamps the next
  timestep to `CKTdeltaOld[0]` (the last accepted step) rather than being used as a
  literal bound.

## Verification

`discontinuity_examples/verify_discontinuity.py` (`ALL PASS`) — a conductance
switch (`I = g·V(a,b)`, `g` jumps at `V(a,b)=vth`) that announces
`$discontinuity(0)` while in the switched region:

- **timestep limiting** — the same transient produces ~590× more (finer)
  timepoints with the announcement on than off, i.e. the discontinuity actually
  limits the timestep;
- **solution unchanged** — the DC operating point is identical either way (the
  announcement changes timestep control, never the computed result).

`$bound_step` (positive values) is unaffected by the sentinel change, and every
prior example folder still passes.

## Known limitations

- The degree `n` is treated uniformly (any n ≥ 0 ⇒ "limit the step here"); ngspice's
  OSDI timestep control has no finer degree-specific hook.
- `$discontinuity` and `$bound_step` share the `bound_step` output slot within one
  evaluation (last-writer-wins); a negative value is the discontinuity sentinel, a
  positive value an explicit bound.
- Requires the accompanying ngspice rebuild; a stock ngspice ignores the sentinel
  (a negative `bound_step` there would be a no-op or, in an unpatched `OSDItrunc`,
  wrongly clamp to a negative step — so the two must be built together).
