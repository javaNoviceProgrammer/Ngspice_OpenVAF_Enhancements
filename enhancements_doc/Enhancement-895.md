# Enhancement-895: the device tests ask no more than the solve resolves — at `reltol=1e-9` E-889 ended a Gummel–Poon stage's transient "Timestep too small" at 0.78 ps

**Scope:** F1 of the
[analyses correctness campaign of 2026-10-16](../docs/bug_hunts/2026-10-16_ngspice-openvaf-r-analyses-correctness-campaign.md),
a regression of [E-889](Enhancement-889.md).

ngspice:
- `maths/ni/niconv.c`: what the device tests count as no move.
- `osdi/osdiload.c`: `OSDIconvTest`'s row tolerance.
- `include/ngspice/cktdefs.h`: `CKTconvScale`.

**ngspice only.**

**Suites:**
- [`convtest_examples`](../examples/convtest_examples/): checks [10] to [12] are new, 12 of 12 per
  solver. On the E-894 binaries [10] fails under both solvers.
- `warmstart`, `failacct`, `linesearch`, `bsrcconv` and `oprobust` pass. These are the suites
  that move when Newton's phases or its guard change.
- The full sweep: 591 of 591.

## What was wrong

E-889 made the device convergence tests decide. They see the new solution, with every unknown that
moved by no more than its rounding held at the load point, so that the solve's noise is not taken
for Newton's step. That rounding was 64 ε of the unknown's own value. The solve does not resolve a
node that finely. Its error is rounding at the scale of the whole circuit's volts (the scale
[E-869](Enhancement-869.md)'s guard already uses), not of the node's own value. At ordinary
tolerances the difference hides under reltol. At `reltol=1e-9` it did not.

**A Gummel–Poon common-emitter stage**, from the campaign's Family A (seed 2):
- 5.8 V supply, `reltol=1e-9 abstol=1e-15 vntol=1e-12`.
- The emitter sits at 20 mV, and it moved 1.55e-15 V each iteration: 350 of its own ulps, but
  rounding at the circuit's 5.8 V.
- At t = 50 fs the base current's conductance holds the capacitive companion C/h, 38 S. That made
  the move 16 times the base current's tolerance.
- Newton never converged, and the step shrank until the run ended "Timestep too small": at 0.78 ps
  under KLU, at 0.057 ps under Sparse.
- E-888 ran it to the end, 209 ns in 53 008 points.

**A compiled VBIC 1.3 stage's operating point** (seed 4), the corpus model built with openvaf-r.
Three of its rows failed:
- **The internal base node** bounced 6e-14 V through `rbx`'s 0.1 S. That is below the deck's
  `vntol` of 1e-12 V, so the node test called it no step.
- **The thermal row** was judged against the user's `abstol` of 1e-15. That is a current, and the
  row is a power, in watts.
- **The internal collector** is tied to two other nodes by 1000 S. A common step of 1e-10 V left
  1e-12 A of rounding in the differences, against a tolerance of 4.5e-13 A.

On macOS under KLU, E-894 found the operating point only through dynamic gmin stepping: 1,359
iterations, against E-888's 71 without an aid. Under Sparse every build needs the aid. E-888 takes
1,913 iterations and E-894 2,758.

Plain Newton on this deck is path-dependent, though, and the operating point is a poor test of the
change:
- With the deck's element values perturbed by 1e-15 to 1e-9 of themselves, E-888 itself needs
  gmin stepping in 3 of 80 runs (40 decks, both solvers), even at `itl1=1000`.
- With a `.nodeset` at the solution, E-894 converges without an aid too, in 8 to 348 iterations.
- The first CI run of this change found linux-arm's E-895 taking the aid under KLU, where macOS
  does not.

## The change

**`NIconvTest`**: an unknown has not moved when it moved by no more than the larger of:
- the absolute tolerance the node test grants it: `vntol` for a voltage, `abstol` for a current,
  or its nature's `abstol` unless the user set the option;
- 64 ε of the largest unknown of its kind (voltages or currents) in the solution.

A step the node test calls no step cannot be asked to move a current by less. What the device
tests exist for is many decades above both floors: a junction moving 26 mV between two 100 V
nodes.

**`OSDIconvTest`**:
- A residual whose nature differs from the terminals' keeps its nature's `abstol`. The user's
  `abstol` is a current, so it overrides only rows of the terminals' nature. A thermal row's
  tolerance is 1e-9 W in the standard disciplines.
- A row's predicted change ΔI = Σ J·Δx is granted the rounding of the terms it sums:
  64 ε · Σ|J_rj|·s_j. Here s_j is the largest of x_j, its load point and the largest unknown of
  j's kind. Nodes that move together through large conductances leave the rounding of their
  differences behind.

`NIconvTest` hands `OSDIconvTest` the two kind scales in `CKTconvScale`, beside the load point in
`CKTconvLoaded`.

## The checks

`convtest_examples`, new:
- **[10]** The Gummel–Poon stage at `reltol=1e-9` runs its transient to the end. E-894: "Timestep
  too small" at 0.78 ps (KLU) or 0.057 ps (Sparse).
- **[11]** The VBIC stage finds its operating point at E-888's value, 3.2037005189 V. Only the
  value is asked, and the route is reported: whether plain Newton gets there depends on the
  rounding (above). E-894 passes it, through gmin stepping.
- **[12]** A control: [1]'s diode between two 100 V nodes still converges off at `reltol=1e-9`.
  A junction that moves by more than `vntol` is still a step to the device tests.

E-889's checks [1] to [9] pass unchanged.

With the change:
- Seed 2 runs to 209 ns in E-888's 53 008 points.
- The VBIC converges in 71 iterations on macOS under KLU, E-888's count, to E-888's value. Under
  Sparse it takes 1,913, E-888's count. Across the 80 perturbed runs E-895 matches E-888's route
  in 79, and in the 80th both need gmin stepping.

## Cost

Fewer iterations, never more:
- **Family A** of the previous campaign, 500 networks built-in and Verilog-A, against E-894 under
  either solver: every network still solves, with no residual verdict. 27 runs take fewer
  iterations, none more. The built-in total goes from 6,672 to 6,652, the Verilog-A total from
  6,328 to 6,316.
- **The benchmark suite's transients**, run ten times longer, against E-894:
  - the diode rectifier and the RC ladder: unchanged iterations, points and waveforms;
  - the built-in BSIM4 ring oscillator: 5.7 % fewer iterations and 4 % less time;
  - the Verilog-A BSIM4 ring oscillator: 0.5 % fewer iterations.

  The rings' frequencies against a `reltol=1e-6` run: built-in 4.7e-4 off (E-894 4.4e-4, E-888
  5.1e-4), Verilog-A 4.9e-4 (E-894 5.0e-4).

## Limits

The absolute floor is the node test's own `vntol`. With `reltol` tightened and `vntol` left at its
default of 1 µV, the device tests now accept a junction step of up to 1 µV, which moves its
current by up to 4e-5 of itself. That is the step the node test accepts too, so set `vntol` along
with `reltol`. The new checks do: `vntol=1e-12`.
