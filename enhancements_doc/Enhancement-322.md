# Enhancement-322 — `.param` fast-sweep, optimizer tier

Enhancements 320/321 gave the `sweep` command a fast path that re-evaluates a
swept `.param`'s dependent device values and pushes them into the live circuit
in place, skipping the full per-point `reset`. The **optimizer** (`optimize`)
had the same cost: every objective evaluation of an `-dparam` (symbolic `.param`)
knob did `alterparam` + `reset`, re-parsing and rebuilding the whole circuit —
and an optimization runs tens to hundreds of evaluations.

E-322 shares the fast-path engine with the optimizer.

## Sharing the engine

`sw_fp_build` / `sw_fp_apply` / `sw_fp_free` (the capture-classify-selfcheck-push
machinery from E-320/321) are now exported via `com_sweep.h`. The optimizer:

- **arms once** before the search (`opt_fp_arm`): it collects the `OPT_DECKPARAM`
  knob names and calls `sw_fp_build`, which captures their dependent device/model
  values (top-level and subcircuit-internal) and self-checks them;
- in **every** evaluation (`opt_eval` for the scalar methods — Nelder-Mead,
  Levenberg-Marquardt, PSO, DE, SA — and `opt_eval_objs` for NSGA-II) it pushes
  the candidate's deck-param values in place with `sw_fp_apply` instead of
  `alterparam` + `reset`;
- **frees** the capture at the end.

The conservative classifier and arm-time self-check are unchanged, so the
optimizer inherits the same guarantee: if any deck-param feeds a subcircuit
shadow, a structural slot, or a derived param, the path disarms and the
optimizer runs exactly as before.

## Two opt-outs

- **`-center` (design centering, E-206)** keeps the reset path: its inner
  Monte-Carlo *re-samples* process variation on each `reset`, which is a
  re-draw, not a deterministic value push.
- **Small circuits** keep the reset path. The in-place apply has a fixed
  per-evaluation cost (numparam re-eval + dico ops) roughly independent of
  circuit size, while a reset's cost grows with the deck; they cross at about 80
  device instances. Below that a small deck re-parses faster than the fast
  path's overhead — and because the in-place values differ from the reset path
  in the last few digits (numparam's value-string formatting), an extremely
  tight `-tol` on a tiny circuit could otherwise send the two paths to different
  iteration counts. So `opt_fp_arm` counts the flattened device instances and
  only engages the fast path at `>= 80`.

## Correctness

Across Nelder-Mead, PSO, DE and NSGA-II, the fast-path optimum is **identical**
to the reset-path optimum on the same problem (e.g. a 122-device ladder fit:
`rtop = 361.914` under both NM and DE, `382.872` under both PSO; NSGA-II arms
and returns its Pareto front). Every existing `optimize` verify check (41 total)
still passes.

## Measured speedup

A 4000-device fixed ladder, single `-dparam` knob, Nelder-Mead to convergence:
**0.94 s → 0.17 s (5.6×)**. As with the sweep, the win grows with circuit size;
on tiny circuits the guard keeps the (already sub-30 ms) reset path.

## Scope

The `optimize` command's `-dparam` knobs, all methods except `-center`.
Instance-parameter (`-param`) and model-parameter (`-mparam`) knobs were already
in-place; `-dparam` now joins them on large circuits.

## Files

- `ngspice-46/src/frontend/com_sweep.{c,h}` — `sw_fp_build`/`sw_fp_apply`/
  `sw_fp_free` de-static'd and declared for sharing.
- `ngspice-46/src/frontend/com_optimize.c` — `opt_fp_arm` (with the device-count
  guard) and `opt_fp_apply`; the fast-path branch in `opt_eval` and
  `opt_eval_objs`; arm before dispatch, free at cleanup.
- `examples/optimize_examples/verify_optimize.py` — a large-circuit `-dparam`
  optimization that arms the fast path and still converges (2 new checks).
