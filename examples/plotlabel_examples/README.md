# plotlabel_examples — Enhancement-282

`ft_agraf` (`src/frontend/plotting/agraf.c`) sizes its axis-label lines as
`maxy + margin + FUDGE + 1` (FUDGE = 7) and terminates them at the last byte. It
budgets the exponent width by formatting **0.0**:

```c
sprintf(buf, "%1.1e", 0.0);   /* expect 0.0e+00 */
shift = (int) strlen(buf) - 7;
```

`0.0` always has a 2-digit exponent, so the layout assumes two digits. Real data can
need three -- denormal or very large values give labels like `1.00e-320` (9 chars vs
8). The last label's `memcpy` then overwrites the line's terminating `'\0'`, and the
following `out_printf("%s\n%s\n", line2, line1)` reads past the heap buffer (ASan:
`heap-buffer-overflow READ of size 82` on an 81-byte region).

Fix: remember the allocation bound (`maxy` is reassigned later), clamp the label copy
to it, and re-assert the terminator. Rendering is byte-identical for ordinary data.

## Verify

```
python3 verify_plotlabel.py
```

Five checks: `asciiplot` of `1e-320`, `1e300`, `1e-300`, and both extremes together are
clean; an ordinary plot still renders its legend, axis and points.
