# Scoping a parallel-factorization solver for ngspice

## Why

On large Verilog-A/OSDI circuits the runtime is dominated by the **linear solve**,
and specifically by the **numeric factorization**, which is single-threaded. A
measured profile of a 2D resistor mesh (≈180k instances, `.op`, `.option klu`)
spends **≈57% in `klu_kernel` + `klu_refactor`** and essentially 0% in device
`eval`. In a long transient the one-time setup amortizes away and factorization is
an even larger share of per-step cost. See
[ngspice_solver_notes.md](ngspice_solver_notes.md) for the full profile and the
KLU-vs-Sparse scaling.

The existing OpenMP scaffolding (in `osdi/osdiload.c`, `#ifdef USE_OMP`)
parallelizes only device `eval()`. Because `eval` is 10–25% of runtime, Amdahl
caps that at ≈1.1–1.3×. **The factorization is the real target, and no amount of
`eval` parallelism reaches it.** This document scopes replacing/augmenting the
single-threaded factorization with a parallel sparse direct solver.

## The one fact that shapes everything: circuit matrices are *ultra*-sparse

A SPICE Jacobian has ≈3–6 nonzeros per row regardless of size (each node touches a
handful of neighbours; the 5×10⁵-node mesh has ≈2.5×10⁶ nonzeros, ≈5/row). KLU
(a left-looking Gilbert–Peierls solver with BTF + AMD) is not an incidental choice
— it is *the* right serial algorithm for this class, and it beats general
multifrontal solvers (UMFPACK, SuperLU, PARDISO) on circuit matrices precisely
because those do more fill-in and floating-point work to expose the dense frontal
blocks that BLAS parallelizes.

This creates the central tension of the whole effort:

> The solvers that are *easy* to parallelize (multifrontal, via threaded BLAS) are
> the ones that are *algorithmically wrong* for ultra-sparse circuit matrices, so
> their parallel speedup can be eaten by their higher serial flop count. The
> solver that is *right* for circuits (KLU's approach) is *hard* to parallelize.

Any honest scope must confront this, not wish it away.

## The integration seam (good news)

ngspice already abstracts the solver behind the **SMP layer**
(`include/ngspice/smpdefs.h`), and KLU is a second implementation living behind it
alongside Sparse 1.3. A third solver plugs into the same seam. Concretely:

- **Device stamping is solver-agnostic through CSC.** Every device has a
  `*bindCSC.c` that binds pointers into the shared compressed-column value array
  (`Ax`), and stamps into those pointers each load. **136 device files use this,
  and a new solver that consumes the same CSC (`Ap`/`Ai`/`Ax`) format needs *zero*
  changes to any of them.** This is the single biggest reason the effort is
  bounded.
- **The solver lifecycle is already the circuit-friendly one:** `klu_analyze`
  (once — symbolic ordering) → `klu_factor` (first numeric) → **`klu_refactor`
  (every Newton iteration, reusing the symbolic pattern)** → `klu_solve`. Every
  serious sparse solver offers this analyze-once / refactor-many split; it must be
  used, or the per-iteration cost of re-analyzing will erase any parallel gain.
- **The work concentrates in `maths/KLU/klusmp.c`** — the ≈15 SMP entry points
  (`SMPnewMatrix`, `SMPpreOrder`/`SMPreorder` → analyze, `SMPluFac`/`SMPcLUfac` →
  factor/refactor, `SMPsolve`/`SMPcSolve`/`SMPcaSolve` → solve, plus determinant
  and column ops for `.pz`). A new `*smp.c` mirrors these.
- **`.option` dispatch:** `CKTkluMODE` is a 1-bit mode today. A third solver means
  a small mode enum (`sparse` / `klu` / `<new>`), threaded through the ≈34 files
  that branch on it and the ≈15 analysis drivers (`acan.c`, `noisean.c`,
  `distoan.c`, `cktsens.c`, `cktpzset.c`, `dcpss.c`, `span.c`, …). Most are the
  one-line real↔complex binding switch already present for KLU.

The bad news: **the complex duality doubles the port.** AC, noise, `.pz`, `.disto`,
and the RF analyses go through the complex path (`SMPcLUfac`/`SMPcSolve`/
`klu_z_solve`/`klu_z_tsolve` — 20 call sites in `klusmp.c`). A parallel solver must
handle complex matrices and the *transposed* (adjoint) solve that noise/S-parameters
need, or those analyses fall back to KLU/Sparse. (This is exactly the ground
E-113/E-171/E-172 fought over for KLU.)

## Candidate solvers

Evaluated against: fit for ultra-sparse circuit matrices, analyze-once/refactor-many
support, real **and** complex + transposed solve, macOS arm64, license, and whether
it adds a new external dependency.

| Solver | Circuit fit | Refactor | Complex+transpose | arm64 | License | New dep? |
|---|---|---|---|---|---|---|
| **NICSLU** | **Excellent** — parallel Gilbert–Peierls, purpose-built for circuit simulation | yes | yes | source build | GPLv3 / commercial | yes (but small, self-contained) |
| **PARDISO** (Panua) | Good (supernodal, handles unsymmetric) | yes | yes | yes (Panua), **no** (Intel MKL is x86-only) | commercial | yes |
| **UMFPACK** (SuiteSparse) | Fair — multifrontal, more fill on circuits | yes (symbolic/numeric split) | yes | yes | permissive (matches vendored KLU) | **no code dep** (same SuiteSparse), needs threaded BLAS |
| **SuperLU_MT** | Fair — supernodal, pthreads/OpenMP | yes | real; complex is a separate build | yes | permissive | yes |
| **KLU + parallel BTF** | N/A — only helps *block-diagonal* circuits | reuses KLU | inherits KLU | yes | already in-tree | **no** |

Notes that decide it:

- **KLU + parallel BTF** is the cheapest thing imaginable (factor independent BTF
  blocks on OpenMP threads) and should be prototyped *first* as a baseline — but it
  helps only circuits that decompose into many weakly-coupled blocks. A connected
  mesh or a densely-fed-back analog block is **one BTF block**, so it does nothing
  for the very cases that motivated this. Low ceiling, near-zero cost, good sanity
  check.
- **NICSLU** is the best *algorithmic* fit: it keeps KLU's low-fill left-looking
  approach and parallelizes the column factorization across a dependency
  (elimination) tree — designed for exactly these matrices, with published
  circuit-matrix speedups of ≈3–8× at 8–16 threads. Cost: a new (GPLv3) dependency
  and a from-source build. Its API mirrors KLU closely (analyze/factor/refactor).
- **UMFPACK** has the **lowest integration cost** — it is part of the SuiteSparse
  already vendored for KLU, so it adds no new project, only its module and a link
  to a threaded BLAS (Accelerate on macOS is multithreaded; OpenBLAS elsewhere).
  But per the ultra-sparse tension above, on true circuit matrices it may not beat
  single-threaded KLU in wall-clock until the matrices are large and relatively
  dense. It is the right choice **only if** the target is big post-layout meshes
  (which *are* denser than a transistor netlist), not general analog circuits.
- **PARDISO / MKL** is ruled out as a default path by Apple Silicon: Intel MKL's
  PARDISO has no native arm64, and Panua-PARDISO is commercial. Viable as an
  optional x86/Linux back end, not the primary.

## Recommendation

A **two-track** plan, because the tension above means no single solver is a clean
win:

1. **Track A (low cost, immediate): parallel-BTF KLU.** Add an OpenMP loop over
   independent BTF blocks in the existing KLU refactor. Reuses all KLU machinery,
   no new dependency, and directly benefits circuits with repeated/weakly-coupled
   subcircuits (large digital-ish or multi-core-IP netlists). Sets a floor and
   validates the threading/build story. Ceiling is topology-limited and it does
   nothing for single-block meshes — that's expected.
2. **Track B (the real lever): integrate NICSLU as a third SMP back end.** Best fit
   for the ultra-sparse regime, keeps the low-fill algorithm, real speedup on the
   connected circuits Track A can't help. Gated behind `.option nicslu` (or
   auto-selected by size), with KLU remaining the default and the correctness
   oracle.

