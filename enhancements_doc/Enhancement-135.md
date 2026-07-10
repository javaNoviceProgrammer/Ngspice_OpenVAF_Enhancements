# Enhancement-135 — Harmonic-Balance source-stepping continuation

The Harmonic Balance engine of [E-134](Enhancement-134.md) solves the periodic steady
state by Newton on the `(2K+1)N` conversion matrix. Newton converges quadratically —
**once it is close enough**. For a strongly-driven circuit, where the nonlinearity is
comparable to the linear term (a power amplifier near compression, a sharp diode
rectifier at large amplitude), a cold full-strength Newton from `V = 0` overshoots and
**diverges** (the residual blows up to `1e69` in a step or two).

This enhancement makes `hb` robust on those circuits with **source-stepping
continuation** — the standard homotopy for hard steady-state problems. No new syntax:
it is automatic and transparent.

## Method

Every independent source is scaled by a homotopy factor `λ`, and HB solves a sequence
of problems `λ: 0 → 1`, each **warm-started** from the previous solution:

- at `λ = 0` the circuit is unexcited and the solution is `V = 0` (known exactly);
- each level solves `F(V; λ) = I_R(V) + [dq/dt](V) − λ·Is = 0` by the same Newton as
  E-134, starting from the last converged `V`;
- as `λ` climbs, the steady state moves along a continuous path, so the warm start is
  always inside Newton's basin.

The stepping is **adaptive with backtracking**, so it costs nothing on easy circuits
and subdivides only as much as a hard one needs:

- the **first level is full strength** (`dλ = 1`), so a circuit that would have
  converged directly still converges at `λ = 1` on the first try — **bit-identical** to
  the plain solve;
- if a level fails (Newton exhausts its iterations, the residual goes non-finite, or the
  Jacobian is singular), `dλ` is **halved** and the level retried from the last
  converged `V`;
- if a level converges, `dλ` **grows** (×1.7) so the ramp accelerates once past the hard
  region;
- if `dλ` collapses below `1e-5` the circuit is reported as having no reachable steady
  state at that drive (singular or non-convergent), rather than silently returning
  garbage.

All independent sources — bias **and** drive — ramp together (classic source stepping).
To sweep the RF drive at a fixed DC bias instead, step the drive amplitude with `alter`
across separate `hb` calls.

`set hb_verbose` now prints the `λ` of each level alongside the per-iteration residual,
so the continuation path is visible. The final line reports the total Newton iterations
and the number of continuation steps, e.g.
`HB: converged in 62 iterations, 3 continuation steps (|F| = 1.7e-11)`.

## Verification

`verify_hb.py` gains a strongly-driven check (now 9/9):

- **strongly-driven diode rectifier** — 5 V into a 20 Ω source resistance and a sharp
  `IS=1e-14` junction. A cold full-strength Newton diverges (`|F| → 1e69`); with
  continuation HB ramps through **3 steps** (backing off to `λ = 0.25`, then climbing)
  and converges. The spectrum matches the transient `fourier` steady state to **<0.1 %**
  for DC, f₀ and 2f₀ (DC 1.2442 vs 1.2438, f₀ 2.0273 vs 2.0262, 2f₀ 1.0004 vs 1.0008).

The other eight checks are unchanged and **bit-identical** — they all converge at
`λ = 1` on the first level, so continuation adds no iterations and no numerical
difference on circuits that never needed it.

## Files changed

| File | Change |
|---|---|
| `ngspice-46/src/spicelib/analysis/dcpss.c` | wrap `HBanalyze`'s Newton loop in the adaptive `λ`-continuation loop: scale `Is` by `λ`, warm-start/checkpoint/restore `V` per level, backtrack on failure, grow on success; report iterations + continuation steps |
| `examples/hb_examples/verify_hb.py` | strongly-driven rectifier check (diverges cold, converges via continuation, matches transient) |

## Scope

Single-tone HB (E-134) made robust for strongly-driven / stiff nonlinear circuits via
automatic adaptive source-stepping. Follow-ups (unchanged from E-134): a sparse block
solve to scale past the dense `(2K+1)N ≤ 900` cap, and **multi-tone** HB (true
incommensurate QPSS). A drive-only continuation (bias held fixed) is a natural
refinement of the all-sources ramp used here.
