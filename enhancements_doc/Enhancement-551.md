# Enhancement-551: `pyplot` ticks in engineering units, axes labelled by type, the deck's `*` off the title

**Scope:** improvement 3 of the `pyplot` review recorded in
[E-547](Enhancement-547.md). **ngspice only; the compiler is unchanged.**

**Suites:** [`pyplot_examples`](../examples/pyplot_examples/) 40 → 47,
reading the rendered tick texts as well as the script; the twelve suites that
exercise pyplot pass. Reference
[§5.2](../docs/internals/ngspice_internals/ngspice_pyplot.md).

## What was wrong

The default figure showed `0.0005, 0.0010` along an axis labelled `s`, `V`
on the other, and `* rc lowpass` for a title — the deck's comment marker
included.

## What changed

* **Engineering ticks.** Each axis is formatted by matplotlib's
  `EngFormatter` in the unit of the vector type it carries: `500 µs`,
  `1 ms`, `−500 mV`, `10 kHz`, `1 kΩ`. Only SI units take prefixes (s, Hz, V,
  A, W, F, C, Ω, S); dB, rad, Celsius and the noise densities stay plain
  numbers. The formatter is installed *after* the axis scale, because
  `set_xscale('log')` replaces whatever formatter was there.
* **Typed labels.** The default labels read `time [s]`, `voltage [V]`,
  `frequency [Hz]`, `decibel [dB]`; a mixed plot reads `voltage [V]` on the
  left and `current [A]` on the right. A label the user gives is kept
  verbatim, with the ticks still in the unit.
* **A clean title.** The default title drops the deck's leading `* `; a
  `title` given on the command is untouched.
* **`set pyplot_eng=off`** keeps plain tick numbers and the typed labels.
* The Bode frequency axis, the eye's folded time axis, a contour's axes and
  colour bar, and a histogram's value axis get the same ticks.

## Verification

| check | result |
|---|---|
| the default RC figure | `time [s]` / `voltage [V]`, ticks `500 µs` … `1 ms` and `−500 mV` … `1 V` |
| `v(out) i(v1)` | `voltage [V]` left, `current [A]` right, `µA` ticks on the twin |
| `xlabel "my x" ylabel "my y" title "my title"` | kept verbatim, ticks still in the unit |
| `pyplot_eng=off` | plain numbers, typed labels |
| `db(v(out)) xlog` | `decibel [dB]` with plain ticks, `10 kHz`-style ticks on the log axis |
| the deck's `* eng probe deck` | `eng probe deck` |
| `-fft` / `-hist` | `Frequency [Hz]` and `Magnitude [V]` / `voltage [V]` |
| `pyplot_examples` | 47 / 47, both solvers |
| full sweep | 455 of 455 |
