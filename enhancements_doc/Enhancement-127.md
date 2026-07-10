# Enhancement-127 — pseudo-transient continuation

A convergence-robustness enhancement: `.option ptcont` adds a **pseudo-transient
continuation** (PTC) homotopy to the DC operating-point solve. ngspice's convergence
cascade already had static gmin stepping, source stepping, and a transient-op
fallback; the "principled `Ẋ`-embedded continuation" flagged as the remaining gap
(alongside the globalized Newton line search that [E-111](Enhancement-111.md) added)
is what this fills.

## The method

The DC problem `f(x) = 0` is embedded in a fictitious backward-Euler pseudo-transient

```
f(x) + Gps·(x − x_prev) = 0,   Gps = Cps / dτ,
```

which is one implicit step of `Cps·ẋ = −f(x)` in a *pseudo*-time `τ`. Marching the
pseudo-timestep `dτ` from small (`Gps` large — the system is diagonally dominant,
strongly damped, trivially solvable) to large (`Gps → 0` — the pseudo-term vanishes
and the equation becomes the true `f(x) = 0`) relaxes the solution to the DC
operating point along a **stable trajectory**.

Each pseudo-step is an ordinary Newton solve of the augmented system, reusing
ngspice's existing machinery:

- the **`Gps` diagonal** is added at factorization time through the same path gmin
  stepping uses (`CKTdiagGmin`, applied by `LoadGmin` / the KLU diagonal load), so it
  works under both linear solvers;
- the **`Gps·x_prev` coupling** is added to the right-hand side inside `NIiter`, right
  after the load. This is the essential difference from static gmin stepping: without
  it the step is a memoryless gmin-shunted solve; with it the step is a genuine
  backward-Euler move from the previous point, so the iterate follows the operating
  curve rather than jumping to a distant (possibly spurious) root.

A switched-evolution-relaxation rule adapts `dτ`: grow it (aggressively when the step
converged in few iterations) after a successful step, shrink it and backtrack to the
last good point after a failed step. A final solve at `Gps = 0` polishes the exact
DC answer. The driver sits in `CKTop` as another cascade fallback, gated on
`.option ptcont`; it is off by default.

## Verification

A behavioral exponential with **no** junction limiting — a deliberately stiff
nonlinearity where plain Newton misbehaves:

```
B1 1 0 I = 1e-14 * (exp(V(1)/0.026) - 1)
R1 2 1 100
V1 2 0 100
```

From `V = 0`, plain Newton overshoots the enormous `exp` derivative and settles on a
**spurious** root, `V(1) ≈ 70.5 V`. Pseudo-transient continuation follows the stable
trajectory to the **physically correct** operating point,

```
V(1) = 0.837922 V   (the root of 1e-14·(exp(V/0.026) − 1) = (100 − V)/100),
```

matching the analytic value. `verify_ptcont.py`, run under **both** KLU and
Sparse1.3, checks three things:

1. `.option ptcont` is accepted;
2. **result-neutrality** — on a battery of normal nonlinear circuits (diode, BJT,
   two-diode divider, resistor network) the operating point with `ptcont` on is
   identical to a normal run (a convergence aid must never change the answer);
3. **convergence power** — on the stiff circuit `ptcont` reaches `0.837922 V` (matched
   to the analytic root), differing from the spurious `70.5 V` plain Newton returns.

All 21 checks pass under both solvers.

## Files changed

| File | Change |
|---|---|
| `ngspice-46/src/include/ngspice/optdefs.h`, `tskdefs.h`, `cktdefs.h` | `OPT_PTCONT` / `TSKptcont` / `CKTptcont` + `CKTpseudoGmin`, `CKTpseudoPrev` |
| `ngspice-46/src/spicelib/analysis/cktsopt.c`, `cktntask.c`, `cktdojob.c` | wire `.option ptcont` through the task → circuit (off by default) |
| `ngspice-46/src/spicelib/analysis/cktop.c` | `pseudo_transient` homotopy driver + its slot in the `CKTop` convergence cascade |
| `ngspice-46/src/maths/ni/niiter.c` | add the `Gps·x_prev` coupling to the RHS after the load |
| `ngspice-46/src/spicelib/analysis/cktdest.c` | free `CKTpseudoPrev` |
| `examples/ptcont_examples/` | `ptcont_demo.cir`, `verify_ptcont.py`, `README.md` |

## Scope

PTC is a general DC-convergence aid, verified result-neutral and shown to converge a
stiff circuit that plain Newton fails. It composes with the existing cascade (it can
be a fallback after gmin/source stepping, or the sole homotopy when those are
disabled) and works under both linear solvers. Automatic triggering heuristics (when
to reach for PTC without the user asking) and coupling it into the `errpreset`
robustness presets are natural follow-ups.
