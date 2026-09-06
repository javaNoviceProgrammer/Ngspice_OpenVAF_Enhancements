# Enhancement-568: the operating point stops failing on four ordinary circuits — a guard scaled to its row, a `pwl` limiter that lets go at a corner, a `.nodeset` hold with a budget, and a damped-Newton last rung

**Scope:** operating-point robustness under both linear solvers, from a 29-deck OP
torture battery run under KLU and Sparse 1.3 (latches, Schmitt triggers, op-amps of
gain 1e6 to 1e9, diode strings and grids, a 400-node diode mesh, sub-threshold and
floating-gate MOSFETs, BSIM4 / HiCUM / PSP stages through OSDI, ideal-inductor loops,
far and wrong-state nodesets, negative-resistance latches). `src/maths/ni/niiter.c`,
`src/maths/KLU/klusmp.c`, `src/include/ngspice/smpdefs.h`,
`src/spicelib/analysis/cktop.c`, `src/xspice/icm/analog/pwl/cfunc.mod`. **ngspice only.**

**Suites:** new [`oprobust_examples`](../examples/oprobust_examples/) (32 checks per
solver, both solvers); [`linesearch_examples`](../examples/linesearch_examples/) has one
check reworded (its latch, see below); `bsrcconv` (E-256), `linesearch`, `trustregion`,
`convhelp`, `ptcont`, `solvercore`, `ctrlnode`, `netinit`, `guardsweep` pass; full sweep
467 of 467 on both solvers.

## The survey

Every deck of the battery converges under both solvers, and the two solvers agree on
every printed value. What the battery found is not disagreement but *cost*: four decks
that are ordinary circuits took hundreds to tens of thousands of iterations, or failed
outright, for reasons that have nothing to do with the circuits.

| deck | before (Sparse / KLU) | after |
|---|---|---|
| VCVS of gain 1e6 in unity feedback | 4 iterations / **127, through gmin stepping**; Sparse trips too from gain 1e8 | 3 iterations, both, up to gain 1e9 |
| 21 decades of conductance spread into a diode | 132, through gmin stepping | 4 |
| `E … TABLE` Schmitt trigger | **38 462 iterations across gmin, source stepping and optran, then failure**, both | 16, plain Newton |
| `.nodeset v(out)=100` on a 3 V diode clamp | 2160 / 1400, six "singular matrix" reports under KLU only, NaN in the abandoned solves | 229, both, no report |
| two behavioural voltage sources in a ring | **37 673 iterations, then failure**, both | 53 |

Three more decks cost 130 to 290 iterations and are left alone, because the cost is the
circuit's: a floating MOSFET gate (no DC path; the ladder ends in optran and the gate
takes whatever the source ramp couples into it — the six "singular matrix: check node g"
reports say exactly that), two ideal inductors in parallel (an undetermined current
split, resolved by optran), and a HiCUM stage biased through 10 MΩ (dynamic gmin,
131 iterations, the same on both solvers).

## What was wrong

**R1 — the false-convergence guard cancelled itself on a high-gain row.**
Enhancement-256's guard declines a converged point whose KCL residual is large,
measuring each row's residual against `abstol + reltol · |(G·x)_k|`. On the branch row
of a VCVS of gain 1e6, `(G·x)_k` is the difference of million-sized terms and is
*supposed* to be zero; on the KCL row of a node with no independent source it is the
residual *itself*. Either way the scale collapses to `abstol` and the solve's own
rounding reads as a violation: under KLU the branch row's 1e-10 of its terms, under
Sparse from gain 1e8 the output node's 2e-10 A in 2e-2 A of terms, one part in 1e8.
Newton had converged in 4 iterations; the guard sent CKTop into gmin stepping for 127
more (the two solvers round differently, which is the only reason they differed).
`linesearch` and `trustregion` bypass the guard, `abstol=1e-10` cleared it.

