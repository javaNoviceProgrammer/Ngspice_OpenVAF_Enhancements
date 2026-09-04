# Enhancement-543: the Monte Carlo commands answer honestly, and a compiled MOSFET converges like a built-in one

**Scope:** everything since [E-542](Enhancement-542.md) — the five findings of
the Monte Carlo hunt
([`docs/bug_hunts/2026-09-04_monte-carlo-commands.md`](../docs/bug_hunts/2026-09-04_monte-carlo-commands.md))
and the four of the large-circuit sweep
([`docs/bug_hunts/2026-09-04_large-circuits-speed-and-correctness.md`](../docs/bug_hunts/2026-09-04_large-circuits-speed-and-correctness.md)),
plus the KLU defect the last of those uncovered. **ngspice only; the compiler
is unchanged.**

**Suites:** [`examples/osdilimit_examples/`](../examples/osdilimit_examples/)
(new, 12 checks), [`montecarlo_examples`](../examples/montecarlo_examples/) 10
→ 15, [`highsigma_examples`](../examples/highsigma_examples/) 10 → 14,
[`wcd_examples`](../examples/wcd_examples/) 19 → 31 with a compiled fixture,
[`mcpolicy_examples`](../examples/mcpolicy_examples/) 33 → 34,
[`yield_examples`](../examples/yield_examples/) +4,
[`display_examples`](../examples/display_examples/) 18 → 22,
[`klu_tuning_examples`](../examples/klu_tuning_examples/) +3;
[`examples/benchmark_examples/large_bench.py`](../examples/benchmark_examples/large_bench.py)
regenerates the sweep. Full sweep **453 of 453**, both solvers.

## Part 1 — the Monte Carlo commands

A pass over `montecarlo`, `highsigma`, `wcd`, `setseed`, `mccorr`/`mvnorm`
and `.option osdimc` measured every statistic against its closed form and
found the numerical core right everywhere — and five ways the *inputs* could
produce a confident wrong number or a silent one.

* **A quoted or unresolvable spec was scored as 0.** `-spec "vecmax(v(2))"`
  arrived with its quotes and was looked up as one vector name; the failed
  lookup scored 0 against the limits and the report was a definite 0 % or
  100 % yield, because every caller of the evaluator discarded its validity
  flag. Now `-spec`/`-metric` pass through the same `cp_unquote` as
  `-analysis`, and a metric that resolves to nothing is refused with the spec,
  sample and plot named; `wcd` names it at the nominal point instead of
  blaming the operating point.
* **Un-seeded runs were identical replications.** Every command re-seeds
  the netlist PRNG from 1 unless `-seed` is given, so "run it again" returned
  the same samples and the report never said which seed. The default stays —
  a fixed seed pairs the samples across design changes — and is now stated:
  `..., seed 1 (default)` in every banner, a note that a rerun repeats the
  netlist draws (and that `.option osdimc` draws advance per trial), and
  `montecarlo_seed` / `highsigma_seed` / `wcd_seed` for scripts.
* **`wcd` could not see model-declared statistics.** Enhancement-535 held
  every osdimc draw at one sample for the whole search, so a deck whose
  variability was entirely model-declared was refused, and one small netlist
  dimension beside them reported a 4σ event at 106σ. The osdimc applier
  gained a **walk mode** (`OSDImcWalk`): every Gaussian statistical parameter
  takes nominal + σ·z[k] in a fixed enumeration order, uniforms are held, and
  the trial counter's baseline gate does not apply; `wcd` counts those
  dimensions after its nominal evaluation, places them after the netlist's in
  `u`, and shifts them in the `-is` refinement with the same likelihood ratio.
  The osdimc-only deck reports β = 4.0000; the mixed one 3.9601, the analytic
  value; the refinement lands on Φ(−4) within its error bar.
* **`mvnorm(i)` outside the registered matrix was an independent draw.**
  With a matrix registered, an index it does not have — or a fractional one —
  is now a `.param` error naming the range. With none registered the
  independent draw stands (E-151's design, and every deck's state at load,
  before its `.control` block has run `mccorr`), so `mccorr` itself now
  reports an index the deck already used beyond its matrix.
