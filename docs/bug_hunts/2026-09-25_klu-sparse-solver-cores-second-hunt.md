# KLU and Sparse solver cores — the second hunt

**Date:** 2026-09-25, 20:20–21:25 · **Commit under test:** `2b2b09db` (E-733) · **Binary:**
locally built `ngspice-46/build/src/ngspice` (20:15; KLU and XSPICE compiled in, CIDER not) ·
**Solver selection:** `.option sparse` / `.option klu`, every deck run under both ·
**Method:** the glue (`klusmp.c` end to end after the E-566 family), the Newton driver
(`niiter.c`), the AC and distortion drivers, Sparse's ordering, factor and solve
(`spfactor.c`, `spsolve.c`, `spbuild.c`), KLU's refactor, scale and rcond kernels, and the
operating-point ladder (`cktop.c`, `optran.c`) read first; then eight harnesses of small decks
(`sv/harnA.py` … `harnH.py` in the session scratchpad, some 260 runs) whose answers are
checked against an **exact rational reference** (Python `fractions`, real and complex MNA),
against each other across the two solvers, and against the dense eigenvalue pole-zero.
No fixes were applied; every deck is inline.

The first solver hunt ([2026-09-06](2026-09-06_klu-sparse-solver-cores.md), fixed as
E-566 to E-571) covered the node-collapse family, the RHS sizing, the complex rebinding
and the reused complex pivot order. This one went underneath and beside it: the numerical
core against exact answers, pivot reuse across events, the thresholds, the determinant path,
size and repetition, OSDI patterns under setup reuse, and what the operating-point ladder
leaves behind in the solver.

**Result: the linear cores are exact.** Ladders over twelve decades with negative
resistances, random 150-edge networks, controlled sources with gains of 1e6 and 1e-9, an
RLC ladder over eighteen decades at eight frequencies, a switch event that changes the matrix
by twelve decades mid-transient — both solvers reproduce the exact reference to rounding
(1e-8 at worst on values of 1e-64), agree with each other to 1e-13 on a stiff transient, and
every KLU ordering/scaling/BTF combination does the same. What the hunt found is around the
cores: **one wrong-answer defect in the operating-point ladder that both solvers inherit, one
solver-dependent verdict on an unsolvable netlist, one dead option, one order-dependent
pole-zero, and a quadratic ordering cost.**

