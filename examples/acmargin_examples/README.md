# `.meas ac` gain / phase margin (Enhancement-203)

ngspice's `.measure` already covers TRIG/TARG, FIND…WHEN, AVG/RMS/INTEG/DERIV, MIN/MAX,
PP, ERR, and `param='…'`. The one loop-stability quantity it lacked was **AC margins**.
There was no `gain_margin` / `phase_margin` function, and the manual recipe

```
.meas ac gm FIND vdb(out) WHEN vp(out)=-180    ← cannot work
```

**fails**, because `vp()` is wrapped to (−180, 180] — the phase never actually equals
−180°, so the crossover is never found.

This adds two `.meas ac` functions, computed on the **unwrapped** phase:

```
.meas ac pm phase_margin v(loopgain)    ; PM = 180 + phase at the 0 dB gain crossover
.meas ac gm gain_margin  v(loopgain)    ; GM = -gain(dB) at the -180 deg phase crossover
```

Each reports the margin and its crossover frequency (`… at= <freq>`). A loop with no
finite −180° crossover (e.g. a one- or two-pole loop, infinite gain margin) is reported
as such rather than as a bogus number.

Also fixed here: a batch (dot-card) `.meas ac … vdb(out)` used to mis-parse the `db`
suffix in the auto-save pass ("can't parse 'vd'") and leave the node unsaved → "no data
saved for AC". `vdb`/`vp`/`vm`/… now save the base `v(…)` correctly.

## Verification

`verify_acmargin.py` — 5 checks against **closed-form** loop gains (buffered one-pole
sections, so the poles sit exactly where placed): a stable 2-pole loop's phase margin
matches analytic to <1° (and its gain margin is correctly reported infinite); a 3-pole
loop's phase *and* gain margin both match the closed form; and a batch `.meas ac
vdb(out)` dot-card runs and returns the right value.

## Running

```sh
python3 verify_acmargin.py
```
