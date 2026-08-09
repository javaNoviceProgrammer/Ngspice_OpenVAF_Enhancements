# sweepparam_examples — Enhancement-427

A swept parameter value the device refused, and an event that landed on the last
timepoint.

```
python3 verify_sweepparam.py
```

32 checks. Every boundary is pinned from **both** sides — the refusals *and* the
legitimate sweeps that must keep working. Two of the five round-34 findings
changed shape once they were measured properly, and one was withdrawn outright.

| | what happened | what it produced |
|---|---|---|
| 1 | `dc @n1[r] -2000 -1000 500` on `r ... from (0:inf)` | three rows at R = **−2000, −1500, −1000**, rc = 0 |
| 2 | `dc @n1[k] 0 1 0.25` on `k ... from [0:1]` | five correct rows **plus** a spurious "out of bounds" |
| 3 | `@(timer(0,1e-8))` over `tran ... 1e-6` | **100** ticks where 101 were due |
| 4 | `dc @n1[n] 1 4 1` on `parameter integer n` | *"…named "`@n1[n]`" is not in the circuit"* — every clause false |

## The two that are easy to get wrong

**The sweep sets one value past `stop`.** It advances, then tests the stop
criterion, so a sweep ending exactly at a range edge steps outside it. That
spurious "out of bounds" predates this enhancement — and the first version of the
fix turned that valid sweep into a hard error. Both directions are pinned here.

**The rejection test keys on the device, never on the value.** A negative
resistance is legitimate for a built-in resistor, so
`dc @r1[resistance] -2000 -1000 500` still yields its three rows. That case is a
check in this suite precisely so nobody "tidies" the guard into a sign test.

## What must keep working, and is checked here

* real sweeps: multi-point, single-point, nested, and the value restored afterwards
* a sweep ending exactly **at** the edge of a `from` range — no complaint, all rows
* a **built-in** resistor swept negative (E-426 established this is supported)
* integer sweeps over whole numbers; a fractional one refused rather than
  publishing duplicate points under an abscissa that disagrees with the device
* the timer cases that were always correct (dt = 5e-9, 1e-7, 1e-9), and a `tstop`
  just *before* the last event still giving one fewer
* `.ic` on a device-internal node failing for a **built-in** diode too — a
  uniform limitation, not an OSDI gap, pinned so it is not misread as a
  regression later

## Note on the harness

`rows()` is told how many columns to expect. A reader that guesses scores a
single-row plot, and a three-column sweep table, as "no output" — which is how
two round-34 leads were briefly mis-scored before being withdrawn.
