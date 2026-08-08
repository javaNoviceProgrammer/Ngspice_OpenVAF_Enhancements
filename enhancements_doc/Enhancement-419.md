# Enhancement-419 — three integration methods, and what measuring them showed

ngspice shipped two integration methods: trapezoidal (the default) and
Gear/BDF at orders 1–6. This adds three more — `trbdf2`, `sdirk` and `adams` —
and, just as usefully, measures all five against each other so the choice is
made on numbers rather than reputation. Two of the numbers overturned what I
expected, and both are recorded below rather than quietly dropped.

## What was missing

Trapezoidal is A-stable but **not L-stable**: its amplification factor tends to
−1 as `h·λ → −∞`, so at a sharp transition it rings. ngspice's only answers were
`xmu < 0.5`, which slides toward backward Euler and costs an order, or
`method=gear`, which is L-stable but less accurate at equal order — you pay for
the fix everywhere, not just where the ringing was.

## The one interface everything hinges on

`NIintegrate` is the single funnel: every reactive element becomes

```
geq = ag[0]·C        ceq = state0[ccap] − ag[0]·q_n
```

No device knows which method is running, and there are 86 `CKTag` call sites
across 41 device directories. So an implicit method is coefficient work in one
file — and an explicit one is impossible here, which is item 4.

### `method=trbdf2`

A one-step **composite**: trapezoidal over `[t, t+γh]`, then BDF2 across `t`,
`t+γh`, `t+h`. With **γ = 2−√2** both sub-steps share the leading coefficient

```
2/(γh) == (2−γ)/((1−γ)h) == 3.4142135…/h
```

— the root of `γ²−4γ+2` — so the Jacobian scaling does not change between
stages. Order 2 and **L-stable**.

Neither sub-step needed a new formula. Stage 1 is exactly the existing
trapezoidal order-2 rule at `δ = γh`; stage 2 is the Gear order-2 shape with
unequal-step BDF2 coefficients (`h₁=(1−γ)h`, `h₂=γh`), which sum to zero so a
constant charge integrates to exactly zero current. Stage 2 needs both earlier
charges at once, so the state slots are **rotated once mid-step** — the same
rotation `dctran` already performs on acceptance — and the interior slot is
spliced back out afterwards, so the accepted history that `CKTterr` and `NIpred`
see never contains the stage value. It is genuinely self-starting: stage 2 reads
only `state1` and `state2`, both produced by this step, so it never needs the
order-1 starter that Enhancement-181 showed imposes an O(h²) floor.

### `method=sdirk`

Alexander's 3-stage, order-3, L-stable SDIRK, restricted to **stiffly accurate**
tableaux (`a[s][j] == b[j]`, so `c[s] == 1`). That restriction is what lets
Runge–Kutta fit ngspice at all: without it a step ends in a weighted
*combination* of stage values, and every value a device holds has to come out of
a solve, not an assignment. With it, the last stage **is** the answer.

Coefficients are **derived from γ in code**, not written as literals: a mistyped
Butcher digit does not crash, it quietly costs an order of convergence.

Fully implicit RK (Radau IIA, Gauss–Legendre) is out of scope — coupled stages
need one `s·n × s·n` system, and ngspice builds one `n×n` circuit matrix per
solve.

### `method=adams`

Adams–Moulton of order `maxord`. The weights are **derived per step from the
actual spacing**, by integrating the Lagrange basis through the current
timepoint and the `k−1` before it, in normalised coordinates `τ=(t−t_{n+1})/h`.
The textbook `(5,8,−1)/12` are fixed-step, and ngspice never takes fixed steps;
normalising also keeps the Vandermonde entries O(1), where raw seconds would be
~1e−10 raised to the k-th power — the underflow the Gear branch warns about in
its own comment.

**Not stiffly stable above order 2.** The Adams stability region shrinks with
order instead of opening to the left half-plane, which is why SPICE
standardised on Gear. AM3+ is here to be measured and for genuinely non-stiff
circuits.

## The error constants are derived, and the derivation is checked

For a Runge–Kutta method `R(z) = 1 + Σ zᵏ⁺¹·bᵀAᵏe`, so the order-*p* constant is
`C = bᵀAᵖe − 1/(p+1)!`. That formula reproduces the two constants **already in
`cktterr.c`** exactly — 1/12 for trapezoidal and 1/2 for backward Euler — which
is what makes it safe to trust on tableaux nobody has tabulated here.

| method | was | derived | effect |
| --- | --- | --- | --- |
| TR-BDF2 | 1/12 borrowed from trapezoidal | **0.0404401** | trapezoidal overstated its error 2.06× |
| SDIRK | 3/22 borrowed from Gear-3 | **0.0258971** | Gear-3 overstated it 5.27× |

TR-BDF2's derived constant predicts a 2.06× per-step accuracy advantage over
trapezoidal; the fixed-step test independently **measures 2.02×**. Alexander's
tableau satisfies all three order conditions exactly (1, 1/2, 1/6), which
independently confirms the SDIRK implementation without running a simulation.

## What the measurements actually showed

### Accuracy per step — the new methods win

RC step, order pinned, error away from the startup ramp:

| h | trap | gear | trbdf2 | sdirk |
| --- | --- | --- | --- | --- |
| 2.0e−7 | 3.96e−04 | 1.61e−03 | 1.96e−04 | **1.98e−05** |
| 2.5e−8 | 1.66e−05 | 6.68e−05 | 8.08e−06 | **1.26e−07** |
| observed order | 1.80 | 1.80 | 1.80 | **2.76** |

All three second-order methods land on 1.80 and SDIRK on 2.76 — both ~0.2 under
their asymptote from the same step non-uniformity, which is the consistency
check that the measurement is real.

