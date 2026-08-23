# Enhancement-467 — twelve silent acceptances

Twelve places where the deck said one thing and ngspice quietly did another.
None stopped a run; each produced a plausible number, or switched a feature off,
with no diagnostic.

```
python3 verify_silentaccept.py
```

44 checks, both linear solvers. `sa.va` supplies the four-bit bus models used by
the autobus and adapter checks.

## What is checked

| # | was | now |
|---|---|---|
| 1–3 | `set sqrnoise=1` / `interp=1` / `autostop=1` ignored | honoured, and `=0`/`=off` still off |
| 4 | `.option defas=` set the **drain** area | sets the source area |
| 5 | `.option defw=-1e-5` inverted every MOSFET | refused, with a reason |
| 6 | an instance `w=-1e-5` did the same | refused |
| 7 | `R1 ... temp=-300` answered −0.998 V from a +1 V source | refused |
| 8 | KiCad-spelled subcircuit formals left the device floating | connect |
| 9 | `.func sqrt(x)` silently replaced the built-in | warns, still wins |
| 10 | `.adapt nosuchnode` silently disabled adaptation | reported per member |
| 11 | an adapter model also used as a device model, likewise | reported |
| 12 | `meas` max/min/avg/rms/integ failed over a device-parameter `.dc` | all work |
| 13 | `alter @dm[is]` said "no such parameter is" | names the real cause |

## Why the checks look the way they do

Every one is a **differential** against a form of the same deck that already
worked — the bare option spelling beside `=1`, the bracket bus spelling beside
the KiCad one, the point measurements beside the window ones, a source sweep
beside a parameter sweep. A single-deck assertion could pass on a value that is
wrong for an unrelated reason; a differential cannot.

Each label also records the number the **pre-fix** binary produced, so the
suite documents the defect it pins rather than only the fix.

Roughly half the checks assert that something did **not** change. Those matter
as much as the rest: the boolean-option fix touches `cp_getvar` itself, which
around 110 readers depend on, and it has to leave `=0` meaning off, a positive
`defw` untouched, −25 °C an ordinary temperature, and E-462's bracket spelling
working exactly as its own suite requires.

## Note

Two candidates found in the same hunt are deliberately **absent** — they were
re-verified and are not defects. The instance wildcard `@#*[resistance]` was
thought to drop its writes; it does not, and the probe that suggested otherwise
measured a voltage-divider ratio, which is invariant when *every* resistor moves
together. Out-of-range vector indexing was thought to clamp silently; it warns.
Both are recorded in `enhancements_doc/Enhancement-467.md`.