UMFPACK is the fallback for Track B if NICSLU's licensing/build proves
unacceptable, accepting its weaker fit on the sparsest circuits.

## Phasing (Track B)

1. **Real DC only.** New `*smp.c` implementing `SMPnewMatrix`/analyze/factor/
   refactor/`SMPsolve` for the real path; `.option <new>` in `com_option.c`; the
   COO→CSC path reused as-is. Validate on the mesh/ladder benchmarks and the DC
   subset of the suite against KLU (bit-parity target, as the KLU work used).
2. **Complex path.** `SMPcLUfac`/`SMPcSolve` + the **transposed** solve for noise
   and S-parameters (the E-113 lesson: a non-transposed adjoint solve is silently
   wrong on any asymmetric matrix). Unlocks AC, noise, `.disto`, `.pz`, RF.
3. **Analysis-driver sweep.** Thread the solver-mode enum through the ≈15 drivers;
   most changes mirror the existing KLU branch.
4. **Refactor-path tuning.** Ensure the hot `refactor` (per Newton iteration) uses
   the pattern-reuse path and not a re-analyze; this is where the parallel win is
   realized or lost.

## Honest expectations

- **Amdahl ceiling.** Factorization is ≈57% of a one-shot DC and higher in
  steady-state transient. Even with an *infinitely* fast factorization the whole-run
  speedup caps around **2×** for that DC profile; realistically a parallel solver
  delivers ≈3–6× on the factorization alone at 8–16 cores for circuit matrices, so
  expect **≈1.7–2.5× whole-simulation** on large fill-in circuits, more in long
  transients where setup is amortized. This is meaningful but not the order-of-
  magnitude that GPU marketing implies — sparse circuit factorization does not
  parallelize like dense linear algebra.
- **Refactor parallelizes worse than the first factor.** The per-iteration refactor
  reuses the pivot order and does less work, so its parallel efficiency is lower
  than the one-time analyze+factor. Since refactor is the hot path, this caps the
  practical gain.
- **Numerical differences are expected and must be budgeted for.** A different
  pivot order changes rounding; the dual-solver parity harness
  (`check_both_solvers`, `KLU_XFAIL`) is the ready-made safety net — extend it to a
  third solver and treat any XFAIL as a bug, exactly as the KLU bring-up did.
- **Not a substitute for KLU.** KLU stays the default and the correctness oracle;
  the parallel solver is opt-in for large circuits where its overhead is amortized.
  On small circuits it will be *slower* (thread/setup overhead), so auto-selection
  should be size-gated.

## Effort estimate

Comparable to the original KLU integration, which is spread across ≈105 `#ifdef
KLU` files. The device layer (136 `bindCSC` files) is untouched. Realistically:
Track A is a small, self-contained spike; Track B is a multi-week integration
concentrated in one new `*smp.c` plus the analysis-driver sweep, with the bulk of
the risk in the complex/transposed path and in proving parity across the whole
example suite.

## Immediate next step

Before committing to Track B's dependency, run the **Track A parallel-BTF spike**
and, in parallel, a **standalone UMFPACK-vs-KLU wall-clock bake-off** on the 2D
mesh and a transistor mesh (extracted matrices, no ngspice integration). That
produces the one number this whole decision hinges on — *does a parallel solver
actually beat single-threaded KLU in wall-clock on our matrices* — for a few days
of work rather than a few weeks.
