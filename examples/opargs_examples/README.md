# opargs_examples — operator-argument audit + `slew` fix (Enhancement-61)

A full-argument-form audit of the analog operators (LRM 4.5) and events
(LRM 5.10) — 22 probe forms, each verified **at runtime** (compiling proves
nothing about whether a trailing argument is honored) — using the committed
`openvaf-r` and `ngspice-46`.

## The defect found and fixed

**`slew(x, max_pos_rate, max_neg_rate)` ignored its input.** The LRM
(4.5.15) defines `max_neg_slew_rate` as a *negative* number; the lowering
negated it assuming a positive magnitude, so the LRM-conformant spelling
`slew(x, 1e6, -1e6)` produced a **positive lower clamp bound** — the
tracking loop `dy/dt = clamp(K·(x−y), lo, hi)` was forced to +1e6
unconditionally and the output ramped unboundedly past any target,
ignoring the input entirely. (`transition` shares the same loop but
converts rise/fall *times* into always-positive rates — which is why it
worked while `slew` didn't.) Fixed with sign-robust `|max_pos|` /
`−|max_neg|` bounds: exact for conformant inputs, tolerant of the legacy
positive-magnitude spelling.

## Verified working (runtime evidence, pinned here)

| form | evidence |
|---|---|
| `timer(start, period[, tol])` | fires exactly 5× in 1 µs |
| `$bound_step(5n)` | eval count 120 → 416 |
| `$limit` `"pnjlim"` / user fn (+ extra args) | stiff 5 V/1 Ω diode converges **directly** (raw model needs gmin stepping); exact op |
| `ac_stim("ac", mag, phase)` | V = j1000 exactly |
| `ddt`/`idt`/`idtmod` trailing abstol | exact at AC to 10 digits |
| toleranced `cross`/`above` | fire correctly |
| `transition` 4-arg ramp | exact midpoint — first runtime pin for this operator family |

## Run

```bash
python3 verify_opargs.py
```

16 checks, ALL PASS.
