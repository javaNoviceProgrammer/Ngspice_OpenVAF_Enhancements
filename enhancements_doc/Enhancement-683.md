# Enhancement-683: `@(final_step)` fires at the end of every analysis, and what it assigns stays — `pz`, `tf`, `sens`, `disto` and `sp` never called the final step, and under `ac`/`noise` the E-412 snapshot discarded its writes

**Scope:** F2 of the
[bug hunt of 2026-09-21](../docs/bug_hunts/2026-09-21_ngspice-osdi-analyses-sens-and-events.md).
ngspice: `src/osdi/osdiload.c` (`OSDIfinalStep`: the bias-point capture is used whenever
it is valid, the E-412 snapshot only when it is not; the analysis name from a helper shared
with `OSDIload`), `src/spicelib/analysis/tfanal.c`, `pzan.c`, `span.c`, `distoan.c`
(the final-step call at the end), `cktsens.c` (the base operating point kept and put back
before the call). `examples/finalstep_examples/` (a counter module and nine checks, 35).
**ngspice only.**

**Suites:** [`finalstep_examples`](../examples/finalstep_examples/) 35 of 35 per solver,
both solvers (8 of the 9 new checks fail on the E-680 binaries; the changed-bias control
passes there); `opvarac` (E-412) 19 of 19, `lrmevents`, `analyses`, `evtnoise`,
`sensrestore`, `sensstate`, `senscplx`, `osdisens` unchanged; full sweep 531 of 531.

## What was wrong

A module counting its final steps, `@(final_step) begin cf = cf + 1; $strobe(...); end`,
with `cf` an operating-point variable:

| analysis | strobe | `cf` read afterwards |
|---|---|---|
| `op`, `dc`, `tran` | once | 1 |
| `ac`, `noise` | once | **0** |
| `pz`, `tf`, `disto`, `sp`, `sens` (DC or AC) | **never** | 0 |

LRM 5.10.2 places `final_step` on the last step of *any* analysis. `OSDIfinalStep` was
called from `acan.c`, `dcop.c`, `dctran.c`, `dctrcurv.c` and `noisean.c` and nowhere else
([E-53](Enhancement-53.md) added it to the four analyses that existed for it then, E-677
the noise one), so five analyses ended without the event. Under `ac` and `noise` the event
fired, but [E-412](Enhancement-412.md) restores the instance after the evaluation. That
snapshot was written when the evaluation ran on the last frequency's small-signal solution
(`CKTrhsOld`), so that no operating-point variable would be recomputed from a complex
response; [E-677](Enhancement-677.md) moved the evaluation to the bias point the analysis
linearised around, captured at the `MODEINITSMSIG` load, after which the values the
evaluation writes are the operating point's own — plus whatever the event body assigned,
which is exactly what a model wants read back. The snapshot discarded both alike.

## What changed

**Every analysis calls the final step.** `tfanal.c`, `pzan.c`, `span.c` and `distoan.c`
call `OSDIfinalStep` once their result is out, as `acan.c` does before closing its plot. A
`sens` has no `MODEINITSMSIG` load and its AC sweep re-runs `CKTsetup` per frequency and
solves the small-signal system into `CKTrhsOld`, so `cktsens.c` keeps a copy of the base
operating point from its `CKTop`, puts it back into `CKTrhsOld` after the E-440 model
restore, and calls the final step there — once, not per perturbation.

**The bias point is used whenever it is valid.** The capture carries a validity mark now:
set at the `MODEINITSMSIG` load, cleared by any DC or transient evaluation (an `op`, a
`dc` point, a transient step — each moves the operating point and leaves the right one in
`CKTrhsOld`). `OSDIfinalStep` evaluates at the capture whenever the mark is set, whatever
`CKTmode` says at the end: `.tf` and `.pz` end in `MODEDCOP`, `.sp` in `MODESP`, `.disto`
in `MODEAC` with `CKTrhsOld` pointed into its own storage, and none of them says "small
signal" the way `MODEAC` did. An `op` after an `ac`, at a new bias, sees the new bias.

**The snapshot is kept only for the case it was written for:** a small-signal analysis
whose bias point is not available. At the bias point the evaluation's results stay, as
they do after an `op` or a transient. E-412's guarantee is unchanged — an operating-point
variable read after an `ac` is the operating point's, and its suite pins it.

**One helper names the analysis.** E-53's job consultation (the operating point of an
`AC` or `NOISE` job carries that name) lived inline in `OSDIload`; it is
`osdi_job_name_flags` now and `OSDIfinalStep` uses it too, so the final step of a job
carries the name its operating point carried: `tran` and a `dc` sweep are what `CKTmode`
says, everything else is `static` plus `ac`, `noise` or `dc`. The final steps of `tf`,
`pz`, `sp`, `disto` and `sens` say `dc`, as their operating points do today; the hunt's F3
is where that list is decided, in one place.

## Verification

| check | result |
|---|---|
| `pz`, `tf`, `sens` (DC), `sens` (AC), `disto`, `sp` on a 1 kΩ module at a 0.2 V bias | one `FS_CNT` strobe each, V = 0.2 (0.1822 for the `sp` deck, whose ports carry their 50 Ω), `cf` = 1 afterwards |
| `ac`, `noise` | one strobe at 0.2 V, `cf` = 1 afterwards (was 0) |
| `ac`, then `alter V1 dc=0.4`, then `op` | the second strobe at 0.4 V |
| the hunt's nonlinear deck (diode through 1 kΩ): `op`, AC `sens`, DC `sens`, `ac` at 1 V, then `alter vin dc=2` and `op`, `tf`, `pz`, `disto`, then `tran` at 1 V | 0.629443 ×4, then 0.662637 ×4, then 0.629441 |
| E-677's checks (V = 0.2 and a negative `last_crossing` at the final step of `ac`/`noise`) | unchanged |
| the E-680 binaries on the suite | 8 of the 9 new checks fail |
| full sweep | 531 of 531 |

## What this does not do

- A `sens` still runs `@(initial_step)` once per perturbation (nine times for two
  two-terminal devices): each perturbation is a fresh setup of the instance, which is how
  finite-difference sensitivity works; only the final step is once.
- `analysis("ac")` at the operating point of `sp`, `pz`, `disto`, `tf` and an AC `sens`
  is the hunt's F3; the shared helper is where its answer will go.
- The E-412 snapshot still guards an evaluation with no bias point (a small-signal mode
  with no valid capture); no analysis reaches that path now.
