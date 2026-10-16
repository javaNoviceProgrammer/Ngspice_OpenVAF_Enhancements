# Enhancement-890: the local polynomial fits are made in a local coordinate — `deriv` at dpolydegree=3 returned 3e20 times a sine's derivative, and `fourier` at polydegree=4 read every harmonic as 3831

**Scope:** F2 of the
[nonlinear correctness campaign of 2026-10-15](../docs/bug_hunts/2026-10-15_ngspice-openvaf-r-nonlinear-correctness-campaign.md).

ngspice:
- `maths/poly/polyfit.c`: `ft_polyfit` fits in a local coordinate and returns it as `frame`.
- `maths/poly/polyeval.c`: `ft_pevalf` evaluates in that coordinate.
- `maths/poly/interpolate.c`: `ft_interpolate` evaluates in the frame. Its last segment now uses
  the last fit's degree, and it frees its buffers on the error paths.
- `maths/cmaths/cmath4.c`: `deriv` divides the differentiated coefficients by the frame's width.
- `frontend/plotting/plotcurv.c`: the plot curve fitter evaluates in the frame.
- `include/ngspice/fteext.h`, `maths/poly/polyfit.h`, `maths/poly/polyeval.h`: the prototypes.

`examples/polyfit_examples/` is new. **ngspice only.**

**Suites:**
- [`polyfit_examples`](../examples/polyfit_examples/): 6 of 6 per solver. On the E-888 binaries 5
  of 6 fail.
- The 48 suites that use `fourier`, `.four`, `deriv`, `linearize`, `interpolate`, the polynomial
  degrees or the random functions pass.
- The full sweep: 591 of 591.

## What was wrong

`ft_polyfit` fits a polynomial through degree + 1 points. It built the Vandermonde matrix on the
abscissa itself: 1, t, t², t³ with t near 0.5 s and the points 1 µs apart. Its condition grows as
(t/h)^degree. Gaussian elimination still returns coefficients that reproduce the points, but the
coefficients themselves are wrong by as much, and they cancel when evaluated at t again. The fit
behind its callers was therefore only as good as t/h allowed:
- `fourier` and `.four` with `polydegree`;
- `deriv` with `dpolydegree`;
- `interpolate`, `linearize`, and plot interpolation.

`deriv` of a 1 kHz sine at 1 µs steps, against 2πf·cos:

| run | dpolydegree=3 | dpolydegree=4 |
|---|---|---|
| 2 ms | 4.2e-8 | 1.3e-4 |
| 50 ms | 1.2e-2 | 3.4e33 |
| 500 ms | 3.2e20 | 3.8e40 |

`fourier` of four stacked harmonics at 5.07 MHz, one period, 1000 points:
- **`polydegree=3`:** the 4th harmonic is 1.07° off, and the 5th and 6th, which are zero, read
  1.2e-4 and 2.3e-5.
- **`polydegree=4`:** every harmonic reads 3831.

A pure 1 kHz sine over 2000 ms read a THD of:
- 1.8e-9 % at degree 1;
- 4.2e-7 % at degree 2;
- 3.8e-7 % at degree 3;
- `nan` at degree 4.

The straight line of degree 1, (x₁y₀ − x₀y₁)/(x₁ − x₀), lost t/h of its digits too.

## The change

The fit is made in u = (x − c)/w. Here c is the centre of the points' span and w is its
half-width, so u runs over [−1, 1]. `ft_polyfit` returns the coefficients of u and the frame
(c, w).
- **Every evaluation** goes through `ft_pevalf(x, frame, …)`, which makes the change of variable.
- **`deriv`** divides the differentiated coefficients by w.
- **Degree 1** is fitted in u as well. Two coincident points now fail the fit instead of
  returning infinite coefficients; the plot fitter then rotates the axes, as it does for any
  vertical segment.

The signature changed, so the compiler found every caller.

Two things in `ft_interpolate` were wrong alongside:
- **The degree of the last segment.** It was evaluated at the requested degree, though its fit
  may have been lowered; that read coefficients the fit had not written.
- **Leaked buffers.** Its error returns leaked its four buffers.

## The checks

`polyfit_examples`:
- **[1]** `deriv` at `dpolydegree=3` over 500 ms is within 1e-7 of the derivative: 2.1e-8, the
  method's own error.
- **[2]** At `dpolydegree=4` over 50 ms it is within 1e-9: 5.8e-11.
- **[3]** (control) At the default degree 2 the error is 6.58e-6, as before.
- **[4]** `fourier` at `polydegree=3`: the 4th harmonic's phase is within 0.001°, and the zero
  harmonics read 1.1e-13.
- **[5]** At `polydegree=4` the fundamental reads 0.975116.
- **[6]** The pure sine over 2000 ms reads a THD of about 3e-11 % at every degree from 1 to 4.

## Limits

`deriv` of a nested `dc` sweep treats the whole vector as one curve. The points beside each group
boundary, where the inner sweep starts over, are fitted across the jump and are wrong: 1.0 off on
a parabola. This is the same before and after; the vector carries no grouping for `deriv` to
follow.
