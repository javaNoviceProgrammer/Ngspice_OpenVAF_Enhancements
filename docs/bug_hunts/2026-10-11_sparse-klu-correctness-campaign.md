# Bug hunt — a correctness campaign on the Sparse and KLU solvers

**When:** 2026-10-11, after the [third robustness campaign](2026-10-10_ngspice-openvaf-r-third-robustness-campaign.md)
was folded and released (E-856 to E-866).
**Binary:** the repo's `ngspice-46/build/src/ngspice` at E-866, tree at `ad656b18`, KLU and XSPICE
compiled in.

**Method:** the two solver-core hunts ([2026-09-06](2026-09-06_klu-sparse-solver-cores.md),
[2026-09-25](2026-09-25_klu-sparse-solver-cores-second-hunt.md)) and the third campaign's ac,
pz, tf and sens families found the cores exact on ac and on most dc. This campaign aimed at
what they had not measured. One target was the real (dc and transient) solve, which has no
refinement step; E-860 gave one to ac. Another was the pivot order a sweep reuses, which
Sparse refactors with a test for exact zeros only. A third was row scaling, which KLU does by
default and Sparse never does. The analyses that solve with the same factors were covered too.
Every deck ran under `.option sparse` and `.option klu`, one simulation at a time under a 12 GB
RSS cap, through throwaway harnesses in the session scratchpad (`rc4/*.py`). The references
share no code with ngspice: an exact MNA solve over Python `Fraction`s for dc, and numpy
complex MNA for ac, noise, `sp` and sensitivities.

- **A. Dc sweeps of a resistance.** 1 000 random networks of R (15 % negative), V, I, L (a dc
  short) and E, F, G, H sources. One resistor is swept over 4 to 12 decades, up or down. Each
  of 13 380 points is checked against the exact solve. A second run of 300 networks repeats
  every sweep value as a fresh `op` after `alter`.
- **B. Scale invariance.** 300 networks with every resistance and transresistance scaled by
  1e-9 to 1e12, and currents and transconductances by its inverse. The node voltages must not
  change: 3 600 operating points.
- **C. High gains.** 300 networks with VCVS and CCVS gains of 1e6 to 1e12, VCCS of 1e2 to 1e6 S,
  and CCCS of 1e4 to 1e9. The operating point is checked against the exact solve. Then a
  follower and an inverting amplifier at gains of 1e3 to 1e15: op, transient and ac.
- **D. Noise, the adjoint solve.** 300 random R/C/L/K networks with controlled sources, and 300
  inductor-heavy ones at 0.1 to 10 Hz: 7 954 points against Σ 4kT/R |y_a − y_b|², with
  Aᵀy = e_out.
- **E. `sp`.** Two-port S-parameters of 655 networks against (Z − G*)(Z + G)⁻¹ in power waves:
  equal 50 Ω ports, unequal ports (10 Ω to 1 kΩ), and the inductor-heavy family. 10 556 points
  in all.
- **F. Ac sensitivities.** `sens v(out) ac` for every R, C, L and gain of 350 networks:
  48 930 values against the exact derivative.
- **G. Targeted decks.** The two solvers' options (`pivrel`, `pivtol`, `klu_scale`, `klu_btf`,
  `klu_ordering`) on the families above. Ammeter decks in dc, ac and transient, the load
  stepped by a switch or a time-varying resistor. Nonlinear sweeps (diode, BJT, NMOS) against
  fresh operating points at reltol 1e-9. `pivrel=1` timed on resistor meshes.

Nothing was fixed; this is the list.

