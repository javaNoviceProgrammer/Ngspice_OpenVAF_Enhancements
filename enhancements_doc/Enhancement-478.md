# Enhancement-478 — the value a guard checks is the value that gets used

Five defects from bug-hunt round 46. Each is a check that was performed followed
by something *else* being used: a different parser, a different end of the range,
a different lookup, or a different loop's state.

## 1. A count was validated with one parser and consumed with another

```c
if (!sw_isfinitenum(a->wl_word, &dn) || ...)   /* validated as a FLOAT -- dn */
    return 0;
n = atoi(a->wl_word);                          /* consumed as an INT         */
if (n < 1) n = 1;                              /* and rewritten if absurd    */
```

`sw_isfinitenum` accepts `2e2` as 200 and `1e6` as 1000000. `atoi` stops at the
`'e'`:

| written | ran | the same number written out |
|---|---|---|
| `sweep lin 2e2` | **2 points** | `lin 200` → 200 points |
| `sweep lin 1e6` | **1 point** | `lin 1000000` → refused, "too many points" |
| `montecarlo 2e2` | **2 samples**, and a yield printed from them | `montecarlo 200` → 200 |
| `highsigma 2e2` | **2 samples** | `highsigma 200` → 200 |

The float the validator had already computed was discarded. Reading it instead
fixes every row: `2e2` is 200, and `1e6` now meets the existing cap rather than
slipping under it. Five sites read a count this way — sweep, montecarlo,
highsigma and wcd's `-maxiter` and `-is` — and they now share `sw_count_arg()`.

**The same block silently rewrote a count below 1.** `lin 0` and `lin -5` became
a one-point run; for `dec`/`oct` that silently changes the **spacing** rather
than the count, and on a `-vs` knob it collapses a sweep dimension to a single
value. Every sibling refuses this: `ac` ("number of points is invalid, must be
greater than…"), `dc` ("Bad syntax"), `tran` ("TSTEP is invalid"), montecarlo,
highsigma and wcd ("must be >= 2"), and `.for` names each malformed range. Now
`sweep` does too.

E-270's "too many points" wording is kept exactly, because `sweepbounds_examples`
pins it.

## 2. `spec` checked one end of its step and segfaulted on the other

```c
if (ft_numparse(&s, FALSE, &stepf) < 0 || stepf > stopf - startf)   /* upper only */
```

A negative step makes `fpts = (stopf - startf)/stepf + 1` negative, and that
count goes straight to the allocator:

```
spec 100 10k -100 v(b)   ->  Error: malloc: can't allocate -784 bytes.
spec 100 10k -1e9 v(b)   ->  SIGSEGV  (EXC_BAD_ACCESS at 0x0 in com_spec)
```

Deterministic, and present in the shipped binary — the NULL from the failed
allocation is taken into the fill loop. The guard now also requires the step to
be finite and positive. Zero goes with it: a zero step is an infinite point
count, caught below only by arithmetic accident.

## 3. Indexing a `@dev[param]` waveform returned the device's live value

```
length(@c1[i])   = 219          the vector is found
@c1[i][50]       = -2.1076e-07  <- that is element 218
@c1[i][218]      = -2.1076e-07  <- the same number, for every index
let z=@c1[i]; z[50] = 3.6497e-05   correct
```

`e448_literal_index()` builds the name `<base>[<k>]` and asks `vec_get()` for it.
For an ordinary base that is a clean miss — nothing is named `myvec[3]` — which
is exactly what makes Enhancement-448's probe safe for ordinary indexing. But
**`vec_get` answers a name beginning with `@` from the device rather than the
plot**, so `@c1[i][50]` was read as "parameter `i` of device `c1`", the trailing
index discarded, and the live value returned. Every element of a saved
device-parameter waveform read back as the value after the run — a plausible
number, silently, for any index.

The probe now declines an `@` base. Nothing legitimate is lost: no vector is ever
*named* `@dev[param][k]`, and Enhancement-441's array instance
`@r[2][resistance]` is unaffected because the lexer keeps that spelling in one
token, so it never reaches an index operator.

`length()`, `maximum()` and `wrdata` were always correct — they take the vector
whole and never build that name — which is why this went unnoticed.

## 4. `fourier` guarded the low end of the fundamental and not the high

A wavelength longer than the time span is refused. There was no test at the other
end, so a fundamental far above the sample rate printed a full report whose every
normalised magnitude was `nan`, summarised as `THD: nan %`, with no diagnostic.

This **warns rather than refuses**, on purpose: Enhancement-445 fixed the
overflow hole here (`1e400` → +INF is refused) and its suite pins that a large
but *finite* fundamental still runs. Refusing would break that recorded decision,
so the run stands and the `nan` is explained:

```
Warning: fundamental 1e+30 Hz has a period of 1e-30 s, below the 9.993e-07 s
this data samples -- the harmonics are not measurable and may read 0 or nan
```

## 5. A nested loop command took the progress line from the outer one

`sweep … -analysis "montecarlo …"` is legal, and the loop-progress state
(Enhancement-477) is a single set of statics. The inner `begin()` overwrote the
outer's label, total and index, and the inner `end()` cleared `outp_loop_active`
for both — so the outer sweep's bar vanished for the rest of the run and the line
was left reading `montecarlo: sample 6/6 [====] 100%` while the outer sweep still
had points to go.

A nested `begin()` is now counted and ignored, and its `end()` decrements, so the
**outer** loop keeps the line. That is the same reasoning that made this feature
not reuse the per-analysis bar in the first place: the inner loop restarts from
zero at every outer point, so it is not the progress worth showing.

Display only — the swept numbers were, and are, byte-identical with the bar on
and off.

## What this deliberately does not change

- **`.four 1e30` still runs** (§4).
- **`psd 0` still clamps its averaging count to 1** — because it *announces* it
  ("Number of averaged data points: 1"). Round 46 reported this as a sixth,
  silent clamp; that was wrong, and the report was wrong because the probe
  filtered for error/warning keywords while this is a plain informational line.
  A check pins it so it is not "fixed" later.

## Verification

`examples/guardmatch_examples/verify_guardmatch.py` — **21/21**. Against the
shipped pre-fix binary the same suite scores **4/21**, and the four that pass are
exactly the pinned decisions.

The checks target the *agreement* rather than the symptom: that two spellings of
one number are treated alike, that both ends of one range are, and that the
vector indexed is the vector named.

Full regression, both solvers. ngspice-only.
