# Enhancement-485 — guards that detected a fault and used the bad value anyway

```
python3 verify_guardsweep.py
```

37 checks, well under a second. **24/37** against the pre-fix binary — 13 checks
discriminate.

## What it is

Round 49 hunted ngspice + OSDI for an hour. The frontend and OSDI paths came back
clean almost everywhere: the parameter, range, temperature, opvar and
state-restoration work of E-426/427/440/455/478/480 is all visibly firing. What it
found instead was one recurring shape, concentrated in the XSPICE code models:

> the code knows the input is unusable, says so, and then answers from it.

## The headline: a bail-out that was commented out

`xspice/cm/cmutil.c`, the shared limiter helper `cm_climit_fcn`:

```c
if (linear_range < 0.0) {
    printf("%s\n",climit_range_error);
/*      limited_out = 0.0; ... return;
*/  }
```

It could not simply be uncommented. Those five lines assign the **locals**, while
the out-parameters are written at the very end of the function — restoring them
verbatim would have left `*out_final` uninitialised, which is very likely why they
were disabled rather than repaired.

The repair fixes the *input* instead of abandoning the evaluation: `limit_range` is
a smoothing half-width, so clamping it to half the limit span leaves the thresholds
coincident — hard limiting at exactly the bounds the deck asked for, the only
reading that still honours them — and every downstream branch stays valid. Three
things follow, all checked:

| | before | after |
|---|---|---|
| `ilimit` output, rails ±1 | **24.48** | 0.437 |
| messages for one `op` | **26** | 1 |
| model named in the text | **"CLIMIT"** (no CLIMIT in the deck) | generic |

## The same shape, four more times

`limit`, `int` and `d_dt` never computed `linear_range` at all, so a `limit_range`
wider than half the span carried the output past the limits those blocks exist to
enforce — **silently**:

| model | range=0.1 | 5 | 99 | 1e6 |
|---|---|---|---|---|
| limit | 0.5 | 1.1125 | 24.5057 | 249999.75 |
| int | 0.0005 | 3.853 | 95.04 | — |
| d_dt | 1.0 | 1.0 | 24.25 | — |

E-468's own comment says it added its checks "as the CLIMIT sibling already does".
It ported two and not CLIMIT's actual one.

`pwl`'s monotonicity guard ended in `break`, which left only the **checking loop**;
the table was then built from the data just declared unusable, and `x=[0 2 1]`
answered 5.5 for an input of 0.5 — above the table's entire y range. It could not
`return` where it stood (`x`/`y` are `STATIC_VAR`-owned, so freeing would
double-free and not freeing would leave a half-built table), so the test moved
beside the `size_error` check it belongs with: before any allocation, refusing on
every evaluation exactly as a length mismatch is refused.

`hyst` and `slew` had no checks at all. An inverted `in_low`/`in_high` pair and a
`hyst` wider than the span both left the block dead at 0.0; a negative `rise_slope`
drove the output to −2.0 on a 0→1 pulse, and a zero slope disabled limiting
entirely.

## And three in the frontend

- **`sens ... ac` validated nothing** while `.ac` — in the same file — rejects the
  same arguments by name. A reversed range did not merely go unreported: it swept a
  **fabricated decade**, 1e6 → 1e7 ascending.
- **`disto`** reported "no such parameter on this device", a device fault it does
  not have, identically for two different sweep-argument faults. Both now share one
  validator that names the offending argument and the card.
- **`.include <a directory>`** and **`source <a directory>`** succeeded silently —
  `fopen()` on a directory succeeds on macOS, the BSDs and glibc — so the deck
  solved a different circuit (v(out) 1.0 instead of 0.5) with no diagnostic
  anywhere. `.lib` was already the guarded sibling.
- **`meas`** clamped a negative `FROM` correctly and then reported the window the
  user asked for rather than the one it used.

## The repair is the codebase's own pattern

`sine`, `square` and `triangle` already do **detect → report → substitute a safe
value** (`freq = 1e-16`), and `pwl`'s size check does **detect → report → return**.
These eight sites had fallen out of an established convention rather than lacking
one.

## What is deliberately NOT here

Three reported findings were withdrawn, one of them at fix time:

- **`sweep`'s negative step** is corrected on purpose — `com_sweep.c:2119` says so
  at the site: `/* fix an obvious sign slip */`. No change made.
- **XSPICE `Limits:` are enforced**, precisely ("Value 5 exceeds limit 0.5 for
  parameter 'input_domain'"); the hunt's filter simply did not match that wording.
- **`.nodeset` on an OSDI internal node** really is ignored; the apparent
  counter-evidence was a diagnostic **echoing the card**, which an unanchored value
  reader matched.

The suite's own `val()` is anchored to the start of a line and its `diagnostics()`
is unfiltered, for exactly those reasons.
