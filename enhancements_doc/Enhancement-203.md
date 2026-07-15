# Enhancement-203 — `.meas ac` gain / phase margin (+ batch `vdb`/`vp` fix)

ngspice's `.measure` is already broad — TRIG/TARG (with `VAL`/`RISE`/`FALL`/`CROSS`/
`LAST`/`TD`/`AT`), `FIND … WHEN`, `AVG`/`RMS`/`INTEG`/`DERIV`, `MIN`/`MAX`/`MIN_AT`/
`MAX_AT`/`PP`, `ERR`, and `param='…'`, across tran/ac/dc/sp. An audit against the
"richer TRIG/TARG, FIND…WHEN, integral/RMS/derivative, AC margins" wish-list found all
of those already present and working — **the one genuine gap was AC margins**.

## Why the manual recipe cannot work

The textbook way to measure margins with the existing primitives is

```
.meas ac pm FIND vp(out) WHEN vdb(out)=0     ; phase margin
.meas ac gm FIND vdb(out) WHEN vp(out)=-180  ; gain margin
```

but the gain-margin form **fails**: `vp()` returns the phase **wrapped** to (−180, 180].
On a loop whose true phase sweeps past −180° (any 3-pole-ish loop), the wrapped phase
jumps from ≈−179° straight to ≈+179° and **never equals −180°**, so `WHEN vp=-180`
reports "out of interval". You cannot find the phase crossover from wrapped phase.

## The new functions

Two first-class `.meas ac` functions, computed on the **unwrapped** phase:

```
.meas ac pm phase_margin v(loopgain)   ; PM = 180 + (unwrapped phase at |gain|=1, i.e. 0 dB)
.meas ac gm gain_margin  v(loopgain)   ; GM = -gain(dB) at the -180 deg phase crossover
```

Each prints the margin and its crossover frequency (`… at= <freq>`). The phase is
unwrapped by undoing the ±360° `atan2` jumps, the 0 dB gain crossover and the −180°
phase crossover are found by linear interpolation, and the crossover frequency is
interpolated in log space (log-spaced sweep). A loop with **no finite −180° crossover**
(a one- or two-pole loop — infinite gain margin) is reported as such, not as a bogus
number. Implemented in `com_measure2.c` (`measure_margin`, dispatched from `get_measure2`).

One subtlety worth noting: ngspice's phase (`vp`, and the measure `'p'` type) honors a
runtime `cx_degrees` flag that defaults to **radians**, so `radtodeg()` is a no-op by
default; the margin code therefore computes phase in degrees explicitly.

## Two bugs the work surfaced

- **`gettok_iv` truncated suffixed vectors.** The batch (dot-card) measure auto-save
  pass extracts each measured vector with `gettok_iv` (misc/`string.c`). It copied the
  leading `v`/`i`, then broke after the *first* following character on `n_paren == 0` —
  so `vdb(out)` became `vd` (and `vm`/`vp`/… were all truncated). The stray `vd` then
  failed to save ("can't parse 'vd'") and left the node unsaved, so a batch
  `.meas ac … vdb(out)` died with "no data saved for AC". Fixed to stop only once the
  parenthesised part has actually closed (`gettok_iv` is used *only* by measure, so the
  fix is contained). A companion `strip_ac_vec` reduces `vdb(out)` → `v(out)` so the
  base node is what gets `.save`d.

## Verification

[`examples/acmargin_examples/verify_acmargin.py`](../examples/acmargin_examples/verify_acmargin.py)
— 5 checks against **closed-form** loop gains (buffered one-pole sections, so the poles
sit exactly where placed): a stable 2-pole loop's phase margin matches analytic to <1°
(84.89° vs 84.89°) and its gain margin is correctly reported infinite; a 3-pole loop's
phase margin (−42.75°) *and* gain margin (−15.92 dB) both match the closed form exactly;
and a batch `.meas ac … vdb(out)` dot-card auto-saves the node and returns the right
value. Full example regression: 166/166.