| | Finding | Severity |
|---|---|---|
| [F1](#f1) | *(fixed in [E-867](../../enhancements_doc/Enhancement-867.md): the real solve refines its answer where the residual says so, as the ac solve does since E-860; the follower is exact at every gain, in 3 iterations)* **dc and transient accuracy, Sparse:** a unity follower built from a high-gain VCVS, with a 0 V source in its feedback path, loses digits in proportion to the gain. At a gain of 1e9 the transient is 2.2e-7 off; at 1e12 the op is 1.8e-5 high after 126 iterations of gmin stepping and the transient 2.4e-4 off; at 1e15 the transient is 25 % off. KLU is exact to 3e-16 at every gain, in 3 iterations. Of 300 random high-gain networks, 20 are wrong under Sparse where KLU is right (worst: a 3.5 mV node 12 % off), and 1 the other way round | high |
| [F2](#f2) | *(fixed in [E-867](../../enhancements_doc/Enhancement-867.md): the same refinement; the ammeter reads 0.6217/R to 1.7e-9 from either end)* **dc sweep accuracy, Sparse:** a dc sweep of a resistance reuses the pivot order chosen at its first point, and Sparse's refactor tests only for an exactly zero pivot. Five elements and an ammeter: sweeping the load from 0.1 Ω to 40 MΩ, the ammeter reads up to 0.5 % wrong; starting the sweep at 10 kΩ, or solving any of those values as an `op`, gives 1e-9. KLU is exact | medium |
| [F3](#f3) | *(fixed in [E-867](../../enhancements_doc/Enhancement-867.md) and [E-868](../../enhancements_doc/Enhancement-868.md): the refinement measures every row that carries more than rounding; the teraohm deck, seed 365 and seed 187 are exact under both solvers)* **dc accuracy, Sparse:** where a node is held only through teraohm resistors, or a small current flows beside large ones, Sparse loses digits that KLU keeps. Teraohm dead ends beside a VCVS read 0.56 mV low on 1.56 V; a 1.4e-11 A ammeter reading next to 70 A is 40 % off. The residual is 2e-17 A: Sparse never scales a row, and KLU's default row scaling makes the difference | medium |
| [F4](#f4) | **sensitivity, both solvers:** `sens … ac` gives the derivative with respect to an inductor coupled by a `K` element with its mutual inductance held fixed. `alter` moves M = k√(L1L2) with L1, so the two disagree: on a transformer `sens` gives 2528 − 977j and `alter` 5087 + 9448j. Every other parameter of 350 networks is right to 2.3e-7 | medium |
| [N1](#n1) | *(fixed in [E-869](../../enhancements_doc/Enhancement-869.md): the guard also allows 1024 ε of a row's own scale, the line below which the refinement takes a row for rounding; the inverter takes 3 iterations up to a gain of 1e15)* **convergence cost:** a linear amplifier with a gain of 1e12 goes through dynamic gmin stepping, 126 iterations instead of 3, because the E-256 guard reads the amplified rounding of its input as a KCL violation. An inverter under KLU, the F1 follower under Sparse; 17 of the 300 high-gain networks under Sparse and 2 under KLU. E-568 measured this up to a gain of 1e9 | low |
| [D1](#d1) | **diagnostic:** with `pivrel=1` Sparse's whole-matrix pivot search accepts nothing, so its fallback is recorded as a small pivot. With `pivtol` set or under `set ngdebug`, E-736 then reports "the pivot for node 4 … is 3370.9, below pivtol (1e-13)" | low |

<a id="f1"></a>
## F1 — a high-gain loop through a 0 V source loses digits under Sparse

*Fixed in [E-867](../../enhancements_doc/Enhancement-867.md). After each solve but the junction
guess's, the residual gives the backward error, row by row over the rows that carry more than
rounding ([E-868](../../enhancements_doc/Enhancement-868.md) settled which those are). Where it
is above rounding, A d = r is solved with the same factors. The follower is exact to
3e-16 at every gain up to 1e15, op and transient, in 3 iterations. Of the 300 high-gain networks,
Sparse is wrong in 5, all of condition 7e16 or more; it was 25. Networks needing gmin stepping
under Sparse: 17, now 3.*

```
* unity follower: a VCVS of gain A, a 0 V source (an ammeter) in the feedback path
vin in 0 dc 1.234567 ac 1 sin(1.234567 0.5 1k)
e1 out 0 in neg 1e12
vfb out neg 0
rl out 0 1k
.option sparse
.control
op
print v(out)                      $ exact: 1.234567 * A/(1+A)
tran 10u 1m
.endc
.end
```

The worst relative error of `v(out)`:

| gain A | op, Sparse | Newton iterations | transient, Sparse | KLU, op and transient |
|---|---|---|---|---|
| 1e6 | 8.1e-11 | 3 | 2.2e-10 | ≤ 3e-16, 3 iterations |
| 1e9 | 1.1e-7 | 3 | 2.2e-7 | ≤ 3e-16 |
| 1e10 | | | 1.6e-6 | ≤ 3e-16 |
| 1e11 | | | 2.6e-5 | ≤ 3e-16 |
| 1e12 | 1.8e-5 | 126 (gmin stepping) | 2.4e-4 | ≤ 3e-16 |
| 1e15 | −1.2e-2 | 126 | 2.5e-1 | ≤ 3e-16 |

The error is about A times the rounding of a double. There is no warning. Without `vfb`, the
feedback wired straight back (`e1 out 0 in out A`), both solvers are exact at every gain. An
inverting amplifier is exact under both at gains up to 1e12 too. The ac of the follower is
exact under both, since E-860's refinement fixes it.

A VCVS of gain 1e6 to 1e12 is the usual ideal op-amp, and a 0 V source in a loop is how a deck
reads a current or feeds an H or F source. On 300 random networks with high gains (C), 20 are
wrong by more than 1e-6 under Sparse on a value KLU gets to 1e-9. Values below 1e-9 of the
largest of their kind are left out of that count. The worst is a 3.5 mV node 11.8 % off
(seed 134), then 7.2 % (seed 193). Only one network is wrong under KLU where Sparse is right.
It is seed 56, 5e-6 off on values of 2e9 V and 1e15 A, after gmin stepping.

`.option pivrel=1` makes the follower exact under Sparse, in 3 iterations; `pivrel=0.1` and
`pivtol=1e-20` change nothing. The gain sits in the `e1` branch row beside entries of 1. Sparse
compares magnitudes across rows as they are loaded, so the order it chooses at a high gain is
poor. In a dc sweep of the gain (`dc @e1[gain]`) from 1 upward, every point is exact. Sweeping
down from 1e9, the first point is 1.1e-7 off. KLU divides each row by its largest entry before
it pivots (`klu_scale`, on by default). Refinement with a componentwise residual, as E-860 does
for ac, would also catch it: the residual is large against that row's own terms.

<a id="f2"></a>
## F2 — a dc sweep of a resistance reuses a stale pivot order under Sparse

*Fixed in [E-867](../../enhancements_doc/Enhancement-867.md), by F1's refinement. The order is
still reused; the residual catches what it costs. The ammeter reads 0.6217/R to 1.7e-9, started
at 0.1 Ω or 100 Ω, and seed 239's sensor to 1.4e-9. No network of family A now disagrees with a
fresh `op` beyond rounding.*

```
* the reduced deck: an ammeter, with a 1.4 ohm resistor across it, feeds the swept load
v1 2 0 0.6217
l1 2 3 1u
rsh 3 1 1.4
vam 3 1 0
rl 1 0 1
r8 3 0 24
.option sparse
.control
dc rl 0.1 5e7 1e7
print i(vam)                      $ exact: 0.6217 / R
.endc
.end
```

| R (Ω) | 0.1 | 1e7 | 2e7 | 3e7 | 4e7 |
|---|---|---|---|---|---|
| `i(vam)`, relative error, Sparse | 0 | 2.3e-4 | 5.0e-4 | 1.6e-3 | 5.1e-3 |
| the same, KLU | 1e-16 | 8e-10 | 1e-9 | 2e-9 | 4e-10 |

Started at 100 Ω, the Sparse sweep is 3.7e-5 to 2.8e-3 off. Started at 10 kΩ, 100 kΩ or 10 MΩ it
is within 1.4e-9. A one-point sweep or an `op` at any of those values is right. The answer
depends on where the sweep began.

`NIiter` orders the matrix at `MODEINITJCT`, the sweep's first point, and refactors with that
order at every later point. Sparse's `spFactor` reuses it and stops only on a pivot of exactly
zero. When the swept element moves the pivots by eight decades, the old order's growth goes
unnoticed. `klusmp.c`'s comment on the KLU refactor guard says the opposite: "SPARSE's refactor
tests every reused pivot against its column (spSMALL_PIVOT)". It does not. KLU has the E-439 and
F1 rcond tests on its refactor, and its default row scaling. On this deck neither KLU test fires;
its order is simply good at both ends.

Across family A, 3 of 300 networks disagree under Sparse by more than 1e-6 between a sweep point
and a fresh `op` at the same value, on a quantity that is not at rounding level. The worst is
seed 239, a sensor current of 1.8e-8 A 8 % off, where the fresh `op` is right to 9e-8. Under
KLU none do. With `klu_scale=none`, KLU shows it once (seed 47, 4e-6); `klu_btf=off` and
`klu_ordering=colamd` show nothing. The natural nonlinear sweeps of G agree with fresh
operating points to 1e-9 under both solvers. So do the transients whose load steps by nine
decades through a switch or a time-varying resistor; a B-source's stamps are not a resistor's.
The reuse that matters is the dc sweep of an element value: a resistance, or `@dev[param]`.

<a id="f3"></a>
## F3 — high-impedance nodes and small currents beside large ones, under Sparse

*Fixed in [E-867](../../enhancements_doc/Enhancement-867.md) and
[E-868](../../enhancements_doc/Enhancement-868.md). E-867's refinement made the teraohm deck below
exact, seed 30 at a scale of 1e9 within 7.5e-13, and seed 365's 1.4e-11 A sensor within 2.4e-16.
It measured each row against the largest current of the circuit, though, so seed 187's sensor
row (6e-8 A beside 4e5 A) read as rounding and stayed 1.5e-3 off. Since E-868 a row counts
unless its own terms are at rounding, and seed 187's sensor is within 1.3e-15 under Sparse and
1.1e-15 under KLU (1e-7 before).*

```
* teraohm dead ends beside a VCVS: every node is exactly v(1)
v1 1 0 1.5623065557674634
l15 1 2 1u
r9 2 6 72.58T
r14 2 4 24.29T
r11 3 4 6.532T
l16 3 5 1u
e19 1 7 7 4 -3370.9
.option sparse
.control
op
print v(3) v(4) v(7)
.endc
.end
```

Under Sparse `v(3)`, `v(4)`, `v(5)` and `v(7)` are 1.561742 V, 0.56 mV below the 1.562307 V of
every other node: 3.6e-4. Under KLU every node is 1.562306555767. The KCL residual of the Sparse
answer at node 4 is 2.3e-17 A, so its backward error measured against the whole matrix is at
rounding. Against that row's own terms, about 3e-13 A, it is of order 1e-4. This deck is the
reduction of seed 30 of the scale family (B), whose voltages were exact at every scale except
1e9: there Sparse was 5.5e-4 off and KLU 2e-16. `pivrel=0.1` and `pivrel=1` restore the full
network; on the reduced deck `pivrel=0.1` does not.

The same mechanism shows on currents. In seed 365 of family A, a 0 V sensor carries
1.36e-11 A while 70 A flows through a 13 mΩ resistor. Sparse gives 8.2e-12 A, 40 % off, at a
fresh order; KLU gives it to 1e-16. Beyond rounding-level quantities, the fresh operating
points of A's 300 networks have 2 networks wrong under Sparse (1.4e-6 and 1.6e-6) and none
under KLU.

An electrometer input, a sample-and-hold, a leakage path or a gate node is held through
teraohms, and its voltage is what such a deck is for. KLU's row scaling is the difference. A
refinement step measured componentwise, as for F1, would catch it too.

<a id="f4"></a>
## F4 — `sens … ac` holds a coupled inductor's mutual inductance fixed

```
* coupled inductors: d v(3) / d L1 from sens and from alter
v1 1 0 dc 0 ac 1
r1 1 2 50
l1 2 0 10u
l2 3 0 40u
k1 l1 l2 0.9
r2 3 0 200
.control
sens v(3) ac lin 1 100k 100k
print l1                          $ 2527.59 - 977.073j
ac lin 1 100k 100k
alter l1 = 10.00001u
ac lin 1 100k 100k
let dl1 = (v(3) - ac1.v(3)) / 1e-11
print dl1                         $ 5086.58 + 9447.94j
.endc
.end
```

The exact derivative with M = k√(L1L2) following L1 is 5086.58 + 9447.94j; with M held at its
nominal value it is 2527.59 − 977.07j. `sens` gives the second, `alter` the first. The deck
names k, not M, so holding M is not the derivative the user asked for. It differs in magnitude
by a factor of 4 and in the sign of its imaginary part. Every flag of family F (288 values
under each solver) is an inductor coupled by a `K`. Every other R, C, L and gain is within
2.3e-7, normalized, of the exact derivative. Dc sensitivities are unaffected, since an inductor
is a short at dc.

<a id="n1"></a>
## N1 — a high-gain linear amplifier falls into gmin stepping

*Fixed in [E-869](../../enhancements_doc/Enhancement-869.md). A row is also exempt while its
residual is within 1024 ε of (|G|s)ₖ, sⱼ the largest unknown of j's kind: what x's rounding makes
of the row, and the line below which E-868's refinement takes a row for rounding. The inverter
takes 3 iterations at gains of 1e12, 1e13 and 1e15 under both solvers. E-256's square-root
source is still declined at its false point. Of the campaign's 300 high-gain networks, none needs
more than 20 iterations under either solver.*

```
* inverting amplifier, gain -10, VCVS open-loop gain 1e12
vin in 0 0.1234567
r1 in neg 1k
r2 neg out 10k
e1 out 0 0 neg 1e12
rl out 0 2k
.option klu
.control
op
rusage totiter                    $ 126; 3 under Sparse, 3 under KLU up to a gain of 1e11
.endc
.end
```

The answer is exact, after dynamic gmin stepping. With `.option linesearch`, which skips the
E-256 guard, it takes 3 iterations. With a gain of A, the control voltage of `e1` is of order
v(out)/A, and its rounding, about 1e-16 of the circuit's volts, is multiplied by A in the branch
row's residual. Between gains of 1e11 and 1e12 that passes E-568's exemption of one part per
million of the row's terms, so the guard declines a converged point. The F1 follower under
Sparse does the same at 1e12, and there gmin stepping ends on the wrong answer. Of the 300
networks of C, 17 needed more than 20 iterations under Sparse and 2 under KLU, up to 126.

<a id="d1"></a>
## D1 — `pivrel=1` is reported as a small pivot

`SearchEntireMatrix` accepts an element only if `Magnitude > RelThreshold * LargestInCol`.
With `pivrel=1` the inequality is strict, so no element is accepted, and the search falls back
to the largest element of the reduced matrix. E-736 records that fallback as a pivot below
`pivtol`. On F3's seed 30 with `set ngdebug`:

```
Warning: the pivot for node 4 (from the equation of node e19#branch) is 3370.9, below pivtol (1e-13)
```

The pivot chosen is the right one, and the cost is nil: the diagonal searches run first and
succeed on a 60 × 60 resistor mesh, whose op takes the same 0.07 s at `pivrel=1`. Only the
message is wrong, and it appears only with `pivtol` set or under `set ngdebug`.

## Not defects

- **A sweep's last value is reached by repeated addition.** Swept from 6.7e8 Ω down to 0.075 Ω
  in six steps, the last point lands on 0.07477909 Ω, not the 0.07477903 Ω that start + 6 ×
  step gives in one rounding. Both solvers solve the value they print, so it is the same
  `i(v18)` at 7.8e-7 from the other.
- **Rounding on nodes held at 0 V.** Where a node is tied to ground by sources and inductors,
  Sparse prints 1e-16 V to 1e-20 V and KLU 0. These dominate any per-unknown relative measure
  and are not errors.

## Verified clean

- **D, noise:** 7 954 points within half of the 1e-9 × condition bound of the exact adjoint,
  under both solvers, the inductor-heavy networks included. The adjoint solve has no refinement step, but these
  networks did not need one.
- **E, `sp`:** 10 556 points within a quarter of the 1e-9 × condition bound under both solvers,
  with equal and unequal port impedances; the power-wave definition matches.
- **F, ac sensitivities:** 48 930 values within 2.3e-7 of the exact derivative, normalized (the
  inductor-heavy family within 1e-6), apart from F4 and one output that is identically 0.
- **Ac with a stale order:** the F2 ammeter with an inductive load whose admittance falls twelve
  decades across `ac dec 2 1m 1g` is within 4e-14 under both solvers. Since E-860 the ac path
  refines its answer.
- **B, scale invariance under KLU:** every voltage of 300 networks at every scale from 1e-9 to
  1e12 is within 8.3e-10 of the largest; Sparse is too, except seed 30 at 1e9 (F3).
- **Nonlinear dc sweeps:** a diode clamp, a BJT stage and an NMOS stage, each with an ammeter,
  swept through cutoff. Every point equals a fresh `op` to 1e-9 at reltol 1e-9, under both
  solvers.
- **Transient load steps:** the F2 ammeter whose load switches from 0.1 Ω to 100 MΩ, or rises
  nine decades through `r = '…time…'`, is within 3e-9 under both solvers.
- **KLU options on A:** `klu_btf=off` and `klu_ordering=colamd` change nothing; `klu_scale=none`
  is F2's one case.

The harnesses are in the session scratchpad, `rc4/`: `mna.py` (the generator and the exact
Fraction solve), `stale.py`, `sf.py` and `xs.py` (A), `scale.py` (B), `hg.py` (C), `noise.py` (D),
`sp.py` (E), `acsens.py` (F), the reducers `reduce*.py`, and the decks of `m1/`.
