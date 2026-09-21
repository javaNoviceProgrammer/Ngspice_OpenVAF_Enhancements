# Enhancement-684: the operating points of `sp`, `pz`, `disto` and an AC `sens` answer `analysis("ac")` — one owning-analysis rule feeds `analysis()`, `$simparam$str("analysis_name")` and the qualified step events

**Scope:** F3 of the
[bug hunt of 2026-09-21](../docs/bug_hunts/2026-09-21_ngspice-osdi-analyses-sens-and-events.md).
ngspice: `src/osdi/osdiload.c` (`osdi_job_name_flags`: the small-signal jobs `SP`, `PZ`,
`DISTO` and an AC `SENS` name "ac"; `osdi_analysis_name` reads the same helper).
`examples/analyses_examples/` (a module and nine checks, 29). **ngspice only.**

**Suites:** [`analyses_examples`](../examples/analyses_examples/) 29 of 29 per solver,
both solvers (6 of the 9 new checks fail on the E-680 binaries: four on the name, two on
the final step [E-683](Enhancement-683.md) added; `op`, `ac` and `noise` pass there);
`finalstep`, `lrmevents`, `evtnoise`, `opvarac`, the five suites that read
`analysis_name` (`lrmkernel`, `lrmnoise`, `lrmfuncs`, `osdiplumb`, `rangeguard`) and the
four `sens` suites unchanged; full sweep 531 of 531.

## What was wrong

A model reads `analysis("ac")` at its operating point to choose a small-signal
formulation, to enable an `ac_stim`-style source, or in an `@(initial_step("ac"))` block.
[E-53](Enhancement-53.md) made the operating point of an `ac` job answer "ac" (the phase
belongs to the owning analysis; LRM Table 4-22's "dc" row is 0 there), by consulting the
running job's name for `AC` and `NOISE`. The other small-signal jobs were not on that
list, so their operating points — the only evaluation of the analog block they make —
said "dc":

| analysis | `analysis("ac")` | `analysis("dc")` | `analysis_name` | `initial_step("ac")` |
|---|---|---|---|---|
| `ac` | 1 | 0 | ac | fires |
| `sp`, `pz`, `disto`, `sens … ac` | **0** | **1** | **dc** | **silent** |
| `tf`, `sens` (DC) | 0 | 1 | dc | silent |

An S-parameter sweep is an AC sweep with ports; a pole-zero and a distortion analysis
linearise the model the same way and work in the frequency domain; the AC form of a
sensitivity analysis sweeps the AC response. A model switching on "ac" took its DC path in
all four.

## What changed

**The four belong to "ac".** `osdi_job_name_flags` — the helper [E-683](Enhancement-683.md)
made of E-53's consultation, shared by `OSDIload` and `OSDIfinalStep` — names `SP`, `PZ`,
`DISTO` and a `SENS` job whose `step_type` is not `SENS_DC` "ac", beside `AC` and
`NOISE`. `osdi_analysis_name`, which serves `$simparam$str("analysis_name")`, reads the
same helper instead of its own two `strcmp`s, so the string, the `analysis()` flags and
the qualified step events cannot disagree. The E-53 rule that removes the "dc" bit when
an owning name is set applies unchanged, so `analysis("dc")` is 0 and `analysis("static")`
stays 1 at those points.

**`tf` and a DC `sens` stay "dc".** Both are computed at zero frequency; the LRM's "ac"
is a frequency analysis. The compiler accepts `ac`, `dc`, `ic`, `nodeset`, `noise`,
`static` and `tran` and nothing else, so no finer name (`"sp"`, `"pz"`) is expressible; a
model that needs to tell them apart has `$simparam$str("analysis_type")`, which carries the
same string.

## Verification

| check | result |
|---|---|
| `sp`, `pz`, `disto`, `sens v(a) ac …` | flags ac/dc/static/noise = 1/0/1/0, `analysis_name` "ac", `initial_step("ac")` and `final_step("ac")` fire once, the "dc" events silent |
| `tf`, `sens v(a)` | 0/1/1/0, "dc", the "dc" events fire |
| `op`, `ac`, `noise` | unchanged: dc, ac, noise |
| `tran` | `analysis_name` "tran" |
| the E-680 binaries on the suite | 6 of the 9 new checks fail |
| full sweep | 531 of 531 |

## What this does not do

- It does not touch the reactive-Jacobian computation: `CALC_REACT_JACOBIAN` was already
  set at every `MODEINITSMSIG` load, name or no name.
- It adds no analysis names; the compiler's list is the LRM's.
- A `sens` still runs `@(initial_step)` once per perturbation (E-683's note); each of
  those now carries the right name.
