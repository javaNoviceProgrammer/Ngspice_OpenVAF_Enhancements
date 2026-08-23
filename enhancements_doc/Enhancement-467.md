# Enhancement-467 — eleven silent acceptances

Eleven places where a deck said one thing and ngspice quietly did another.
None of them stopped a run; each produced a plausible-looking number, or
silently switched a feature off, with no diagnostic at all.

They were found in a one-hour hunt over ngspice and OSDI. Four further
candidates are **not** here: re-verification showed they were not defects, and
one of those four was written, tested and then withdrawn when an existing suite
caught it. See *Withdrawn* at the end.

## 1–3. The option spellings that meant nothing

`set sqrnoise=1` reported noise in V/√Hz where the bare `set sqrnoise` gives
V²/Hz. `set interp=1` left 165 transient rows where the bare word interpolates
to 101. `set autostop=1` ran a transient to the end where the bare word stops at
the measurement.

The spelling decides the published **type**: `set interp` is a BOOL,
`set interp=1` a NUMBER, `set interp=true` a STRING. `cp_getvar`'s coercion
table converted between CP_NUM, CP_REAL and CP_STRING and **had no CP_BOOL case
at all**, so all ~110 `cp_getvar(..., CP_BOOL, NULL, 0)` readers in the tree saw
only the bare word and silently ignored the ordinary `=1`.

This is the root of a class that Enhancements 450, 451, 454 and 466 each
repaired at **one call site**: `e454_autobus_var()` and `autoadapt_mode()` are
hand-written cascades asking exactly this question. Answering it in `cp_getvar`
fixes every reader at once.

A number is on when non-zero, so `=0` stays FALSE exactly as before — the change
is confined to values that mean ON. A string is off only for the four
established off-words (`0`, `false`, `no`, `off`), the set E-454 published.

**The fix broke two existing tests, which is how it found its own hazard.** A
cascade that leads with CP_BOOL to mean *"was the bare flag given?"* worked only
because `cp_getvar` refused to coerce. With the coercion, a CP_BOOL probe
answers TRUE for `=debug` as well, and `autoadapt_mode()` returned "on, quiet"
before it could see the mode — swallowing both `.option autoadapt=debug` and the
unknown-value warning beside it. The cascade now reads the **string first**,
because the string is the only spelling that carries a mode. `e454_autobus_var()`
and `ticmarks` were checked against the same hazard and are unaffected: the
first answers a plain yes/no, the second probes CP_NUM ahead of CP_BOOL.

## 4. `.option defas=` set the drain area

```c
case OPT_DEFAS:
    task->TSKdefaultMosAD = val->rValue;   /* <- AD */
```

One word. `TSKdefaultMosAS` is a real field, initialised in `cktntask.c` and
printed by `option` in `com_option.c`; only this assignment named the wrong one.
So the **source-area default could never be set**, and asking for it silently
overwrote the **drain-area** default instead:

| | `@m1[ad]` | `@m1[as]` |
|---|---|---|
| `.option defas=7e-10` — before | **7e-10** | 0 |
| `.option defas=7e-10` — after | 0 | **7e-10** |

## 5–6. Negative geometry — written, then withdrawn

A negative width does not shrink a MOSFET, it **sign-inverts** its current:
`.option defw=-1e-5` gives `i(vd)` = +1.8e-04 where +1e-5 gives −1.8e-04, and an
instance `w=-1e-5` does the same. The hunt recorded both as silent.

They are not. **Enhancement-438's `.option warn_physics` already reports them** —
`instance 'm1' has w = -1e-05 -- a channel width cannot be negative` — by both
routes, the option default and the instance line. The finding was really "the
report is opt-in", and opt-in is E-438's deliberate design: it flags a strictly
negative value only, because these parameter names are shared across devices
where zero is the ordinary unset default, and warning six times on a healthy
circuit is the fastest way to get a diagnostic switched off.

A guard was nevertheless written here, in `INPdevParse` beside the temperature
one, warning and **ignoring** the value. **E-438's own suite caught it**: by
ignoring the value the guard removed it before the physics check could see it,
so the two checks that pin the negative-geometry report failed. The guard is
withdrawn; keeping the value is `warn_physics`'s contract and it is not this
enhancement's to change. The suite pins that contract instead.

## 7. Instance temperature below absolute zero

`.option temp=-300` has warned since Enhancement-426, and `osdi/osdisetup.c`
makes the same check for an OSDI instance. The per-instance knob on a
**built-in** device had no guard at all:

| | `v(out)` |
|---|---|
| `R1 in out 1k tc1=0.01` | 0.5 |
| `R1 ... temp=-300` | **−0.998** |
| `R1 ... temp=-1e6` | **−0.998** |
| `R1 ... dtemp=-400` | **−0.5** |

A negative absolute temperature drives the temperature factor negative, so the
resistance goes negative and a network of three positive-valued parts delivers a
negative voltage from a +1 V source.

The guard is in `INPdevParse`, the one place every built-in device's `name=value`
pairs are applied, so it covers all of them at once and warns-and-ignores like
`E426_BAD_OPT` does at option level. `dtemp` is a delta, so it is judged against
the ambient in force as the card is parsed. An ordinary sub-zero temperature is
untouched — −25 °C is not the line, absolute zero is.

## 8. The KiCad bit spelling, where the option never reached

Enhancement-462 made `.option autobus=kicad` spell a bit `a_0_` rather than
`a[0]`, because KiCad's SPICE exporter rewrites every bracket in a net name to an
underscore. INP2N learned the new spelling; the **subcircuit formal detection**
in `subckt.c` did not, and tested `o[len] == '['` in two places.

