# solverannounce_examples — Enhancement-266

ngspice printed `Using SPARSE 1.3 as Direct Linear Solver` (or the KLU line) on
**every** analysis. The `sweep` command re-runs the analysis for each point, so a
five-point sweep printed the line five times — as did Monte Carlo, `optimize`, and
the other loop commands.

The solver line is now announced **once**, and again only when the active solver
changes (`.option klu` / `.option sparse`), via an announce-on-change helper
(`CKTannounceSolver`) shared by `CKTsetup` and `CKTpzSetup`. A single analysis is
unchanged (still one line); a fresh process still announces once, so the HB and
benchmark suites that detect KLU by grepping for the line still work.

Run `sparse_sweep.cir` before/after: a five-point sweep that used to print the
SPARSE line five times now prints it once.

## Verify

```
python3 verify_solverannounce.py
```

Four checks: a 5-point sweep announces SPARSE once (was 5×); a single `op` still
announces once; a `sparse → klu` switch re-announces; a KLU analysis still prints
the KLU line.
