# Enhancement-80 — temperature physics validation

Physcheck round 3: E-57 validated the **static** laws of compiled industry
models, E-75 the **charges** — this suite validates the **thermal axis**:
the `$temperature`/`$vt` plumbing, the OSDI instance temperature offset,
and the classic junction/MOS temperature laws, quantitatively.

## The laws (11 checks)

1. **`$vt` tracks kT/q** at every point of a `.dc temp -50..150` sweep
   (worst 10⁻⁷ — the documented E-59 constants-vintage residual).
2. **The instance temperature offset** — `dtemp=10` at temp=17 °C gives
   the *identical* current (12 digits) to a plain instance at 27 °C. This
   also pins **the fix**: OSDI instances used to accept only the
   unconventional spelling `dt`; the conventional `dtemp` (every built-in
   device's spelling) is now an alias.
3. **Thermal noise ∝ T** — the nres 4kT/R twin's output noise *power*
   ratio between 127 °C and 27 °C equals T₂/T₁ to 10⁻¹⁴ (ngspice spectra
   are amplitude densities — square before comparing!), and the
   OSDI ≡ built-in identity holds at the hot temperature.
4. **MEXTRAM 505 junction laws** — dV_BE/dT at 1 mA sits at −1.3…−1.5
   mV/K (the textbook window) across −25…125 °C, and the Arrhenius
   activation energy from I_C(T) is pair-consistent to 0.9% with an
   E_g estimate of 1.25 eV — silicon.
5. **PSP103's ZTC point** — dI_d/dT > 0 in weak inversion (V_th drop
   wins), < 0 in strong inversion (mobility wins): the sign flip that
   makes zero-temperature-coefficient biasing possible.
6. **The CMC default-off idiom, pinned** — diode_cmc's *default* card has
   |dV_f/dT| < 0.5 mV/K: corpus defaults are placeholders, not silicon
   (the E-56 lesson, now with a thermal check guarding it).

## Files

`verify_tempphys.py` (11 checks), `vtprobe.va` (V = `$vt`), `nres.va`
(the 4kT/R noisy resistor), `plot_tempphys.py` → `plots/thermal_laws.png`
(three panels: the kT/q line, the MEXTRAM V_BE(T) slope, the PSP103 ZTC
crossover).
