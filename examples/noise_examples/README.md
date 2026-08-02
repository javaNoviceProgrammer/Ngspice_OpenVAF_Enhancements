# Noise-source examples (version10, Enhancement-9)

Self-contained, analytically-verified examples for OpenVAF's Verilog-A
**noise analog operators**, exercised through ngspice `.noise` analysis:

| operator | file | status in the version10 baseline |
|---|---|---|
| `white_noise(pwr)` | `thermal_noise.va` | already worked (upstream) |
| `flicker_noise(pwr, exp)` | `flicker_noise.va` | already worked (upstream) |
| `noise_table("file")` / `noise_table(array)` | `table_noise.va` | **new in Enhancement-9** |
| `noise_table_log("file")` | `table_noise_log.va` | **new in Enhancement-9** |

Toolchain (version10, as required):

- compiler : `../OpenVAF-master-20260610/target/opt/openvaf-r`
- simulator: `../ngspice-46/build/src/ngspice` (locally built, OSDI-capable)

See `../Enhancement-9.md` for the full implementation write-up. In particular,
`noise_table`/`noise_table_log` **crashed the compiler** in the version9/version10
baseline (an `unimplemented!("noise tables")` in the OSDI backend plus a
placeholder table with no data); Enhancement-9 makes them read real data and
generate real interpolation code. `white_noise`/`flicker_noise` were already
fully functional and are included here as verified reference examples.

## The models

* **`thermal_noise.va`** — a resistor whose Johnson–Nyquist noise is modelled
  explicitly as `white_noise(4*k*T/R)`, a frequency-independent current-noise
  PSD.
* **`flicker_noise.va`** — a biased element with a white thermal floor plus a
  `flicker_noise(KF*|Ibias|^AF, EF)` term giving a `1/f^EF` low-frequency
  slope (module named `flicker_demo`, since `flicker_noise` is a reserved
  operator keyword).
* **`table_noise.va`** — reads a measured current-noise PSD from
  `noise_table.txt` via `noise_table("noise_table.txt", "measured")`.
* **`table_noise_log.va`** — reads the *same* spectrum from
  `noise_table_log.txt`, whose frequency column is stored as `log10(f)`.

### Table-file format and interpolation semantics

A `noise_table` data file is two whitespace-separated columns, `<frequency>
<power>` (blank lines and `#`/`//`/`*` comments ignored). The power column is
the current-noise PSD `S_i(f)` in `A^2/Hz`. The device evaluates it by
**piecewise-linear interpolation of the tabulated power over `log10(frequency)`**,
**clamped** to the first/last point outside the tabulated range. `noise_table`
takes linear frequencies (internally `log10`-ed); `noise_table_log` takes an
already-`log10(f)` first column — both interpolate in the same log-frequency
domain and return the same linear power, so `noise_table.txt` and
`noise_table_log.txt` here describe an identical spectrum.

An inline real array `noise_table({f0, p0, f1, p1, ...})` is also supported and
behaves identically to the file form (see `../Enhancement-9.md`).

## Running

```sh
../OpenVAF-master-20260610/target/opt/openvaf-r thermal_noise.va    -o thermal_noise.osdi
../OpenVAF-master-20260610/target/opt/openvaf-r flicker_noise.va    -o flicker_noise.osdi
../OpenVAF-master-20260610/target/opt/openvaf-r table_noise.va      -o table_noise.osdi
../OpenVAF-master-20260610/target/opt/openvaf-r table_noise_log.va  -o table_noise_log.osdi
../ngspice-46/build/src/ngspice -b thermal.cir     # -> thermal_onoise.txt
../ngspice-46/build/src/ngspice -b flicker.cir     # -> flicker_onoise.txt
../ngspice-46/build/src/ngspice -b table.cir       # -> table_onoise.txt
../ngspice-46/build/src/ngspice -b table_log.cir   # -> table_log_onoise.txt
python3 verify_noise.py                            # compiles+runs+verifies+plots
```

`verify_noise.py` does everything above (compile → simulate → verify → plot).
It exits non-zero if any spectrum disagrees with its closed-form analytical
value beyond tolerance.

## The test circuit

Each deck uses the same output-noise measurement topology:

```
V(in) --[ r1 = 1 kΩ ]-- V(out) --[ n1 = OSDI noise device ]-- gnd
```

`.temp 26.85` sets the circuit to exactly 300.00 K so that ngspice's own
resistor `r1` thermal noise and the model's `Temp=300` agree, allowing an exact
analytical comparison. The reported `onoise_spectrum` is the total output-noise
voltage density `√S_out(f)` in `V/√Hz`, with

```
S_out(f) = ( S_i,device(f) + 4kT/R1 ) · Zout² ,   Zout = R1 ‖ R_device .
```

## Verification results

`verify_noise.py` compares every swept frequency point against the analytical
`S_out(f)`:

```
white       : max relative error = 1.6e-07   PASS
flicker     : max relative error = 1.5e-07   PASS
table       : max relative error = 2.5e-09   PASS
table_log   : max relative error = 2.5e-09   PASS
table_log vs table: max |diff| = 0.0         PASS   (bit-identical)
```

The `table` check includes a non-trivial interpolated point: at `f = 1 kHz`
(`log10 f = 3`, midway between the `log10 f = 2` and `log10 f = 4` nodes) the
interpolated power is `1e-12 + (1e-16 − 1e-12)·(3−2)/(4−2) = 5.0005e-13`, giving
`onoise = √(5.0005e-13)·1000 ≈ 7.0714e-4 V/√Hz`, which ngspice reproduces as
`7.071414e-4`. Below `1 Hz` and above `10 kHz` the spectrum correctly clamps to
the endpoint values (visible as the flat regions in `noise_spectra.png`).

![noise spectra](noise_spectra.png)

Top-left: white (flat). Top-right: flicker `1/f` rolling off to the white
floor. Bottom-left: the interpolated table spectrum vs analytic. Bottom-right:
`noise_table_log` overlaid on `noise_table` (identical).