**R2 — the `pwl` code model's limiter locked into a two-cycle in positive feedback.**
`E … TABLE` and `G … TABLE` expand to an XSPICE `pwl` instance
(`input_domain=0.1 fraction=TRUE limit=TRUE`). Since 1991 that model limits its own
input to 30 % of a segment per Newton pass, so that Newton "sees every piece of the
table on its way", and forces a stop at each breakpoint. On a Schmitt trigger (gain
5000 between ±1 mV, ±5 V outside, the output fed back to the positive input) that walk
never ends: on the sloped piece Newton points toward the far clamp, on the flat piece
just past the corner it points back, and the limiter hands the input across the corner
0.6 mV at a time, for ever — a two-cycle at 1.0 mV / 1.6 mV, the same under gmin
stepping, source stepping and optran (none of them changes the loop's algebra), 38 462
iterations, then "could not be simulated". Both solvers, since the matrix is right; the
model's own limiter is the whole story. The E-153 trust region and E-111 line search
could not help either: the limiter sits inside the device load, below the solver's
step control.

Two things were noticed on the way. The Schmitt's *transient* fails at its switching
instant for a different reason — the deck as written has no capacitance, so at the fold
the +5 V state simply ceases to exist and there is no trajectory to integrate; with any
node capacitance (`.option cshunt=1p`) both the old and the new model switch at
±0.4485 V. And the first sighting of the failure was a misdirection: with the code
models not loaded (no `SPICE_LIB_DIR`), the `a` instance the expansion generates is
refused and Enhancement-492 then reports "controlling node `eamp_int1` does not exist" —
true, but a consequence, and the second message is the one the eye lands on.

**R3 — a `.nodeset` the circuit cannot satisfy ate the whole Newton budget.**
CKTload holds a nodeset node whose KCL row carries no branch current by *replacing* the
row with `v = nodeset` (the CIDER form, so that a numerical device's huge conductance
cannot override it). A diode from that node to a stiff 3 V source, asked to sit at
100 V, therefore has no equilibrium to settle to: `DEVpnjlim` lets the junction climb a
quarter volt per pass, the hold (`MODEINITFIX`) waits for the circuit to settle, and it
never does. After the 100 iterations of `itl1` the junction stands near 18 V, the
diode's `exp(vd/vte)` — unguarded, unlike the BJT's and the MOSFETs' — overflows, the
matrix holds infinities, and the two solvers part ways only in how they say so: KLU's
factor finds a NaN pivot and reports "singular matrix: check node vclamp#branch"
(six times, once per gmin attempt), Sparse's zero-pivot test passes a NaN and says
nothing. Both then finish the point through source stepping, 2160 and 1400 iterations
later, at the correct 1 V. A nodeset of 10 V cost 229 iterations the same way; 5 V
cost 52.

The diode's `exp()` was deliberately *not* clamped the way the BJT's and the MOSFETs' are.
It was tried: with the argument capped at `MAX_EXP_ARG` a junction driven that far puts a
finite 1e295 S into the matrix instead of an infinity, Newton's step at such a
conductance is too small to register, and the iterate is accepted as converged by the
voltage test with a KCL residual of 1e294 A — a diode of *negative* area, the
guaranteed-failure generator behind Enhancement-438's `sweep` test, went from "3 of 5
points did not converge" to five plausible-looking answers, 33 V among them. A NaN that
fails is better than a number that lies; the hold budget below keeps the junction far
from either.

**R4 — a loop of ideal voltage-defined branches has nothing the ladder can soften.**
Every rung of CKTop is a continuation: gmin stepping shunts the nodes, source stepping
scales the independent sources, pseudo-transient and optran add dynamics. Two
behavioural voltage sources feeding each other — `b1 q 0 v=f(v(qb))`,
`b2 qb 0 v=g(v(q))`, a `tanh` buffer and inverter in a ring with one solution at
(2.5 V, 2.5 V) — have no node a shunt can pull (the sources dictate both voltages), no
independent source to scale and no capacitor to integrate. Plain Newton visits the four
saturated corners in a four-cycle, each rung runs its full course on the same cycle,
and the point is abandoned after 37 673 iterations. `.option linesearch` finds it in 53.

## What changed

**R1.** `SMPmultiplyAbs()` (new, `klusmp.c`, both matrix forms) returns
`Σ_j |G_kj||x_j|`, the magnitude of the terms that make up row *k* — its term traffic.
The guard keeps E-256's scale and exempts a row only while its residual is below one
part per million of `Σ_j |G_kj||x_j| + |b_k|`: three decades finer than the `reltol`
voltage test can resolve, two above the worst rounding seen. A non-finite residual
still fires. Two other formulations were measured and rejected. Scaling the residual
by the term traffic itself stopped the guard declining a point it should: on the
`warmstart` suite's diode ladder the node below the source converges in voltage with a
residual that is 19 % of its net current, the extra Newton step the guard forces moves
the answer by 51 µV, and at default `reltol` twenty of four hundred samples sit within
that of the spec edge (213 → 193 in band). A floor of 1e4 machine epsilons on the
traffic kept the ladder but not Sparse at gain 1e8, whose rounding on the output node
is 1e-8 of the traffic, four decades above epsilon. With the parts-per-million
exemption the ladder is untouched, the VCVS converges in 3 iterations up to gain 1e9
under both solvers, the conductance-spread deck goes from 132 to 4, and E-256's own
suite still declines the points it was written for. The line-search and trust-region
merit are unchanged.

**R2.** Two rules in the `pwl` model's limiter. (1) When the previous input and
Newton's new one lie on the same linear piece of the smoothed curve — no corner region
between them — the model *is* the line Newton linearised, so the step is taken in full;
limiting there could only slow it. (2) The limiter counts the direction changes of its
limited steps since it last stood idle (a forced stop at a breakpoint splits one move
into two same-direction steps, so a change is counted against the last non-zero step);
after two changes it is fighting Newton, not guiding it, and Newton's value is accepted
in full until an evaluation needs no limiting — the first release lands on the flat
piece, the next carries the input across the high-gain region in one step, which is the
jump the crawl could never make. The streak resets at each new timepoint. The record
behind `STATIC_VAR(last_x_value)` grows from one double to a small struct; the callback's
`free()` is unchanged. The Schmitt converges in 16 plain iterations (13 with the line
search, 14 with the trust region); a TABLE op-amp in negative feedback, a seven-point
table in a loop, the transient thresholds and every suite that uses the model are
unchanged.

**R3.** `NIiter` gives the hold a budget: on a deck with nodesets, `MODEINITFIX` is
released after `max(10, itl1/10)` passes whether or not the circuit has settled — every legitimate
nodeset measured (a BJT flip-flop's state, a Schmitt's state, a 5 V nodeset on the
clamp) settles in 5 to 12 passes, and a hold that has not settled in ten is a nodeset
the circuit cannot satisfy. The 100 V nodeset now costs 229 iterations under both
solvers with no report; 10 V costs 82 and 5 V costs 50, all by plain Newton — released
after ten passes the junction stands near 3 V, twenty decades short of overflow. A deck
without nodesets is not subject to the budget: there `MODEINITFIX` is simply the phase in
which plain Newton runs its whole course and the released phase confirms the point, and
cutting it at ten passes moved the `warmstart` suite's diode ladder by one iteration's
worth, 51 µV, which at default `reltol` is twenty of four hundred samples across a spec
edge. The budget does apply, nodesets or not, when `.option linesearch` or
`.option trustregion` is on: both globalizations act only in the released phase, so on
a deck whose plain Newton cycles they never acted at all — the ring below under
`.option linesearch` ran its hundred iterations in the hold phase and was abandoned,
before this change as much as after it. With the budget the globalization the user
asked for takes over after ten passes.

One consequence is documented in `linesearch_examples`. Its bistable latch names two
B-source outputs in its `.nodeset`; a hold cannot move a voltage-defined node (the KCL
row keeps the branch current and the source dictates the voltage), and plain Newton on
that pair is a (5 V, 0 V) / (0 V, 5 V) two-cycle, so plain Newton never converged there.
Before, the hold phase swallowed the whole budget in that cycle — the line search acts
only in the released phase, so it never ran — and both the ON and the OFF run fell
through to gmin stepping's (0, 0) root. Now OFF still reaches (0, 0) through gmin
stepping, while ON finds the (2.5, 2.5) root nearest the nodeset by damped Newton. The
suite's identity check for that one deck becomes "each run lands on a root of the
latch"; result-neutrality is a property of points plain Newton converges to, and this was
never one.

**R4.** CKTop ends with one more rung: a damped-Newton solve (the E-111 line search)
from scratch, announced as `Starting damped Newton (line search)`, taken only after
gmin stepping, source stepping, pseudo-transient and optran have all failed and skipped
when the line search is already on. Because it runs last, no deck that converges today
can be handed a different root; only a point that would otherwise be abandoned reaches
it. The ring converges there in 53 iterations under both solvers.

## Verification

| check | result |
|---|---|
| VCVS of gain 1e6, 1e8, 1e9 in unity feedback; the 21-decade conductance spread | v(out) = 1 in 3 iterations, v(c) = −1 mV in 4, plain Newton, both solvers (were 127 gmin iterations under KLU at 1e6, Sparse from 1e8; 132 for the spread) |
| the `E … TABLE` Schmitt: default ladder, `linesearch`, `trustregion`, `noopiter`; the expansion written by hand with `input_domain` 0.01 and 0.5; vin = 0.3 with `.nodeset` ±4.9 | −4.946 V in 16 / 13 / 14 iterations by plain Newton, 38 under `noopiter`; 16 and 17; the nodeset picks the state in 8 and 13 (was 38 462 iterations and failure on every variant) |
| a TABLE op-amp in negative feedback; a seven-point table in a loop; the Schmitt transient with `cshunt=1p` | 0.69986 V in 3 iterations; 0.83333 / 0.66667 in 10; switches at −0.4485 / +0.4484 V — all unchanged |
| `.nodeset v(out)` = 100, 10, 5 on the 3 V diode clamp | 1 V in 229 (dynamic gmin), 82 and 50 (plain Newton) under both solvers, no "singular matrix", no NaN (were 2160 / 1400 with six reports under KLU; 229; 52) |
| a BJT flip-flop whose `.nodeset` selects the c1-high state | v(c1) = 4.6148 in 12 iterations, plain Newton, unchanged |
| the `tanh` buffer-inverter ring; the same with `.option linesearch`; the `tanh` bistable pair without a nodeset | (2.5003, 2.5001) through the announced last rung; the same point with the rung not repeated; (0, 0) in 3 plain iterations, unchanged (the ring was abandoned after 37 673 iterations) |
| the 29-deck battery under both solvers | every deck converges, every value identical across solvers; the four decks above are the only changes |
| `oprobust_examples`; `linesearch_examples`; `bsrcconv`, `trustregion`, `convhelp`, `ptcont`, `solvercore`, `ctrlnode`, `netinit`, `guardsweep` and the eleven suites that instantiate `pwl`; full sweep | 32 / 32 both solvers; 17 / 17; all pass; 467 of 467 |