So a subcircuit whose formals are written the way KiCad actually emits them —
`.subckt s a_0_ a_1_ a_2_ a_3_ ...` — matched nothing, the bare `a` on the device
line stayed one token, and the device bound positionally with most of its
terminals floating: **v = 1.0 where the bracket spelling of the same circuit
gives 0.5238095**, and with no "not connected" warning, because every terminal
*was* connected — to nodes nothing else drives.

Two readers of one rule, for the third time in this feature (E-454, E-464, here).
Both now ask one function. The bracket spelling is **always** accepted, since the
option decides what INP2N *generates*, not how the user wrote the `.subckt` line;
the underscore spelling is accepted only when the option is on, so an ordinary
node called `foo_1_` is never mistaken for a bus bit by a deck that never asked
for the convention.

## 9. `.func` over a built-in

`.func sqrt(x) {x*2}` silently replaced the built-in for every expression in the
deck: `sqrt(500)*100` became 100000 instead of 2236.07. `ln` turned 621.46 into
150000; `abs` turned +1000 into −998.

The user's definition still wins — refusing would break any deck that
deliberately overrides one, and Enhancement-399 established that a fix must be no
wider than its evidence. What was missing is being told. The name is checked
against `fmathS`, the one list the evaluator itself consults, exported rather
than copied.

## 10–11. `.adapt` and the adapter model

The adapter **model** name was validated ("is not defined in this deck", "is not
an OSDI device"). The **node list** beside it was not checked at all, so one typo
switched the whole feature off and the deck answered the unadapted number:

| | `v(a[0])` | said |
|---|---|---|
| `.adapt b` | 0.7590361 | — |
| `.adapt nosuchnode` | **0.7560976** | **nothing** |
| `.adapt` (no names) | **0.7560976** | **nothing** |
| `.adapt 42` | **0.7560976** | **nothing** |

Naming a model that is *also* a device model as the adapter did the same. That
skip exists for idempotency — an already-adapted deck must not be adapted again,
`b_f` becoming `b_f_f` — so it is kept, and now distinguishes our own injected
`n_adapt<N>_` lines from a user device that happens to use the model.

Both are reported per member at Error level, never silenced by Enhancement-466's
quiet default: these are mistakes in the deck, not preferences about how much to
print. `.adapt b, nosuchnode` still adapts `b` and names only the member that
went nowhere.

## 12. `meas` over a `.dc` of a device parameter

Every **window** function failed:

```
Error: measure  f1  max(TRIG) : out of interval
```

max, min, avg, rms and integ, at any value range, even with an explicit
`from`/`to` matching the sweep exactly — while the **point** functions
(`find ... when`, `when`) worked on the very same plot, `when` correctly
returning 3000 as the resistance where `v(out)` = 0.25. So the sweep was plainly
usable and only the interval setup could not find its axis.

The scale lookup was a fixed list of four names — `v-sweep`, `i-sweep`,
`temp-sweep`, `res-sweep` — and a `.dc` of a device parameter (Enhancement-427)
names its scale **`param-sweep`**. `display` marks it as the plot's
`[default scale]`, so the data was never in doubt.

Adding a fifth name would fix today's case and leave the next sweep kind to fail
the same way, so the fixed list is now a fast path with the plot's own default
scale behind it. Written once and called from both `dc` branches — the list
appeared **twice**, which is how one of them could have been updated alone.

## 13. The diagnostic that named the wrong thing

`alter @dm[is]=4e-14` answered:

```
Error: no such parameter is.
```

But `is` plainly exists — `altermod @dm[is]` sets it and `@dm[is]` reads it back.
`dm` is a **model**, and `alter` looks only at instance parameters, so the lookup
failed for a reason the message never mentioned. It now says so, and names the
command that works. A genuinely absent parameter still reports as absent.

## Withdrawn

Four candidates from the same hunt are **not** fixed here:

- **The instance wildcard was said to drop `resistance` writes.** It does not.
  The probe measured `v(out)` of a voltage divider, and `@#*[resistance]` sets
  **every** resistor including the load, so the ratio is invariant under the very
  change being tested. Measuring the current instead shows it working exactly as
  documented: −5e−4 → −2.5e−4. The reported "frozen sweep curve", "accessor
  reporting a change that did not happen" and "dormant values flushing later"
  were all this one artifact. `temp` appeared to behave differently only because
  `tc1` was set on one resistor, which broke the symmetry.
- **Out-of-range vector indexing was said to clamp silently.** It warns —
  `Warning: upper limit 9 should be 4` — once per bound, for every out-of-range
  index.
- **A negative instance `w`/`l`**, and **a negative `defw`/`defl`/`defad`/
  `defas`** — see §5–6 above. Already reported by `.option warn_physics`; the
  guard written for them was withdrawn when E-438's suite caught it suppressing
  that report.

Three of the four were rejected by re-verifying the measurement, and the fourth
by the regression suite. Both are cheaper than shipping the fix.

## Verification

`examples/silentaccept_examples/verify_silentaccept.py` — **42/42**, both
solvers. Every check is a differential against a form of the same deck that
already worked, and each records the number the pre-fix binary produced.

Pinned unchanged alongside the fixes: `=0`/`=off` still mean off; a positive
`defw` is untouched and a negative one still reaches `warn_physics` with its
value intact; −25 °C is still an ordinary temperature; the bracket
spelling still works under `autobus=kicad` (E-462's suite); a non-builtin `.func`
name does not warn; `.adapt b` stays silent; `meas` over source and `temp` sweeps
is unchanged; the point functions are unchanged; `altermod` is unchanged.

Full regression: see the change report. ngspice-only — the compiler is untouched.
