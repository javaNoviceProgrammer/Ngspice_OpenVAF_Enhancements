# Enhancement-475 — a stated value is honoured or refused, never replaced

```
python3 verify_explicitvalue.py
```

41 checks, both linear solvers.

## The shape

Seven defects from bug-hunt round 44, all the same shape: something the deck
said was discarded and something else quietly put in its place, or a refusal
named a fault other than the one it found. None raised an error.

| | before | after |
|---|---|---|
| `sin(0 1 0)` | one cycle per simulation — frequency = 1/TSTOP | DC |
| `X1 a 0 div rr=5k` (subckt declares `r`) | silently 1 kΩ, the default | warned, still the default |
| a failed `meas` into an existing name | the previous value stayed readable | the name is dropped |
| `tran … 0 -1u` (negative TMAX) | "singular matrix: check node b" | "TMAX is invalid" |
| `pivtol`/`pivrel`/`minbreak`/`srcsteps`/`gminsteps`/`ramptime` | nonsense accepted silently | refused, like their siblings |
| any unevaluable `{{ }}` | "outside any .for loop" — 13 ways | names the expression |
| nested `.for` reusing the index | "device already exists" | names the shadowing |

The last two are defects in Enhancement-474, shipped hours earlier, and
contradict its own rule that one fault gives one message pointing at the mistake.

## Why the oracle sweeps TSTOP

A default quietly standing in for a stated value **is invisible if you look at
one run**. `sin(0 1 0)` produces a perfectly reasonable sine; only when the
simulation is lengthened does it become a different sine. So the checks vary the
thing the default is drawn from — TSTOP for the frequency, the timestep for the
control cases — rather than asserting a single number.

For the subcircuit, the oracle is the current the circuit actually draws
(`i(v1) = -1/2r`), because `v(b)` in the obvious test deck is set by the
surrounding divider and would have been blind to the parameter entirely.

## What must NOT be "fixed"

Three findings from the same round look exactly like these and are recorded
decisions. Checks `[20]`–`[22]` pin them:

- **negative R/C/L** stay unflagged — E-438: *"negative passives are the very
  idiom this project's own examples use"*
- **`pow(-4,0.5)` = 2** and **`1/0` = 1e32** — E-256/446 chose finite over NaN,
  *"because a NaN here poisons the Newton Jacobian"*
- **`pulse tr=0` takes the timestep** — documented in a comment above the code;
  unlike a frequency, a zero rise time has no meaning for an integrator

Each was re-confirmed by reading the code rather than the behaviour. That is the
difference between this list and the seven that were fixed.

## Harness notes

Three of this suite's own first-run failures were the harness: a body without a
trailing newline glued `.control` onto the last element line (so three decks ran
malformed), and one check compared two `None`s and called that agreement.
`run()` now forces the newline, and `[4]` asserts a real waveform.

`diagnosed()` is deliberately case-**insensitive** — ngspice writes both
`Warning` and `WARNING - …`, and a case-sensitive filter reported a guarded
option as silent during the hunt.
