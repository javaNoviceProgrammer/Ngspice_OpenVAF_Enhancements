# RF noise figure of an LNA (Enhancement-168)

[Enhancement-165](../../enhancements_doc/Enhancement-165.md) validated a production
model's device **noise** (spectral density). This example lifts that to a
circuit-level figure of merit — the **noise figure** of a low-noise amplifier —
and checks it against the two textbook RF-noise results: **optimum source
matching** and the **Friis cascade formula**.

The LNA is a common-emitter stage built from the **HICUM/L2** SiGe HBT (OSDI),
AC-coupled, driven from a source resistance `Rs`. From ngspice's `.noise`
analysis the noise figure is

```
NF = 10*log10( inoise² / (4kT·Rs) )          [T0 = 290 K]
```

where `inoise` is ngspice's input-referred noise density — the noise factor `F`
is the total input-referred noise power over the source-resistor thermal noise.

## What is validated

- **Extraction / spectrum.** `NF(f)` is a couple of dB, positive everywhere
  (physical), flat across the white mid-band, and rises at high frequency as the
  input capacitance rolls off the gain.
- **Noise match** (figure, Panel A). `NF(Rs)` is a **U-curve** with an interior
  minimum — an **optimum source resistance** `Rs_opt`. At small `Rs` the
  amplifier's input **voltage noise** `en` dominates; at large `Rs` its input
  **current noise** `in` dominates. The two asymptotes cross near the minimum. The
  current noise extracted from the high-`Rs` branch equals the base **shot noise**
  `√(2q·IB)` — the physical origin of the optimum.
- **Friis cascade** (figure, Panel B). A two-stage cascade obeys
  `F_total = F1 + (F2−1)/G_av1`. With a high-gain first stage `F_total → F1` — the
  **first-stage-dominance** principle that lets the front-end LNA set the system
  noise figure — and with a low-gain first stage the second stage contributes a
  clearly measurable amount that still matches Friis.

## Files

- **`verify_noisefigure.py`** — the validation (6 checks under **both** the Sparse
  and KLU solvers; `.noise` works under KLU since
  [E-113](../../enhancements_doc/Enhancement-113.md) fixed the KLU adjoint solve):
  NF positive + flat mid-band; NF rises at high f; NF(Rs) U-curve; `in` = base shot
  noise; Friis + first-stage dominance (high `G1`); Friis quantitative (low `G1`).
- **`make_noisefigure_fig.py`** → **`noisefigure.png`** — Panel A the noise-match
  U-curve with the `en`/`in` asymptotes and `Rs_opt`; Panel B the Friis cascade NF
  versus first-stage gain, collapsing onto `F1`.
- **`noisefigure_demo.cir`** — a minimal hand-runnable single-stage LNA that prints
  `NF(f)` at 10 MHz … 10 GHz.

## Running

```sh
python3 verify_noisefigure.py        # validation (both solvers)
python3 make_noisefigure_fig.py      # figure

openvaf-r ../../OpenVAF-master-20260610/integration_tests/HICUML2/hicuml2.va -o hicuml2.osdi
ngspice -b noisefigure_demo.cir
```

## Notes

- **Available power gain.** The Friis `G_av1` is the first stage's *available*
  power gain, measured as `|v_c|²·Rs/Rout` with `Rout ≈ RC`. The second stage's
  noise factor `F2` is measured with a source resistance equal to the first stage's
  output impedance (`≈ RC1`) — the impedance it actually sees.
- **Reference temperature.** `NF` is pinned to the standard `T0 = 290 K`
  (`.options temp=16.85`), so the `4kT·Rs` in the formula uses the same temperature
  as ngspice's resistor thermal-noise model — the extraction is self-consistent.
- **Device is a BJT for a reason.** The base **current** gives a finite input
  current noise `in = √(2q·IB)`, which is what produces the high-`Rs` side of the
  NF minimum; a MOSFET (no gate current) would not show the same optimum from shot
  noise. The HICUM default noise is white (no flicker — see E-165), so `NF(f)` is
  flat at low frequency rather than showing a 1/f corner.
