# Enhancement-63 — RF analyses with OSDI devices: `.sp` / transient noise / PSS + `span.c` NaN fix (version11)

This document describes Enhancement-63: round 2 of the analysis-coverage
work (Enhancement-62), probing the RF-flavored ngspice analyses —
S-parameters, transient noise, and periodic steady state — with OSDI
(Verilog-A) devices against built-in twins. One stock-ngspice defect found
and fixed (`span.c`); ngspice-only, no compiler/ABI change.

## `.sp` — S-parameter analysis: exact

- A series 100 Ω **OSDI resistor** between 50 Ω ports gives the textbook
  S11 = R/(R+2Z0) = 0.5 and S21 = 2Z0/(R+2Z0) = 0.5, exactly.
- A frequency-dependent OSDI R + C shunt two-port is **bit-identical** to
  the built-in R/C twin across three decades (1 MHz – 100 MHz).
- **Arbitrary port count**: `span.c` allocates every matrix
  `CKTportCount × CKTportCount`, so `.sp` is fully N-port — a 3-port
  direct junction reproduces the textbook Sii = −1/3 / Sij = +2/3, and
  3-/4-port OSDI resistor stars give the analytic 1/3 and 1/4 exactly
  (bit-identical to built-in twins). Only the `donoise` noise-parameter
  block (NF/SOpt/Rn — inherently two-port concepts) is restricted to
  exactly 2 ports.

## `.sp … donoise` — noise figure: OSDI exact, and a stock NaN fixed

The OSDI noise pipeline (E-42/E-54) reaches S-parameter noise figures: a
Verilog-A resistor with explicit `white_noise(4kT/R)` gives
**NF = 10·log₁₀(1 + R/Z0) = 4.7712 dB exactly**.

**The defect (stock ngspice, exposed by OSDI parity testing):** the same
topology with a *built-in* resistor returned **NaN** for NF/SOpt/NFmin.
`span.c`'s noise-parameter extraction computes
`Ysopt.re = sqrt(SQR(Ycor.re) + Gu/Rn)`, where `Gu` — the uncorrelated
noise conductance — is analytically **zero** for a fully-correlated
single-noise-source topology. Floating-point rounding can land the sqrt
argument at −1e-18: `sqrt(negative)` → NaN. (The OSDI twin's rounding
happened to stay ≥ 0, which is exactly how the parity test caught it.)

**Fix:** clamp the argument to its physical range (≥ 0). After the fix the
built-in single-R case reads 4.7712125 dB — 10·log₁₀(3) to eight digits —
and the multi-source regression case (series 100 + shunt 200) is unchanged
at 7.2016 dB.

## Transient noise: correct propagation, documented parity

A `TRNOISE` source driving an OSDI divider propagates correctly
(deterministic mean exact, noise σ as expected). Device-*internal* noise
(`white_noise`/`flicker_noise`) does not enter `.tran` — the same is true
of every built-in device's noise model; transient noise in ngspice comes
only from `TRNOISE` sources. Parity, not a gap.

## PSS — periodic steady state: OSDI devices are full citizens

`.pss` is experimental and compile-time optional (`--enable-pss`; the
suite auto-detects and SKIPs without it, and the README shows the build
recipe — a `build-pss/` tree keeps it out of the default build).

- **Linear OSDI RC** (1k/1n, driven at 1 MHz): shooting converges (16
  iterations), predicted fundamental within 0.1 ppm, and the fundamental
  harmonic equals the analytic |H| = 1/√(1+(ωRC)²) = 0.1571767 — matching
  the built-in twin to **7 digits**.
- **Nonlinear OSDI diode** (mild drive): converges in 2 shooting
  iterations — the built-in diode twin actually *wanders longer* (its
  frequency estimate jumped to ~2 MHz before settling).
- **Strongly nonlinear rectifiers** defeat the shooting method for
  built-ins and OSDI alike (frequency-estimation wander) — a stock
  characteristic of the experimental PSS core, not an OSDI limitation.

## Examples (`rfanalyses_examples/`, 15 checks, ALL PASS)

`verify_rfanalyses.py`: [1] `.sp` resistive exact; [2] `.sp` RC
bit-identical to built-in; [2b] N-port S-matrices (3-port junction
textbook values, 3-/4-port OSDI stars exact + bit-identical to built-in);
[3] donoise — OSDI NF exact, built-in NF finite
and analytic (**the fix**), 2-resistor regression unchanged; [4] TRNOISE
through OSDI (mean exact, σ in band); [5] PSS — linear exact + twin parity
+ nonlinear convergence (SKIPs cleanly without `--enable-pss`).

## Regression

All version11 example verify suites pass with the rebuilt ngspice; no
compiler change (crate tests / corpus stand as of Enhancement-61/62).
