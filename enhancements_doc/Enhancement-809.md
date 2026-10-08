# Enhancement-809: an interval measurement whose TO lies past the end of the data says the window was cut

**Scope:** D16 of the
[ngspice + OSDI hunt of 2026-10-08](../docs/bug_hunts/2026-10-08_ngspice-osdi-hierarchy-sweeps-events-and-outputs.md).
ngspice:
- `frontend/com_measure2.c`: new `e809_window_cut`, called after `avg`, `rms`, `integ`, `min`,
  `max`, `min_at`, `max_at` and `pp`; `pp`'s echo ends at the data's end.

`examples/osdislips_examples/` (section [15], seven checks). **ngspice only.**

**Suites:** [`osdislips_examples`](../examples/osdislips_examples/) 93 of 93 per solver (6 of the 7
in [15] fail on the E-795 binaries); the full sweep, 538 of 538.

## What was wrong

A model's `$finish` ended a `tran 10n 1u` at 0.503 µs. Then:

```
.meas tran vavg avg v(1) from=0 to=1u
vavg                =  7.54200e-01 from=  0.00000e+00 to=  5.02800e-07
```

The average covered [0, 0.503 µs], not the [0, 1 µs] asked for. E-485 already made the echo
print the window actually used. But a reader of `vavg` (a script, a `.meas param`, an optimizer
objective) gets a number for half the window, and nothing said so. `pp` echoed the requested
`to= 1.00000e-06`, a window it did not cover. A `when` or `find` past the end fails with "out of
interval", which is clear.

## The change

After an interval measurement, if TO was given and the data end before it (beyond rounding), a
warning:

```
Warning: measure vavg: the data end at 5.028e-07, before TO=1e-06; the avg covers the window up to 5.028e-07 only.
```

It applies to every analysis: `tran`, `ac`/`sp` on the frequency scale, and `dc` on its sweep
scale (either direction). `pp` now echoes the end of the data too, as the other kinds do since
E-485. Nothing is printed during `autostop`'s per-point checks. A window inside the data, or no
TO, says nothing.

## The checks

osdislips [15]:

- avg, rms, integ, max and pp: each warns that the data end at 5.028e-07, before TO=1e-06;
- pp's echo is the window used;
- a window inside the data, and one without TO, say nothing.

## Limits

- The warning is on stderr, beside the result rather than in the result line, so scripts that
  read `name = value` lines read the same lines as before.