* **A contradictory spec yielded 0 % in silence.** `-max` below `-min` is
  refused at parse time by all three commands, each naming the consequence it
  would have reported.

## Part 2 — large circuits

Four circuit families to 40 000 BSIM4 MOSFETs and 67 000 OSDI instances,
every deck under both solvers and against its built-in twin. The two solvers
agree to 1e-15 on every node of every operating point and to the last bit on
AC; the compiled models agree with their twins to 1.6e-9 V at DC and a 1 %
per-stage delay; KLU is 1.2–2.7× ahead on chains, 4–8× on meshes, 10× on a
compact-model grid, and the only solver that finishes a 9 800-MOSFET grid.
Four things cost time or misled at scale, all fixed:

* **The OSDI MOSFET operating point fell into gmin stepping where the
  built-in converged directly** — the headline. A chain of 100 OSDI BSIM4 or
  PSP103 inverters needed 333 iterations with dynamic gmin stepping where the
  built-in twin took 9; a 40×40 grid 167 iterations and 5 s. A Verilog-A
  model gets step limiting only through `$limit`, and those models ship
  without one. The simulator now recognizes a 3/4-terminal MOSFET
  (`d,g,s[,b]`) or BJT (`c,b,e[,s]`) by its terminal names at load, reads the
  model's polarity (`type`) and threshold (`vth0`/`vto`), and does in the
  Newton loop what `b4ld.c` does — the cold-start guess, then `DEVfetlim` /
  `DEVlimvds` / `DEVpnjlim` — in the **type-normalized frame**, across the
  model's own internal drain/source/gate/bulk nodes when its series
  resistances keep them live. A model that limits itself, carries a further
  terminal (a thermal node), keeps another live internal node (MEXTRAM's
  `b1`/`e1`) or is a two-terminal module is left alone; PSP103's
  noise-correlation branch is a flow unknown and does not count. Result:
  **8 iterations** on those chains and on the 40×40 grid under Sparse
  (0.56 s), the 70×70 grid's op in 16 s where it timed out, the 40 000-device
  chain's op 30 s from 53 s — and every operating point the same to 1e-16.
  `.option noosdilim` switches it off; `set osdilim_verbose` says, once per
  model, what was decided and why.
* **KLU's refactor reused pivots the matrix had outgrown.** With the limiter
  in place the grid converged in 8 under Sparse and wandered for 137 under
  KLU: at the third solve `klu_refactor` reused a pivot order chosen on a
  wholly different Jacobian and returned a wrong direction with no error,
  where Sparse's refactor flags a small pivot and reorders. E-439's exact-zero
  rcond test now also treats a collapse of rcond by more than 1e-6 relative to
  the last full factorization as a small pivot and reorders; KLU's own
  singular verdict is preserved around the estimate. 12 iterations.
* **`rusage` reported a negative fill-in under KLU** (the formula counted the
  diagonal twice and the off-block entries never), and in a KLU build the
  Sparse-mode total read 0. Both count correctly.
* **BSIM4's own `$strobe` printed a line twice per instance per setup** —
  80 000 lines on the largest deck. The display funnel shows an identical
  complete line five times within one run of output and then counts it into
  one summary line, keyed by text in a ring of recent messages so a constant
  line survives interleaving; `$write` partial lines are never coalesced; a
  message that begins with newlines emits them before the instance head.

## Verification

| check | result |
|---|---|
| quoted `-spec "vecmax(v(2))"` under `tran` | 20 / 20 (was 0 / 20); `v(nosuch)` refused by all three commands |
| `wcd` on the osdimc-only deck / with a 1 Ω netlist resistor | β = 4.0000 / 3.9601 (was refused / 106.7) |
| `mvnorm(3)` against a 2×2 matrix | `.param` error naming `mvnorm(1..2)` |
| 100-stage OSDI BSIM4 / PSP103 chain op | 8 iterations, no stepping (was 333 / 387 with stepping) |
| 40×40 OSDI BSIM4 grid op, Sparse / KLU | 8 / 49 (was 167 / 70; built-in 9 / 48) |
| operating points after the limiter | identical to 1e-16 at every node |
| 3 200-device grid, model chatter | 12 lines (was 6 400) |
| full sweep | 453 of 453 suites, both solvers |
