# Enhancement-206 — design centering / yield optimization

The capstone that fuses two whole subsystems:

- the **optimizer** (Nelder-Mead / LM / PSO / DE / SA, E-130–197), and
- the **Monte-Carlo yield suite** (`agauss`/`mccorr` sampling + `montecarlo` specs, E-149–151).

**Design centering** optimizes the *nominal design point* to maximize **parametric
yield / Cpk** under process variation — a real Spectre/ADS capability.

## Usage

```
optimize -dparam xc <init> <lo> <hi> ...      the nominal design point to centre
         -center -samples N [-lhs] [-seed s]
         -analysis "<cmd>"
         (-spec <metric> [-max HI] [-min LO])...   pass/fail limits, as in montecarlo
         [-method nm|pso|de|sa]
```

The outer optimizer searches the design knobs; at each candidate the inner loop runs
`N` Monte-Carlo samples (each `reset` re-samples the deck's `agauss`/`mccorr` process
variation around the current centre), evaluates every spec, and reduces to the
**worst-case Cpk** (the smooth objective the optimizer maximizes) and the pass-fraction
**yield** (reported). The design knobs feed the `agauss` centres.

Cpk is the objective because raw yield is a granular step function that stalls a
simplex, whereas Cpk is continuous and monotone in yield. A fixed inner seed gives
every candidate the same process draws (common random numbers); with `-lhs` the
stratified sample-mean is ≈ 0, so the optimum lands right on the analytic centre.
Results are published as `dcenter_yield` / `dcenter_cpk`.

## Example

```
optimize -dparam xc 4.0 3 7 -center -lhs -samples 120 -analysis op \
         -spec v(out) -max 6 -min 4 -seed 3
```

For an output ~ N(xc, 0.5) with spec [4, 6], this centres `xc` from an off-centre 4.0
to ≈ 5.00 (the midpoint), recovering the analytic Cpk = 1/(3·0.5) = 0.667.

## Verify

```
python3 verify_dcenter.py
```

Synthetic problems with known optimal centres: the optimizer finds the midpoint from
an off-centre start; the centred yield beats the off-centre start's (≈ 50% → ≈ 95%);
and two design params centre independently on their own spec windows.
