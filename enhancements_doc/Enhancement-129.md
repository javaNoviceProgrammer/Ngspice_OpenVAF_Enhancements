# Enhancement-129 — sweep progress bar

A usability enhancement to ngspice's console output: the throttled
"Reference value" status line printed during a DC / AC / transient / noise sweep
now carries a **live progress bar and percentage**.

## Before / after

ngspice already printed, every 0.25 s and redrawn in place with a carriage return,
a status line showing the current sweep variable:

```
 Reference value :  5.91926e-04
```

It tells you *where* the sweep is but not *how far along*. E-129 appends a bar:

```
 Reference value :  5.91926e-04  [==================      ]  74%
```

## The fraction

The 0–1 completion fraction is computed per analysis, in `outitf.c`, from data
already on the circuit / job (`outp_progress_frac`):

- **transient** — elapsed time over the run: `(CKTtime − TSTART) / (TSTOP − TSTART)`;
- **AC** and **noise** — the current frequency's position in the sweep band,
  linear for `lin` or logarithmic for `dec`/`oct`:
  `log(f/f₀) / log(f₁/f₀)`;
- **DC** — the accepted-point count over the product of the nested sweep step
  counts (so it is correct for multi-source `.dc` nesting).

Analyses with no well-defined span (operating point, transfer function, …) return
−1 and keep the original plain line — no bar, no misinformation. The bar is a
fixed width so the in-place redraw never leaves stale characters, and it is emitted
through the same throttled, `!ft_norefprint && !cp_background` path as before (so
`-o` / background / `set nomodcheck`-style quiet runs are unaffected). It writes
only to the status line on stdout — never into the rawfile or `wrdata` output.

## Verification

`verify_progressbar.py` runs a long-enough sweep of each kind (past the 0.25 s
throttle), decodes the carriage-return-updated line, and checks (22/22):

- the bar (`[…] NN%`) is emitted for tran / AC / DC / noise;
- the printed percentage matches the analytic sweep fraction at that reference
  value — within 0.5 % across all four (transient linear-in-time, AC/noise
  log-in-frequency, DC linear-in-source);
- the bar fill length is proportional to the percentage;
- the percentages are monotone non-decreasing and reach ≈100 %;
- an operating-point run prints **no** bar (and still returns its result).

It is a front-end output feature, independent of the linear solver, so it is
checked once (the bytes are identical under Sparse and KLU).

## Files changed

| File | Change |
|---|---|
| `ngspice-46/src/frontend/outitf.c` | `outp_progress_frac()` (per-analysis 0–1 fraction) + `outp_print_reference()` (status line with bar); the six "Reference value" print sites now call the helper. Includes `acdefs.h` / `trcvdefs.h` for the AC/DC job structs |
| `examples/progressbar_examples/` | `progressbar_demo.cir`, `verify_progressbar.py` |

## Scope

Covers the four swept analyses (DC, AC, transient, noise); non-swept analyses are
untouched. A natural follow-up is a bar for the periodic-steady-state shooting
loop (`.pss` and the RF suite built on it), whose progress is the shooting-iteration
count rather than a swept reference variable.
