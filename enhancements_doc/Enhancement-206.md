# Enhancement-206 — design centering / yield optimization

The capstone that **fuses two whole subsystems**: the optimizer (Nelder-Mead / LM /
PSO / DE / SA, [E-130](Enhancement-130.md)–[197](Enhancement-197.md)) and the
Monte-Carlo yield suite (`agauss`/`mccorr` sampling + `montecarlo` specs,
[E-149](Enhancement-149.md)–[151](Enhancement-151.md)). Design centering optimizes
the **nominal design point** to maximize **parametric yield / Cpk** under process
variation — a real Spectre/ADS capability.

## The fusion

The optimizer's `opt_eval` already does *apply knobs → run analysis → evaluate
objective*. Design centering replaces the objective with an **inner Monte-Carlo run**:

```
optimize -dparam xc <init> <lo> <hi> ...   (the nominal design point to centre)
         -center -samples N [-lhs] [-seed s]
         -analysis "<cmd>"
         (-spec <metric> [-max HI] [-min LO])...   (pass/fail limits, as in montecarlo)
         [-method nm|pso|de|sa]
```

- The **outer** optimizer searches the design knobs.
- At each candidate, the **inner** loop runs `N` Monte-Carlo samples — each `reset`
  re-samples the deck's process variation (`agauss`/`.param`, and any `mccorr`
  correlations) around the current design centre — evaluates every spec, and reduces
  to the **worst-case Cpk** and the pass-fraction **yield**.
- The design knobs feed the `agauss` *centres*, so moving the design point shifts the
  whole distribution; the process σ stays in the deck.

## Why Cpk is the objective (yield is reported)

Raw yield is a **granular step function** (with finite `N` it changes in jumps),
which stalls a simplex. **Cpk** — `min(gap to each active limit) / (3σ)` per spec,
worst-cased across specs — is **continuous** and monotone in yield, so it is the
smooth objective the optimizer maximizes; the yield is computed and reported
alongside. Maximizing Cpk centres the distribution in its spec window (and rewards
lower sensitivity), which is exactly design centring.

A **fixed inner seed** gives every candidate the *same* process draws (common random
numbers), so the objective is deterministic and smooth. With **`-lhs`** the stratified
sample-mean is ≈ 0, so the optimum lands right on the analytic centre.

## Implementation

`com_optimize.c` only. `opt_eval`'s in-place-knob application was factored into
`opt_apply_inplace` (so the MC loop can re-apply the centre after each `reset`
re-sources the deck), and a new `opt_eval_center` runs the inner MC and returns
`-min(Cpk)`. The methods (nm/pso/de/sa) are unchanged — they call `opt_eval`, which
now returns the centering cost. Reuses the E-149/151 sampling (`mc_lhs_config`,
`mc_sss_off`, `setseed`). `lm` is rejected for `-center` (Cpk is not a least-squares
residual); the default method is Nelder-Mead. Results are published as
`dcenter_yield` / `dcenter_cpk` vectors.

## Verification

Synthetic problems with **known optimal centres** (`examples/dcenter_examples`):

- **[center]** output ~ N(xc, 0.5), spec [4, 6] ⇒ the yield/Cpk-optimal centre is the
  midpoint 5; from an off-centre start (4.0) the optimizer recovers xc ≈ 5.00 and the
  analytic Cpk = 1/(3·0.5) = 0.667.
- **[improves]** the centred design's yield (~95%) beats the off-centre start's (a
  `montecarlo` at xc = 4.0 sits near 50%).
- **[twoknob]** two design params with a lower and an upper spec on two outputs centre
  independently (xa → 5 on [4,6], xb → 10 on [9,11]).

## Scope

Front-end only; solver-independent. Composes with everything the optimizer and the MC
suite already support — `-lhs`, `mccorr`/`mvnorm` correlations, all optimizer methods,
and the `-param`/`-mparam`/`-dparam` knob kinds.
