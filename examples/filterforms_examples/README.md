# filterforms_examples — Enhancement-405

Every analog filter operator, in every form the LRM provides, expressing the
**same filter** — checked in **dc, ac and tran** against closed-form transfer
functions.

`laplace_nd` / `laplace_np` / `laplace_zd` / `laplace_zp` and
`zi_nd` / `zi_np` / `zi_zd` / `zi_zp` differ only in whether the numerator and
denominator arrive as ascending-power **coefficients** or as **roots** (given as
`(real, imaginary)` pairs). Three filters are written in all four forms of each
family:

| filter | H | dc gain |
| --- | --- | --- |
| `lap1` | `1 / (1 + s/1e6)` | 1 |
| `lap2` | `(1 + s/4e6) / (1 + s/1e6)` | 1 |
| `lap3` | conjugate pole pair at `-0.5e6 ± j1e6` | 1 |
| `zi1` | pole at `z = 0.5` | 2 |
| `zi2` | zero at `0.25`, pole at `0.5` | 1.5 |
| `zi3` | conjugate pole pair at `0.4 ± j0.3` | 2.2222 |

> **Not part of the routine regression sweep.** It is listed in
> `_setup.REGRESSION_EXCLUDE`, so `run_regression.py` skips it by default. Run it
> directly, or with `run_regression.py --all` / `NG_RUN_ALL=1`. This is a
> deliberate scoping choice, not a performance one — the whole check runs in
> about two seconds.

| File | What |
| --- | --- |
| `filter_forms.va` | 24 modules: 8 operators × 3 filters, each driving a probe port so the response reads back as a node voltage |
| `verify_filterforms.py` | compiles once, then runs dc / ac / tran per module and compares against closed form |

```
python3 examples/filterforms_examples/verify_filterforms.py
```

## Three oracles, because each covers what the others miss

1. **Analytic.** `H(s)` in closed form, at dc and at five ac frequencies
   spanning 1 kHz to 3 MHz — enough range that the 1-pole response sweeps
   0.99998 → 0.0398 in magnitude and 0° → −87.7° in phase, so the comparison
   cannot pass on flat unity.
2. **Cross-form.** The four spellings must agree *with each other*. This needs no
   knowledge of the sign convention at all, and it is what caught
   Enhancement-405: `zi_np`/`zi_zp` had every pole and zero **reciprocated**, so
   a pole written `0.5` landed at `z = 2` and the four forms read 2.0 against
   −1.0.
3. **Final value.** A step response must settle to the dc gain.

## Two things worth knowing before changing this

**The `zi_*` reference is the bilinear (Tustin) equivalent, not an ideal sampled
response.** A z-domain filter is a sampled-data system, and lowering converts
`H(z)` to a continuous `H(s)` via `z⁻¹ = (1 − sT/2)/(1 + sT/2)` rather than
modelling zero-order hold — a documented approximation. Checking against an ideal
sampled response would fail for reasons that are not defects.

**The transient oracle may only be applied after the stimulus has settled.** The
pulse source has a finite rise time, and every `zi_*` filter has a direct
feedthrough term once bilinear-transformed, so it tracks its input
*instantaneously*: during the ramp the output is `d₀·u(t)`, not `d₀`. Comparing
against an ideal step reports a 0.66 error at `t = 1e-14` that is entirely the
oracle's fault. The `laplace_*` filters here have no feedthrough and hide it.

## Verified to fail

Against the shipped binary from **before** Enhancement-405, the same 85 checks
give **58 pass / 27 fail**, exit code 1 — and the failures are exactly the
root-taking z-forms (`zi_zp` dc 0.5555556 against 2.2222, transients diverging to
−3.5e6, cross-form dc spreads of 1.667). **Zero `laplace_*` failures in that
run**, which is the same conclusion the corpus differential reached from the
other direction: Enhancement-405 touched the z-domain root convention and left
the Laplace path alone.

```
OPENVAF_BIN=/path/to/old/openvaf-r python3 verify_filterforms.py   # 58/85, exit 1
```

## Enhancement-712: many filters and many Jacobian entries (robustness campaign F9)

Section "Enhancement-712" of `verify_filterforms.py` (10 checks, 95 in all) guards the
compile time and memory of a module with many Laplace filters, and the answers such
modules give. A module of 100 `laplace_zp` filters of twenty poles each (2 000 filter
states, 6 200 Jacobian entries) took 113 s and 48 GB before
[E-712](../../enhancements_doc/Enhancement-712.md): the root-to-polynomial expansion
selected the LRM's zero-root exception at run time with four branch diamonds per
(root, coefficient) pair — 54 000 blocks for twenty filters, all folded away a moment
later — and the OSDI descriptor module's straight-line helper functions hit two
quadratic LLVM backend passes. The checks:

- the 100-filter module compiles in under 60 s and 4 GB (1.6 s and 0.54 GB; 119 s and
  47.9 GB on the E-711 binaries), its dc current is 100 × V — every filter has unit dc
  gain — and its step response settles to that current;
- a zero root written as the literal `0` and as a parameter set to `0` give the same
  differentiator, 0.532018 at 100 kHz against the analytic value (the compile-time
  path and the `select` path);
- a 300-node resistor ladder (904 Jacobian entries, so its descriptor module is the
  -O0 path) compiles in under 20 s (0.4 s; 4.3 s before) and its dc current is
  3.01 V over 301 kΩ to eleven digits.

```
OPENVAF_BIN=/path/to/E-711/openvaf-r python3 verify_filterforms.py   # 93/95, exit 1
```
