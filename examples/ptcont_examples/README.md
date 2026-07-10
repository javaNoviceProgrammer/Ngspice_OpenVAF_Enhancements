# Pseudo-transient continuation — Enhancement-127

`.option ptcont` adds a **pseudo-transient continuation** homotopy to the DC
operating-point solve — the "principled `Ẋ`-embedded continuation" that ngspice's
convergence cascade otherwise lacked (it had static gmin stepping, source stepping,
and a transient-op fallback, but not this).

## What it does

The DC problem `f(x) = 0` is embedded in a fictitious backward-Euler pseudo-transient

```
f(x) + Gps·(x − x_prev) = 0,   Gps = Cps / dτ,
```

and the pseudo-timestep `dτ` is marched from small (`Gps` large — strongly damped
and well-conditioned) to large (`Gps → 0` — the true DC operating point). Each step
is a Newton solve of the augmented system: the `Gps` diagonal is added at
factorization time (the same mechanism as gmin stepping), and the `Gps·x_prev`
coupling is added to the right-hand side inside the Newton loop. That coupling is
the key difference from static gmin stepping — it makes every step a move along a
**stable trajectory** from the previous point, so the solve tracks the operating
curve instead of jumping. A switched-evolution-relaxation rule grows `dτ` when a
step converges easily and shrinks it (backtracking) when a step fails.

It is **off by default** and, like any convergence aid, **result-neutral**: when the
standard solve already converges, the answer is identical.

## `ptcont_demo.cir`

A behavioral exponential with **no** junction limiting — a deliberately stiff
nonlinearity:

```
B1 1 0 I = 1e-14 * (exp(V(1)/0.026) - 1)
R1 2 1 100
V1 2 0 100
```

From `V = 0`, plain Newton overshoots the enormous `exp` derivative and settles on a
**spurious** root (`V(1) ≈ 70.5 V`), whereas pseudo-transient continuation follows
the stable trajectory to the **physically correct** operating point

```
V(1) = 0.837922 V   (the root of 1e-14·(exp(V/0.026)−1) = (100−V)/100).
```

gmin and source stepping are disabled in the demo (`gminsteps=0 srcsteps=0`) so the
result depends on the pseudo-transient homotopy alone.

## Verification

`verify_ptcont.py` (run under **both** KLU and Sparse1.3) checks:

1. `.option ptcont` is accepted;
2. **result-neutrality** — on a battery of normal nonlinear circuits (diode, BJT,
   two-diode divider, resistor network) the operating point with `ptcont` on is
   identical to a normal run;
3. **convergence power** — on the stiff circuit, `ptcont` reaches the correct DC
   `0.837922 V` (matched to the analytic value), differing from the spurious
   `70.5 V` plain Newton returns.
