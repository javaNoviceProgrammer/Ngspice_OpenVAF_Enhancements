# Enhancement-202 — `.sp` S-parameter matrix inverse is O(N³), not O(N!)

The `pre_snp` stress test ([Enhancement-201](Enhancement-201.md)) noted a *separate*
wall: producing the input Touchstone file with ngspice's own `.sp` analysis was itself
pathologically slow — an 8-port took ~13 s and a **10-port ~18 minutes**, growing by
roughly a factor of `N` per added port. That is in the RFSPICE analysis, not the
converter, and this enhancement removes it.

## The cause: an O(N!) matrix inverse

The `.sp` analysis builds the port S-matrix at every frequency (`CKTspCalcSMatrix` in
`cktspdum.c`), which inverts `N × N` complex matrices — several per frequency, for the
S, Y and Z matrices. The complex inverse (`cinverse` in `maths/dense/dense.c`) was
computed by the **adjugate / determinant** method (Cramer's rule):

```c
CMat* cinverse(CMat* A) {
    CMat* B = cadjoint(A);        // adjugate
    cplx  de = cinv(cdet(A));     // 1 / determinant
    return complexmultiply(B, de);
}
```

and `cdet` is a **recursive cofactor expansion — O(N!)**, while `cadjoint` computes
`N²` cofactors (each an `(N−1)×(N−1)` determinant), so `cinverse` is `O(N·N!)`. With
several inverses per frequency across a whole sweep, the cost explodes by a factor of
`N` per port — `6! → 7! → 8!` is exactly the measured ×7, ×8, ×9 per added port.

## The fix: Gauss-Jordan elimination

`cinverse`/`cinversedest` now invert by **Gauss-Jordan elimination with partial
pivoting** on `[A | I]`, in `O(N³)`. It is a drop-in replacement — same signature, same
result (the true inverse), computed the standard way. Profiling had shown ~99 % of an
8-port `.sp` run sat inside `CKTspCalcSMatrix`; with the fix that disappears.

Behavior is preserved: the old `cinverse` never returned `NULL` (the adjugate always
produced a matrix, garbage for a singular input), so the new one returns `NULL` only on
a true allocation failure and zero-fills a singular matrix — the singular case does not
arise for a well-posed `.sp` network. `cdet`/`cadjoint` remain for any other callers.

## Results

| ports | old `.sp` | new `.sp` |
|------:|----------:|----------:|
| 8     | ~13 s     | 0.3 s     |
| 10    | ~18 min   | 0.02 s    |
| 16    | (infeasible) | 0.03 s |
| 32    | (infeasible) | 0.09 s |

~50,000× at N=10. The extracted S-parameters are unchanged — verified against the
closed-form network to ~2×10⁻⁷. The same inverse is used by the periodic S-parameter
path (`.psp` / PSS in `dcpss.c`), which benefits as well; the full example regression
(touchstone, rfanalyses, psp, …) is unchanged.

Together with [Enhancement-201](Enhancement-201.md) (the `pre_snp` fit and model-size
scalability), the whole measured-block workflow — extract or import an N-port `.sNp`,
convert it to an OSDI device, simulate — now scales to many ports; the remaining limit
is OpenVAF's compile time for the generated model.

## Verification

[`examples/spscale_examples/verify_spscale.py`](../examples/spscale_examples/verify_spscale.py)
runs a **12-port** R-L-C ladder through `.sp` + `wrsnp` (a port count that took minutes
before) and checks two things: the extraction completes in a fraction of a second, and
every entry of the extracted 12×12 S-matrix matches the closed-form network across the
sweep (max abs error ~2×10⁻⁷) — the fast inverse is exact, not just fast. Full example
regression: 165/165.
