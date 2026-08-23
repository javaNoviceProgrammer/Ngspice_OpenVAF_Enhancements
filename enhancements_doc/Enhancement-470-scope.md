# Enhancement-470 (scope) — move `sweep`'s loop into the analysis kernel

**Status: scoped, not implemented.** This is a design note, written from
measurements on a 2448-unknown dielectric-stack deck.

## The observation

`.dc` and `sweep` differ in *where the point loop runs*, and on a large circuit
that is worth two orders of magnitude:

| same circuit, sweeping the source `Vin0`, 501 points | per point |
|---|---|
| `.dc Vin0 1.0 1.5 0.001` | **0.32 ms** |
| `sweep Vin0 lin 501 1.0 1.5` | **33.96 ms** |

`.dc` loops inside `CKTdcTrCurv`: the matrix is built and factored once, and a
source change touches only the right-hand side, so each point is a
back-substitution. `sweep` issues a fresh `op` per point from the frontend —
full setup, rebuild, re-factor.

On a trivial circuit the two are indistinguishable (0.02 vs 0.03 ms/point), so
this is not per-point bookkeeping overhead; it is work proportional to the
circuit that `.dc` does once and `sweep` repeats.

## What this would and would not buy

It would **not** buy the 100×. That figure comes from the matrix being
*invariant* under a source change. The knobs `sweep` exists for — model and
instance parameters — change device admittances, so the matrix changes at every
point and re-factorisation is unavoidable.

What it would buy is the per-point **setup** cost. Measured on the same deck:

- one `op` analysis, reported by `option acct`: **9.4 ms**
- one sweep point: **~30 ms**

so roughly 20 ms/point is setup that a kernel-internal loop would do once.
A 1001-point wavelength sweep would plausibly fall from ~30 s to ~10 s. That
estimate is the honest bound of what I can claim from measurement; the split
between "re-setup" and "rebuild + re-factor" inside the 30 ms has not been
instrumented, and doing so is the first task below.

## Why `.dc` cannot simply be used instead

It refuses the knob outright:

```
Fatal error: DC Transfer Function: Voltage source, current source, or resistor
named "@interface1[wavelength_nm]" is not in the circuit
```

`.dc` accepts sources, resistors and `temp`. An OSDI/Verilog-A **model**
parameter is not sweepable by it at all — which is why `sweep` exists.

## Proposed work

1. **Instrument first.** Split the 30 ms into setup / load / factor / solve with
   a per-phase timer behind `option acct`. If setup is not the ~20 ms this note
   assumes, the rest of the plan changes. *Do not skip this step* — the whole
   case rests on it.
2. **Add a kernel-side parameter-sweep driver**, modelled on `CKTdcTrCurv`:
   set up once, then per point apply the knob through the existing
   `if_setparam*` path, re-load and re-factor, solve, and append to the plot.
3. **Route `sweep` into it** for the knob classes that are already in-place
   (`SW_MODEL`, `SW_INSTANCE`) — the ones `sw_wildcard_knob()` classifies today.
   Everything else keeps the present path.
4. **Keep the fallback.** E-465's re-source path must remain for `.param` knobs
   and anything the fast path disarms on; this is an addition, not a
   replacement.

## Risks, and what the suite must pin

- **The results must not move.** Every existing sweep suite has to pass
  unchanged, and the new path needs a differential against the old one on the
  same deck — same numbers, fewer seconds.
- **State restoration.** E-437/E-440 established that a sweep must put its knob
  back; a kernel-side loop bypasses the frontend paths those fixes live in, so
  the restore has to be re-proved, not assumed.
- **Plot and `save` semantics** must stay identical, including E-431/432's
  unresolved-`-output` refusal and the vector limit.
- **Analysis reuse.** A per-point `op` currently re-initialises everything;
  sharing setup across points is exactly where a stale value from the previous
  point could survive. This is the same hazard class as E-380 and E-384, and it
  is the reason step 1 exists.

## Interaction with Enhancement-469

`.option saveused` (shipped) attacks the other half of the same problem — what
is *stored* per point rather than what is *computed*. On the deck above it is
worth 14.5×, against the ~3× estimated here, and the two are independent.
`saveused` should be measured out of the way first when timing any of this.
