# Enhancement-689: a model's `analysis("ic")` initial condition takes effect under `tran … uic` — the ic branch ran once, in the one unsolved evaluation `uic` makes, and its `ic` was dead

**Scope:** F7 of the
[bug hunt of 2026-09-21](../docs/bug_hunts/2026-09-21_ngspice-osdi-analyses-sens-and-events.md).
ngspice: `src/osdi/osdiload.c` (`OSDIuicSeed`: the transient's start vector seeded from the
ic-branch potential contributions; the uic evaluation's flags kept for it),
`src/maths/ni/niiter.c` (the hook after the one load `uic` makes),
`src/include/ngspice/osdiitf.h`. `examples/analyses_examples/` (two modules, seven checks,
36). **ngspice only.**

**Suites:** [`analyses_examples`](../examples/analyses_examples/) 36 of 36 per solver, both
solvers (5 of the 7 new checks fail on the E-680 binaries; the two controls — an
unconditional potential source, and the run without `uic` — pass there); `warmstart`,
`failacct`, `linesearch`, `tranopdelay`, `finalstep`, `checkpoint`, `dynorder`,
`integmethod`, `integaccuracy`, `hbosc`, `pssdriven`, `rfpss`, `robustness`, `trnoise`,
`reusecache`, `lrmfuncs`, `lrmnoise`, `analysis` unchanged; full sweep 531 of 531.

## What was wrong

LRM 4.6.1 applies an initial condition in the initial-condition analysis that precedes
a transient:

```verilog
if (analysis("ic")) V(p, n) <+ ic; else I(p, n) <+ ddt(c * V(p, n));
```

With `ic=0.5`, driven through 1 kΩ from 1 V, beside a built-in `c2 … ic=0.5`:

| run | the model's `v(a)`, first points | built-in `v(b)` |
|---|---|---|
| `tran 0.1u 1u uic` | 3.0e-5, 6.0e-5, … charging from 0 | 0.5005, … from 0.5 |
| `tran 0.1u 1u` | 0.5 at t = 0, then charging from 0.5 | 1.0 (SPICE ignores `ic=` without `uic`) |
| `uic` and `.ic v(a)=0.5` | 0.50002, … from 0.5 | — |

Without `uic` the initial-condition analysis is the transient operating point; the
analysis-noise audit gave that phase its `"ic"` flag, the potential contribution is
solved there and the transient starts from `ic`. With `uic` ngspice skips the operating
point: `NIiter` loads every device **once** at the start vector (the deck's `.ic` values,
0 elsewhere) so that the built-in capacitor and inductor can seed their own state from
their `ic=`, and integrates. The OSDI loader reported that evaluation as the ic analysis
(`analysis("ic")` = 1, the LRM's TRAN-OP column), the model took its ic branch, and the
branch equation it stamped — V(p,n) − ic = 0 — went into a matrix nothing solved. A
Verilog-A device cannot write the state vector as the built-ins do; its parameter was
dead under `uic`, the capacitor's history started at 0 V, and only a `.ic` on the node
worked.

## What changed

`OSDIuicSeed`, run from `NIiter` right after that one load, **seeds the start vector with
the ic-branch potential contributions** — which say exactly what a `.ic` on the model's
nodes would:

- **Which rows are initial conditions.** Every branch-current unknown of every OSDI
  instance (a "flow node": the row of a potential contribution) is looked at. The instance
  is evaluated twice, with `analysis("ic")` and without; a row whose residual differs
  between the two is specific to the ic branch. An unconditional `V(p,n) <+ vdc` (a source)
  or `V(p,n) <+ r*I(p,n)` (a resistor written with its branch current) is the device's own
  equation, identical in both, and is left to the first timestep — as the built-in source
  is, whose node starts at 0 and snaps at the first step.
- **How a row is met.** V(p,n) − ic = 0 is met by the minimum-norm change of the free node
  voltages it involves (its coefficients read from the instance's own stamps of the load;
  ground and the deck's `.ic` nodes are fixed): a branch to ground sets its node to `ic`, a
  floating branch splits the difference. The rows are projected one at a time and swept to
  convergence (Kaczmarz), the circuit is reloaded at the seeded vector and the rows checked
  again — a linear row is met in one round, a nonlinear one gets up to six.
- **The built-ins see it.** Devices with a `DEVsetic` hook (the capacitor's `CAPgetic`,
  which takes `ic` from the node voltages when none is given) are re-run, so a built-in
  capacitor without `ic=` on a seeded node starts from the seeded value instead of pulling
  it back to 0.
- **Said.** One Note names the seeded nodes; a row whose nodes are all fixed (ground, or held
  by a `.ic` that disagrees) is reported as not applied, with its residual. A deck without
  such branches has no active row: nothing moves and the `uic` path is what it was.

## Verification

| check | result |
|---|---|
| a branch to ground, `tran … uic`: `v(a)` at the first point | 0.500015 (was 3.0e-5); Note "seeds v(a) = 0.5" |
| beside the built-in `c2 b 0 1n ic=0.5`: `v(a)` and `v(b)` at the first and third points | identical to 1e-6 |
| `.ic v(a)=0.3` and the model's `ic=0.5` | 0.3; Warning: the condition n1 places on V(p,n) is not applied, its node is held |
| a floating branch `n1 x y`: the Note, and `v(x)−v(y)` at the first point | "v(x) = 0.25, v(y) = -0.25"; 0.500008 |
| an unconditional `V(p,n) <+ vdc` under `uic` | no Note; the node at 1 V from the first step, as before |
| a built-in `c3 a 0 1n` without `ic=` on the seeded node | `v(a)` starts at 0.5 (was 1.5e-5) |
| without `uic` | 0.5 at t = 0, as before; no Note |
| the E-680 binaries on the suite | 5 of the 7 new checks fail (the two controls pass) |
| the Newton-phase and uic suites; full sweep | unchanged; 531 of 531 |

## What this does not do

- The ic branch's **current** contributions (`I(p,n) <+ …` under `analysis("ic")`) are
  not constraints on node voltages and are not seeded.
- The built-in capacitor's `ic=` without `uic` is still ignored, SPICE's rule; the model's
  `ic` without `uic` is applied by the transient operating point, as before.
- The uic evaluation still answers `analysis("ic")` = 1 — it *is* the ic phase now — and
  the ic branch is evaluated a few times (the load, the two probing evaluations, the reload
  and its probe): a `$strobe` there prints each time, a counter counts them (4 in the
  suite's model).
- A `.ic` wins where it disagrees with the model's value; two rows that contradict each
  other (two instances asking different voltages of one node pair) are reported, not
  reconciled.
