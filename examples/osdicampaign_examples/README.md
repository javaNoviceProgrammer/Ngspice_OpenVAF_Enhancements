# OSDI robustness + correctness campaign

83 checks over the OSDI device path — analyses, both solvers, sweeps, all seven
optimizers, Monte Carlo, RF, and deliberate abuse. **Every check has an oracle**,
so a pass means the number is *right*, not that a run finished.

## This is not part of the regression suite — on purpose

`examples/run_regression.py` discovers `examples/*_examples/verify_*.py`. This
driver is named `run_campaign.py`, so the routine sweep never picks it up.

The regression suite answers *"did anything change?"* and runs on every fold.
This answers *"is the OSDI path correct?"*, takes several minutes, and is worth
running when the OSDI or analysis machinery is touched.

```bash
cd examples/osdicampaign_examples
python3 run_campaign.py          # all phases
python3 run_campaign.py A C      # only the named phases
```

It compiles the models in `va/` to `_*.osdi` and writes `_*.cir` decks as it
goes; both are gitignored and cleaned up on exit.

## The five kinds of oracle

| phase | oracle | checks |
|---|---|---|
| **A** | **closed form** — the answer is derived on paper. Every case runs under *both* Sparse and KLU, which must also agree with each other | 36 |
| **B** | **differential** — the identical circuit built from ngspice's own built-in devices; the OSDI version must match it | 11 |
| **C** | **analytic optimum / exact probability** — an optimisation whose optimum is known exactly, and a Monte Carlo whose yield has a closed-form value | 14 |
| **D** | **cross-analysis** — PSS and HB must reproduce the AC result on a linear circuit; `.sp` against exact S-parameter algebra | 6 |
| **E** | **robustness** — corrupt input and lifecycle abuse must give a clean error, never a signal, hang, or wrong answer afterwards | 16 |

Highlights of what is actually pinned down:

- `.noise` on a Verilog-A resistor equals **√(4kTR)**; `.pz` puts the RC pole
  **exactly** on −1/RC; `.sp` reproduces S11 = Z/(Z+2Z₀) and S21 = 2Z₀/(2Z₀+Z);
  a matched 50 Ω load gives |S11| ≈ 1e-17.
- OSDI devices are **bit-identical** (`0.00e+00`) to the built-in `R`, `C`, `L`,
  `G`, and through `.tf`, `.pz` and `.sens`.
- `nm`, `lm`, `pso`, `de`, `sa` all find the analytic optimum; `nsga` and `nsga2`
  return Pareto fronts whose every point lies on the analytic curve.
- Monte Carlo agrees with a hand-rolled `reset`-loop oracle *and* with the exact
  Gaussian probability; `-lhs` lands on it too.
- 2000 OSDI instances in one circuit still solve to the exact divider value.

## Two explained differences (not defects)

**The diode vs ngspice's built-in `d`** differs by 7.35e-6, and that difference
is *constant* across `reltol` from 1e-3 to 1e-12 — so it is not convergence.
Backing the thermal voltage out of the I–V curve: OpenVAF's `$vt` is
`0.0258649231535`, exactly the Verilog-A `constants.vams` kT/q, while the
built-in diode uses its own constant 0.24 ppm away. Neither is wrong, and
OpenVAF's is the LRM value.

**PSS** sits a fraction of a percent off the AC oracle, and the error *falls* as
the time grid is refined (7.6e-3 → 3.6e-3 → 8.9e-4). That is shooting-method
discretisation, so the check asserts **convergence under refinement** rather than
a fixed tolerance.

## Usage notes worth keeping

Each of these cost a diagnostic cycle while the campaign was written, and each
looks like a bug at first:

- `(*type="instance"*)` parameters cannot be swept or tuned as **model**
  parameters — that needs a model-parameter model (`va/m_resm.va` is the pair to
  `va/m_res.va` for exactly this).
- Multi-knob sweeps separate knobs with **`-vs`**. The family vectors are named
  `<output>_<knob>_<value>`, and printing them needs a **named** output
  (`-output vo=v(out)`), because `v(out)_rb_1000` parses as a call to `v()`.
- `nsga` / `nsga2` require **two or more** objectives and print a Pareto front
  table, not a scalar optimum.
- `.noise` spectral density lands in plot **`noise1`**; the analysis leaves
  `noise2` (the integrated totals) current.
- `.sp` wants the **card** form plus `run`; at a single frequency the
  S-parameters are **scalars**, so `S_1_1[0]` is an error.
- ngspice echoes `print` tags **lowercased** in `tag = value`.
- A swept analysis prints a **table**, not `tag = value` — index it or use `meas`.

## Models

`va/` holds seven purpose-built Verilog-A models, each small enough that its
behaviour is exactly derivable: `m_res` (instance-parameter resistor), `m_resm`
(the model-parameter twin), `m_cap`, `m_ind`, `m_diode` (uses `$vt`), `m_vccs`,
and `m_rnoise` (a resistor with exact 4kT/R thermal noise).

Result when last run (2026-07-27): **83/83, no ngspice or OSDI defect found.**
