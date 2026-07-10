# Enhancement-133 — quasi-periodic (two-tone) steady state (`qpss`)

A new command, **`qpss`**, computes the **two-tone / multi-fundamental steady-state
spectrum**: driven by two tones f1 and f2, it resolves the response into every
mixing product **k1·f1 + k2·f2**, including the third-order **intermodulation**
(IM3 at 2f1−f2 / 2f2−f1) that a single-tone AC or PSS analysis cannot show. This is
the workhorse of RF linearity characterisation — two-tone tests, IM3/IP3, spectral
regrowth.

```
qpss <expr> <f1> <f2> [periods] [maxorder]
```

- **`<expr>`** — the output to analyse, e.g. `v(out)`.
- **`<f1> <f2>`** — the two tone frequencies (the two-tone sources are in the
  netlist as ordinary `SIN` sources).
- **`periods`** — number of beat periods to run for the transient to settle
  (default 8); increase for high-Q circuits.
- **`maxorder`** — report products up to `|k1|+|k2| ≤ maxorder` (default 5).

Output is a labelled spectrum — each product's 2-D harmonic index `(k1,k2)`, its
frequency, magnitude and phase:

```
QPSS: two-tone steady state of v(out)
  f1 = 1e+08 Hz, f2 = 1.1e+08 Hz, beat fb = 1e+07 Hz; 4 beat periods, order <= 3
  (k1,k2)      frequency [Hz]        |value|         phase [deg]
  ( 1, 0)       1.000000e+08     1.124860e-03      -90.000   <- f1
  ( 0, 1)       1.100000e+08     1.124856e-03      -90.000   <- f2
  ( 2,-1)       9.000000e+07     3.749541e-04      -90.000   <- IM3 (2f1-f2)
  (-1, 2)       1.200000e+08     3.749499e-04      -90.000   <- IM3 (2f2-f1)
```

## Method

For two **commensurate** tones (a rational ratio, so they share a beat frequency
`fb = gcd(f1,f2)`) the circuit's steady state is periodic at `fb`. `qpss`:

1. auto-derives `fb` from the two tones (Euclidean algorithm on the reals);
2. runs an ordinary **transient** over `periods` beat periods (to reach steady
   state) at a step fine enough to resolve the highest reported harmonic;
3. takes the **last beat period** and evaluates the Fourier coefficient **directly
   at each exact intermod frequency** `k1·f1 + k2·f2` by trapezoidal integration
   (a direct DFT at the known frequencies — **exact** for commensurate tones, with
   no resampling or FFT-bin rounding);
4. labels each product by its 2-D harmonic index `(k1,k2)`.

This transient-sampling method is deliberately **not** a beat-frequency shooting
PSS: shooting is slow, needs reactive state, and here would integrate the whole
beat period per iteration. The transient runs once and is fast (~0.1 s for the
memoryless examples) and robust. As a front-end command it drives an ordinary
transient, so it is **independent of the linear solver** (KLU or Sparse) and works
with **built-in and OSDI/Verilog-A devices** alike.

## Verification

`verify_qpss.py` drives a memoryless weak nonlinearity `i = g1·v + g3·v³` with two
tones and checks the analytically-known two-tone products (11/11):

- **fundamentals / IM3 / 3f exact** — for a pure cubic (`g3=0.5`, A=0.1) the
  fundamentals are `1.125e-3`, the IM3 products `3.75e-4`, the third harmonics
  `1.25e-4`, matching `0.5·(A(sin+sin))³` to <2 %.
- **no even-order products** — an odd nonlinearity's `(-1,1)`, `(2,0)`, … terms are
  ~10⁻⁹ (correctly zero).
- **IP3 slope law** — with a linear+cubic mix, halving the drive drops the
  fundamental **2×** (slope 1) and the IM3 **8×** (slope 3) — the defining 3rd-order
  intermodulation behaviour.
- **beat-frequency derivation** — 100/110 MHz → `fb = 10 MHz`; 30/33 MHz → `fb = 3 MHz`.
- **OSDI / Verilog-A** — a compiled controlled cubic (`vacube.va`) gives the same
  fundamentals and IM3 as the built-in behavioural source.

## Files changed

| File | Change |
|---|---|
| `ngspice-46/src/frontend/com_qpss.c` / `.h` | new — the `qpss` command: derive fb, run the two-tone transient, direct-DFT the last beat period at each `k1·f1+k2·f2`, print the labelled 2-D spectrum |
| `ngspice-46/src/frontend/commands.c`, `com_commands.h`, `Makefile.am` (+`Makefile.in`) | register + build the command |
| `examples/qpss_examples/` | `verify_qpss.py`, `vacube.va` |

## Scope

Commensurate two-tone (multi-tone by extension) steady-state spectrum via transient
sampling, verified against the analytic intermodulation products and the IP3 slope
law, for built-in and OSDI devices. This covers the common two-tone-IMD /
linearity use case. Honest limitations and natural follow-ups: **incommensurate**
tones (an irrational ratio, no common period) need a true frequency-domain
**harmonic-balance** engine; because the tones here are commensurate, high-order
products can *fold* onto the same frequency (the reported `(k1,k2)` is the
lowest-order label at that frequency — unambiguous for the closely-spaced tones of
a real two-tone test); and a small-signal **QPAC** (periodic AC around the two-tone
point) would extend the suite as PAC did for PSS.
