# Production compact-model noise validation — Enhancement-165

Enhancements [159](../../enhancements_doc/Enhancement-159.md)–[161](../../enhancements_doc/Enhancement-161.md)
validated a real compact model's DC, coverage, and small-signal (AC / C-V / fT)
behavior; [E-164](../../enhancements_doc/Enhancement-164.md) its large-signal RF.
This one exercises the remaining untested small-signal path — OSDI's `.noise`
stamping of the models' own `white_noise` / `flicker_noise` sources — on
production models, compiled in place from the OpenVAF integration-test sources.

![noise validation](modelnoise.png)

## BSIM4 — validated against ngspice's built-in

The output-noise spectral density `Sv(f)` of a BSIM4 common-source amplifier is
compared to ngspice's **built-in** BSIM4 over the full band (Panel A). Both the
low-frequency **1/f flicker** region (`Sv ∝ 1/√f`) and the flat high-frequency
**thermal floor** match to **< 2 %** — a stringent check that the OSDI noise
stamping reproduces the native model's noise physics.

```
openvaf-r ../../OpenVAF-master-20260610/integration_tests/BSIM4/bsim4.va -o bsim4.osdi
ngspice -b modelnoise_demo.cir
```

## HICUM — validated against shot-noise physics

HICUM/L2 (SiGe HBT) has no ngspice built-in, so its noise is checked against
physics. Its default noise is **white** (shot + resistance thermal, no flicker by
default) — a flat spectrum, in clear contrast to the MOSFET's 1/f rise. With a
small source resistance so the intrinsic device noise dominates, the output-noise
floor tracks the collector **shot-noise** line `√(2q·Ic·RC²)` across two decades of
bias current (Panel B) and scales as `√Ic` — the defining bipolar white-noise
behavior.

## Verify

```
python3 verify_modelnoise.py    # 5 checks, under BOTH the Sparse and KLU solvers
python3 make_modelnoise_fig.py  # -> modelnoise.png
```

- **[1]** OSDI BSIM4 output-noise spectrum matches built-in BSIM4 to < 4 % (≈ 1.5 %).
- **[2]** BSIM4 shows the 1/f flicker region (`Sv(1Hz)/Sv(10Hz) ≈ √10`).
- **[3]** BSIM4 shows the flat thermal floor at high frequency.
- **[4]** HICUM noise is white (flat) at mid-band — no flicker by default.
- **[5]** HICUM output floor tracks the collector shot noise `2q·Ic·RC²` and scales
  as `√Ic`.

`.noise` runs under both solvers (KLU included, since
[E-113](../../enhancements_doc/Enhancement-113.md) fixed the KLU adjoint solve).

## Why the results are physically correct

- **Flicker (1/f).** Trap-related carrier-number fluctuation gives a power density
  `∝ 1/f`, so the amplitude density falls as `1/√f` — exactly the low-frequency
  slope, matching the built-in model.
- **Thermal floor.** Channel/resistance thermal noise is white, giving the flat
  high-frequency floor.
- **Shot noise.** A DC current `Ic` crossing a junction carries shot noise
  `i² = 2q·Ic`; through the `RC` load that is `2q·Ic·RC²` at the output, tracking
  the collector current across the bias sweep.

See [Enhancement-165](../../enhancements_doc/Enhancement-165.md) for the full
write-up.
