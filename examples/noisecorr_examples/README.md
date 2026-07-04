# noisecorr_examples — correlated (same-named) noise sources (Enhancement-42)

Demonstrates **noise-source correlation by name** — noise functions with the
same name argument are the *same* physical source (LRM 4.6.4) and sum
**coherently** as amplitudes at the output — using the committed
`openvaf-r` and `ngspice-46`.

## What was broken

The name argument of `white_noise`/`flicker_noise`/`noise_table` only labelled
the per-source output vectors; every source was treated as independent
(powers summed). A same-named pair read `sqrt(2)`× instead of `2`×, and an
anti-phase contribution of the same source (`<+ -white_noise(S,"n")`), which
must cancel, *added* noise instead.

Two-sided fix: OpenVAF folds the contribution factor into the loaded noise
power as `fac*|fac|` (magnitude unchanged, sign preserved), and ngspice's OSDI
noise analysis groups same-named sources within an instance and sums their
signed amplitudes against the complex transfer before squaring. Uniquely-named
sources are bit-identical to before; instances never correlate with each other.

## Run

```
python3 verify_noisecorr.py
```

Checks (ALL PASS, exact): same-named pair 2e-6 (was 1.414e-6); distinct names
1.414e-6 (unchanged); anti-phase same-named pair 0 (cancellation); scaled
factors `|2+1|`·1e-6 = 3e-6; same name across two *instances* stays independent
(2.828e-6); white+flicker under one name group across kinds (2e-6 at 1 Hz);
per-source vectors report the group total on the group's first source.
