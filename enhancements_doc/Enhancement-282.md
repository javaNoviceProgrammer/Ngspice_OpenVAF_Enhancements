# Enhancement-282 — ngspice: `asciiplot` read past its axis-label buffer on a 3-digit exponent

Pursuing a lead left over from the Enhancement-279 audit — the `(int) floor(...)` casts
in the plotting code — turned up a different (and real) defect one layer over: an
axis-label buffer over-read in `ft_agraf`.

## The bug

`ft_agraf` (`src/frontend/plotting/agraf.c`) allocates its two axis-label lines as
`maxy + margin + FUDGE + 1` bytes (`FUDGE = 7`) and NUL-terminates them at the last
byte. It budgets for the exponent width like this:

```c
sprintf(buf, "%1.1e", 0.0);      /* expect 0.0e+00 */
shift = (int) strlen(buf) - 7;
```

Formatting **`0.0`** always yields a *2-digit* exponent, so `shift` is `0` and the
whole layout silently assumes two digits. Real data can need three: plotting denormal
or very large values produces labels like `1.00e-320` — 9 characters instead of 8. The
last label's

```c
memcpy(&line2[i + margin - ((j < 0) ? 2 : 1) - shift], buf, strlen(buf));
```

then runs one byte too far and overwrites `line2`'s terminating `'\0'`. The subsequent
`out_printf("%s\n%s\n", line2, line1)` therefore walks off the end of the heap
allocation — AddressSanitizer reports a `heap-buffer-overflow READ of size 82` on an
81-byte region, inside `vsnprintf`.

On the shipped build it does not necessarily fault: whether it prints heap garbage or
crashes depends entirely on what follows the buffer.

## Fix

`src/frontend/plotting/agraf.c`:

- remember the allocation bound in `line_end` — `maxy` is **reassigned** further down
  (`maxy = spacing * nsp`), so the bound cannot be recomputed at the label loop;
- clamp the label `memcpy` so it can never reach the terminator slot (and handle a
  negative offset);
- re-assert `line2[line_end] = '\0'` after the label loop.

Rendering is unchanged: for ordinary data the output is byte-for-byte identical to the
previous build.

## Verification

`examples/plotlabel_examples/verify_plotlabel.py` (5 checks): `asciiplot` of denormal
(`1e-320`), `1e300`, and `1e-300` data, and of both extremes together, are each clean
where they previously over-read; and an ordinary plot still renders its legend, axis
rule and points. Verified byte-identical rendering against the pre-fix binary.

## Scope

One source file (`src/frontend/plotting/agraf.c`). No change to any rendered plot.
