# polyfit_examples — Enhancement-890

[E-890](../../enhancements_doc/Enhancement-890.md): F2 of the
[nonlinear correctness campaign of 2026-10-15](../../docs/bug_hunts/2026-10-15_ngspice-openvaf-r-nonlinear-correctness-campaign.md).

`ft_polyfit` fitted each local polynomial in the monomials of the abscissa itself, so the fit's
condition grew as (t/h)^degree, and its coefficients cancelled when evaluated at t. It now fits in a
local coordinate that runs over [−1, 1]. `fourier`, `.four`, `deriv`, `interpolate`, `linearize` and
plot interpolation all go through it.

The checks:
- **[1]** `deriv` of a 1 kHz sine at `dpolydegree=3` over 500 ms is within 1e-7 of the derivative.
- **[2]** At `dpolydegree=4` over 50 ms it is within 1e-9.
- **[3]** (control) At the default degree 2 the error is the method's own, 6.58e-6.
- **[4]** `fourier` at `polydegree=3` of four stacked harmonics: the 4th harmonic's phase is within
  0.001°, and the zero harmonics are below 1e-9.
- **[5]** At `polydegree=4` the fundamental is within 1e-5 of 0.975116.
- **[6]** A pure sine over 2000 ms reads a THD below 1e-9 % at `polydegree` 1 to 4.

Run: `python3 verify_polyfit.py` (6 checks per solver). On the E-888 binaries [1], [2], [4], [5]
and [6] fail.
