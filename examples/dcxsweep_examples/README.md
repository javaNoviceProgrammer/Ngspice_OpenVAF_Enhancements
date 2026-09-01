# dcxsweep — `.dc` learns the rest of the parameter surface, and scales

Regression suite for Enhancement-534. The sweep variables the
`sweep`/`altermod` family established now have a native dc arm:

* **model parameters** — `@mod[p]`, including the dotted subcircuit spelling
  `@x1.rmod[p]` (resolved through the same E-433 hierarchy funnel the rest of
  the tooling uses);
* **the wildcard families** — `@*[p]` (every model with `p`), `@#*[p]` /
  `@*[[p]]` (every instance with `p`), `@*:leaf[p]` (every model named
  `leaf`, wherever expansion put it);
* **point scales** — `dc <knob> lin|dec|oct N start stop`, generating exactly
  the point sets the `sweep` command generates (lin interpolates so both
  endpoints are exact; dec/oct are N per decade/octave), on every knob kind,
  nesting included.

Targets are collected once at resolution and written per point through the
DEV tables directly — the **machine-write** path, so an `osdimc` statistical
nominal is never recentered by a sweep (E-531) — with one `CKTtemp` per point
and the E-495 collapse guard armed however many targets move. A wildcard name
is read verbatim on the card (the token grammar used to break at `*`), and
works the same typed in a `.control` block.

Two repairs that fell out of the work, pinned here: the parameter-sweep
**overshoot slack is now relative** — `dc @dm[is] 1e-14 5e-14 1e-14` is five
points ending at 5e-14, where the absolute `1e3·DBL_EPSILON` slack let it run
to 2.7e-13, five times past stop (latent in E-62 since tiny parameters became
sweepable; classic volt/ohm-scale sweeps are bit-identical). And integer
parameters refuse the fractional lin/dec/oct generators outright while
keeping E-427's whole-number rule for the classic triple.

What deliberately did **not** change: the classic `start stop step` triple is
untouched byte-for-byte; a collapse-gated model parameter is refused with the
E-495 message naming `sweep` as the correct instrument (and the `sweep`
command's dc handover — widened to all of these spellings and grids by the
same enhancement, see `sweepdc_examples` — falls back to its per-point loop
on exactly that refusal); `dc temp` semantics are untouched.

| File | Pins |
|---|---|
| `dcxosdi.va` | A collapse-gated OSDI model (`rd` moves the topology), a plain model parameter `g`, and an integer `nseg` — the guard, machine-write restore, and integer-rule checks run against it. |
| `verify_dcxsweep.py` | 20 checks, both solvers: every spelling on closed-form circuits, the scale grids against exact values, the relative-slack repair, guards (the OSDI runtime one and the built-in static one -- a node-building BJT `rc` is refused where its `bf` sweeps), restores, nesting, and the untouched classic triple. |

Run it:

```bash
python3 verify_dcxsweep.py
```
