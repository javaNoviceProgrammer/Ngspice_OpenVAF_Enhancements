# Enhancement-864: complex `%` takes a real divisor — `v(1) % 2` after an ac was refused

**Scope:** F9 of the
[third robustness and correctness campaign of 2026-10-10](../docs/bug_hunts/2026-10-10_ngspice-openvaf-r-third-robustness-campaign.md).

ngspice: `maths/cmaths/cmath2.c`, `cx_mod`.

`examples/cplxmod_examples/` (new). **ngspice only.**

**Suites:**
- [`cplxmod_examples`](../examples/cplxmod_examples/): 5 of 5 per solver. On the E-863 binaries
  2 fail; [3], [4] and [5] are controls.
- The full sweep: 571 of 571.

## What was wrong

[Enhancement-480](Enhancement-480.md) made `%` a real modulo. For complex operands it takes the
real and imaginary parts modulo the divisor's real and imaginary parts, and it checked that both
of the divisor's parts were nonzero. A real divisor promoted to complex has an imaginary part of
0, so:

```
ac lin 1 1k 1k
let a = v(1) % 2
```

failed "argument out of range for mod", and so did `let z = 5.5 + j(7.25)` followed by `z % 2`.
`v(1) % (2+j(1))` evaluated.

## The change

A divisor with no imaginary part takes both parts modulo itself: (a + jb) % d is
fmod(a, d) + j·fmod(b, d). A divisor of 0 is still refused. A complex divisor keeps E-480's
part-by-part rule. One with a zero real part, such as `j(2)`, is still refused, as there is no
real modulus to take the real part by.

## The checks

`cplxmod_examples`:
- **[1]** After an ac, `v(1) % 2` evaluates, each part modulo 2 (refused on E-863).
- **[2]** (5.5 + 7.25j) % 2 is 1.5 + 1.25j, and % 0.3 part by part.
- **[3]** (control) A divisor of 0 is still refused.
- **[4]** (control) A complex divisor: part by part.
- **[5]** (control) Real % real: 5.5 % 3 is 2.5, −5 % 3 is −2.