| # | finding | severity |
|---|---|---|
| [F1](#f1--source-stepping-leaves-the-diagonal-gmin-armed-every-later-solve-in-the-job-carries-a-gmin-shunt-on-every-node) | *(fixed in [E-734](../../enhancements_doc/Enhancement-734.md): the diagonal gmin is put back at source stepping's exit)* after source stepping — succeeded or failed — `CKTdiagGmin` stays at `gmin`; the transient operating point, every transient time point and every DC sweep point that follow are solved with a 1e-12 S shunt on every diagonal. A 1e11 Ω divider beside a diode clamp reads 0.476 V instead of 0.500 V through the transient; a 1e14 Ω node beside a singular loop reads 990 V instead of 100 kV. Both solvers, no message | **high** — wrong answers on high-impedance nodes, silent |
| [F2](#f2--an-unsolvable-loop-of-voltage-sources-succeeds-under-sparse-with-1gmin-amperes-and-fails-under-klu) | *(its symptom closed by [E-734](../../enhancements_doc/Enhancement-734.md): the loop is refused under Sparse too; the branch-row mechanism stays)* a KVL-inconsistent loop of three voltage sources ends in "Transient op finished successfully" with 1e12 A circulating under Sparse; under KLU the same deck fails. F1's leaked gmin lands, under Sparse alone, on the branch-row diagonals that pivoting created; KLU adds gmin only to stamped diagonals | **medium** — a spurious operating point; the two solvers disagree on whether a netlist is solvable |
| [F3](#f3--pivtol-is-inert-under-both-solvers) | `.option pivtol` never rejects a pivot: ngspice's `spmatrix.h` maps Sparse's `spSMALL_PIVOT` to `OK`, so `SearchEntireMatrix`'s fallback to the largest element is reported as success; KLU ignores the value by construction. A matrix of 1e-14 S pivots solves under `pivtol=1e-3` with no word. E-475 validates an option that does nothing | **medium-low** — the manual promises a minimum pivot that is not enforced |
| [F4](#f4--pole-zero-finds-two-three-four-or-five-poles-on-the-same-stage-depending-on-the-solver-its-knobs-and-the-decks-line-order) | Muller's `pz` on a common-emitter stage returns 2 poles under KLU (default), 3 with `klu_btf=off`, 5 with `klu_scale=sum` or `colamd`, 5 under Sparse — and 5 under KLU too once three deck lines are moved; on the linearised stage Sparse gives up with 3 and KLU finds 5; `.option pzeig` gives the same 4 finite poles under both | **medium** — incomplete pole lists, with only a "giving up" warning |
| [N1](#n1--sparses-ordering-is-quadratic-in-the-node-count) | *(fixed in [E-735](../../enhancements_doc/Enhancement-735.md): the lists stay in a layout the ordering never walks through and the scan is a bucket index; same pivots, same factors; the 300 × 300 mesh reorders in 9 s)* Sparse's Markowitz ordering costs 1.5 s at 10k nodes, 17–37 s at 40k and 226 s at 90k on a 2-D resistor mesh (94 % of the run is "matrix reorder time"; equal or random values alike); KLU takes 1.8 s at 90k | low — known character, now measured |

Four diagnostic slips and the smaller notes are at the end.

## What was read and run

* `klusmp.c` after E-566: the conversion, `SMPsizeHint`/`SMPmarkOccupied`, every factor,
  refactor, reorder and solve entry with the E-439/E-499/F7 rcond guards, `SMPgetError` with
  E-570's zero-line search, `SMPfindElt`, `SMPcAddCol`, `SMPmultiply`/`SMPmultiplyAbs`,
  `spDeterminant_KLU`. Confirmed clean by reading: the E-256 merit multiply runs before
  factorization (Sparse factors in place); `SMPzeroRow` has no KLU branch but also no caller;
  every `SMPcSolve` caller (AC, distortion, eigenvalue, sensitivity) factors complex first.
* `niiter.c` in full (the reorder decisions, the E-111/153/256/568 blocks), `nireinit.c`,
  `niaciter.c`, `niditer.c`; `spfactor.c`'s `spOrderAndFactor`, `spFactor`, the pivot
  searches and the singular exits; `spsolve.c`; `spbuild.c`'s translation, growth and
  `spEnsureNode`; `klu_refactor.c`'s zero-pivot test, `klu_scale.c` (an empty row scales
  by 1), `klu_diagnostics.c`'s rcond, `klu_kernel.c`'s threshold pivoting; `cktsetup.c`'s
  reservation block; `cktop.c`'s six rungs and `optran.c`.
* Harness A: 40-node ladders over 12 decades (positive, 30 % negative), 30-node random
  networks, controlled sources, a 12-section RLC ladder at 8 frequencies, the 2026-09-06 F7
  ladder's transient — all against the exact reference or across solvers. B: eleven singular
  and pathological topologies. C: ladders to 300k nodes, meshes to 90k, 5000-fold repetition
  with `destroy all`, solver switching mid-session, 300-point sweeps with and without setup
  reuse. D: the 12-combination KLU knob grid and the pivot thresholds against the reference.
  E: an OSDI module whose internal node collapses on a parameter, swept across the collapse
  under reuse; a 20-internal-node module with conductances over 18 decades, linear and
  nonlinear. F: a 20-node wide-range ladder with a switch that changes one branch by twelve
  decades mid-transient, the end state against the exact DC of the new topology. G:
  sensitivity (DC and AC), noise, pole-zero, `tf`, distortion, a fifteen-decade AC and a
  stiff switched transient on a BJT stage, across solvers. H: the dense pole-zero, denormal
  pivots, the loop under every ladder setting, an inductor across a source, a cutset of
  current sources.

## F1 — source stepping leaves the diagonal gmin armed: every later solve in the job carries a gmin shunt on every node

```spice
* a diode clamp with a 10 Gohm bias network, and a 100 Gohm divider beside it
.option noopiter gminsteps=0
V1 in 0 5
R1 in a 1e10
R2 a 0 1e10
D1 a 0 dm
.model dm d(is=1e-15)
Vs s 0 1
Rs s z 1e11
Rz z 0 1e11
.control
op
print v(a) v(z)
tran 1u 10u
print v(z)[5]
.endc
.end
```

The options only force the ladder onto its source-stepping rung ("Source stepping
completed", twice — once for the `op`, once for the transient's operating point). The
divider's node `z` is 0.5 V by inspection.

| | `op`: v(z) | `tran`: v(z) at 5 µs |
|---|---|---|
| Sparse, plain | 0.5000 | 0.5000 |
| Sparse, after source stepping | 0.5000 | **0.4762** |
| KLU, plain | 0.5000 | 0.5000 |
| KLU, after source stepping | 0.5000 | **0.4762** |

0.4762 is exactly 0.5 × 2e-11 / (2e-11 + 1e-12): node `z` is carrying a 1e-12 S shunt to
ground through the whole transient. The operating point itself is right because it is the
last converged step inside the rung; everything solved after the rung returns is wrong.
Nothing is printed.

The same shunt is what makes the singular decks of F2 "succeed", and it is visible there
without forcing anything: an inductor across an ideal source (`V1 a 0 1`, `L1 a 0 1u`, a
divider on `a`) plus the 1e14 Ω node `I9 0 z 1n`, `R9 z 0 1e14` gives, under both solvers,
`v(z) = 990.099` at the operating point, through a transient, and at every point of a
`dc I9 1n 2n 1n` sweep (990 and 1980 V), where the node alone reads 1e5 V. With
`.option gmin=1e-10` it reads 9.999 V: the shunt is `gmin`, whatever gmin is.

**Root cause.** `gillespie_src` (`cktop.c:755-946`, the default source stepping) ends its
loop with (line 917)

```c
        ckt->CKTdiagGmin = ckt->CKTgmin = gminstart;
```

on every exit, success or failure. Every other rung restores `CKTdiagGmin` to `CKTgshunt`
(0 by default) when it is done — `dynamic_gmin` at `:526`, `spice3_gmin` at `:598`,
`new_gmin` at `:807/:822`, `pseudo_transient` at `:378` — and `NIiter` factors with
`trGmin = ckt->CKTdiagGmin` (`niiter.c:113`) on every call, `LoadGmin`/`LoadGmin_CSC` adding
it to every diagonal the matrix has. Nothing between jobs resets the field (`grep` finds it
set only in `cktop.c`), so a transient's time points, a DC sweep's later points, the
`optran` rung that runs after a failed source stepping, and the plain Newton of the *next*
job all start from a circuit with gmin on every node. The AC path already knows: E-571's
comment in `acan.c:501-503` reads "the ladder leaves CKTdiagGmin at gmin and optran solves
with it" and holds its own zero rows to match — it worked around the leak instead of
closing it.

Who meets this: any deck whose operating point needs source stepping — the ordinary reason
being a hard nonlinear circuit at its first `tran` — and has a node above a few hundred
megohms: electrometer front ends, gate-bias networks, `1e12` pull-ups, sensor models.
1e-12 S against a 1e9 Ω node is a 0.1 % error, against 1e11 Ω it is 10 %.

**Fix direction.** Restore `CKTdiagGmin = CKTgshunt` at `gillespie_src`'s exit, as its
siblings do (`CKTgmin` still goes back to `gminstart`). Then re-run the E-566/E-571
suites (`solvercore`, `dcpath`): the "node nothing conducts to reads I/gmin"
expectation must come from E-575's explicit `dcpath` stamp, not from this leak — with the
leak closed, a floating node whose ladder failed is singular in `optran`, which is the
honest verdict E-566 asked for.

*Fixed in [E-734](../../enhancements_doc/Enhancement-734.md).* `gillespie_src` exits with `CKTdiagGmin = CKTgshunt`
like every other rung. The divider reads 0.5 V through the transient and the sweep, the
1e14 Ω node 1e5 V, and the loop is refused on both solvers. Five suites had pinned the
leaked point itself and move with it: a floating node under `dcpath=off` is refused (it
was never held by anything but the leak), the rejected HiSIM-SOI's noise aborts cleanly
after a refused operating point, and the OSDI open gate's transient-op point moves by
0.7 mV. The E-566 warning printed on the no-hold path now says nothing holds the node,
and a `.tf` card naming a phantom node is refused before the operating point (its
refusal had been reached only because the leak let the point "succeed").

## F2 — an unsolvable loop of voltage sources "succeeds" under Sparse with 1/gmin amperes, and fails under KLU

```spice
* three voltage sources in a loop whose voltages do not sum to zero
V1 a b 1
V2 b c 1
V3 c a -1
R1 a 0 1k
.control
op
print v(a) v(b) v(c) i(v1)
.endc
.end
```

Kirchhoff's voltage law is violated by 1 V around the loop: the deck has no solution.

| | Sparse | KLU |
|---|---|---|
| plain Newton, dynamic gmin, true gmin, source stepping | `singular matrix: check node v1#branch` × 6, every rung fails | `check node v3#branch` × 6, every rung fails |
| transient op (`optran`) | **"Transient op finished successfully"**: v(a) = −2000, v(b) = −2000, v(c) = −2001, **i(v1) = 1.0000e12 A** | "Transient op failed, timestep too small"; the op is abandoned |
| `.option gmin=1e-10` | i(v1) = 1.0000e10 A | fails |
| `.option gmin=1e-6` | i(v1) = 1.004e6 A | fails |
| `.option srcsteps=0` or `gmin=0` | fails | fails |

The circulating current is exactly the KVL mismatch over gmin: 1 V / 1e-12 S. The
consistent loop (`V3 c a -2`, sum zero, rank deficient) is the same story with an arbitrary
3.0003 A under Sparse and a failure under KLU. With `set ngdebug` the Sparse run shows
*dynamic gmin succeeding at every rung down to 1e-12* on a matrix that is singular by
construction, and source stepping's inner gmin ladder doing the same.

**Root cause.** Two things meet. F1's `CKTdiagGmin` is left at `gmin` once source stepping
has run (with `srcsteps=0` the deck fails, with `gminsteps=0` it still "succeeds"). And under
Sparse the diagonal that receives it exists on the *branch rows*: Sparse's
`ExchangeRowsAndCols` creates a missing diagonal element during pivoting
(`spcFindElementInCol(..., YES)`, `spfactor.c:2068-2077`), so after the first singular
factorization the voltage-source branch rows own a `Diag[]` entry, and `LoadGmin`
(`klusmp.c:2329`) adds gmin to every non-NULL `Diag[I]` — turning `v(a) − v(b) = 1` into
`v(a) − v(b) + gmin·i = 1`, a 1e-12 Ω series resistance that makes the loop "solvable" with
1e12 A. KLU's `LoadGmin_CSC` adds gmin only to `KLUmatrixDiag[]`, which
`SMPconvertCOOtoCSC` fills from *stamped* diagonal entries; a branch row has none, the loop
stays singular, and KLU reports the truth. So whether gmin stepping regularises a branch
equation depends on the solver and on the pivot history — the same deck gets two verdicts.

**Fix direction.** F1's reset removes the value. Independently, the two solvers should agree
on *where* diagonal gmin goes: the KLU rule (stamped diagonals only) is the sane one, and
Sparse can follow it by recording the diagonals that exist before the first factorization
and having `LoadGmin` add only to those.

*Symptom closed by [E-734](../../enhancements_doc/Enhancement-734.md).* With the leak gone the loop is refused under Sparse as
under KLU. The branch-row diagonals that pivoting creates still receive the diagonal gmin
during the gmin ladder's own rungs, so the two solvers still differ in what a rung
regularises; that part stays open.

## F3 — `pivtol` is inert under both solvers

```spice
* every conductance is 1e-14 S; every pivot is 1e11 below the threshold
.option pivtol=1e-3
I1 0 a 1p
R1 a 0 1e14
R2 a b 1e14
R3 b 0 1e14
R4 b c 1e14
R5 c 0 1e14
.control
set ngdebug
op
print v(a) v(c)
.endc
.end
```

Both solvers print `v(a) = 62.5`, `v(c) = 12.5` (the exact answer) and nothing else —
with `pivtol=1e-3`, `pivtol=1e-3 pivrel=1`, on a 1×1 matrix (`I1 0 a 1p`, `R1 a 0 1e14`
alone), on the 40-node ladder with `pivtol=1` whose columns hold 1e-10 S, and in a
transient. The option's value reaches the solver (`cktdojob.c:272`,
`SMPreorder(..., CKTpivotAbsTol, ...)`, `spOrderAndFactor(..., AbsThreshold, ...)`) and
the searches test it (`spfactor.c:1128-1178`, `:1333`, `:1517`, `:1657`, `:1795`); what
happens when every candidate fails the test is

```c
    Matrix->Error = spSMALL_PIVOT;
    return pLargestElement;              /* SearchEntireMatrix, spfactor.c:1830 */
```

and `include/ngspice/spmatrix.h:89` reads `#define spSMALL_PIVOT OK`. The factorization
continues on the largest element it could find and returns success; no caller can see that
the threshold was crossed. KLU's `SMPluFac`/`SMPreorder` begin with `NG_IGNORE (PivTol)`
and pass only `pivrel` into `Common->tol`. So the option the manual describes as "the
minimum acceptable pivot" has no effect on either solver, and E-475's validation
("a pivot magnitude must be positive to mean anything") guards a value nothing reads.
(`pivrel` does act: it steers the choice among candidates, and KLU's `tol`; with nothing
passing, the fallback is the same.)

**Fix direction.** Decide what `pivtol` should mean. If it is to be a floor, map
`spSMALL_PIVOT` to a distinct code, let `SMPreorder` turn it into `E_SINGULAR` with a
"pivot below pivtol" line, and have KLU compare `Common->rcond`-style pivots against it
after a full factorization. If it is to stay a Sparse-internal preference, say so in the
option's documentation and print a note when a deck sets it.

## F4 — pole-zero finds two, three, four or five poles on the same stage depending on the solver, its knobs, and the deck's line order

```spice
* ce
Vcc vcc 0 12
Vin in 0 dc 0.7 ac 1
Rs in b 1k
Rb1 vcc b 100k
Rb2 b 0 22k
Q1 c b e qm
.model qm npn(bf=150 is=1e-15 cje=2p cjc=1p tf=0.3n rb=50)
Rc vcc c 4.7k
Re e 0 1k
Ce e 0 100u
Cc c out 10u
Rl out 0 100k
Cs out 0 1p
Lp c c2 1n
Rp c2 0 1e9
.control
pz in 0 out 0 vol pz
print all
.endc
.end
```

| run | poles reported |
|---|---|
| Sparse | −1e18 (the "infinite" marker), −5.9265e8, −5.7693e7, −53.963, −0.95511 |
| KLU, default (`amd`, `max`, BTF on) | **−53.963, −0.95511** — "iteration limit reached; giving up after 218 trials" |
| KLU, `klu_btf=off` or `klu_scale=none` | −5.7693e7, −53.963, −0.95511 — gives up after 239/245 |
| KLU, `klu_scale=sum`, or `klu_ordering=colamd`, or `klu_btf=off klu_scale=none` | the five Sparse reports |
| KLU, `pivrel=1` or `1e-6` | the same two as the default |
| KLU default, the deck with `Lp`, `Rp`, `Cs` moved to the top | the five |
| `pz … cur pz` (current output) instead of `vol` | five under both |
| `.option pzeig` (dense eigenvalues, E-171's alternative) | −5.9265e8, −5.7693e7, −53.963, −0.95511 under both |
| the BJT replaced by its linear model (`Rbb 50`, `Rpi 3.9k`, `Cpi 20p`, `Cmu 1p`, `Gm 0.038`, `Ro 100k`) | Sparse: 3 and "giving up after 227 trials"; KLU: 5 |

The four finite poles are real (`pzeig` and three independent Muller runs agree on them);
the missing ones are always the far ones. The determinant that Muller's iteration searches
is mathematically the same for every ordering, but its rounding near a far root is not: the
matrix at s ≈ −6e8 spans 1e-9 S to 6e4 S (`Ce`), and which pivots absorb the cancellation
depends on the elimination order and the row scaling — `spDeterminant_KLU` multiplies
`Udiag[k]·Rs[k]` in whatever order KLU chose. `cktpzstr.c` gives up at `NITER_LIM = 200`
trials or three "aberrations", and there is no second attempt with a different order. The
2026-09-06 hunt's F7 was the same sensitivity on the AC path, where a re-pivot could be
forced by an rcond test; here there is no reference factorization to compare against.

**Fix direction.** When Muller gives up with fewer roots than the previous attempt found (or
than `pzeig` reports for a matrix under its size limit), retry once under a different
setting — `klu_scale=sum` and `colamd` both rescued this stage — or fall through to `pzeig`
and say so. At the least, the "giving up" warning should say how many roots it has and that
`.option pzeig` exists.

## N1 — Sparse's ordering is quadratic in the node count

| deck | unknowns | Sparse | of which reorder | KLU | fill-in Sparse / KLU |
|---|---:|---:|---:|---:|---|
| ladder, 300 000 nodes | 300 001 | 0.34 s | — | 0.71 s | 0 / 0 |
| mesh 100 × 100 | 10 001 | 1.5 s | | 0.1 s | 3.70e5 / 3.53e5 |
| mesh 200 × 200 | 40 001 | 17.8 s (37 s in a busier run) | 16.5 s | 0.6 s | 2.09e6 / 1.92e6 |
| mesh 300 × 300 | 90 001 | 225.8 s | | 1.8 s | 5.87e6 / 5.32e6 |

The fill-in is comparable, so it is not the elimination: `rusage` puts 94 % of the 200 × 200
run in "matrix reorder time", and the equal-valued and random-valued meshes cost the same
(16.5 s against 16.3 s), so it is not the tie-breaking either. Sparse 1.3's `SearchDiagonal`
scans every remaining diagonal for the smallest Markowitz product at every step, which is
O(n) per pivot and O(n²) in all; the measured 1.5 → 17 → 226 s over 10k → 40k → 90k is
n^2.3. Chain-like circuits are unaffected (the 300k ladder above). This is the character the
solver notes already describe for OSDI-heavy decks; the numbers here are for the plain
resistor mesh, with no device evaluation in the way.

*Fixed in [E-735](../../enhancements_doc/Enhancement-735.md).* The scan was not the cost:
a sampler put 83 % of the run in the row and column exchanges and 11 % in fill-in creation.
Sparse keeps its lists sorted by internal row and column, an interchange renumbers rows or
columns, and moving the pivot to position `Step` walked, for every element of the two rows
and then of the two columns, its column from the top to find the predecessor and on to the
other position — through the entries of rows and columns eliminated long ago and through
the active part; every fill-in walked its column and its row from the start (4.5e8, 8.5e8
and 6.2e8 hops on the 200 × 200 mesh, against 1.4e8 arithmetic operations; the scan 8.0e8,
sequential and cheap). The ordering now keeps the lists in a layout in which finished
entries are never moved (they carry their external number and are relabelled once at the
end), the active part of a column is sorted by a key that travels with the row, an
interchange only relabels, a fill-in is spliced at a known place, and the Markowitz scan is
a bucket index that finds exactly the diagonal the scan found. The same pivots, fill-ins,
operations and final lists come out (86 matrices dumped bit for bit with the old and the new
code; the 122 Sparse decks here print the same numbers), and the mesh times are 0.29 s,
3.2 s and 15.6 s for 100, 200 and 300 (reorder 0.17, 1.9 and 9.3 s — two orderings per
operating point, which is `NIiter`'s design), against 1.5, 17.8 and 225.8 s; the rest is
Sparse's numeric refactorization and the fill of the mesh, as for KLU.

## Diagnostic slips (both solvers unless said)

* **D1 — `gmin=0` and the DC-path hold.** `.option gmin=0` with two capacitor-held nodes
  prints "no DC path from node 'b' to ground; gmin (0 S) installed to provide one" — a hold
  of nothing — then six `singular matrix: check node b`, every rung fails, and "Transient op
  finished successfully" reports v(b) = v(c) = 0.3147 V for nodes whose DC voltage is
  undefined. The message should say the hold is off when gmin is 0, and the run should not
  be called successful.
* **D2 — an overflow is reported as a timestep.** `B1 a 0 i = 1e308*v(a)*1e10` puts an
  infinity into the matrix; the run ends in "Transient op failed, timestep too small …
  trouble with node a" with no word about the overflow. (`exp(1000*v(a))` is limited and
  fine.)
* **D3 — an inductor across an ideal voltage source.** `V1 a 0 1`, `L1 a 0 1u`: every rung
  reports `check node l1#branch`, then "Transient op finished successfully" with
  i(v1) = −10.0005 A — which is V·T/L for the transient op's own 10 µs duration, an
  artefact of the rung, not an operating point. Both solvers. (With F1 closed this deck
  would fail honestly; today the leak and the integration together manufacture a number.)
* **D4 — a cutset of current sources.** `I1 0 a 1m`, `I2 a b 2m`, `R1 b 0 1k`: KCL cannot
  hold at `a` (1 mA in, 2 mA out). Both solvers print "no DC path from node 'a' to ground;
  gmin installed" and v(a) = −1e9 V. The hold is E-575's and the number is honest for it,
  but the message names a missing path where the problem is a 1 mA mismatch; a KCL-cutset
  check would name the sources.

## Smaller notes (not pursued)

* `i(v1)` through a 1e12 S element beside a 1 S load is off by 1.2e-4 (Sparse) and 2.2e-5
  (KLU): the branch current is recovered from voltages that agree to 1e-16, and the
  conditioning (1e12) sets the error — inherent to MNA, the same under both, not a solver
  fault.
* `pz` on a six-element RLC over twelve decades gives up after 236 trials under both solvers
  with three poles; `pzeig` was not tried on it.
* KLU with `pivrel=1` (full partial pivoting) is *less* accurate on the indefinite ladder
  than with the default threshold (7.1e-7 against 7.6e-9 relative, on values of 1e-50);
  Sparse with `pivrel=1` is unchanged. Odd but within the reference tolerance; left.
* `sens v(c)` on a BJT stage warns "the sensitivity to 'ikf' is not a number at this
  operating point … reported as 0" on every run; correct, and repeated per run.
* A resistor of 1e320 Ω is refused at parse time ("Error on line 4"); 1e308 Ω fed 1 nA gives
  1e299 V under both, as it should.

## What held

* **Exactness.** Against the rational reference: the 40-node ladder over 12 decades
  (1.4e-10 / 2.2e-10 worst relative error, Sparse / KLU, on a node at 1.9e-51 V); three
  ladders with 30 % negative resistances (1.5e-8 at worst, on values of 1e-64 — rounding, not
  a defect; the matrices are indefinite and need off-diagonal pivots); two 30-node random
  networks with 150 resistors and six current sources (9e-15 and 1.5e-12); a network of VCVS
  and VCCS with gains 1e6 and 1e-9 through branch rows with zero diagonals (2e-16 / 2e-11);
  the 12-section RLC ladder at 1 Hz … 1 THz against the exact complex solve (2.7e-8 / 5.5e-12);
  and the same ladder under every one of the 8 KLU ordering × scaling × BTF combinations at
  1 GHz and 1 THz (1e-9 at worst).
* **Pivot reuse across an event.** A 20-node ladder over 12 decades with a switch that
  changes one branch from 1e12 Ω to 1e-3 Ω at 1 µs: the transient's end state matches the
  exact DC of the closed circuit to 2.1e-9 (Sparse) and 1.8e-9 (KLU), with trapezoidal and
  Gear, with `pivrel=1`; the reverse event (short opening) to 2e-15. Sparse's fast refactor
  tests only for an exact zero pivot, yet on this network the order chosen before the event
  stays usable after it. The 2026-09-06 F7 ladder's pulse transient agrees between the
  solvers to 3e-13 at 2002 points, under both integrators.
* **Size and repetition.** Ladders of 20k, 100k and 300k nodes (0.2 / 0.7 / 2.3 s Sparse,
  peak 55 / 241 / 711 MB); 5000 `op`s, 3000 `op`/`ac`/`tran` triples, 1000
  `noise`/`pz`/`sens` triples and 5000 `alter`+`op` pairs in one session with `destroy all`:
  peak RSS flat to within 0.9 MB under both solvers (without `destroy all` the retained
  plots grow it, by design). `option klu` and `option sparse` switch mid-session with the
  announcement line and identical answers. A 300-point `sweep` with setup reuse equals the
  same sweep with `noreusesetup`.
* **Analyses across solvers.** DC sensitivity (318 scalars, identical), AC sensitivity over
  1 Hz–1 GHz (400 vectors; 8e-10 of each column's maximum), noise over 1 Hz–1 GHz
  (1e-9), `tf` (identical), distortion (identical), a fifteen-decade AC on the BJT stage
  (3e-9), a stiff switched transient on it (7e-9 over 2001 points).
* **OSDI.** A module whose internal node collapses when `rs = 0`, swept from 0 to 2 under
  setup reuse: the values are right (0.5, 0.50025, 0.5005) and the earlier collapse-change
  warning fires and rebuilds; `alter` across the boundary between two `op`s and inside a
  sweep likewise. A 20-internal-node module with 34 conductances over 18 decades: the linear
  form matches the rational reference to 1.9e-8 / 9.4e-9 (its built-in-resistor twin to
  1.1e-7 / 5.5e-8); the nonlinear form's 1.7e-7 Sparse-vs-KLU difference is Newton's
  tolerance, not the solve.
* **Singular topologies where the verdicts agree.** Two sources in parallel with different
  values, two with the same value, two inductors in parallel at DC, an ideal LC tank driven
  exactly at resonance ("matrix is singular" under both), a KVL-consistent cutset of current
  sources, exact cancellation on a diagonal (G = 1e-3 + 1e-3 − 2e-3 = 0: both pivot around
  it and give the exact −2 V / −1 V through op, dc, tran and ac).

## Coverage, honestly

Not exercised: XSPICE code models (the uninstalled binary cannot load them), CIDER, the
OpenMP build, guard-malloc (the 2026-09-06 hunt swept the solver suites under it), the PSS
and harmonic-balance dense solvers, KLU's kernels line by line (skimmed: `lpivot`,
`klu_refactor`'s zero test, `klu_scale`, `klu_rcond`), Sparse's complex refactor loop, and
F1's persistence into a *later job that needs no ladder* — the `dc` sweep and the transient
show it persisting past the rung within a job, and no reset exists between jobs, but a deck
whose second job converges without any rung was not constructed. The harnesses are in the
session scratchpad under `sv/` (`lib_sv.py`, `mna.py`, `harnA.py` … `harnH.py`, one
directory of decks and outputs each).
