# clog2_examples — `$clog2` correctness (Enhancement-101)

`$clog2(n)` is the IEEE-1800 system function returning `ceil(log2 n)` — the
number of bits needed to index `n` distinct values. Enhancement-101 fixes two
bugs found by a probe sweep: (1) every call was rejected with "expected 2
arguments" (a bad 2-arg signature; the lowering always took one arg), and (2)
once callable, the value was `floor(log2 n)+1`, which overcounts exact powers of
two (`$clog2(16)` gave 5, not 4).

`clog2_demo.va` exposes `$clog2` results as operating-point variables. The
verify reads them back in ngspice via `.op` and checks the constant-folded
literals `$clog2(1,2,3,4,7,8,16,17,1024)` and the runtime parameter path
`$clog2(N)` for `N ∈ {16, 33, 1}` against `ceil(log2 n)` — including the
powers-of-two cases the old code got wrong. Run: `python3 verify_clog2.py`
(13 checks).
