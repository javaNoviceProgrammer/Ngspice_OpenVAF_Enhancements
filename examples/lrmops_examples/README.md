# lrmops — the analog operators against Accellera VAMS-2023 §4.5

[Enhancement-514](../../enhancements_doc/Enhancement-514.md). A clause-by-clause
audit of the LRM's analog operators; this suite pins the eight defects it found.

## What it checks

**The headline is one root cause with three faces**: a transient seeded its state
arrays with **zero** instead of with the converged operating point.

| clause | what it requires | what happened |
|---|---|---|
| 4.5.9 | `slew` *"returns the value of expr"* when the input is not moving | ramped up from 0 at the slew rate for `\|V_bias\|/rate` seconds |
| 4.5.7 | `Output(t) = Input(max(t-td, 0))`, i.e. `Input(0)` before one delay | read 0 for the whole first `td`, then stepped to the bias |
| 4.5.10 | `last_crossing` **negative** until the expression has crossed | returned 0.0, and a positive expression faked a crossing at t=0 |

Five smaller clauses come with them: `transition`'s `time_tol = 0` (4.5.8 defines
it, the compiler refused it), `idtmod(…,nature)` (Table 4-19 lists it, the
signature could never match), a negative `zi_*` transition time (4.5.12 forbids
it, it compiled), a zero-transition z-filter contributed directly to a branch
(4.5.12 forbids it, silent), and a `td` exceeding `maxdelay` (4.5.7 defines a
*substitution*; it was a hard error, so a conformant model was rejected).

## Why the inputs are biased

Every stimulus is deliberately **away from zero**. The defective state was seeded
with 0, and every stimulus in the pre-existing `absdelay`/`slew`/`transedge`/
`defaulttransition` suites starts at 0 — `PULSE(0 1 …)`, `PWL(0 0 1p 0 2p 1 …)`,
`dc 0` — which is precisely where a zero-seeded state is indistinguishable from a
correct one. That is why this went unseen; a suite that starts at zero cannot
catch it.

## Paired regression checks

Every state check has a partner asserting the operator still **does its job**, so
a fix that simply disabled the operator would fail loudly:

- `slew` still rate-limits a real edge to 0.55 V after 5.5 µs at 1e5 V/s
- `absdelay` still transports a 1→0 edge to arrive exactly one delay later
- `last_crossing` still times a real crossing at 5 µs
- `maxdelay` is still substituted for an over-long `td`

## Running

```bash
python3 verify_lrmops.py
```

**25 checks, both solvers.** On the shipped (pre-fix) binaries: **4/25**.
