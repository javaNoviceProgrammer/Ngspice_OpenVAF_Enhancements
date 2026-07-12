# Enhancement-171 — KLU/Sparse solver audit: complex determinant + pivot tolerance

A deep audit of the two linear-solver stacks — the KLU↔SMP bridge
(`maths/KLU/klusmp.c`, plus ngspice's KLU additions `klu_extract.c` /
`klu_utils.c` / `klu_multiply.c`) and the Sparse 1.3 side it mirrors — hunting
for defects the way [E-37](Enhancement-37.md)/[E-38](Enhancement-38.md) audited
the compiler. It found that **pole-zero analysis under `.option klu` silently
produced garbage for any circuit with complex poles or zeros**, through two
independent, stacked defects. Both are fixed; an obsolete "not supported" guard
is removed.

![klu pole-zero fixed](../examples/klupz_examples/klupz.png)

## The smoking gun

A series RLC with textbook poles at −5000 ± j·999 987.5 rad/s:

| | pole 1 | pole 2 | pole 3 | pole 4 |
|---|---|---|---|---|
| **Sparse** | −5000 + j·999 987.5 | −5000 − j·999 987.5 | | |
| **KLU (before)** | −100 | −10 | −0.89 | 0 |
| **KLU (after)** | −5000 + j·999 987.5 | −5000 − j·999 987.5 | | |

Real-axis poles/zeros were correct all along — which is why the regression's
single-real-pole RC check always passed and the defect stayed invisible.

## Defect 1 — the complex determinant formula (`spDeterminant_KLU`)

PZ's Muller iteration evaluates `det(G + sC)` at complex trial points via
`SMPcDProd`. The KLU determinant was adapted from Sparse's `spDeterminant`, but
the two solvers store pivots differently: Sparse's `Diag` holds **reciprocal**
pivots (its solve multiplies), while KLU's `Udiag` holds the **actual** pivots
(its solve divides). The adaptation built each pivot as the mixed quantity
`(1/(Ux·Rs), Uz·Rs)` and took its complex reciprocal — algebraically correct
**only when `Uz = 0`** (real pivot), garbage otherwise. Every complex-plane
determinant evaluation was wrong, so Muller wandered blind.

The real branch had three more latent defects: its pivot loop **never executed**
(the loop index was left at `N` by the preceding permutation scan, so the
determinant was always ±1.0), it **divided** instead of multiplying, and it never
wrote `*piDeterminant`, leaving the caller to consume an uninitialized stack
value. Both branches computed the permutation sign as `#non-fixed-points / 2` —
wrong for any cycle longer than 2 (a 3-cycle is an *even* permutation but was
counted odd).

The rewrite: `det(A) = sign(P)·sign(Q) · Π (Udiag[k]·Rs[k])` with the parity
computed exactly by cycle decomposition, complex multiplication done properly,
and the imaginary part always written. After the fix the KLU determinant matches
Sparse to **~14 digits at every trial point**.

## Defect 2 — the unsanitized pivot tolerance (`SMPcReorder`/`SMPreorder`)

Pole-zero calls `SMPcReorder(..., PivRel = 0.0)`. Sparse's `spOrderAndFactor`
**sanitizes** an out-of-range threshold (`≤ 0` or `> 1`) back to its stored
default; the KLU branch assigned it straight to `Common->tol`. With `tol = 0`,
KLU's partial pivoting accepts a diagonal with `|diag| ≥ 0·max` — i.e. an
**exactly-zero pivot**. At PZ's `s = 0` trial an inductor branch has a zero
diagonal (`−sL = 0`), so the factorization came back `KLU_SINGULAR`, PZ recorded
a **spurious root at the origin**, and the deflated search never expanded past
|s| ≈ 10 — yielding the four bogus "poles" above. Both `SMPcReorder` and
`SMPreorder` now mirror Sparse's sanitization (an in-range `PivRel` still takes
effect; DC/AC/transient pass the default 1e-3 and are unaffected).

## Guard removal

With both root causes fixed, the [E-113](Enhancement-113.md)-era guard in
`pzan.c` — "pole-zero finite-zero computation is not supported with 'option
KLU'" (added when the zero search was seen to go spuriously singular, i.e.
defect 2) — is removed. The finite-zero search now works under KLU, and a
genuine `E_SHORT` reports the same "input shorted" diagnostic as Sparse. The
**balanced/differential-output** PZ guard remains: `SMPcAddCol` genuinely has no
KLU implementation.

## Verification

[`examples/klupz_examples/verify_klupz.py`](../examples/klupz_examples/verify_klupz.py)
compares the **full root set** between solvers on six circuits, each anchored to
its analytic answer: series RLC (conjugate pole pair), RC lowpass (the old-good
real-pole case — no regression), lead network (finite real zero), RC highpass
(origin zero), RLC bandstop (**purely imaginary zeros** ±j·10⁶ — the hardest
case), and RLC bandpass (the finite-zero search formerly guarded off). All six:
KLU ≡ Sparse. The full 134-example regression is clean (the tolerance change is
a no-op for every analysis that passes an in-range `PivRel`).

## Scope

The vintage spice3 PZ driver stays numerically fragile near its noise floor
*independent of solver*: on a twin-T notch KLU stalls on the deflated conjugate
zero pair (finds 4 of 6 roots), while on the RLC bandpass it is **Sparse** that
hits its iteration limit (KLU converges cleanly). That is ~1990 Muller-on-
determinant fragility, not a solver defect. Also noted during the audit, left
as-is: `SMPcSolve`/`SMPcaSolve` do not apply the (rarely-active) node-collapsing
map that `SMPsolve` applies, and `SMPcReorder` reports a failed factorization
with status `KLU_EMPTY_MATRIX` as success — both unreachable in normal MNA
operation.
