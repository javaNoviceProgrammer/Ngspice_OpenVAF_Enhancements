# Enhancement-109 — `noise_table` / `noise_table_log` interpolation per the LRM

Gap-hunt round 7 turned to **event runtime semantics** and **noise-spectrum
shapes**. The event battery checked out exactly — a `timer(0, 100µs)` fires 16
times in a 1.55 ms transient, `cross(V, +1)` counts the two rising crossings of
a 1 kHz sine, and `last_crossing` reports the 1.0000 ms crossing time — and
`flicker_noise` reproduces its 1/f law to 7 digits. The **noise-table** battery,
however, found a real LRM violation in *both* table forms.

## The bugs

The LRM is precise about the two interpolation rules:

- **`noise_table`** (LRM 4.6.4.3): *"performs piecewise **linear**
  interpolation"* of the tabulated power over frequency, clamping to the
  endpoint powers outside the tabulated range.
- **`noise_table_log`** (LRM 4.6.4.4): same `(f, p)` input as `noise_table`
  (frequencies in Hz), but interpolated **log-log**:
  `P = 10^( log10 p1 + (log10 p2 − log10 p1) · (log10 f − log10 f1)/(log10 f2 − log10 f1) )`.

openvaf-r (from Enhancement-9) violated both. `NoiseTable::new` log10-ed the
frequency axis of a plain `noise_table` and the runtime interpolator keyed on
`log10(freq)` — so the power was interpolated linearly over **log-frequency**
(a lin-log hybrid). And `noise_table_log` stored its pairs raw against that same
`log10(freq)` key — effectively expecting the *input* frequencies to already be
log10 values, and interpolating the raw power rather than its logarithm. With a
table `{10 Hz: 1e-12, 1 kHz: 3e-12}`:

| form | at 100 Hz, LRM | measured (before) |
|---|---|---|
| `noise_table` | 1.182e-12 (linear in f) | 2e-12 (linear in log f) |
| `noise_table_log` (`{10: 1e-12, 1k: 1e-16}`) | 1e-14 (log-log) | 1e-12 — **flat** (mis-keyed input clamped to the first point) |

## The fix

Two files, keeping the existing unrolled piecewise-linear runtime interpolator
and changing only the coordinate systems:

- **`hir_lower/callbacks.rs`** (`NoiseTable::new`): a plain `noise_table` now
  stores `(f, p)` **raw**; `noise_table_log` stores `(log10 f, log10 p)`.
- **`osdi/load.rs`** (`build_noise_table_interp`): gains the `log` flag — the
  lookup key is the raw frequency for the linear form and `log10(freq)` for the
  log form, and the log form's interpolated `log10(P)` is mapped back with
  `10^v = exp(v·ln10)`. Endpoint clamping is unchanged in both forms.

The Enhancement-9 `noise_examples` suite — which had pinned the nonconformant
behaviour (its reference used log-f interpolation, and its `_log` deck fed a
log10-frequency column) — was updated to the LRM laws: the `_log` data file now
carries frequencies in Hz, and the references implement linear-in-f and log-log
respectively (all four spectra pass at ≤4e-9 relative error, and the two forms
agree at the tabulated nodes).

## Verification

`noisetable_examples` (9/9): a 1 mS device injects each table form, and the
`.noise` output spectrum is checked against the closed-form laws — the linear
form at 10/100/1000 Hz (at 100 Hz the LRM's 1.1818e-12, **not** the 2e-12 the
old lin-log gave), the log-log form at the same points (1e-14 at the log
midpoint), and endpoint clamping a decade outside the range on both sides. Full
regression: all verify suites (including the corrected `noise_examples`) plus
the OpenVAF integration tests remain green.
