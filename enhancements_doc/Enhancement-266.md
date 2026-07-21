# Enhancement-266 — ngspice: announce the direct linear solver once, not on every analysis

Running the `sweep` command reprinted

```
Using SPARSE 1.3 as Direct Linear Solver
```

on **every sweep point**. A five-point sweep printed it five times; a hundred-point
sweep, a hundred times. The same noise appeared under every command that re-runs
the analysis for many points — Monte Carlo, `optimize`, the pso/de/sa optimizers.

## Cause

`CKTsetup()` (and `CKTpzSetup()` for pole-zero) print the active solver
unconditionally at the top of the setup:

```c
if (ckt->CKTmatrix->CKTkluMODE)
    fprintf(stdout, "Using KLU as Direct Linear Solver\n");
else
    fprintf(stdout, "Using SPARSE 1.3 as Direct Linear Solver\n");
```

`CKTsetup` runs once per analysis. The `sweep` command sets the knob and re-runs
the `-analysis` command for each point (`alter`/`altermod` in place, or
`alterparam` + `reset` — which re-sources the deck and rebuilds the circuit), so
each point calls `CKTsetup` and reprints the line.

## Fix

The line is now emitted only when the active solver **changes** — an
announce-on-change helper, `CKTannounceSolver()`:

```c
void CKTannounceSolver(int klu) {
    static int announced = -1;      /* -1 none, 0 SPARSE, 1 KLU */
    int mode = klu ? 1 : 0;
    if (announced == mode) return;
    announced = mode;
    fprintf(stdout, klu ? "Using KLU as Direct Linear Solver\n"
                        : "Using SPARSE 1.3 as Direct Linear Solver\n");
}
```

Both `CKTsetup` and `CKTpzSetup` call it instead of the raw `fprintf`. The
last-announced solver is tracked **process-wide** (a `static`), not per circuit,
because a `.param` sweep re-sources the deck — a per-circuit flag would still
repeat every point. Consequences:

* a multi-point sweep (or Monte Carlo / optimize run) announces the solver **once**;
* a single analysis still announces it once — unchanged;
* a genuine solver switch (`.option klu` / `.option sparse`) has a different mode
  and **re-announces**;
* a fresh ngspice process starts un-announced, so batch runs and the dual-solver
  test harness (which re-execs once per solver) still print it once each — and
  the HB and benchmark suites, which detect KLU by grepping for the line, still
  see it.

## Verification

`examples/solverannounce_examples/verify_solverannounce.py` (4 checks): a
five-point sweep announces SPARSE exactly once (was five times); a single `op`
still announces once; a `sparse → klu` switch in one process re-announces both;
and a KLU analysis still prints the KLU line (the detection the HB/benchmark
suites rely on). The full dual-solver example regression is unchanged (the message
is not part of any numerical comparison).

## Scope

Three files: `spicelib/analysis/cktsetup.c` (helper + call), `cktpzset.c` (call),
`include/ngspice/cktdefs.h` (prototype). No change to any analysis result, only to
how often the informational solver line is printed.
