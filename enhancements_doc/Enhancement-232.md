# Enhancement-232 — KLU solver-glue correctness hardening

A deep read of the linear-solver dispatch layer turned up four latent defects.
None affects any circuit that actually solves — but they are genuine (a
dereference-before-null-check, a real/complex path inconsistency, a missing
bounds guard, a dead assignment), so they are fixed together as a hardening pass.

## Where to audit — one file, both solvers

ngspice ships two linear solvers, but only **one** SMP (sparse-matrix-package)
dispatch layer is compiled at a time. `sparse/Makefile.am` builds `spsmp.c`
only `if !KLU_WANTED`; the shipped build **has** KLU, so `KLU/klusmp.c` is the
sole active layer, and it routes *both* solvers through its `CKTkluMODE`
branches (KLU branch + a Sparse `else` branch). So `klusmp.c` is the single
point of truth, and the audit centred there. The mature SuiteSparse code it
calls (`amd_*`, `btf_*`, `colamd`, `klu_*`) was treated as trusted upstream.

Prior work had already fixed the *functional* KLU bugs — the E-113 adjoint
transpose (`klu_z_tsolve`), the E-114/115 sensitivity/distortion gaps, and the
E-171/172 pole-zero determinant/`SMPcAddCol` — and those fixes are confirmed
still in place. What remained were the four hygiene defects below.

## The four fixes (all in `src/maths/KLU/klusmp.c`)

**A — dereference before the NULL check.** `SMPluFac` and `SMPsolve` read
`KLUmatrixCommon->status` *before* their `if (KLUmatrixCommon == NULL)` guard,
so the guard can never protect anything. The complex twin `SMPcLUfac` already
does it correctly — NULL check first, with an early `return` — which proves the
intended pattern. Reordered both to match (`SMPsolve`, being `void`, now checks
the status fields only inside the non-NULL `else`). `KLUmatrixCommon` is
allocated for the matrix's whole lifetime so it is never actually NULL here;
this aligns the real path with the complex path and satisfies a static analyzer.

**B — real/complex node-collapse asymmetry (the substantive one).** The real
`SMPsolve` gathers and scatters the RHS through the node-collapse permutation
`KLUmatrixNodeCollapsingNewToOld`; the complex `SMPcSolve` and `SMPcaSolve`
copied the RHS with a plain identity (`RHS[i+1]`). If a structural-zero column
ever collapsed a node (`NewToOld` ≠ identity), the AC / noise / pole-zero RHS
would be silently mis-ordered relative to the DC/tran solve. It is dormant —
`NewToOld` is the identity for any circuit that factors (an empty MNA column is
structurally singular and does not solve at all), which is why KLU AC/noise/pz
have always matched Sparse — but the two paths were inconsistent. Both complex
solves now apply the identical gather/solve/scatter, so a future change to the
collapse logic cannot quietly break complex analyses. Behaviour is unchanged
for every solvable circuit (verified bit-for-bit against Sparse).

**C — missing ground guard in `SMPcZeroCol`.** It indexes `KLUmatrixAp[Col-1]`
with no lower-bound check, so `Col == 0` reads `Ap[-1]`. Its sibling
`SMPfindElt` already guards this (`if (Col < 0) return NULL` after decrement);
added the matching `if (Col < 1) return 0`. Pole-zero passes node indices ≥ 1,
so this never fired, but the guard makes the two accessors consistent.

**D — dead assignment in `SMPmultiply`.** The real-matrix branch ended with
`iSolution = iRHS;`, which only reassigns a by-value local pointer and does
nothing (a real matrix has no imaginary product). Removed.

## Verification (`examples/solverfix_examples`)

`verify_solverfix.py` (4 checks) proves the invariant that matters for a
behaviour-preserving change: on an **asymmetric** network (a VCVS makes the MNA
matrix non-symmetric, so the noise *adjoint* solve genuinely differs from the
forward solve), KLU still agrees with SPARSE 1.3 **to the bit** on AC, on the
noise spectrum (exercising the most-changed `SMPcaSolve`), and on pole-zero
roots (`SMPcaSolve` + `SMPcZeroCol` + `SMPcAddCol`), plus a clean DC-op +
transient run under KLU.

## Scope

ngspice only, one file (`src/maths/KLU/klusmp.c`); no analysis, device, OSDI, or
compiler change, and no behavioural change for any circuit that solves. Full
regression: 191/191.
