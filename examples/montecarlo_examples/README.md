# montecarlo_examples — Monte Carlo with Verilog-A (OSDI) devices (Enhancement-66)

Statistical simulation over OSDI parameters — the remaining workflow gap
after parameter sweeps (E-62) and `alter` — probed end-to-end and found
**fully working**. Like Enhancements 57 and 60, the deliverable is the
validation itself: no compiler or ngspice source changes.

## The two MC idioms (both work)

1. **The `reset` idiom** — `.param rr = agauss(1k, 100, 3)` feeding a
   `.model` card (`r={rr}`) or an instance line (`N1 a 0 mm r={rr}`, with
   `(* type="instance" *)`); each `reset` re-throws the dice and re-runs
   the OSDI model/instance setup.
2. **The `alter` loop** — control-language random vectors
   (`sgauss(0)`, `sunif(0)`) assigned per run via `alter @n1[r] = value`;
   no netlist re-parse (faster), and `setseed N` makes the whole run
   sequence bit-reproducible.

Distribution semantics (verified analytically): ngspice's
`agauss(nom, avar, sig)` draws with σ = avar/sig; `aunif(nom, avar)` is
uniform on [nom−avar, nom+avar]; `sgauss(0)` is standard normal;
**`sunif(0)` is already uniform on [−1, 1]** (not [0, 1] — easy to get
wrong).

## The gotcha (pinned by check [6])

Every textual occurrence of a random-valued `{param}` **draws
independently** — two devices written with the same `{rr}` get *different*
values in the same run. Matched/correlated devices need the `alter` idiom,
where one control-language value is explicitly assigned to each instance.

## Run

```bash
python3 verify_mc.py    # 12 checks
python3 plot_mc.py      # regenerates plots/mc_distributions.png
```

Checks: reset-idiom MC on model-card and instance-line params (mean/σ vs
analytic, ±5σ bounds), the seeded `alter` loop (σ exact to statistics +
bit-reproducibility), `aunif` bounds, single-draw seed reproducibility,
the independent-draws gotcha, and a nonlinear diode MC whose op-point
spread matches the analytic sensitivity σ_V ≈ v_t·σ_Is/Is.

The plot shows 500-run gaussian and uniform MC histograms sitting on the
analytic transformed densities of I = 1V/R.
