# noisetable_examples — `noise_table` / `noise_table_log` interpolation (Enhancement-109)

The two tabulated noise operators interpolate a spectral-power table `(f, p)`
between its points, and the LRM is precise about *how*:

- **`noise_table`** (LRM 4.6.4.3): piecewise-**linear** interpolation of the
  power over **frequency**.
- **`noise_table_log`** (LRM 4.6.4.4): same `(f, p)` input (frequencies in Hz),
  but interpolated **log-log** —
  `P = 10^( log10 p1 + (log10 p2 − log10 p1)·(log10 f − log10 f1)/(log10 f2 − log10 f1) )`.

Both clamp to the endpoint powers outside the tabulated range. Enhancement-109
corrected both: `noise_table` had interpolated linearly over `log10(f)` (a
lin-log hybrid), and `noise_table_log` had expected a `log10`-frequency input
column and interpolated the raw power — both nonconformant.

## What's here

`noisetable_demo.va` is a 1 mS conductor (so the output-noise PSD is
`S(f)·R²` with `R = 1 kΩ`) whose `kind` parameter selects the source:

- `kind=0` → `noise_table('{10, 1e-12, 1000, 3e-12}, "nt")` — linear-in-f; at
  100 Hz the LRM value is `1e-12 + 2e-12·(100−10)/(1000−10) = 1.1818e-12` (not
  the `2e-12` the old lin-log hybrid gave).
- `kind=1` → `noise_table_log('{10, 1e-12, 1000, 1e-16}, "ntl")` — log-log; at
  100 Hz (the log midpoint) the value is `sqrt(1e-12·1e-16) = 1e-14`.

## Verify

```
python3 verify_noisetable.py
```

Compiles the model and reads `onoise_spectrum` from ngspice `.noise` analysis,
checking the linear-in-f law at 10/100/1000 Hz, the log-log law at the same
points, and endpoint clamping a decade below and above the tabulated range. See
[`../../enhancements_doc/Enhancement-109.md`](../../enhancements_doc/Enhancement-109.md)
for the full write-up. Companion suite: [`../noise_examples/`](../noise_examples/)
(the E-9 origin suite, corrected to the same laws).
