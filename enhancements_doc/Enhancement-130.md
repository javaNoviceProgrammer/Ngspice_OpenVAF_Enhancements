# Enhancement-130 — built-in Nelder-Mead optimizer

A new front-end command, `optimize`, gives ngspice a **built-in parameter
optimizer**: it varies a set of circuit/device parameters, re-runs an analysis,
and minimizes a scalar objective expression — a derivative-free downhill-simplex
(Nelder-Mead) search. Previously this had to be scripted by hand in a `.control`
loop.

## Usage

```
optimize -param <name> <init> <lo> <hi>  [-param ...]
         -analysis <command ...>
         -minimize <expression ...>
         [-maxiter <N>] [-tol <T>] [-verbose]
```

- **`-param name init lo hi`** — a parameter to vary. `name` is an `alter` target:
  a device instance (`R1`, `C1`) or a device parameter (`@m1[w]`). Up to 16.
- **`-analysis <cmd>`** — the analysis to run each iteration (`op`, `ac dec 20 1 1meg`,
  `tran 1u 1m`, …). Collects every token up to the next `-<letter>` flag, so no
  quoting is needed.
- **`-minimize <expr>`** — the scalar cost to minimize, an ordinary ngspice
  expression over the result vectors, e.g. `(v(out)-0.3)^2` or
  `(mag(v(out))-0.5)^2`. Its last value is used.
- **`-maxiter`** (default 100), **`-tol`** (default 1e-6), **`-verbose`** (print the
  cost each iteration).

Each candidate is applied in place with `alter <name>=<value>` (no re-source), the
analysis is run, and the objective is evaluated. The search runs in **normalized
[0,1] parameter space** — each parameter is mapped to its `[lo,hi]` range — so it is
scale-invariant across parameters that differ by orders of magnitude (e.g. a
kilohm resistor and a nanofarad capacitor optimized together). On convergence the
circuit is left at the optimum and the best parameter values + final cost are
printed.

## Implementation notes

- The command lives in `frontend/com_optimize.c`. The Nelder-Mead simplex
  (reflection / expansion / contraction / shrink, bounds-clamped) is standard.
- Sub-commands (`alter`, the analysis) are dispatched **synchronously** through the
  command table (`cp_coms`) rather than `cp_evloop()`, which — called re-entrantly
  from inside a command — would *defer* them to the outer interpreter loop.
- The hundreds of inner analyses would otherwise flood the console. A new
  `ft_optimizing` flag (set only during an evaluation) gates the "Doing analysis"
  banner (`cktdojob.c`), the "No. of Data Rows" line, and the E-129 progress bar
  (`outitf.c`) at their source — an external `stdout` redirect does not survive
  `docommand`'s `cp_ioreset()`. `-verbose` disables the gate.

## Verification

`verify_optimize.py` optimizes circuits with **known analytic optima** and confirms
the command reaches them (9/9):

- **DC divider** — minimize `(v(out)-0.3)^2` over `R1` (R2=1k). `v(out)=R2/(R1+R2)`
  ⇒ `R1 = 2333.3 Ω` exactly; the optimizer finds 2333.33, `v(out)=0.3`.
- **AC low-pass** — minimize `(mag(v(out))-0.5)^2` over `R1` at 1 kHz (C=100n).
  `|H|=1/√(1+(2πfRC)²)=0.5` ⇒ `R = 2756.6 Ω`; found 2756.6, `|H|=0.5`.
- **Two parameters (2-D simplex)** — a divider where `R1=3k, R2=2k` uniquely gives
  `v(out)=0.4` and `R1+R2=5k` (`i(V1)=−0.2 mA`); minimize the compound objective
  `(v(out)-0.4)² + (|i(v1)|-0.2m)²`. Found `R1=3000, R2=2000` exactly.
- Output is quiet by default (1 banner for ~67 evaluations); `-verbose` prints
  per-iteration progress.

A front-end command, independent of the linear solver, so it is checked once.

## Files changed

| File | Change |
|---|---|
| `ngspice-46/src/frontend/com_optimize.c` / `.h` | the `optimize` command: option parsing, Nelder-Mead, synchronous sub-command dispatch, objective evaluation (`ft_getpnames_from_string`/`ft_evaluate`) |
| `ngspice-46/src/frontend/commands.c`, `com_commands.h`, `Makefile.am` (+`Makefile.in`) | register + build the command |
| `ngspice-46/src/frontend/options.c`, `include/ngspice/fteext.h` | the `ft_optimizing` quiet flag |
| `ngspice-46/src/spicelib/analysis/cktdojob.c`, `frontend/outitf.c` | gate the per-analysis banner / row count / progress bar on `ft_optimizing` |
| `examples/optimize_examples/` | `optimize_demo.cir`, `verify_optimize.py` |

## Scope

A general Nelder-Mead optimizer over `alter`-able parameters, verified to reach
analytic optima in 1-D and 2-D. Natural follow-ups: gradient / least-squares
methods for smooth problems, multi-analysis objectives (combine several runs),
and optimizing `.param` values directly (which needs a re-source that does not
re-run the analysis).

**Update ([E-762](Enhancement-762.md)).** The report's last line now says why the search stopped: `converged` (unchanged) on the simplex's own tolerance, `stopped at -maxiter (N iterations) -- NOT converged` with a NOTE when the cap ran out first, `NO SOLUTION -- no evaluation solved`, `unchanged -- nothing was optimised`; `optimize_status`, `optimize_converged`, `optimize_cost` and `optimize_evals` are published for a `.control` script.

**Update ([E-763](Enhancement-763.md)).** The parser refuses what it cannot mean: a bound or init that is not a number, an init outside `[lo, hi]`, a bare `-method`, a stray token, a knob named twice; an objective that begins with `-` must be quoted (`-minimize "-v(out)"`) or written `0-v(out)`, and the message says so.

**Update ([E-764](Enhancement-764.md)).** A seventh method, `-method cmaes`, joins the simplex; `-polish` runs Nelder-Mead (or LM for a `-target` fit) from a global method's best point with a first simplex edge of 0.05 in the cube instead of 0.1, and `-starts k` runs the simplex from k Latin-hypercube points besides the given one, reports each start and continues the winner with the full budget. Under `-method nm` alone `-polish` prints a NOTE and is ignored.

**Update ([E-765](Enhancement-765.md)).** `-method bayes` hands the rest of its evaluation budget to the simplex once its surrogate has located the basin, with a first simplex edge of 0.02 and the remaining evaluations as the iteration cap; the simplex's own run and report are unchanged.

**Update ([E-766](Enhancement-766.md)).** Under a constrained solve (`-constrain`) the simplex minimises the augmented objective, and a simplex that has gone flat against a bound -- every vertex the same clamped value in one coordinate -- is rebuilt around its best vertex with an inward edge instead of passing the convergence test; the unconstrained simplex is unchanged. `-min` stays the `-minimize` alias except right after a `-constrain` or a `-spec`.

**Update ([E-768](Enhancement-768.md)).** A second local method, `-method tr`, a trust region on a quadratic model, reaches the simplex's optima in a half to a seventh of the evaluations on smooth objectives and carries the knob bounds inside its subproblem. The polish and the surrogate's hand-off run it instead of the simplex; the simplex is still the `-minimize` default and is unchanged.
