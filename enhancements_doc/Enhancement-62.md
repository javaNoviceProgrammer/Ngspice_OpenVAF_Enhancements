# Enhancement-62 — ngspice analysis coverage for OSDI devices: `.dc @inst[param]` sweeps + `.disto` warning

This document describes the changes made to **ngspice-46** in the
`version11/` directory following an analysis-coverage probe of OSDI
(Verilog-A) devices across every ngspice analysis beyond
op/dc/ac/tran/noise. ngspice-only — no compiler/OSDI ABI change.

## The probe (built-in-twin comparisons, E-57 technique)

| analysis | verdict | evidence |
|---|---|---|
| `.tf` | **exact** | OSDI divider: TF = 0.75, Z_out = 750 Ω, Z_in = 2 kΩ (with a parallel built-in twin) |
| `.pz` (linear) | **exact** | OSDI RC pole −1e6 rad/s, bit-identical to the built-in RC |
| `.pz` (nonlinear bias) | **parity** | "input signal is shorted" — but the *built-in diode circuit fails identically*: an ngspice pz quirk, not an OSDI gap |
| `.sens` (DC) | **exact** | dV/dR matches the analytic divider derivative (−1.875e-4 / +6.25e-5) |
| `.sens` (AC) | **exact** | dV/dacmag = 0.5 − 0.5j at the pole frequency |
| `.dc temp` sweep | **exact** | `$temperature`-dependent R: all points match 1/R(T), °C→K included |
| `alter` / `altermod` / instance-line / `print @n1[r]` | **works** | via `(* type="instance" *)` (the OSDI instance-kind convention) |
| `.dc @n1[r]` param sweep | **GAP 1** | fatal error — sweep code hardcodes Vsource/Isource/Resistor/temp |
| `.disto` | **GAP 2** | **silent zeros**: OSDI diode measured 0.0 where the identical built-in diode measured 1.8e-6 |

## Gap 1 fixed: generic `.dc @inst[param]` sweeps

`dctrcurv.c` recognized only voltage sources, current sources, resistors,
and `temp` as sweep variables. A new **`PARAM_CODE`** sweep type accepts
`@inst[param]`:

- `DCTfindInstParam` resolves the instance by case-insensitive name walk
  (the sweep name is a raw token, not an interned IFuid, so the device
  hash can't be used) and looks the parameter up in the device's own
  `instanceParms` table (settable, real-valued);
- `DCTsetInstParam` sets each sweep value through the generic `DEVparam`
  interface and refreshes with `DEVtemperature` — for OSDI devices exactly
  the `alter` path (`setup_model` + `setup_instance` re-run);
- integrated into every arm of the sweep machinery: stop criterion,
  nested-level reset, per-step increment, plot scale (`param-sweep`),
  XSPICE event step, and end-of-sweep restore (the saved value is
  restored; the parameter necessarily stays marked "given");
- the previous value is captured with `DEVask` before the sweep.

Works for **any** device type: OSDI instance-kind parameters
(`.dc @n1[r] 1k 4k 1k` — I = 1/R exact at every point), built-in devices
(`.dc @r1[resistance]`), and **nested** with other sweep variables
(`.dc @n1[r] 1k 2k 1k V1 1 2 1` — inner level resets correctly).

New struct fields `TRCVvParmId` / `TRCVvNow` in `trcvdefs.h` (devices have
no generic readback field to consult mid-sweep).

## Gap 2 fixed: `.disto` warns instead of silently lying

Distortion analysis needs per-device Taylor coefficients (`DEVdisto`);
the OSDI ABI only exposes first derivatives, so OSDI nonlinearities are
invisible to `.disto` — and ngspice **skipped such devices without a
word**. A `.disto` run over an OSDI diode reported exactly 0.0 distortion
while the identical built-in-diode circuit reported 1.8e-6.

`CKTdisto.c` (`D_SETUP`) now prints a prominent warning for every OSDI
device type present in the circuit (recognized by the
`DEVpublic.registry_entry` marker that only OSDI device types carry):

```
Warning: Verilog-A (OSDI) device type 'odio' has no distortion model;
         .disto results will NOT include its nonlinearities.
```

The analysis still runs (results remain valid for circuits whose
nonlinear devices are all built-ins and whose OSDI content is linear).
Implementing real OSDI distortion would require higher-order derivatives
through the OSDI ABI — an order of magnitude beyond this enhancement's
scope, now documented instead of silent.

## Examples (`analyses_examples/`, 19 checks, ALL PASS)

`verify_analyses.py`: [1] `.tf` exact; [2] `.pz` exact + OSDI ≡ built-in;
[3] `.sens` DC + AC exact; [4] temp sweep exact; [5] **new** `@inst[param]`
sweeps (OSDI, built-in, nested); [6] alter/altermod/instance-line/readback
(including "altermod must not override a given instance value");
[7] **new** `.disto` warning + analysis completion.

The folder doubles as a **tutorial**: nine standalone, commented decks
(`tf.cir`, `pz.cir`, `sens_dc.cir`, `sens_ac.cir`, `temp_sweep.cir`,
`param_sweep.cir`, `nested_sweep.cir`, `alter.cir`, `disto.cir` — each
runnable with `ngspice -b <deck>.cir` and stating its expected numbers),
a walk-through README, and `plot_analyses.py`, which renders the sweep
results to `plots/`: `param_sweep.png` (the new `@n1[r]` sweep vs analytic
1/R), `nested_sweep.png` (the I = V/r curve family), `temp_sweep.png`
(1/R(T) overlay), and `ac_lowpass.png` (RC Bode plot with the `.pz` pole
at −3 dB and the `.sens ac` point at −45° marked).

## Regression

All version11 example verify suites pass (ngspice rebuilt); no compiler
change, so crate tests and the corpus stand as of Enhancement-61.
