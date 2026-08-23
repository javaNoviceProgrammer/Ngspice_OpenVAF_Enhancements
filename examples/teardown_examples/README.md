# Enhancement-470 — OSDI teardown was quadratic

```
python3 verify_teardown.py
```

11 checks, both linear solvers. `rint.va` is a two-terminal device with one
**internal** node, so a chain of N instances gives the teardown N nodes to
delete — which is the whole point.

## What was wrong

`CKTdltNNum()` finds its node by scanning the circuit's node list from the head,
and `OSDIunsetup()` calls it once per internal node: O(k·N). Every repeated
analysis pays it. A profile of a 1001-point sweep over a 2448-unknown circuit
found **77% of the entire run** in it — in the teardown *between* points, not in
the solve or the setup.

Now the caller marks every number it wants gone and one walk of the list removes
them all.

| stack periods | before | after | |
|---|---|---|---|
| 5 | 1.7 ms/pt | 1.2 ms/pt | 1.4× |
| 10 | 4.0 ms/pt | 2.3 ms/pt | 1.8× |
| 25 (2448 unknowns) | 32.9 ms/pt | 7.6 ms/pt | **4.3×** |

Full deck: 29.78 s → 7.12 s, byte-identical results.

## Why most of the suite is not about speed

A teardown that frees the wrong node, frees one twice, or leaves one behind
would corrupt the **next** analysis rather than fail loudly. So nine of the
eleven checks are about the numbers and the bookkeeping: analytic ladder
voltages, three `op`s giving the identical answer, a sweep matching `op`s taken
by hand at the same settings, the same N internal nodes appearing each cycle
instead of accumulating, an internal node holding its value across cycles, and
five cycles raising no error.

The two timing checks assert **scaling** — doubling the instance count must cost
well under 4× per point — not milliseconds, which would only measure the
machine.

## A note on the internal node

`n0#mid` is legitimately visible in the plot, exactly as `q1#collector` is for a
BJT. An early draft of this suite asserted it should *not* appear and failed;
what actually matters is that it appears **once per analysis, not once per
setup cycle**, which is what check 6 pins.