### Accuracy per Newton iteration — trapezoidal wins

Timepoints are the wrong cost unit: TR-BDF2 solves twice per step and SDIRK
three times. Measured with `rusage traniter`, and compared at **matched
iteration count** along each method's own curve (so the comparison does not
depend on `trtol` being calibrated alike):

| circuit | winner | runner-up |
| --- | --- | --- |
| rc_step @181 it | **trap 6.75e−05** | adams3 2.29e−04 |
| stiff_2scale @312 it | **trap 3.35e−05** | gear 9.92e−05 |
| diode_clamp @2791 it | **gear 2.65e−03** | adams3 9.93e−03 |
| rlc_ring @12799 it | **adams3 3.20e−04** | sdirk 1.19e−02 |

Trapezoidal or Gear wins three of four. **Adams-3 wins the oscillatory
non-stiff case by ~100×**, exactly where Adams theory says it should and where
BDF's damping hurts most — though it is catastrophic at loose tolerance
(1.3e+08 at its loosest), so it wants a guard rail.

Recalibrating the constants barely moved this table, which is itself the
finding: the (cost, error) curve belongs to the method, and a wrong constant
costs predictability of the `trtol` knob, not efficiency.

### So the case for TR-BDF2 is L-stability, and only that

A 1 ns edge arriving while the step is pinned at 20 µs = 20·τ:

| method | settles in | max \|v−1\| after the edge | sign alternations |
| --- | --- | --- | --- |
| trapezoidal | never — still ringing 200 µs later | 9.09e−02 | **25** |
| gear | ~4 steps | 6.98e−02 | 4 |
| **trbdf2** | **2 steps** | **4.53e−03** | 7, all ≤1e−6 |

Trapezoidal's measured ratio is **−0.8182** = exactly the theoretical
`(1−h/2τ)/(1+h/2τ) = −9/11`, so the test is measuring the mechanism it claims
to. None of the smooth-circuit cost metrics can see this property.

**Recommendation, stated plainly: none of the three should become the default.**
All are opt-in. TR-BDF2 is worth having because it is the only answer to
trapezoidal ringing that does not cost an order or accuracy everywhere; Adams-3
is worth having for oscillatory non-stiff circuits; SDIRK has the best accuracy
per step and no case on cost.

## Two corrections to earlier claims in this work

* I reported that trapezoidal and Gear **hit an accuracy floor** the new methods
  could pass. That was wrong — an artefact of sweeping `trtol` only down to 0.5.
  At `trtol=1e-4` trapezoidal reaches 1.1e−05 on rc_step, not the 2.7e−03
  "floor". The ceiling was in the harness.
* `verify_syntaxhl.py` was named as the likely source of twelve orphaned ngspice
  processes because it runs a bare `[NGSPICE]` matching their argv. It tests
  clean; the attribution was wrong. (The failure mode is fixed regardless, in
  the preceding commit.)

## Item 4: the explicit family is NOT here, and why

Forward Euler, Adams–Bashforth and explicit RK were in scope and are not
implemented. This is an obstacle, not unfinished effort:

An explicit method cannot be stamped into the simultaneous MNA system. With
`ag[0]=0` a reactive element becomes a fixed current source, which *looks* like
an explicit stamp; a series RC with constant `Vin` then returns
**`v_{n+1} = v_n`** — the solution never moves. The general reason: at Newton
convergence a reactive element's current **is** `state0[ccap]` whatever `ag[0]`
is, so `ag[0]` only sets the Newton derivative. Charge is a dependent quantity
`q(v)`; prescribing it means prescribing `v`, which a conductance-plus-current
stamp cannot do.

Also ruled out: stamping `q*` from a spare state slot (resistive elements still
stamp, giving a blend, not FE); one Newton iteration of backward Euler (for a
linear circuit that lands *exactly* on the BE solution — fully implicit); and
penalty scaling `ag[0]=1/(hε)` (measures the regulariser).

What remains is a separate marching path: recover the reactive matrix `C` alone
(two loads per step, `ag0=1` minus `ag0=0`), advance the charge explicitly, and
recover `v` by solving against `C` with the structurally `0=0` algebraic rows
regularised — a new solve path across both Sparse and KLU, ending in a method
that is stability-limited into uselessness on stiff netlists.

## Verification

* **`examples/integmethod_examples` 13/13, both solvers.** Every check is one
  that would catch a silent error: AM2 byte-identical to `trap`; the ringing
  ratio asserted as a *number*; SDIRK's order separated from the second-order
  pair; and trapezoidal pinned as a control that is still off where the others
  have settled.
* **OSDI is checked explicitly.** OSDI loads its Jacobian with `ckt->CKTag[0]`
  alone, while TR-BDF2's stage 2 and Adams order ≥3 need `ag[1]`/`ag[2]`. Had
  OSDI bypassed `NIintegrate` the new methods would have been silently wrong for
  Verilog-A devices while looking healthy on built-in R/L/C. It does not, and
  all five methods agree to **0.0e+00** between SPARSE and KLU on an OSDI device.
* **Full regression 336/336**, both solvers. The default path is untouched:
  `trap` and `gear` are unchanged in every respect.

## Found by

Asked to add these methods, and answered partly by measuring them. Three harness
bugs had to be beaten first, each of which produced a confident wrong table:
the step was never pinned (needs `ordfix`); a `pulse` source plants a breakpoint
that floods `t≈0` and cuts the step, so a stiff transition cannot be excited
with one; and `delta` starts at ~1e−10 and grows ~1.5× per step, so it reaches a
large `tmax` pin only well into the run. The last is general: **you cannot
excite a stiff transient early in an ngspice run, because the step controller
has not grown yet.**
