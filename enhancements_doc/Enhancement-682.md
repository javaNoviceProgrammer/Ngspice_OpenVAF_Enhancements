# Enhancement-682: `sens` over a current source no longer prints `GET ERROR` lines — the voltage-source-only pwl options were declared askable with nothing to ask

**Scope:** N2 of the
[bug hunt of 2026-09-21](../docs/bug_hunts/2026-09-21_ngspice-osdi-analyses-sens-and-events.md).
ngspice: `src/spicelib/devices/isrc/isrc.c` (`r` and `td` declared `IP`, settable and
not askable, as the voltage source declares its own).
`examples/sensrestore_examples/` (five checks, 21). **ngspice only.**

**Suites:** [`sensrestore_examples`](../examples/sensrestore_examples/) 21 of 21 per
solver, both solvers (3 of the 5 new checks fail on the E-680 binaries: the `GET ERROR`
lines, the two `show` rows, the seventeen-device sweep); `internalnode`, `sensstate`,
`senscplx`, `osdisens` unchanged; full sweep 531 of 531.

## What was wrong

Every `sens` in a deck with a current source printed, on stdout, in the middle of the
analysis:

```
GET ERROR: Isource:I:i1 -> param r (27)
GET ERROR: Isource:I:i1 -> param td (28)
```

three times per parameter per current source per sweep — twenty-four lines for two
sources and two sweeps. [E-447](Enhancement-447.md) had declared the pwl options `r`
(repeat) and `td` (delay), which exist for voltage sources only, on the current source so
that the card could refuse them by name ("pwl `r=` is not supported for current sources")
instead of the generic "unknown parameter". It declared them `IOP` — settable *and
askable* — but `ISRCask` has no case for them (there is nothing to ask: the card refuses
the value, nothing is ever stored), so an ask returns `E_BADPARM`. The sensitivity walk
(`cktsgen.c`) admits every parameter flagged `IF_SET | IF_ASK | IF_REAL`, asks it for
its base value, and prints the failure. The voltage source declares its `r` and `td`
`IP` — settable only — and was never walked for them. No other device has the gap: a
DC and an AC `sens` over seventeen device types (R, C, L, K, V, I, D, Q, M, J, E, G, F, H,
B, S) prints nothing else.

## What changed

**`r` and `td` are `IP` on the current source.** The walk no longer sees them, `show`
no longer lists them (they showed as unaskable), and the card keeps E-447's refusal
word for word. The sweep over the seventeen device types is quiet in DC and AC.

## Verification

| check | result |
|---|---|
| `sens v(nb)` over two current sources into a resistor | no `GET ERROR`/`SET ERROR` (was four lines per sweep) |
| the source's own sensitivity | `i1` = dv(nb)/dI1 = R1 = 1000, still reported |
| `show i1` | no `r`, no `td` row |
| `alter i1 r=1`, `alter i1 td=2` | E-447's refusal, twice, naming the reason |
| a DC and an AC `sens` over seventeen device types | no ask or set error; `r1` and `iin` reported |
| the E-680 binaries on the suite | 3 of the 5 new checks fail |
| full sweep | 531 of 531 |

## What this does not do

- The pwl `r`/`td` for current sources stay unimplemented; E-447's decision to refuse
  them by name is unchanged.
- The walk's `GET ERROR` print itself stays: it is right for a genuine ask failure, and
  nothing in the device tables raises one now.
