# inputguard_examples — Enhancement-426

Inputs ngspice accepted without ever checking them, and the confident wrong
answers that followed.

```
python3 verify_inputguard.py
```

88 checks. Every one is measured as a number, and **every boundary is pinned
from both sides** — the refusals *and* the legitimate spellings that must keep
working. That second half is the point of the suite: three proposed fixes were
killed during review because they would have rejected something real.

| | what was accepted | what it produced |
|---|---|---|
| 1 | a mistyped output node, in the session's first analysis | `tf v(a,nosuch)` = **1.0**; `sens` all `-0.0`; `onoise_total` = 0.0 — and a heap read at `3.999110e+252` |
| 2 | `ac dec 10 100k 1k` | a *different* sweep: 31 points over 1e5…1e8 |
| 2 | `noise` with an inverted range | `onoise_total = 0.0`, from a loop that never ran |
| 2 | `.dc` with a step pointing away from stop | a plot containing no vector |
| 3 | `meas MAX @dev[param]` without a `.save` | the one-point snapshot, reported as the maximum |
| 4 | `temp = -500` | a **negative** thermal voltage, `$vt = -0.0195 V` |
| 5 | `itl2 = 0` | 736,920 Newton iterations instead of 55 |
| 6 | `m = -1` | a 2 kΩ resistor stamping **−2000 Ω** |
| 7 | `1e400` | `inf` — a resistor silently became an open circuit |
| 8 | a failing OSDI `setup_model` followed by a good one | SIGSEGV, zero bytes of output |

## What must keep working, and is checked here

* equal sweep endpoints — 19 `.ac`, 4 `.noise`, 9 `.sp` cards in this repo
* `dc v1 1 1 1` (single point, 13 decks) and `dc v1 2 0 -0.5` (descending, 2 decks)
* `m=0` — the ordinary "disable this instance" idiom, deliberately left silent
* `itl6=0` — a table **synonym** for `srcsteps`, documented, 4 decks rely on it
* `temp=-25` — ordinary; the line is absolute zero, not freezing
* `1k2`, `2meg5`, `1e5x`, `1kk`, `0x10`, `5kohms` — documented scale-factor forms
* a `.tf` card placed **before** the devices that define its nodes (E-349's case)
* `@r1[resistance]` still returning the nominal value it was given

## Note on the harness

`run()` captures **stdout and stderr together**, deliberately. ngspice writes its
own `$finish`/`$stop` Notes to stdout while the OSDI log callback writes
WARN/ERR/FATAL to stderr — a check that watches one stream scores the other as
silent, which is exactly how the original report came to claim `$finish` printed
nothing.
