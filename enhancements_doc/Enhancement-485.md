# Enhancement-485 — guards that detected a fault and used the bad value anyway

Eight sites, seven files, one shape: the code establishes that its input is
unusable, says so, and then answers from it.

## Why

An hour-long hunt over ngspice + OSDI came back with the frontend and the OSDI
paths clean almost everywhere — parameter and range validation, `alter`/`altermod`,
every temperature path, opvars after all nine analyses, node collapse,
`$simparam`, the severity system tasks, timers, noise, `sens` values against
analytic, Sparse-vs-KLU, subcircuit parameter binding, `.tran`/`.four`/`spec`/`pz`
arguments: all correct, and the work of E-426/427/440/455/478/480 visibly firing.

The defects were concentrated in the XSPICE code models, and they were all the
same defect.

## The headline: a bail-out that was commented out

`xspice/cm/cmutil.c`, inside the shared limiter helper `cm_climit_fcn` that
`ilimit` calls:

```c
if (linear_range < 0.0) {
    printf("%s\n",climit_range_error);
/*      limited_out = 0.0;
    pout_pin = 0.0;
    pout_pcntl_lower = 0.0;
    pout_pcntl_upper = 0.0;
    return;
*/  }
```

The five lines that give the detection meaning are commented out, so the helper
detects the crossed linear range, announces it, and falls through into the
smoothing arithmetic anyway.

**They could not simply be restored.** They assign the *locals*; the
out-parameters are written at the end of the function, so an early `return` there
would have left `*out_final` and the three partials uninitialised. That is very
likely why they were disabled rather than repaired — and it is why this
enhancement fixes the input rather than abandoning the evaluation.

`limit_range` is a smoothing half-width. When twice it exceeds the limit span the
two thresholds cross and the parabolic arithmetic runs over an inverted region.
Clamping it to half the span leaves the thresholds coincident — hard limiting at
exactly the bounds the deck asked for, the only reading that still honours them —
and every downstream branch stays valid.

| | before | after |
|---|---|---|
| `ilimit` output, rails ±1, `v_pwr_range=99` | **24.48** | 0.437 |
| messages emitted for a single `op` | **26** | 1 |
| model named in the message | **"CLIMIT"**, in a deck with no CLIMIT | generic wording |

The 26 copies are the defect Enhancement-480 fixed for LIMIT's own messages; the
shared helper was never covered, and it is a raw `printf` with no instance context,
so the repair is a report-once flag rather than an INIT gate.

## The same shape, four more times

**`limit`, `int`, `d_dt`** never computed `linear_range` at all, so a `limit_range`
wider than half the span carried the output past the limits those blocks exist to
enforce — and all three declare `out_lower_limit`/`out_upper_limit` as *mandatory*
parameters, so this is a block leaving bounds the deck was required to state:

| model | 0.1 | 5 | 99 | 1e6 |
|---|---|---|---|---|
| limit | 0.5 | 1.1125 | 24.5057 | 249999.75 |
| int | 0.0005 | 3.853 | 95.04 | — |
| d_dt | 1.0 | 1.0 | 24.25 | — |

Silent throughout, and linear in `limit_range`, so unbounded. Enhancement-468's own
comment at `limit/cfunc.mod:149` says it added its checks "as the CLIMIT sibling
already does" — it ported the negative-range and inverted-limits ideas and not
CLIMIT's actual guard, which is this one.

**`pwl`**'s monotonicity guard — added by E-480 — ended in `break`, which leaves
only the *checking loop*. The code then built the interpolation table from the data
it had just declared unusable: `x_array=[0 2 1] y_array=[0 1 4]` at an input of 0.5
returned **5.5**, above the table's entire y range, after printing "x_array must
increase monotonically!".

It could not `return` where it stood: `x` and `y` are `STATIC_VAR`-owned and
released by the callback, so freeing there would double-free and not freeing would
leave a half-built table for every later evaluation. The test therefore moves to
sit beside the `size_error` check it belongs with — before any allocation, reading
the parameter directly, refusing on every evaluation exactly as a length mismatch
is refused, with the message gated on INIT so a rejected table costs one line
rather than one per iteration.

