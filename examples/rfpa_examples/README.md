# Large-signal RF of a real transistor — Enhancement-164

Enhancements [159](../../enhancements_doc/Enhancement-159.md)–[161](../../enhancements_doc/Enhancement-161.md)
validated a production compact model's DC, coverage, and small-signal (AC / C-V /
fT) behavior. This one drives a real device **hard** and extracts the large-signal
RF figures of merit — gain compression (P1dB), harmonic distortion, and
third-order intermodulation (IP3) — for a common-emitter amplifier built from the
bundled **HICUM/L2 SiGe HBT** (compiled in place from the OpenVAF integration-test
sources, with the E-161 dynamic parameters `t0 = 10 ps`, 1 fF junction caps).

![AM-AM + two-tone IM3](rfpa_ip3.png)

## The amplifier

`Vcc = 3 V`, `RC = 400 Ω` collector load, base biased at `0.77 V` through a `50 Ω`
RF source resistance. Small-signal gain ≈ 7.7 (17.8 dB), collector at ≈ 2.7 V.

```
openvaf-r ../../OpenVAF-master-20260610/integration_tests/HICUML2/hicuml2.va -o hicuml2.osdi
ngspice -b rfpa_demo.cir
```

## Results

- **AM-AM (Panel A)** — the power gain *expands* to ≈ 20.7 dB and then compresses,
  the exponential-transconductance signature of a bipolar; the 1-dB compression
  point (P1dB) sits at the high-drive end. HD3 climbs with the textbook **3:1
  slope** (a straight line on the dB–dB axes).
- **Two-tone IM3 (Panel B)** — for two equal tones the third-order intermodulation
  products (`2f1−f2`, `2f2−f1`) appear just outside the fundamentals at ≈ −30 dBc,
  the in-band distortion that sets IP3.
- **IIP3** — extracted from the single tone as `IIP3 = A/√(3·HD3)` (since the
  two-tone IM3 is exactly 3× the single-tone HD3 for a third-order nonlinearity),
  it comes out **constant at ≈ 0.134 V** across drive level, confirming the
  third-order model.

## Method note (a real finding)

The frequency-domain harmonic-balance engines (`hb`/`qpss`, E-134/136) — the ones
that just got netlist dot-cards (E-162/163) — **do not converge** on this stiff,
many-internal-node production model in an amplifier configuration: `hb` returns
`error 103` at any drive level, and the two-tone `qpss` is prohibitively slow
(> 2 min for a single point). So the characterization here uses **transient +
Fourier/FFT**, which integrates reliably on the heavy model. Transient is the
robust route for large-signal RF on production compact models; HB/QPSS remain the
tool of choice for lighter, well-conditioned circuits (the E-134/136 examples).

## Verify

```
python3 verify_rfpa.py     # 4 checks, under BOTH the Sparse and KLU solvers
python3 make_rfpa_fig.py   # -> rfpa_ip3.png
```

- **[1]** the transient small-signal gain matches the `.ac` gain (7.744 vs 7.742).
- **[2]** the third harmonic follows the 3:1 slope (HD3 ∝ A³).
- **[3]** single-tone `IIP3 = A/√(3·HD3)` is constant across drive (≈ 0.134 V,
  spread < 2 %).
- **[4]** the amplifier compresses at high drive (gain 7.74 → 5.97 at 150× drive).

## Why the results are physically correct

- **Gain expansion → compression.** The BJT collector current is exponential in
  Vbe, so a large drive raises the *average* transconductance (expansion) until
  the collector clips (compression) — exactly what Panel A shows.
- **3:1 HD3 / IM3.** A third-order term `a₃x³` produces a third harmonic ∝ A³ and,
  for two tones, IM3 products ∝ A³ that are 3× the single-tone HD3 — the basis of
  the single-tone IIP3 extraction.

See [Enhancement-164](../../enhancements_doc/Enhancement-164.md) for the full
write-up.
