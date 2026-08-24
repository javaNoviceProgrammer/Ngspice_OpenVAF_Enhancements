# Enhancement-478 — the value a guard checks is the value that gets used

```
python3 verify_guardmatch.py
```

21 checks, one solver (front-end argument handling; the numbers are unchanged).

## The shape

Five defects from bug-hunt round 46. In each, a check was performed and then
something *else* was used.

| | checked | used | result |
|---|---|---|---|
| counts | a float parser | `atoi()` | `lin 2e2` ran **2** points |
| `spec` step | against the span | as a divisor | negative → **SIGSEGV** |
| `@dev[param][k]` | `vec_get(name)` | the device, not the plot | every index the same value |
| `fourier` | wavelength vs span | period vs sample rate | silent `THD: nan %` |
| loop bar | `outp_loop_active` | a different loop's state | outer bar lost |

## The count defect is the clearest

```c
if (!sw_isfinitenum(a->wl_word, &dn) || ...)   /* validated as a FLOAT -- dn   */
    return 0;
n = atoi(a->wl_word);                          /* consumed as an INT -- and dn */
                                               /* is thrown away               */
```

`sw_isfinitenum` accepts `2e2` as 200 and `1e6` as 1000000. `atoi` stops at the
`'e'` and returns 2 and 1. So `sweep lin 2e2` ran 2 points, `montecarlo 2e2` drew
2 samples and printed a yield computed from them, and `sweep lin 1e6` ran **one**
point — while the identical number written `1000000` was correctly refused as
too many.

Five sites read a count this way (sweep, montecarlo, highsigma, wcd's `-maxiter`
and `-is`). They now share `sw_count_arg()`, which uses the value the validator
already produced.

The same block also silently rewrote `n < 1` to 1. For `lin` that is a 1-point
run; for `dec`/`oct` it silently changes the **spacing**, and on a `-vs` knob it
collapses a whole sweep dimension. Every sibling refuses this — `ac` ("number of
points is invalid"), `dc`, `tran`, montecarlo, highsigma, wcd and `.for` all name
it — and now so does `sweep`.

## The crash

`spec`'s guard read `stepf > stopf - startf` — the upper end only. A negative
step makes `fpts` negative, that count reaches the allocator, and the returned
NULL is dereferenced:

```
spec 100 10k -100  v(b)   ->  "can't allocate -784 bytes"
spec 100 10k -1e9  v(b)   ->  SIGSEGV (EXC_BAD_ACCESS at 0x0 in com_spec)
```

Deterministic, and present in the shipped binary. `[9a]`–`[9c]` pin all three
magnitudes; `[12]` pins that a positive step is untouched.

## Why the subscript returned the same number every time

`e448_literal_index()` builds the name `<base>[<k>]` and asks `vec_get()` for it.
For an ordinary base that is a clean miss — nothing is called `myvec[3]` — which
is what makes E-448's probe safe. But **`vec_get` answers a name beginning with
`@` from the device, not from the plot**, so `@c1[i][50]` was read as "parameter
`i` of device `c1`", the index discarded, and the live value returned. Every
element of a saved waveform read back as the value after the run.

`length()`, `maximum()` and `wrdata` were always right — they take the vector
whole and never build that name — which is why this survived. `[18]` pins them.

## What must NOT be "fixed"

- **`.four 1e30` still runs.** Enhancement-445 fixed the overflow hole here and
  its suite pins that a large but finite fundamental is accepted. This adds a
  warning so the `nan` is explained; refusing would break that decision.
  `[13]`/`[14]`.
- **`psd 0` still clamps to 1** — because it *announces* it
  ("Number of averaged data points: 1"). Round 46 reported this as a silent
  clamp and was wrong: the probe filtered for error/warning keywords and this is
  a plain informational line. `[15]` pins it.

## Harness note

Three of round 46's findings were withdrawn for the same reason this suite
checks agreements rather than symptoms: a row that began `nan` was dropped by a
regex expecting a digit, a diagnostic was missed by printing only the first
seven lines, and a column index was read as the wrong column. When a probe says
"silent", widen the filter before believing it.
