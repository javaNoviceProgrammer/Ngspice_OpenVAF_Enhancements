# Enhancement-319 — ngspice: transient-form QPSS leaked the fundamental into every mixing bin

Found in the correctness campaign, using the strongest RF oracle available: the periodic steady
state a QPSS reports must equal what the HB-form QPSS and a plain long transient + DFT give.

## The bug

The transient-form quasi-periodic steady state — `qpss <expr> <f1> <f2> [periods] [maxorder]`
(as opposed to the `… hb K1 K2` form) — runs a two-tone transient, then computes each 2-D
harmonic `k1·f1 + k2·f2` by a **trapezoidal integral** of `v(t)·exp(−j2πf·t)` over the "last
period" `[tt[i0], tt[end]]` of the **raw transient grid** (`com_qpss.c`). That window is:

- **not exactly the beat period `T = 1/gcd(f1,f2)`** — `tt[i0] ≥ wstart` but not `= wstart`, so the
  window is short by up to one `tstep`;
- **non-uniform** (the transient grid varies), and its **endpoints are non-periodic**.

A trapezoidal DFT over such a window leaks the large DC/fundamental (`~tstep/T`) into *every*
mixing bin. On a **linear** two-tone RC circuit — where every product with `|k1|+|k2| ≥ 2` is
analytically **exactly 0** — every bin read `~5.8e-4 · |dominant line|` (**~−45 dB**), scaling
linearly with the DC line (the leakage signature). Confirmed against the HB-form (`~1e-16`) and a
plain `.tran` + uniform DFT. It contradicted the mode's own docstring claim of "a direct DFT,
exact for commensurate tones."

## The fix

Resample the last beat period onto a **uniform grid over exactly `[wend − T, wend)`** (linear
interpolation of the transient data), then Fourier-project with the rectangular rule. For
commensurate tones every reported harmonic `k1·f1 + k2·f2 = m·fb` completes an integer `m` cycles
in `T`, so a uniform DFT over exactly `T` is **exact** — a linear circuit's mixing products come
out at the grid-resolution floor (`~6.6e-8`, **~−122 dB**), a **4-decade** improvement. The grid
count `M` is chosen to resolve the highest harmonic and to not downsample the transient grid.

Real distortion products are unchanged: the `qpss_examples` strong IM3 (`3.75e-4`) still matches
the built-in to 4 digits, and on a single-tone diode the transient-form `(2,0)` matches the
HB-form to 5 digits.

## Honest limit

The transient-form's residual floor is grid-limited (`~−122 dB` relative; identical across 4/16/64
settling periods, so it is interpolation/grid resolution, not settling). Products **above** that
are now accurate; the very weakest (below `~−120 dB`) remain floor-limited — for those the HB-form
(`qpss … hb K1 K2`, exact to machine precision) is the tool. Before this fix the floor was
`~−45 dB`, masking anything weaker.

## Verification

`examples/qpssleak_examples/verify_qpssleak.py` — on the linear two-tone RC every mixing product is
now `< 1e-5` of the fundamental (pre-fix `~7e-3`), while the fundamentals are present; **fails on
the pre-fix binary**. The `qpss_examples` suite (12 checks, incl. the strong IM3) still passes.

## Scope of change

`src/frontend/com_qpss.c`, the transient-form Fourier projection only (the `… hb` form was already
exact and is untouched).
