# KLU solver-glue correctness hardening (Enhancement-232)

A source audit of `src/maths/KLU/klusmp.c` — the SMP dispatch layer that ngspice
compiles when KLU is enabled (it handles **both** solvers via `CKTkluMODE`
branches; the pure-Sparse `spsmp.c` is compiled only in a no-KLU build) — found
four latent defects. All are fixed here, and all are **behaviour-preserving**
for any circuit that actually solves.

| | Defect | Fix |
|---|---|---|
| **A** | `SMPluFac` / `SMPsolve` dereference `KLUmatrixCommon->status` *before* the `== NULL` guard (the complex twin `SMPcLUfac` checks NULL first) | reorder to check NULL first, matching `SMPcLUfac` |
| **B** | complex solves `SMPcSolve` / `SMPcaSolve` copy RHS with a plain identity map, while real `SMPsolve` routes RHS through the node-collapse map `NewToOld` — a silent AC/noise/pz mis-ordering if a node ever collapsed | apply the same gather/scatter in the complex solves |
| **C** | `SMPcZeroCol` reads `KLUmatrixAp[Col-1]` with no ground guard (`Ap[-1]` if `Col==0`) | add the `Col >= 1` guard `SMPfindElt` already has |
| **D** | `SMPmultiply` had a dead `iSolution = iRHS;` (assigns a by-value local) | remove |

**B** is the interesting one: the node-collapse map is the identity for any
solvable circuit (it only differs when a structural-zero column collapses a
node, which makes the matrix singular and unfactorable anyway), so the complex
solves produced correct results in practice — but the two paths were
inconsistent, a latent trap if collapse were ever made productive. **A**, **C**,
**D** are defensive-code / dead-code hygiene: the NULL branches never fire
because `Common` lives for the matrix's lifetime, and `Col` is always ≥ 1.

## Verify

```sh
python3 verify_solverfix.py
```

Proves the invariant that matters: KLU still agrees with SPARSE 1.3 **to the
bit** on AC, noise (which exercises the modified *adjoint* `SMPcaSolve`), and
pole-zero, on an **asymmetric** network (a VCVS makes the MNA matrix
non-symmetric so the adjoint solve genuinely differs from the forward solve),
plus a clean DC-op + transient run under KLU. Since the fixes don't change
behaviour, "unchanged vs Sparse" is exactly the correct result.
