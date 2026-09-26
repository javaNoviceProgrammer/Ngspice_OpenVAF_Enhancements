# Enhancement-736: a pivot below `pivtol` is reported, under both solvers — the option the manual calls "the absolute minimum value for a matrix entry to be accepted as a pivot" reached both solvers and changed nothing anyone could see (Sparse took the largest element left when nothing passed and returned a verdict ngspice maps to OK, KLU ignored the value); a deck that sets `pivtol` is now told which node's pivot fell at or below it, and `set ngdebug` reports the default floor too

**Scope:** F3 of the
[second KLU/Sparse solver-core hunt of 2026-09-25](../docs/bug_hunts/2026-09-25_klu-sparse-solver-cores-second-hunt.md),
and the item [E-475](Enhancement-475.md) left open. **ngspice only, both solvers.**
`src/maths/sparse/spfactor.c` (the record in `SearchEntireMatrix`), `spalloc.c`
(`spWhereSmallPivot`), `spdefs.h`, `spsmp.c`; `include/ngspice/spmatrix.h`, `smpdefs.h`
(`SMPsmallPivot`), `cktdefs.h`, `optdefs.h` (`ERRP_PIVTOL`); `maths/KLU/klusmp.c` (the
U-diagonal check after `klu_factor` and `klu_z_factor`); `maths/ni/niiter.c`
(`NIsmallPivot`), `niaciter.c`, `niditer.c`; `spicelib/analysis/cktsopt.c` (the given bit).
[`examples/solvercore_examples/`](../examples/solvercore_examples/) (section [F3, second hunt], 10
checks, 37 per solver). Handbook [§3.7](../docs/handbook/03-ngspice-workflows.md). The hunt
page; a note in E-475.

