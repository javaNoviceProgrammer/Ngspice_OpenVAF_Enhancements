# Enhancement-31 — complex poles/zeros in laplace/zi root forms (version11)

This document describes the change made to **OpenVAF-r** in the `version11/`
directory to support **complex conjugate poles and zeros** in the root-based forms of
the Laplace and z-domain filter operators.

## What the root forms are

The Verilog-AMS filter operators come in four forms each, differing in how the
numerator and denominator are given:

| suffix | numerator | denominator |
|--------|-----------|-------------|
| `_nd`  | polynomial coefficients | polynomial coefficients |
| `_np`  | polynomial coefficients | **poles (roots)** |
| `_zd`  | **zeros (roots)** | polynomial coefficients |
| `_zp`  | **zeros (roots)** | **poles (roots)** |

for both `laplace_*` and `zi_*`. Per the LRM the pole/zero vectors hold
**(real, imaginary) pairs**: element `2k` is the real part and `2k+1` the imaginary
part of root `k`. A complex conjugate pair is `'{re, +im, re, -im}`; a real root is
`'{re, 0}`.

## The bug

`laplace_np`/`laplace_zd`/`laplace_zp` and `zi_np`/`zi_zd`/`zi_zp` all lowered their
root vectors through a single helper, `laplace_roots_to_poly`, which expanded the
array as a list of **individual real roots** `Π_k (s - r_k)` — ignoring the
(real, imaginary) pairing entirely. Consequences:

- a vector like `'{-1e6, -3e6}` was read as **two real poles** (−1e6 and −3e6)
  instead of the LRM's **one complex pole** (−1e6 − 3e6·j);
- **complex conjugate poles/zeros could not be expressed at all**, so every resonant
  / underdamped second-order section was impossible. A Q=5 resonant low-pass built
  with `laplace_np` and the correct complex pole pair produced **−242 dB of garbage**
  (the imaginary parts were treated as extra real roots, one of them in the
  right-half-plane).

## The fix

`laplace_roots_to_poly` ([`hir_lower/src/expr.rs`]) now consumes the vector as
**(real, imaginary) pairs** and forms `Π_k (s - (re_k + j·im_k))` with full complex
arithmetic — each polynomial coefficient carried as a `(re, im)` pair of MIR `Value`s
— and returns only the **real** coefficients:

```rust
// coefficients as (re, im) Values, ascending powers; start at 1 + 0j
let mut re = vec![F_ONE];
let mut im = vec![F_ZERO];
let mut k = 0;
while k < roots.len() {
    let rr = roots[k];
    let ri = if k + 1 < roots.len() { roots[k + 1] } else { F_ZERO };
    k += 2;
    // new = s*P - (rr + j*ri)*P   (complex multiply, then subtract from the shift)
    ...
}
re   // imaginary parts cancel for conjugate-paired (physical) inputs
```

For a physical, real-coefficient transfer function the roots come in conjugate pairs,
so the imaginary parts of the product cancel to zero; taking the real part both
realises that and harmlessly drops floating round-off. A trailing unpaired element
(odd-length vector) is treated as a purely real root, so a lone real pole/zero may
still be written `'{r}` as well as `'{r, 0}` (keeps single-real-root models working).

This one helper is shared by all six root-based forms — both `laplace_*` and `zi_*` —
so the single change covers every one of them. No OSDI/ngspice change; the roots are
turned into ordinary polynomial coefficients exactly as before, just correctly.

### Behaviour change

Because the vector is now interpreted as pairs, an **even-length** vector means half as
many roots as it used to. Existing models that relied on the old real-list convention
must switch to the paired form: `'{-1e6, -3e6}` (two real poles) becomes
`'{-1e6, 0, -3e6, 0}`. The shipped `laplace_examples/laplace_variants.va` was updated
accordingly (single real roots such as `'{-2e6}` are unaffected thanks to the
lone-element leniency).

## Verification — `complexpole_examples/`

`complexpole_demo.va` builds two second-order sections that **require** complex roots
and cross-checks the root form against the equivalent `laplace_nd` polynomial baseline.
`verify_complexpole.py` (ALL PASS) checks, end-to-end through version11's own
`openvaf-r` + `ngspice`:

1. a resonant low-pass via `laplace_np` (complex conjugate **poles**) matches
   `laplace_nd` to `0.00 dB` across the sweep;
2. the complex poles produce a real resonant **peak of +18.06 dB at exactly 1 MHz**
   (textbook `20·log₁₀(Q=8)`) — impossible with real-only roots;
3. a notch via `laplace_zd` (imaginary-axis complex **zeros** at ±j·ω₀) matches
   `laplace_nd` to `0.00 dB`, with a deep null (−290 dB) at ω₀.

Additionally spot-checked: `laplace_zp` (complex poles *and* zeros) and `zi_np`
(complex poles in the z⁻¹ domain, matched to the equivalent `zi_nd` real polynomial).
Existing `nd` and single-real-root examples (`laplace_lpf`, `zi_lpf`,
`laplace_zd_only`, `laplace_mixed_var_literal`) are unchanged and regression-checked.
