# Enhancement-184 — sweep progress bar reaches 100%

A follow-up fix to the [Enhancement-129](Enhancement-129.md) sweep progress bar: the bar sometimes stopped short of 100% at the end of a run, e.g.

```
 Reference value :  1.32920e+03  [====================   ]  82%
No. of Data Rows : 101
```

## The cause

The "Reference value" status line is **throttled** — it is redrawn in place only when more than 0.25 s has elapsed since the last update (so a fast inner loop does not spend all its time printing). The final sweep point almost always lands *within* 0.25 s of the previous tick, so its print is skipped: the bar freezes at whatever the last throttled update showed (here 82%), and the run then prints "No. of Data Rows" on the next line. The bar reaching 100% was therefore never reliable — it only happened when the last point's timing happened to fall past a 0.25 s boundary.

## The fix

`outp_print_reference()` now records the latest reference value and a "a bar was shown this run" flag on every call. A new `outp_finish_reference()` is invoked from the two end-of-run sites (`fileEnd`, `plotEnd`) — immediately before the "No. of Data Rows" line — and, if a bar was shown, reprints it **full at 100%**, in place, using the sweep's *true* endpoint:

- **transient** → `CKTfinalTime`;
- **AC** → `ACstopFreq`; **noise** → `NstopFreq`;
- **DC** → the last swept source value.

So the closing frame is always, e.g.

```
 Reference value :  1.00000e+06  [========================] 100%
No. of Data Rows : 101
```

It is a one-shot per run (reset at analysis start and after firing), stays silent for analyses that never showed a bar (operating point, transfer function, …), and honors the same `ft_optimizing`/`ft_norefprint`/`cp_background` guards as the throttled line — so quiet/background/optimizer runs are unaffected, and nothing is written to the rawfile.

## Verification

`examples/progressbar_examples/verify_progressbar.py` — the existing 22-check suite, with the end-of-run assertion tightened from *"reaches near 100% (≥ 90 %)"* to **"reaches exactly 100%"** for all four swept analyses (tran / AC / DC / noise). That check was what let the 82 % case slip through before. Front-end output only, solver-independent (identical bytes under Sparse and KLU). Full example regression: 149/149.
