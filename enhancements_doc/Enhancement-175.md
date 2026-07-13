# Enhancement-175 — RF-suite audit: the dropped parametric term in every periodic small-signal analysis

A full audit of the RF suite — `.sp`/Touchstone ([E-63](Enhancement-63.md)/[E-64](Enhancement-64.md)/[E-72](Enhancement-72.md)), PSS/PAC/pnoise/pxf ([E-117](Enhancement-117.md)–[E-126](Enhancement-126.md)), PSP ([E-132](Enhancement-132.md)), HB ([E-134](Enhancement-134.md)/[E-135](Enhancement-135.md)), the two-tone QPSS family ([E-136](Enhancement-136.md)–[E-142](Enhancement-142.md)) — driven by analytic anchors and cross-analysis invariants. Most of the suite came back **exact**; one real defect surfaced, in the mathematical heart of every periodic small-signal analysis.

![rfconv](../examples/rfconv_examples/rfconv.png)

## The bug: column frequency in the conversion matrix

All LPTV small-signal analyses build the harmonic conversion matrix. The code scaled the reactive coupling by the **column** (input-sideband) frequency:

```
H_nm = G_{n−m} + j·ω_m·C_{n−m}        (as shipped)
```

For a small signal `δv` riding a frozen periodic capacitance `C(t) = ∂Q/∂v|orbit`, the exact linearized current is `δi = d/dt[C(t)·δv] = Ċ·δv + C·δv̇`, and the product rule collapses the two terms to the **row** (output-sideband) frequency:

```
I_n = j·ω_n·Σ_m C_{n−m}·δV_m    ⟹    H_nm = G_{n−m} + j·ω_n·C_{n−m}
```

Using `ω_m` silently **drops the parametric-pumping term `Ċ·δv`** — the very term that makes a pumped varactor a parametric converter. Every conversion sideband through a time-varying capacitance came out scaled by exactly `ω_in/ω_out`; on the audit circuit the ±1/±2 sidebands were **3× / 5× / 7× / 9× too small** (the measured pre-fix/truth ratios were 0.3333, 0.2000, 0.14286, 0.11111 — the ω-ratios to five digits, which is what confirmed the diagnosis beyond doubt).

**Affected**: `pac`, `psp`, `pnoise`, `pxf`, `qpac`, `qpnoise`, `qpxf`, and the `phasenoise` adjoint — for any circuit with nonlinear/pumped capacitance (varactors, junction and MOS capacitances: every real mixer and oscillator). **Unaffected**: LTI circuits — no off-diagonal `C` harmonics, and `ω_n = ω_m` on the diagonal — which is exactly what every prior regression check used. The [E-171](Enhancement-171.md) pattern again: accidental correctness in the untested region.

## The subtlety: why HB was innocent (and must not be "fixed")

The harmonic-balance **residual** uses the same matrix builders — with the column frequency — and that is **correct there**: HB's reactive current is the exact chain rule `d/dt Q(v(t)) = C(v(t))·v̇(t)`, whose n-th harmonic is `Σ_m C_{n−m}·(jω_m V_m)`. This is why HB and QPSS-HB matched transient ground truth all along while the small-signal analyses did not — and it means a blanket "fix" would have broken HB.

The repair is therefore a **mode flag** on the two builders (`pac_build_matrix`, `qp_build_matrix`) and the two inline copies (the PAC adjoint and the phasenoise adjoint):

- `smallsig=1` (pac/psp/pnoise/pxf/qpac/qpnoise/qpxf/phasenoise): **row** frequency — restores the parametric term;
- `smallsig=0` (HB/HBOSC/QPSS-HB residual + Jacobian): chain-rule **column** frequency — byte-for-byte unchanged behavior.

## Evidence

Ground truth is a plain **transient + one-beat Fourier projection** (the time-domain integrator is independent of all conversion-matrix machinery), on a 1 kΩ → OSDI varactor (`C(v)=c0(1+αv)`) pumped at 1 V/1 MHz with a 1 mV probe at 250 kHz:

| sideband | truth /V | fixed /V | pre-fix /V (ratio) |
|---|---|---|---|
| sb0 250k | 0.53817 | 0.53821 | 0.53821 (diagonal, unaffected) |
| lsb1 750k | 0.020755 | 0.020765 | 0.006922 (**1/3**) |
| usb1 1.25M | 0.021050 | 0.021058 | 0.004212 (**1/5**) |
| lsb2 1.75M | 0.0012221 | 0.0012284 | 0.0001755 (**1/7**) |
| usb2 2.25M | 0.0012407 | 0.0012439 | 0.0001382 (**1/9**) |

Regression safety was proven directly: the linear-circuit PAC control produces **identical** output pre/post fix.

## What the audit found clean

- **`.sp` + Touchstone (17 checks)**: series-R/shunt-C/3-port star vs analytic S-parameters to 10 digits; the asymmetric-2-port S21/S12 column-order trap; reciprocity; RI/MA/DB, Y/Z (v1 normalization) and GHz round-trips through `wrsnp`/`rdsnp`; N-port row-major 4-pairs-per-line layout.
- **HB**: analytic cubic — fundamental `a1A+(3/4)a3A³` and H3 `(1/4)a3A³` exact to 7 digits; even harmonics at machine zero; Sparse/KLU identical. (A wrong-looking first run turned out to be HB *correctly* solving `|v|³` — ngspice B-source `^` is `pow(|x|,y)`; its even harmonics matched `4/3π`, `8/5π` analytically.)
- **QPSS-HB / QPSS-tran**: two-tone fundamentals `a1A+(9/4)a3A³`, IM3 `(3/4)a3A³`, H3 — exact (HB mode) / within transient truncation (tran mode); the commensurate-tone aliasing guard fires correctly.
- `cktspnoise.c` is a dead fossil (`#ifdef RFSPICE_`, never compiled) — noted.

## Verification

[`examples/rfconv_examples/verify_rfconv.py`](../examples/rfconv_examples/verify_rfconv.py) — 5 checks × both solvers: transient truth vs QPSS-HB (chain-rule path unchanged), truth vs fixed `qpac` (all five sidebands within 2%), the pre-fix ω-ratio signature is absent, and the HB / QPSS-HB analytic anchors. Full example regression: 138/138.