**`hyst`** and **`slew`** had no checks at all. An inverted `in_low`/`in_high` pair
and a `hyst` wider than the in_low..in_high span both left the block dead at 0.0
for every input; a negative `rise_slope` drove the output to −2.0 on a 0→1 pulse
and a zero slope disabled limiting entirely. A `Limits:` range in `ifspec.ifs`
cannot express a relationship between two parameters, which is why the declared
limits do not catch the inverted pair. Both are now reported once at INIT and
repaired to the nearest sane reading — the pair swapped, the half-width clamped,
the slope's magnitude used.

`slew`'s report is emitted from the INIT block rather than beside the repair,
because the repair sits inside the `MIF_TRAN` branch where INIT has already passed —
the same shape as the `TIME != 0` gate E-480 had to move out of LIMIT.

## And three in the frontend

**`sens ... ac` validated nothing.** `dot_sens` passed `numsteps`, `start` and
`stop` straight to `INPapName`, while `dot_ac` — in the same file — rejects both a
non-positive point count and a reversed range by name. A reversed range did not
merely go unreported: it swept a **fabricated decade**, 1e6 → 1e7 *ascending*, when
the deck asked for 1e6 down to 1.

**`disto`** refused the same arguments but reported `doAnalyses: no such parameter
on this device or parameter is missing` — a device fault it does not have, and the
same text for two different faults. Both cards now share one validator that names
the card and the offending argument.

**`.include <a directory>`** and **`source <a directory>`** succeeded in silence.
`fopen()` on a directory succeeds on macOS, the BSDs and glibc; the read then yields
nothing, so the include contributed an empty file and the deck solved a *different
circuit* — a divider whose second resistor lived in the include read v(out)=1.0
instead of 0.5, with no diagnostic anywhere in the output. A missing file was
already caught, and `.lib` refuses a directory outright; both paths now test that
the resolved path is a regular file, which is the property those checks assume.

**`meas`** clamped a negative `FROM` to the start of the data — the value it
returns is correct — and then reported the window the user asked for:

```
neg  =  8.01248e-01 from=  -1.00000e+00 to=  5.00000e-06
```

The same report corrects an over-range `TO`. The clamp now happens where `m_from`
is what the report prints, and it is announced.

## The repair is the codebase's own pattern

`sine`, `square` and `triangle` already do **detect → report → substitute a safe
value** (`if (freq <= 0) { cm_message_send(...); freq = 1e-16; }`), and `pwl`'s size
check does **detect → report → return**. These eight sites had fallen out of an
established convention rather than lacking one, which is what makes them defects
and not design.

## What this deliberately does NOT change

Three reported findings were withdrawn, one of them at fix time:

- **`sweep`'s negative step is corrected on purpose.** `com_sweep.c:2119` states it
  at the site: `if ((f1 - f0) * st < 0.0) st = -st;  /* fix an obvious sign slip */`
  — a documented convenience sitting directly above the zero-step refusal the hunt
  had called its guarded sibling. No change made.
- **XSPICE `Limits:` declarations ARE enforced**, precisely: `Value 5 exceeds limit
  0.5 for parameter 'input_domain' of model ...`. The hunt's diagnostic filter
  matched `error|warning|****` and that message contains none of those words.
- **`.nodeset` on an OSDI internal node really is ignored.** The apparent
  counter-evidence was the warning **echoing the card** (`Please check line
  .nodeset v(n1#mid)=0.5`), which an unanchored value reader matched.

The suite's helpers are written against those last two: `val()` is anchored to the
start of a line, and `diagnostics()` returns every non-routine line rather than
keyword matches.

## Verification

`examples/guardsweep_examples/verify_guardsweep.py` — **37/37**, well under a
second. Against the pre-fix binary the same suite scores **24/37**: thirteen checks
discriminate.

Every fix is paired with the control that must not move: a normal `limit_range`, a
well-formed `pwl` table, a normal hysteresis block and slew rate, a valid
`sens ... ac`, `sens ... dc` and `disto`, a real `.include`, and a `meas` whose
window was already legal — each verified to produce its previous value and, where
it did before, to stay silent.

Full regression **399/399**, both solvers. ngspice-only, no compiler change.
