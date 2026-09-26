# Enhancement-738: under Sparse the diagonal gmin goes to the stamped diagonals, as under KLU — the loader fed whatever the pivot order had put on the internal diagonal, which after the MNA preorder and the Markowitz exchanges is the ±1 twins of voltage sources and inductors and any other chosen pivot, so the gmin ladder regularised different equations under the two solvers, an unsolvable loop of sources climbed every rung under Sparse and none under KLU, and a node beside a source got no shunt at all; the stamped diagonals are recorded at the first preorder and fed from then on

**Scope:** F2 of the
[second KLU/Sparse solver-core hunt of 2026-09-25](../docs/bug_hunts/2026-09-25_klu-sparse-solver-cores-second-hunt.md)
— its symptom was closed by [E-734](Enhancement-734.md), this is the mechanism, which was
not the one the hunt described. **ngspice only, Sparse only; KLU is untouched.**
`src/maths/KLU/klusmp.c` (`SparseGminDiag`, the Sparse branch of `SMPpreOrder`, `LoadGmin`,
`SMPnewMatrix`, `SMPdestroy`), `src/maths/sparse/spsmp.c` (the same for a build without KLU),
`include/ngspice/smpdefs.h` (`SMPgminDiag`).
[`examples/solvercore_examples/`](../examples/solvercore_examples/) (section [F2, second
hunt], 5 checks, 42 per solver). Handbook [§3.7](../docs/handbook/03-ngspice-workflows.md).
The hunt page; a correction in E-734's write-up.

**Suites:** `solvercore` 42 of 42 per solver, both solvers (39 of 42 under Sparse on the E-737
binary: the three loop checks; 42 of 42 under KLU); `oprobust` 38 of 38, `dcpath`, `floatnode`
16 of 16, `singularname` 12 of 12, `acgminhold` 10 of 10, `internalnode` 28 of 28,
`explicitvalue` 41 of 41, `linesearch` 17 of 17 per solver, both solvers, `warmstart` 5 of 5,
`failacct` 9 of 9, `convhelp` 35 of 35, unchanged; no new build warnings; full sweep, run
alone. Beyond the suites: the 122 Sparse decks of the hunt's harnesses print the same values on
the E-737 binary and this one, and only the loop decks change what their ladders say.

## What was wrong

```spice
* three voltage sources in a loop whose voltages do not sum to zero
V1 a b 1
V2 b c 1
V3 c a -1
R1 a 0 1k
.control
set ngdebug
op
.endc
.end
```

Since E-734 the point is refused under both solvers. Under Sparse the ladders still said,
rung after rung, "One successful gmin step" — 22 of them, dynamic gmin's eleven and source
stepping's inner eleven — on a matrix that is singular by construction, where KLU reported
`singular matrix: check node v3#branch` at every one. The hunt read this as Sparse's pivoting
creating a diagonal element for the branch row and `LoadGmin` feeding it. That element exists
(it is a fill-in), but it is a side effect: the exchange the hunt cited creates nothing (its
lookup passes `NO`), and the mechanism is where the loader looks.

Sparse indexes `Diag[]` by *internal* row, and the array follows the pivot order. The MNA
preorder swaps a voltage source's column with a node's so that the source's ±1 twins sit on
the diagonal (`SwapCols`: `Diag[Col1] = pTwin2`); the Markowitz ordering exchanges rows and
columns and, at exit, sets `Diag[I]` to whatever sits at internal `(I, I)`; and the loader
walked that array:

```c
	for (I = Matrix->Size ; I > 0 ; I--)
	    if ((diag = Diag [I]) != NULL)
		diag->Real += Gmin ;
```

A print of each entry the loader touched, with its external row and column:

