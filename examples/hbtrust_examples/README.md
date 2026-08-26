# Enhancement-484 — a converged flag is not a correct answer

```
python3 verify_hbtrust.py
```

16 checks, ~2 s. **10/16** against the Enhancement-483 binary — 6 checks discriminate.

## What it is

Enhancement-483 made the harmonic-balance bound reachable (`set qpss_tol`) and
taught the Newton loop to recognise a stalled residual. It left a hole.

The **stall** path reported what it settled for — `STALLED above tol ... after a
532224607x reduction`. The **ordinary tolerance** path reported nothing. So a deck
that loosened the bound far enough had its solution accepted with a clean
`converged in 3 iterations` and no hint that anything was wrong.

It can be very wrong. On the two-tone FET amplifier in this suite,
`set qpss_tol=1e-1` at K=4 accepts a residual that came down by only ~100×, and
the third-order products land **6 dB out** — silently. That is worse than the
failure E-483 fixed, because a refusal is honest and a wrong number is not.

```
QPSS-HB: WARNING -- accepted at |F| = 4.982e-02, only a 101x reduction from
5.042e+00. tol = 1.0e-01 was loose enough to stop early; the harmonics may be
badly wrong. Tighten qpss_tol, or reduce K1/K2.
```

## The threshold is calibrated, not chosen

`QP_LOWRED_WARN` is deliberately a **different constant** from
`QP_STALL_ACCEPT`: one decides whether to accept a stalled residual at all, this
one decides whether to believe an accepted one.

Its value comes from measurement, and checks [3] and [4] are the measurement:

| run | reduction | OIP3 | vs the K=2 reference | warned? |
|---|---|---|---|---|
| `hb 2 2`, default | 5.3e8× | 33.976 dBm | reference | no |
| `hb 3 3`, `qpss_tol=1e-3` | 55345× | 33.944 dBm | **0.033 dB** | no |
| `hb 4 4`, `qpss_tol=1e-1` | 101× | 27.818 dBm | **6.16 dB** | **yes** |

[3] fails if the warned answer turns out to be fine; [4] fails if the threshold
drifts onto the good one. A warning that fires on a good answer is one people
learn to ignore — Enhancement-445's note — so the bar sits between the two
measured cases and the suite holds it there.

## What this does NOT claim

It does not test that `hb 4 4` gives a right answer, **because it does not**. The
Newton step degrades as harmonics are added on this device:

| K | reduction achieved |
|---|---|
| 2 | 5.3e8× |
| 3 | 7.8e4× |
| 4 | 1.5e2× |

That degradation is invariant to drive level (60 dB), `beta` (100×), `is` (to
zero), `alpha` (16×), `cgs`/`cgd` (to zero), the chokes and blocking caps (8
orders of impedance), the circuit topology, and the DFT oversampling (doubled).
`pss_csolve` has partial pivoting and `tmalloc` is `calloc`, so neither the solve
nor uninitialised memory explains it. It remains an open question in
`qp_build_matrix`'s harmonic-domain Jacobian.

What this enhancement guarantees is narrower and worth having on its own: **when
the solver cannot give a correct answer, it does not quietly give a wrong one.**

## Also in this fold

A `const char *` → `char *` qualifier fix in `com_qpss.c`. E-483's `qpss_knob()`
declared its name parameter `const`, while `cp_getvar` takes a non-const `char *`
— two discards-qualifiers warnings, which this project keeps at zero. Caught by
the `build-shared` rebuild, whose output I had been filtering to errors only.
