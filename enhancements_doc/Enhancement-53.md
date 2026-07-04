# Enhancement-53 — `@(final_step)` + analysis-phase lists on step events (version11)

This document describes the changes made to **OpenVAF-r** and **ngspice-46**
in the `version11/` directory to implement the `@(final_step)` event and the
analysis-phase lists on both step events (`@(initial_step("tran","ac"))`,
LRM 5.10.2) — the last visibly missing Verilog-A (LRM Annex C) feature.

## What was broken

The probe (`@(initial_step)`, phase-qualified variants, `@(final_step)`
through tran and op) confirmed two documented gaps:

1. **`@(final_step)` never fired.** Enhancement-7 implemented
   `@(initial_step)` via a one-shot `EVAL_FLAG_IS_INITIAL_STEP` but left
   `final_step` as a documented fail-safe no-op — firing needs "the analysis
   is over" knowledge the per-iteration eval loop doesn't have (before E-7 it
   fired on *every* evaluation).
2. **Analysis-phase lists were silently dropped.** The AST/HIR always carried
   `Event::Global { phases: Vec<String> }`, but `lower_event_control` matched
   `{ kind, .. }` — `@(initial_step("ac"))` fired during a transient run and
   `@(initial_step("tran"))` fired during an op (the recurring
   "scaffolded-but-unwired at a boundary" pattern).

## The fix

### `@(final_step)` — one dedicated post-analysis evaluation

- **`hir_lower`**: new `ParamKind::IsFinalStep` (sibling of `IsInitialStep`,
  same `op_dependent` classification); `lower_event_control` gates the body
  on it.
- **`osdi/src/eval.rs`**: `EVAL_FLAG_IS_FINAL_STEP = 1 << 21` (next additive
  bit above E-7's `1 << 20`, still clear of the core ABI's flag space; not an
  ABI change — no descriptor/stride is touched).
- **ngspice**: new `OSDIfinalStep(CKTcircuit *)` in `osdi/osdiload.c`
  (declared in `ngspice/osdiitf.h`), called once at the **successful end** of
  each analysis — `dctran.c` (last accepted transient point), `dcop.c` (an op
  is both the first and last point of its analysis), `dctrcurv.c` (last DC
  sweep point), `acan.c` and `noisean.c` (end of the frequency sweep). It
  issues one dedicated `eval()` per OSDI instance with
  `EVAL_FLAG_IS_FINAL_STEP` set, computed at the converged final solution
  (`CKTrhsOld`); the results are deliberately **not loaded** into the
  matrix/RHS — the analysis is over, the call exists so `@(final_step)`
  bodies ($strobe/$fdisplay summaries, cleanup assignments) run exactly once.
  The `ANALYSIS_*` flags are set from `CKTmode` with `OSDIload`'s mapping so
  phase-qualified `@(final_step("tran"))` matches.

### Phase lists — reuse the `analysis()` matcher

`lower_event_control` now lowers `@(step("a","b"))` as
`step_flag & (analysis("a") | analysis("b") != 0)` using the same per-name
`CallBackKind::Analysis` callback that `analysis(...)` itself uses
(Enhancement-30's OR-shape, factored as `lower_phase_filter`). An empty list
fires in every analysis, as before.

### The AC/noise op-phase mapping gap

`@(initial_step("ac"))` still didn't fire in an AC run: an AC job's **first
model evaluation happens during its DC operating-point phase**, where
`OSDIload` set only `ANALYSIS_DC|ANALYSIS_STATIC` — so the one-shot fired
with no "ac" match. ngspice already treats tran's op phase as part of tran
(`MODETRANOP → ANALYSIS_TRAN`), but `CKTmode` cannot distinguish an AC job's
op from a standalone op. `OSDIload` now consults the running job's type
(`ft_sim->analyses[ckt->CKTcurJob->JOBtype]->name`) and adds the
`ANALYSIS_AC` (or `ANALYSIS_NOISE`) **name bit only** during that op — *not*
the reactive `CALC_*` bits `is_ac` carries, which would wrongly enable
ddt/integration during an operating point. This also makes `analysis("ac")`
hold through the whole AC analysis per LRM 4.6.1.

## What now works (`finalstep_examples/`, 23 checks, all exact)

| analysis | behavior |
|---|---|
| tran 2 µs | `final` fires **exactly once at t = tstop** and sees the converged solution (V = 1.0 at two full sine periods, 1e-6); `final_tran` fires; `final_ac`/`final_dc` silent; `initial_ac` silent; multi-phase `("ac","tran")` fires |
| op | single point = first **and** last: `initial`, `initial_dc`, `final`, `final_dc` fire once each; tran/ac-qualified silent |
| ac sweep | `final` + `final_ac` fire once after the sweep; `initial_ac` + multi-phase fire (op-phase mapping fix); tran/dc-qualified silent |
| dc sweep 0→2 V | `final` fires once and sees the **last sweep point** (V = 2.0 exact); `final_dc` fires |
| noise sweep | `initial` + `final` fire once each |
| peak tracking | the LRM's classic use case: a variable accumulated across the whole transient is reported once at `final_step` (vpeak = 1.5, 1 %) |

`verify_finalstep.py`: 23/23 PASS. Regression: all 48 example verify suites
ALL PASS; crate tests (hir_lower, sim_back, osdi) all pass.

## Notes

- **Not an OSDI ABI change**: the flag is an additive bit in the existing
  `flags` word (same convention as E-7); no descriptor layout moves, so
  existing `.osdi` files stay loadable (they just never see the new bit).
- With `autostop`, `final_step` fires at the autostop point (the last point
  the analysis actually solved), which is the LRM-correct reading of "the
  last point of the analysis".
- Interrupted/failed analyses do not fire `final_step` — only the successful
  completion paths call `OSDIfinalStep`.
- The final-step evaluation may update hidden/event state slots; every
  analysis re-initializes them (`osdisetup.c` resets), so subsequent analyses
  are unaffected.
