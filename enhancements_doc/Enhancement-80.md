# Enhancement-80 — temperature physics validation + the `dtemp` alias

This document describes Enhancement-80: **physcheck round 3, the thermal
axis**. E-57 validated the static laws of compiled industry models, E-75
the charges; this suite validates temperature — the `$temperature`/`$vt`
plumbing, the OSDI instance temperature offset, and the classic
junction/MOS thermal laws, quantitatively. The audit found **one ngspice
defect** (fixed): OSDI instances rejected the conventional `dtemp`
instance parameter.

## The fix: `dtemp` on OSDI instance lines

The OSDI glue has full instance-temperature-offset plumbing
(`OsdiExtraInstData.dt`, honored by the temperature update), but the
synthetic instance parameter was registered under the name **`dt`** —
while every built-in ngspice device (R, C, diode, MOS, …) spells it
**`dtemp`**. `n1 a b mod dtemp=10` failed with *"unknown parameter
(dtemp)"*. One alias `IFparm` entry in `osdiinit.c` registers both
spellings; the identity is pinned to 12 digits: `dtemp=10` at
`temp=17` ≡ a plain instance at `temp=27` (and the historic `dt` still
works).

## The laws (`tempphys_examples/`, 11 checks, ALL PASS)

1. **`$vt` tracks kT/q** at all 21 points of a `.dc temp -50..150` sweep
   — worst 1.0×10⁻⁷, the documented E-59 constants-vintage residual.
2. **The `dtemp` identity** (above) — pinning the OsdiExtraInstData
   plumbing end-to-end through the temperature update.
3. **Thermal noise ∝ T**: the nres 4kT/R twin's output noise **power**
   ratio between 127 °C and 27 °C equals T₂/T₁ to **3.5×10⁻¹⁴**, and the
   OSDI ≡ built-in identity holds at the hot temperature (3×10⁻⁷). A
   units trap worth recording: ngspice noise spectra are **amplitude**
   densities (V/√Hz) — square before comparing against power laws.
4. **MEXTRAM 505 junction laws**: dV_BE/dT at 1 mA lands at
   **−1.3…−1.5 mV/K** (the textbook window) across −25…125 °C, and the
   Arrhenius activation energy extracted from I_C(T) at fixed V_BE is
   pair-consistent to **0.9%** with an E_g estimate of **1.25 eV** —
   silicon, recovered through the whole toolchain from a compiled
   compact model.
5. **PSP103's zero-temperature-coefficient point**: dI_d/dT **> 0** in
   weak inversion (the V_th drop wins) and **< 0** in strong inversion
   (mobility wins) — the sign flip that makes ZTC biasing possible.
6. **The CMC default-off idiom, thermally pinned**: diode_cmc's *default*
   card shows |dV_f/dT| < 0.5 mV/K and a near-zero activation energy —
   corpus defaults are placeholders, not silicon (the E-56 lesson; a
   naive "check the diode tempco at defaults" would chase a phantom
   defect).

`plot_tempphys.py` renders the three-panel figure: the kT/q line, the
MEXTRAM V_BE(T) slope (at 100 µA — the default card's tiny I_S puts 1 mA
into high injection where the cold-temperature op wobbles), and the
PSP103 ZTC crossover.

## Regression

ngspice rebuilt warning-free with the one-line alias; all 71 example
verify suites pass, the integration suite 28/28, the VA_TEST corpus
compiles 92/92 (compiler unchanged).
