# Enhancement-832: an unseeded `$random` or `$arandom` draws a new value in each analysis and each instance, and `setseed` reproduces them

**Scope:** F16 of the
[ngspice + OSDI hunt of 2026-10-08](../docs/bug_hunts/2026-10-08_ngspice-osdi-hierarchy-sweeps-events-and-outputs.md).

Compiler:
- `hir_lower/src/callbacks.rs`: a new callback, `RngUnseeded`. It is operating-point dependent,
  so the instance setup cannot hoist it.
- `hir_lower/src/expr.rs`: `lower_rng_seed` seeds the unseeded forms with it.
- `osdi/src/compilation_unit.rs`: resolves the callback to `osdi_rng_unseeded(simparams, handle)`.
- `osdi/stdlib.c`: `osdi_rng_unseeded`.
- `verilogae/src/back.rs`: the new kind in its match. With no simulator, the seed stays 0.

ngspice:
- `osdi/osdiload.c`:
  - the private simparam `$osdi$seed`;
  - `OSDIanalysisSeed`, which sets it.
- `include/ngspice/osdiitf.h`: the declaration.
- `spicelib/analysis/cktdojob.c`: seeds at a job's start, before the setup, and again for each
  later analysis of the job. A `resume` is not seeded.
- `frontend/com_hb.c`: `hb`, which runs outside a job, seeds too.
- `maths/misc/randnumb.c`, `include/ngspice/randnumb.h`: `ng_seed_generation`, a count of the
  generator's seedings.

`examples/seedac_examples/` (new; section [1], five checks).

**Suites:** [`seedac_examples`](../examples/seedac_examples/) 20 of 20 per solver (3 of the 5
checks in [1] fail on the E-831 binaries; the other two are controls). The full sweep, 547 of
547.

## What was wrong

```verilog
@(initial_step) begin r1 = $random; r2 = $arandom; end
```

Four `op`s, around `setseed 1`, `setseed 1` and `setseed 2`, all printed `r1 = 1366254664`.
Two instances `n1` and `n2` of the module drew identical values: in an `op`, after
`setseed 7`, and in a `tran`. As a result:
- a `repeat N op` loop drew one value N times;
- ngspice's seed command had no effect;
- per-device randomness written with the unseeded calls was perfectly correlated across
  devices.

Enhancement-10 made every draw a pure function of a seed and its call site. A pure draw is
stable across Newton iterations, where an advancing seed would destroy convergence. The
unseeded forms had no seed argument, so the lowering supplied 0, and the call site was all
that was left to vary.

## The change

An unseeded draw is now seeded with `osdi_rng_unseeded`. Its seed mixes two values:
- **The simulator's per-analysis seed.** ngspice publishes it as the private simparam
  `$osdi$seed`, a namespaced entry like Enhancement-678's `$osdi$tstep`.
- **The instance's name.** This is the string `%m` prints (FNV-1a).

The seed is constant through one analysis: every Newton iteration, every point of a sweep or
a transient, and the analysis' own operating point. The draw therefore stays pure, and
`RngUnseeded` is operating-point dependent, as `$simparam` is, so the instance setup cannot
freeze it.

ngspice moves the seed at the start of each analysis:
- **Each analysis.** A job's first analysis is seeded before its setup, so a draw in a
  parameter's default and the analysis see one value. Each later analysis of the job (an `op`
  then a `tran` in one `run`) is seeded anew. `hb` is seeded too, and a `resume` is not.
- **What it derives from.** The seed is a function of the generator's seed (`setseed`,
  `set rndseed`, 1 at startup) and of how many analyses have started since that seed was
  set. So `setseed 1` repeats the sequence from its first analysis, and with no `setseed` the
  first analysis draws what `setseed 1` would give.
- **Nothing is taken from the generator's own stream.** No other random quantity in a deck
  (`agauss`, transient noise, osdimc) moves because a model draws.

| | analysis 1 | analysis 2 | after `setseed 1` | after `setseed 2` |
|---|---|---|---|---|
| `n1` `$random` | 1497077349 | 810135438 | 1497077349 | 231718263 |
| `n2` `$random` | −1324851955 | 3320718 | −1324851955 | −1199899942 |

A seeded draw is unchanged. `$rdist_normal(s, 0, 1)`, with `s` set to 5 in the initial step,
returns the same deviate in every analysis and every instance, since the seed is the user's.

**Compatibility:**
- A model compiled earlier still draws with the seed 0.
- A model compiled now, on a simulator that serves neither `$osdi$seed` nor the instance name,
  also draws with the seed 0, the old value.
- A simulator that serves the name but not the seed gives per-instance values that repeat
  across analyses.

## The checks

`seedac_examples` [1], a module with `$random`, `$arandom` and a seeded `$rdist_normal` in its
initial step, and a `$random` in its body:
- Two `op`s draw different `$random` and `$arandom` values (were identical).
- `setseed 1` reproduces the first analysis' draw; `setseed 2` draws another.
- Two instances draw different values (were identical).
- The seeded `$rdist_normal` repeats everywhere (control).
- The body draw holds one value through a transient and a dc sweep.

## Limits

- One call site still returns one value per analysis and instance. A loop that calls `$random`
  N times at one site collects N copies of one draw. Use a seeded form with a varying seed
  (`$rdist_normal(seed + i, ...)`) for that (Enhancement-10, Enhancement-642).
- The seed follows `setseed` and `rndseed`, not `.option mcseed` or a loop command's `-seed`.
  Each osdimc trial is an analysis of its own and draws anew.
