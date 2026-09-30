# optmethods_examples — the optimization methods added to `optimize` from the 2026-09-29 proposal on (Enhancement 764)

```
python3 verify_optmethods.py
```

41 checks, one solver (a front-end command; the linear solver does not enter). 5 of 41
on the E-763 binary, which refuses the method name and the two flags.

The [`optimize` suite](../optimize_examples/) keeps the command's original coverage; this
one checks the methods' claims on standard test functions posed **inside ngspice**: the
knobs are the dc values of independent sources and a behavioural source computes the
objective from them (`B1 out 0 V = ...`), so an evaluation is a single operating point and
a method's whole search takes milliseconds. A compiled conductance whose parameter is
refused at g ≤ 0 (`optguard.va`) supplies the failing region.

Sections [1]–[10] are [Enhancement-764](../../enhancements_doc/Enhancement-764.md): CMA-ES
(`-method cmaes`), `-polish` and `-starts <k>`.

| section | what it pins |
|---|---|
| [1] | a rotated ellipsoid, condition 1e6: CMA-ES to 1e-12 at (0.3, 0.7), the swarm "converged" above 1e-3 at the same seed and budget; the banner's population 6 (recombining 3) |
| [2] | Rosenbrock in four knobs to 1e-8, every knob at 2/3, population 8 |
| [3] | hunt O1: the six-particle swarm still on the bound at 0.0361376 byte for byte; `-polish` takes it below 1e-9 at R2 = 250 in two reported lines; CMA-ES alone reaches 250 |
| [4] | hunt F6: Nelder-Mead's NO SOLUTION after 3 evaluations unchanged; CMA-ES from the same start at g = 1m with E-438's NOTE counting the refused minority; a box refused entirely ends after 13 evaluations as NO SOLUTION |
| [5] | hunt O2, nine decades: LM above rms 1e-5, CMA-ES `-tol 1e-10` below 1e-6 at R2 = 9000, the default `-tol` above 1e-3 (a length in the cube, stated) |
| [6] | two `-seed 1` runs identical to the digit, `-seed 2` different; `-maxiter 1` with the NOTE and the variables; one `-verbose` line per generation, σ down five orders, axis ratio past 100 |
| [7] | `-swarmsize 2` raised to 4 with a NOTE, the `cma` alias; `-polish` under Nelder-Mead a NOTE and the same run; `-polish`/`-starts` under nsga2, a bare `-starts`, `-starts 0`, `-starts abc` refused; the usage line and the unknown-method message |
| [8] | `-polish` on a `-target` fit is Levenberg-Marquardt: three evaluations, R2 = 9000 |
| [9] | a double well: Nelder-Mead from 0.15 in the wrong basin; `-starts 4` prints the banner, five numbered per-start lines and the winner, polishes to 0.8 and publishes `optimize_start`; CMA-ES `-starts 2` doubles its population per start (4, 8, 16); the swarm gets a seed per start |
| [10] | `optimize_status`, `optimize_converged`, `optimize_evals`, `optimize_cost` of a CMA-ES run equal to the report line |
