# Enhancement-115 — KLU support for distortion analysis (`.disto`)

Distortion (`.disto`) was the last analysis that produced **wrong results**
under the **KLU** solver — not a crash and not a refusal, but **silent zero
output**: every `.disto` run under `.option klu` completed with no distortion
data, so distortion always had to fall back to Sparse 1.3. (This gap was surfaced
while validating [Enhancement-114](Enhancement-114.md), when un-skipping the
`analyses` example let its `.disto` sub-test run under KLU.)

## Why it produced nothing

Distortion is a **complex** analysis: a Volterra-series method that solves the
small-signal system at the harmonic and intermodulation frequencies (f1, 2·f1,
3·f1, and — with a second tone — f1±f2, 2·f1±f2, …). Each solve goes through
`NIdIter` → `SMPcSolve`, the *complex* matrix solve — the same machinery AC uses
via `NIacIter`.

Under KLU the matrix is stored once and re-used. AC (`acan.c`) prepares it for
complex solves by, before its frequency loop, calling `DEVbindCSCComplex` for
every device (which re-points the device matrix stamps at the **complex** KLU
storage) and setting `KLUmatrixIsComplex`. Sparse 1.3 needs no such step — it
carries real and imaginary parts together intrinsically.

`distoan.c` had **no KLU code at all**. So under `.option klu` the KLU matrix
stayed in **real** mode, the complex solves in `NIdIter` ran against an
unconverted matrix, and every harmonic came back **zero** — a silent wrong
answer. (`cktsens.c`, fixed in E-114, had been the *only* analysis driver that
referenced KLU; distortion was the last one still unwired.)

## The fix

Mirror exactly what `acan.c` does, in `src/spicelib/analysis/distoan.c`:

- **Before** the harmonic solve loop, once the operating point and matrix are
  set up, convert the KLU matrix to complex mode:

  ```c
  #ifdef KLU
      if (ckt->CKTmatrix->CKTkluMODE)
          if (!ckt->CKTmatrix->SMPkluMatrix->KLUmatrixIsComplex) {
              for (i = 0; i < DEVmaxnum; i++)
                  if (DEVices[i] && DEVices[i]->DEVbindCSCComplex && ckt->CKThead[i])
                      DEVices[i]->DEVbindCSCComplex(ckt->CKThead[i], ckt);
              ckt->CKTmatrix->SMPkluMatrix->KLUmatrixIsComplex = KLUMatrixComplex;
          }
  #endif
  ```

  The whole distortion loop is complex, so this one-time conversion suffices.

- **On exit** (successful completion), convert back to **real** with
  `DEVbindCSCComplexToReal` / `KLUmatrixReal`, exactly as `acan.c` does after AC,
  so a subsequent real analysis (`.op`/`.dc`/`.tran`) in the same interactive
  session finds the matrix in the expected state.

- Add `#include "ngspice/devdefs.h"` for `DEVices` / `DEVbindCSCComplex`.

No changes to the distortion math, the RHS setup (`CKTdisto`), or the Sparse
path.

## Verification

KLU distortion now matches Sparse **bit-for-bit**:

| Case | KLU vs Sparse |
|---|---|
| Built-in diode, single-tone (2nd + 3rd harmonic, every output vector) | identical |
| Built-in diode, two-tone intermodulation (`Df2wanted`) | identical |
| OSDI device model `.disto` completes (was **0** output rows under KLU, now full) | ✓ |
| `.disto` **then** `.tran` in one KLU session (matrix reconverted to real) | both complete, correct |

The `analyses` example now runs **fully under KLU** (`sparse=PASS`, `klu=PASS`) —
its distortion sub-test previously forced a KLU skip. The full example suite is
`101/101` under both solvers.

## Files changed

| File | Change |
|---|---|
| `ngspice-46/src/spicelib/analysis/distoan.c` | add the KLU real↔complex matrix conversion around the distortion solve loop (`DEVbindCSCComplex` before, `DEVbindCSCComplexToReal` after), mirroring `acan.c`; `+devdefs.h` include |
| `examples/_setup.py` | dual-solver harness: `.disto` is no longer a KLU-skip trigger, so the `analyses` example runs its distortion sub-test under KLU |

## Scope — KLU is now analysis-complete but for one case

With distortion fixed, KLU runs **DC, DC-sweep, AC, transient, noise,
S-parameters, single-ended pole-zero, sensitivity, and distortion** — matching
Sparse 1.3 across the entire example suite. The **only** analysis still
Sparse-only under KLU is **balanced-output pole-zero** (a `pz` card whose output
reference node is not ground; KLU's fixed symbolic ordering cannot fold the
zeroed columns — see [Enhancement-113](Enhancement-113.md)). The three known KLU
*numerical* differences are unrelated and unchanged: the stiff `opamp741`
transient (convergence), the degenerate `groundcontrib` single-node topology
(wrong DC), and `hierbranch`'s hierarchical branch-current probes (see
[Enhancement-114](Enhancement-114.md)).
