# Enhancement-143 — gradient least-squares curve fitting for `optimize`

[Enhancement-130](Enhancement-130.md) gave ngspice a built-in `optimize`
command: a derivative-free Nelder-Mead search that varies parameters, re-runs an
analysis, and minimizes a single scalar objective. That is the right tool for a
one-off tuning goal, but the most common optimization job in circuit work is a
**fit** — drive several measurements to their targets at once (curve fitting,
device-parameter extraction), which is a *least-squares* problem with a smooth
objective. Nelder-Mead ignores that structure and crawls.

Enhancement-143 adds a **least-squares mode** to `optimize`: give it one or more
weighted `-target <expr> <value>` measurements, optionally spread over several
`-analysis` stages, and it fits the parameters with **Levenberg-Marquardt** (a
finite-difference Jacobian) — the standard gradient-based least-squares method,
which exploits the sum-of-squares structure to converge in far fewer analysis
runs. The original scalar `-minimize` / Nelder-Mead path is unchanged.

## Usage

```
optimize -param <name> <init> <lo> <hi>  [-param ...]
         -analysis <command ...>
         ( -minimize <expression ...>                       (scalar, Nelder-Mead)
           | -target <expr> <value> [<weight>]  [-target ...]   (least squares, LM)
             [ -analysis <command ...> -target ... ] )
         [-method nm|lm] [-maxiter <N>] [-tol <T>] [-verbose]
```

- **`-target <expr> <value> [<weight>]`** — a measurement to fit. `<expr>` is a
  single ngspice expression token (use the no-space forms `v(out)-v(in)`,
  `mag(v(out))`, `v(out)[3]`), `<value>` the desired value, `<weight>` an optional
  residual weight (default 1; use `1/value` for a *relative* fit when magnitudes
  span decades). The residual is `weight·(expr − value)`; the optimizer minimizes
  the sum of squared residuals. Repeatable, up to 64 targets.
- **Multi-analysis stages** — each `-analysis` opens a stage; every `-target` after
  it is evaluated on that stage's results. A single fit can therefore combine
  different analyses, e.g. a DC operating point **and** an AC response. Up to 8
  stages.
- **`-method nm|lm`** — force the algorithm. Default: least-squares (any `-target`)
  uses **`lm`** (Levenberg-Marquardt); a scalar `-minimize` uses **`nm`**
  (Nelder-Mead). `nm` also works on a least-squares objective (it minimizes the
  summed square); `lm` requires `-target`s.
- **`-minimize`**, **`-param`**, **`-maxiter`**, **`-tol`**, **`-verbose`** — as in
  Enhancement-130. `-minimize` and `-target` are mutually exclusive.

As before, each candidate is applied in place with `alter <name>=<value>` (no
re-source), every stage's analysis is run, and each expression's **last** value is
read (target a single point with a one-point analysis or a vector index). The
search runs in **normalized [0,1] parameter space**, so it is scale-invariant
across parameters that differ by orders of magnitude. On convergence the circuit
is left at the optimum; the sum-squared residual (and its RMS) plus the fitted
parameters are printed.

### Example — two-parameter, two-analysis fit

```
V1 in 0 dc 1 ac 1
R1 in out 3.3k
R2 out 0 3.3k
C1 out 0 100n
.control
optimize -param R1 3.3k 500 8k -param R2 3.3k 500 8k
+        -analysis op                 -target v(out)      0.4
+        -analysis ac lin 1 2000 2000 -target mag(v(out)) 0.221061
.endc
```

recovers `R1 = 3 k`, `R2 = 2 k` — the unique circuit whose DC gain is 0.4 and
whose |H(2 kHz)| is 0.221061 — from a 3.3 k / 3.3 k start.

## Implementation notes

- All changes are in `frontend/com_optimize.c` (plus the one-line help string in
  `commands.c`). No new files, no ABI change.
- The objective is generalized to a list of **stages** (`struct opt_target` with
  an owning `-analysis` index). `opt_eval()` sets the parameters once, then for
  each stage runs its analysis and evaluates that stage's targets while the
  stage's plot is current — filling a residual vector (least squares) or a single
  scalar (`-minimize`). Console chatter is still gated at source by
  `ft_optimizing` (see Enhancement-130).
- **Levenberg-Marquardt** (`levenberg_marquardt()`): a forward-difference Jacobian
  `J` of the residuals w.r.t. the normalized parameters (backward difference near
  the upper bound), the normal equations `A = JᵀJ`, `g = Jᵀr`, and the damped
  solve `(A + λ·diag(A)) δ = −g` with a small dense Gauss-elimination solver
  (`solve_lin`, partial pivoting). λ is decreased on an accepted step and
  increased until a step reduces the cost — the standard trust-region-like LM
  loop. Converges on relative cost improvement or step size below `-tol`.
- Nelder-Mead is retained verbatim; in least-squares mode it minimizes the summed
  square (`opt_eval(…, NULL)`), which is how the `-method nm` comparison runs.

## Verification

`examples/optimize_examples/verify_optimize.py` (23/23; the front-end command is
solver-independent, so it runs once) — checks [1]–[5] are the Enhancement-130
scalar/Nelder-Mead cases; [6]–[10] are new:

- **[6]** LM recovers `R` of an RC low-pass from `|H|` at three frequencies, one
  `-target` per frequency on its own `-analysis` stage.
- **[7]** two-parameter fit of `R1`, `R2` to a DC gain (`op` stage) **and** an AC
  magnitude (`ac` stage) simultaneously → `R1 = 3 k`, `R2 = 2 k`.
- **[8]** LM reaches the same optimum as Nelder-Mead in **27 vs 67** evaluations
  on a two-target RC fit.
- **[9]** **OSDI / Verilog-A device-parameter extraction**: recover *both* the
  saturation current `is` and emission coefficient `n` of a compiled diode from
  two measured I-V points by weighted least squares (`is → 1e-14`, `n → 1.2`).
- **[10]** input validation: `-method lm` without `-target`, `-minimize` together
  with `-target`, and multiple `-analysis` with a scalar `-minimize` are rejected.

`examples/optimize_examples/optimize_lsq_demo.cir` is a runnable least-squares
demo; `optimize_demo.cir` remains the Nelder-Mead demo.

## Scope and follow-ups

Least-squares fitting of `alter`-reachable device/instance parameters over one or
more analyses. Still future work: optimizing symbolic `.param` values directly
(needs a re-source that re-evaluates the netlist without re-running the analysis),
and analytic (adjoint) sensitivities in place of the finite-difference Jacobian.
