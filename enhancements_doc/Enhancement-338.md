# Enhancement-338 — a full 64-bit bus range hung ngspice and grew without bound

Found by fuzzing the array/bus node feature. One netlist line:

```
R1 a[-9223372036854775808:9223372036854775807] r=2k
```

ngspice never returned, and its resident memory climbed to **3.6 GB after 4 s and
7.6 GB after 9 s**. The released binary did the same.

## Root cause — the guard could not see the real width

Enhancement-221 expands a token `base[lo:hi]` into scalar node names, with a
deliberate ceiling so an absurd range is left literal rather than expanded:

```c
long width = (hi >= lo) ? (hi - lo + 1) : (lo - hi + 1);
if (width > BUS_MAX_WIDTH)          /* 8192 */
    return FALSE;
```

`strtol` saturates at `LONG_MIN`/`LONG_MAX`, so the full span yields
`hi - lo + 1` = `LONG_MAX - LONG_MIN + 1`, which **overflows a signed long**.
Signed overflow is undefined behaviour; in practice it wrapped to a small value,
so the guard saw a tiny width and let it through. The loop below then stepped
from `LONG_MIN` toward `LONG_MAX` — about 1.8e19 iterations, appending to a
string each time.

The guard was not missing. It was computing its input with the very overflow it
existed to prevent.

Only the **full** span triggers it. The one-sided cases —
`a[-9223372036854775808:0]` and `a[0:9223372036854775807]` — have a width around
9.2e18, which fits and is correctly rejected. That is why a fuzz corpus using
only *32-bit* extremes (`a[-2147483648:2147483647]`, width 4.29e9) missed it
entirely: that width is representable, so the guard worked.

## The fix

Compute the span in **unsigned** arithmetic, which is exact for every pair of
longs, and compare the span rather than the width so the `+ 1` cannot overflow
either:

```c
unsigned long span = (hi >= lo) ? ((unsigned long) hi - (unsigned long) lo)
                                : ((unsigned long) lo - (unsigned long) hi);
if (span >= (unsigned long) BUS_MAX_WIDTH)
    return FALSE;
```

`strtol` setting `ERANGE` now also rejects an endpoint too large to represent,
rather than letting it be silently clamped to `LONG_MIN`/`LONG_MAX` — values that
then look like an ordinary, acceptable range.

## Why this matters

A netlist is untrusted input. This is a resource-exhaustion defect reachable from
a single line, with no diagnostic and no bound.

## Fuzz and correctness campaign

**Fuzz — 432 decks, 0 crashes, hangs or runaway output.** 54 range tokens
(numeric extremes at 32- and 64-bit, malformed brackets, missing parts, nesting,
control characters, XSPICE `%vd[...]` groups, a 4000-character base name, 40-deep
bracket nesting) crossed with 8 placements (device nodes, subcircuit call,
`.subckt` port list, value position, model name, `print v()`, bare `print`, `let`).

**Correctness — 13/13.** The semantics the feature promises, checked numerically:

- ascending `a[0:1]` and **descending** `c[1:0]` map ports in the right order,
  verified through an **asymmetric** subcircuit (1 k on one port, 10 k on the
  other) so a reversed mapping changes the measured current rather than being
  invisible;
- `.subckt bus4 d[3:0]` expands descending and maps positionally across four
  ports (1 k / 2 k / 4 k / 8 k, each current distinct);
- `R1 a[0:1] 2k` is **one** resistor, not an array — series 2 k + 4 k gives
  0.5 mA;
- a bus element and an explicit scalar name are the **same** node;
- `v(a[0])` and bare `a[0]` resolve to the right node voltage (E-224), while
  ordinary vector indexing (`myvec[2]`) still works;
- non-integer `b[x:y]`, malformed `c[1:2:3]` and already-scalar `d[0]` are left
  untouched;
- the `BUS_MAX_WIDTH` boundary expands at width 8192 and stays literal at 8193.

## Files

- `ngspice-46/src/frontend/inpcom.c` — unsigned span, and `ERANGE` rejection.
- `examples/busoverflow_examples/` — every 64-bit extreme completes, ordinary
  buses still expand, and the guard boundary is intact
  (`verify_busoverflow.py`, 5 checks).