| deck | entries fed | of which ±1 stamps | nodes left without a shunt |
|---|---:|---:|---|
| the loop, every rung | 6 | 4 (both twins of two sources) | none (`a` is the only node with a conductance; the v3 branch's fill-in diagonal got gmin·i) |
| a BJT stage with an inductor, first factorization | 10 | 4 (the twins of `Vcc` and `Vin`) | `vcc`, `in` (source-driven, harmless) |
| the same stage, every later factorization | 10 | 6 (the inductor's twins as well) | `c` and `out`, the inductor's nodes |

So "diagonal gmin" under Sparse meant gmin on the pivots: on the loop it turned
`v(a) − v(b) = 1` into `(1 + gmin)·v(a) − v(b) = 1` and put `gmin·i` into the KCL rows and
into the v3 branch's own equation, which is what made every rung solvable; on the stage it
left the inductor's two nodes without the shunt the ladder is meant to give every node. KLU's
`LoadGmin_CSC` feeds `KLUmatrixDiag[]`, the stamped `(i, i)` entries by external identity, so
a branch row never gets gmin and a node always does. Which equations a rung regularised
depended on the solver and on the pivot history.

## What changed

At its first preorder — before `spMNA_Preorder` swaps columns, before any factorization,
while internal and external numbering agree and `Diag[I]` is the stamped `(I, I)` element or
NULL — Sparse records the address of every stamped diagonal (`SparseGminDiag`,
`SMPgminDiag[]` in the `SMPmatrix`), and `LoadGmin` feeds those, whatever the pivot order has
done since. A voltage source's branch row records NULL and never gets gmin; an inductor's
branch row, which stamps its own diagonal, gets it under both solvers as before. A matrix
that was never preordered (no path in ngspice reaches the loader without one) keeps the old
walk; the record is freed with the matrix and refreshed with a new one.

| deck, Sparse | E-737 | now |
|---|---|---|
| the inconsistent loop | 22 rungs "succeed", 366 singular reports | 0 succeed, 374 singular — KLU's numbers exactly |
| the consistent, rank-deficient loop (`V3 c a -2`) | 22 and 366 | 0 and 374 |
| the loop under `.option gmin=1e-6` | 16 rungs "succeed" | 0 |
| the BJT stage, gmin stepping forced (`noopiter`) | 7 rungs, 23 iterations, v(c) = 10.9391 | the same |
| a floating chain of two sources with `dcpath=off` | 22 rungs solve, the gmin-free point refused | the same (as under KLU) |

## Verification

* **The loops.** With `set ngdebug`, the inconsistent loop, the rank-deficient loop and the
  loop under `gmin=1e-6`: no "successful gmin step", every rung singular, the point refused,
  under both solvers (`solvercore` [F2, second hunt], three checks; the E-737 Sparse binary
  fails all three).
* **Where a point exists.** The BJT stage with the plain Newton attempt skipped climbs the
  ladder to the same point; a floating chain of sources under `dcpath=off` solves its rungs on
  the shunts of the two nodes that stamped a diagonal and is refused at the end, alike under
  both solvers (two checks).
* **No solvable deck moved.** The 122 Sparse decks of the hunt's harnesses (DC, AC, transient,
  noise, pole-zero, sensitivity, distortion, the 300 000-node ladder) print the same values on
  the E-737 binary and this one; the BJT stage with `rshunt` (which E-734 routes through the
  same loader) gives the same voltages to ten digits under both binaries and both solvers; the
  twelve ladder-related suites pass under both solvers.

## What this does not do

* It does not change any operating point that exists: the final solves carry no diagonal gmin
  (E-734), and no deck in the batteries changed a value or an iteration count. The change is
  in what a rung regularises, and it shows only where the ladder is climbing a matrix that has
  no solution.
* It does not give a shunt to a node that stamped no diagonal — a node whose only entries are
  a branch's ±1, such as a floating pair joined by one source under `dcpath=off`. KLU's rule is
  the same, and E-566's zero diagonal covers a node with no entry at all, not that one.
* It does not touch KLU, the pivot choice under Sparse (which still differs from KLU's and can
  still create a branch row's fill-in diagonal — it is just no longer fed), or the `rshunt`
  path beyond routing it to the same stamped diagonals.
