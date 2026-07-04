# complexpole_examples — complex poles/zeros in laplace/zi root forms (Enhancement-31)

Demonstrates **complex conjugate poles and zeros** in the root-based Laplace / z-domain
filter forms (`*_np`, `*_zd`, `*_zp`), using **version11's own** `openvaf-r` and
`ngspice-46`.

## What was broken

The pole/zero vectors of `laplace_np`/`laplace_zd`/`laplace_zp` and the `zi_*`
counterparts are, per the LRM, **(real, imaginary) pairs**. OpenVAF expanded them as a
list of **individual real roots**, so complex conjugate poles/zeros — every resonant or
underdamped section — couldn't be expressed. A Q=5 resonant low-pass via `laplace_np`
with the correct complex pole pair produced **−242 dB of garbage**.

## The fix

`laplace_roots_to_poly` (shared by all six root forms) now reads the vector as
`(re, im)` pairs and expands `Π_k (s − (re_k + j·im_k))` with complex arithmetic,
returning the real polynomial coefficients (the imaginary parts cancel for physical,
conjugate-paired inputs). See `../Enhancement-31.md`.

Root vectors are now written as pairs:

- real root:            `'{r, 0}`  (a lone `'{r}` is also accepted)
- complex conjugate:    `'{re, +im, re, -im}`

## The demo

`complexpole_demo.va` builds two sections that require complex roots and compares the
root form to the equivalent `laplace_nd` polynomial baseline:

- **resonant low-pass** — `laplace_np` with a complex conjugate **pole** pair
  `-w0/(2Q) ± j·w0·√(1−1/4Q²)`;
- **notch / band-stop** — `laplace_zd` with imaginary-axis complex **zeros** `± j·w0`.

## Run

```
python3 verify_complexpole.py
```

Checks (ALL PASS): `laplace_np` (complex poles) and `laplace_zd` (complex zeros) match
the `laplace_nd` baseline to 0.00 dB; the complex poles give a real resonant peak of
+18.06 dB at 1 MHz (= 20·log₁₀(Q=8)); the complex zeros give a deep notch null at 1 MHz.
