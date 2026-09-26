# solvercore_examples — the solver-core defects of 2026-09-06, pinned on both solvers

The bug hunt in [`docs/bug_hunts/2026-09-06_klu-sparse-solver-cores.md`](../../docs/bug_hunts/2026-09-06_klu-sparse-solver-cores.md)
found eight things in the KLU and Sparse glue. Seven were fixed the same day; this suite
keeps them fixed. F6, an XSPICE batch-exit double free, is outside the solver core and
is still open.

| # | what was wrong | what the suite checks |
|---|---|---|
| F1 | a node nothing conducts to (a current source's only load, a controlled-current-source output, a forgotten monitor load) made KLU's `SMPconvertCOOtoCSC` "collapse" its column and mis-address every other node's RHS: 0 V at a 1 V source, 1 A into two dividers, silently | every other node exact under both solvers; the node reads I/gmin under the default `dcpath` hold; with `dcpath=off` setup and solver both name it and the point is refused (E-734) |
| F8 | the same node numbered last was outside the matrix under both solvers (`NIinit` starts at size 0); Sparse's RHS vectors were one short and the current source wrote past them; both printed the current as the voltage, accumulating across a `dc` sweep | exact neighbours, I/gmin on the node, a `dc` sweep that scales instead of summing |
| F2 | `.ic`/`.nodeset` on a node without a diagonal element aborted every analysis under KLU as "out of memory" | stacked supplies, two inductors, a VCVS output — all run with the right values |
| F3 | `.option rshunt` reached the operating point but not ac, noise, sp or disto under KLU | ac, noise and sp match Sparse |
| F4 | an AC interrupted by a breakpoint inside `sweep` left the devices bound to the complex arrays; the next point's operating point was NaN | all three sweep points recorded |
| F7 | KLU's AC reused the first frequency's pivot order across the whole sweep with no check; a wide-range ladder was 26 dB off at 1 THz (613 dB with `pivrel=1`) | the ladder within 0.05 dB of a 70-digit reference at 1 GHz and 1 THz, with either threshold |
| F5 | an infinite pivot hung the determinant normalisation | code guard only (`isfinite`), no deck |
| N1 | Sparse's ordering was quadratic in the node count: its sorted lists were walked through at every interchange and fill-in (second hunt, 2026-09-25; fixed by [E-735](../../enhancements_doc/Enhancement-735.md), same pivots and factors) | a 150 × 150 mesh: the same voltages under both solvers and a reorder time under 4 s (0.9 s here, 6.4 s before); a 30 × 30 RC mesh's AC (the complex ordering); a switch that shorts two mesh nodes mid-transient |

The fixes: `CKTsetup` gives every node without an entry a zero diagonal and tells the
solver the true size (`SMPsizeHint`, `SMPmarkOccupied`); KLU's conversion no longer
collapses columns and the solves use the identity map; `NIreinit` sizes the vectors from
the node count; `CKTacLoad` adds the shunt through `SMPfindElt`; `CKTdoJob` rebinds to
real after any analysis returns; `SMPcLUfac` checks `klu_z_rcond` after every complex
refactor and asks `NIacIter` to re-pivot when it collapsed.

## Run

```
python3 verify_solvercore.py
```

26 checks per solver, all PASS.
