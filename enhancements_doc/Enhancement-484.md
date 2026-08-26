# Enhancement-484 — a converged flag is not a correct answer

The harmonic-balance solver now reports the reduction behind an accepted
solution, so a bound loose enough to stop early cannot hand back a wrong answer
in silence.

## Why

[Enhancement-483](Enhancement-483.md) made the bound reachable (`set qpss_tol`)
and taught the Newton loop to recognise a stalled residual. It left a hole.

The **stall** path said what it settled for:

```
QPSS-HB: converged in 10 iterations, 1 continuation step (|F| = 9.429e-09,
STALLED above tol = 1.0e-10 after a 532224607x reduction -- accepted; ...)
```

The **ordinary tolerance** path said nothing. A deck that loosened the bound far
enough had its solution accepted with a clean `converged in 3 iterations`.

That is not hypothetical. On a two-tone FET amplifier, `set qpss_tol=1e-1` at
K=4 accepts a residual that came down by only about 100×, and the third-order
products land **6 dB out**:

| run | reduction | OIP3 |
|---|---|---|
| `hb 2 2`, default | 5.3e8× | 33.976 dBm |
| `hb 4 4`, `qpss_tol=1e-1` | 101× | **27.818 dBm** |

**This is worse than the failure E-483 fixed.** A refusal is honest; a wrong
number is not. E-483 turned a silent grind into an honest refusal, and in doing so
handed users a knob whose obvious misuse was silent corruption.

## What changed

Whenever a level is accepted on the ordinary `tol` test but the residual rests on
a poor reduction from that level's opening norm, the solver says so:

```
QPSS-HB: WARNING -- accepted at |F| = 4.982e-02, only a 101x reduction from
5.042e+00. tol = 1.0e-01 was loose enough to stop early; the harmonics may be
badly wrong. Tighten qpss_tol, or reduce K1/K2.
```

It names the residual, the reduction, the bound that permitted it, and the two
remedies. The spectrum is still printed — the run is not aborted, because the
user may know exactly what they are doing.

### The threshold is calibrated, not chosen

`QP_LOWRED_WARN` is deliberately a **different constant** from
`QP_STALL_ACCEPT`. One decides whether to accept a stalled residual at all; this
one decides whether to believe an accepted one. Conflating them would tie a
diagnostic to a control decision.

Its value comes from measurement:

| run | reduction | OIP3 | vs the K=2 reference | warned? |
|---|---|---|---|---|
| `hb 2 2`, default | 5.3e8× | 33.976 dBm | reference | no |
| `hb 3 3`, `qpss_tol=1e-3` | 55345× | 33.944 dBm | **0.033 dB** | no |
| `hb 4 4`, `qpss_tol=1e-1` | 101× | 27.818 dBm | **6.16 dB** | **yes** |

Check [3] fails if the warned answer turns out to be fine; check [4] fails if the
threshold drifts onto the good one. A warning that fires on a good answer is one
people learn to ignore — Enhancement-445's note about checks that teach the reader
to skip them — so the bar sits between the two measured cases and the suite holds
it there.

## What this deliberately does NOT claim

**`hb 4 4` still does not give a correct answer on that circuit, and this does not
fix it.** The Newton step degrades as harmonics are added:

| K | reduction achieved |
|---|---|
| 2 | 5.3e8× |
| 3 | 7.8e4× |
| 4 | 1.5e2× |

Ruled out by measurement, none of them the cause: drive amplitude (60 dB), `beta`
(100×), `is` (down to zero), `alpha` (16×), `cgs`/`cgd` (down to zero), the RF
chokes and blocking capacitors (8 orders of impedance spread), the circuit
topology (chokes and caps removed entirely gives the same curve), and the DFT
oversampling (doubled, bit-identical residuals). `pss_csolve` does partial
pivoting, and `tmalloc` is `calloc`, so neither the dense solve nor uninitialised
memory explains it. The remaining suspect is `qp_build_matrix`'s harmonic-domain
Jacobian, and settling that is a separate piece of work.

What this enhancement guarantees is narrower and worth having on its own: **when
the solver cannot give a correct answer, it does not quietly give a wrong one.**

The practical guidance for that circuit is unchanged — `hb 2 2` converges on its
own merits and yields OIP3 ≈ +34 dBm, and `hb 3 3` under `set qpss_tol=1e-3`
corroborates it to 0.03 dB.

## Also in this fold

A `const char *` → `char *` qualifier fix in `com_qpss.c`. E-483's `qpss_knob()`
declared its name parameter `const`, while `cp_getvar` takes a non-const
`char *`, producing two discards-qualifiers warnings at both call sites. This
project keeps its warning count at zero. It surfaced during the `build-shared`
rebuild, whose output had been filtered to errors only — the warnings were present
in the main build too and went unread.

## Verification

`examples/hbtrust_examples/verify_hbtrust.py` — **16/16**, about 2 s. Against the
Enhancement-483 binary the same suite scores **10/16**: six checks discriminate.

The suite pins the warning firing, its four content elements, that the warned
answer really is wrong (measured against the K=2 reference), that the good answer
really is right and is not warned, that the diode two-tone deck and E-483's stall
path are untouched, and that the spectrum is still emitted alongside the warning.

`hbconv` 23/23, `qpssleak`, `distoexact` both solvers, `plotorder` 25/25 and
`pzklu` 4/4 all pass unchanged. Full regression **398/398**, both solvers. ngspice-only, no
compiler change.
