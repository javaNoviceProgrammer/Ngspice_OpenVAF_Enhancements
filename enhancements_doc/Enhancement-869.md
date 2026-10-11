# Enhancement-869: the false-convergence guard allows what a high gain makes of rounding — a linear amplifier of gain 1e12 went through gmin stepping

**Scope:** N1 of the
[Sparse and KLU correctness campaign of 2026-10-11](../docs/bug_hunts/2026-10-11_sparse-klu-correctness-campaign.md).

ngspice: `maths/ni/niiter.c`, the Enhancement-256 guard: a floor of `NI_GUARD_ROUND` times
(|G|s)ₖ on the row exemption Enhancement-568 gave it.

`examples/guardgain_examples/` (new). **ngspice only.**

**Suites:**
- [`guardgain_examples`](../examples/guardgain_examples/): 5 of 5 per solver. On the E-867
  binaries [1] and [3] fail under KLU (126 and 235 iterations); [4] and [5] are controls.
- `oprobust`, `linesearch`, `bsrcconv`, `explicitvalue`, `failacct` and `warmstart`, the
  guard's suites, pass under both solvers.
- The campaign's 300 high-gain networks: none needs more than 20 iterations.
- The full sweep: 573 of 573.

## What was wrong

```
vin in 0 0.1234567
r1 in neg 1k
r2 neg out 10k
e1 out 0 0 neg 1e12
rl out 0 2k
```

This inverting amplifier's answer was exact under both solvers, but under KLU it took 126
iterations of dynamic gmin stepping; at a gain of 1e11 it took 3.

The control voltage of `e1` is v(out)/A, about 1.2e-12 V. It is the difference of two terms of
0.11 V, so it is good to about ε × 0.1 V. The gain multiplies that into the branch row's
residual: 2.5e-5 in 2.5 of terms. The E-256 guard, which declines an operating point whose KCL
residual is large, exempted a row only below one part per million of its terms
([Enhancement-568](Enhancement-568.md)). So it declined the converged point, and
`CKTop` fell through to gmin stepping. Under Sparse the F1 follower did the same at 1e12 until
[Enhancement-867](Enhancement-867.md) made its solve accurate.

## The change

A row is also exempt while its residual is within 1024 ε of (|G|s)ₖ, where sⱼ is the largest
unknown of j's kind, volts or amperes. That is what the rounding of x does to the row: x_j is good
to ε times its kind's scale, not ε times itself. It is also the line below which
[Enhancement-868](Enhancement-868.md)'s refinement takes a row for rounding, so the guard and the
refinement agree on which rows carry only rounding.

At first the bound was 64 ε. Then a network of condition 1.4e12 stepped under Sparse, on a row
the refinement had rightly left alone as rounding. Its residual was 3.3e-9 against a guard bound
of 1.6e-9 and a rounding line of 2.5e-8. The bound is 2e-13 of a row's own scale. The
violations the guard is for are many decades above that: E-256's false point is 0.4 A on a 0.6 V
divider.

The inverter now takes 3 iterations at gains of 1e12, 1e13 and 1e15 under both solvers.
E-256's square-root source is still declined at its false point and reaches the same 0.178012 V,
to the bit.

## The checks

`guardgain_examples`:
- **[1]** The inverter at gains 1e12, 1e13 and 1e15: exact, in at most 5 iterations.
- **[2]** Its transient at a gain of 1e12: exact.
- **[3]** A dc sweep of the gain from 1e12 to 1e15: exact at every point, in at most 25
  iterations (235 under KLU on E-867).
- **[4]** (control) A gain of 1e9: 3 iterations, as before.
- **[5]** (control) The guard still declines E-256's false point: `B I=sqrt(v(n))` on a
  0.6 V / 1 Ω divider reaches v(n) = 0.17805 V, not 0.