**Suites:** `solvercore` 37 of 37 per solver, both solvers (31 of 37 under KLU and 30 of 37
under Sparse on the E-734 binaries: the six checks that expect a warning, and under Sparse
E-735's reorder-time bound as well); `oprobust` 38 of 38,
`floatnode` 16 of 16, `singularname` 12 of 12, `acgminhold` 10 of 10, `internalnode` 28 of
28, `dcpath`, `explicitvalue` per solver, both solvers, unchanged; no new build warnings;
full sweep, run alone.

## What was wrong

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
op
print v(a) v(c)
.endc
.end
```

Both solvers printed `v(a) = 62.5`, `v(c) = 12.5` — the exact answer — and nothing else,
with `pivtol=1e-3`, with `pivtol=1e30`, with the default 1e-13 (which the 2e-14 and 3e-14
pivots are also below), in an operating point, an AC and a transient. The value reaches the
solvers: `cktdojob.c` copies it into `CKTpivotAbsTol`, `SMPreorder` and `SMPcReorder` pass
it as Sparse's `AbsThreshold`, and every search in `spfactor.c` refuses a candidate at or
below it. What happened when every candidate was refused was

```c
    Matrix->Error = spSMALL_PIVOT;
    return pLargestElement;              /* SearchEntireMatrix */
```

with `include/ngspice/spmatrix.h` reading `#define spSMALL_PIVOT OK`: the factorization went
on with the largest element it could find and returned success, and no caller could tell.
That mapping is deliberate — Spice3 removed the small-pivot warning (CIDER's `misc.c` still
carries the commented-out case), and the Sparse verdict is a warning-level code by design.
KLU's `SMPreorder` and `SMPluFac` began with `NG_IGNORE (PivTol)`; only `pivrel` reached
`Common->tol`. So the floor steered Sparse's choice among candidates, was ignored by KLU,
and was never heard of when crossed, and [E-475](Enhancement-475.md) had validated a value
it could not make change anything — it said so, and left the question open.

## What changed

`SearchEntireMatrix` remembers the first pivot an ordering had to take at or below the
threshold — its external row and column and its magnitude — in the matrix frame, cleared at
the start of every `spOrderAndFactor`; `spWhereSmallPivot` reads it. `spSMALL_PIVOT` stays
mapped to `OK`: the factorization *is* complete.

KLU has no absolute threshold, so after every full factorization (`klu_factor`,
`klu_z_factor`) the glue walks the diagonal of U and records the first pivot at or below
`pivtol`, with the unknown's node (`Symbolic->Q`) and the equation's node (`Numeric->Pnum`).
KLU factors the row-scaled matrix when `klu_scale` is on (the default), so each pivot is
scaled back by its row's factor first: `U = D_P · U'` for a row scaling `D`, so the
comparison is in the units of the loaded matrix, as Sparse's is. A refactorization along a
fixed order (`spFactor`, `klu_refactor`) does not check, under either solver: the order is
what was chosen.

`SMPreorder` and `SMPcReorder` leave the record in the `SMPmatrix` (`SMPsmallPivot`), from
Sparse's frame or KLU's diagonal, and `NIiter`, `NIacIter` and `NIdIter` call `NIsmallPivot`
after every reorder that succeeded:

```
Warning: the pivot for node b is 3e-14, below pivtol (0.001)
```

naming the node whose unknown the pivot belongs to and, when the pivot came from another
node's equation, that node too ("the pivot for node x (from the equation of node y) …").
Sparse names the largest element of the reduced matrix at the step it gave up (node `b`,
3e-14, in the deck above); KLU names the first small pivot in its order (node `a`, 2e-14).
The same node at the same magnitude, to rounding, is reported once — KLU factors afresh at
every reorder request, twice in an operating point, once more in a transient or an AC — and
six are printed per run, all of them under `set ngdebug`, like the singular-matrix messages.

**When it speaks.** A deck that sets `pivtol` (any value, including 1e-13) is answered every
time; the default floor is reported only under `set ngdebug`. The reason is measured: with
the default reported unconditionally, one sweep of the 532 suites crossed it 125 times on
decks that are fine — an OSDI branch that carries nothing (8e-79, `tempphys`, `osdilimit`),
a probe source's branch row beside a 10 TΩ path (7e-14, `oprobust`), a thermal node (8e-27,
`electrothermal`), floating nodes the suites float on purpose — none of which a user would
want a warning for on a deck that never mentioned `pivtol`, and Spice3 chose silence there.
The option's own semantics are unchanged: Sparse still refuses a candidate at or below the
floor while an acceptable one exists, KLU still pivots by `pivrel` alone; what is new is
the word when the floor is crossed. Values never change.

## Verification

* The hunt's deck under `pivtol=1e-3`: `Warning: the pivot for node b is 3e-14, below pivtol
  (0.001)` under Sparse, `… node a is 2e-14 …` under KLU, `v(a) = 62.5`, `v(c) = 12.5` as
  before; under `pivtol=1e30` the same warning with `(1e+30)`; under the default, nothing,
  and with `set ngdebug`, `below pivtol (1e-13)`.
* A node held by the `dcpath` gmin alone (1e-12) under `pivtol=1e-10`: "the pivot for node
  y is 1e-12, below pivtol (1e-10)", `v(y)` still I/gmin; under the default, nothing.
* An AC at one frequency and a transient with `pivtol=1e-3` on a 1e-14 S node beside an RC:
  one warning each, from the analysis's own factorization; `vm(x)` unchanged.
* A healthy divider with `pivtol=1e-3`: every pivot is above it; op, AC and transient say
  nothing.
* The E-734 binaries pass the values and fail the six checks that expect a warning.

## What this does not do

* It does not refuse the factorization or change its result: a small pivot is a warning,
  as Sparse designed it; the singular case is still `singular matrix: check node`.
* It does not give KLU an absolute pivot floor in its search; KLU chooses by `pivrel` and
  reports afterwards.
* It does not report from a refactorization along a fixed order, nor from the sensitivity
  and pole-zero analyses, which factor with their own thresholds.
* It does not print the default floor unless `set ngdebug` is on.
