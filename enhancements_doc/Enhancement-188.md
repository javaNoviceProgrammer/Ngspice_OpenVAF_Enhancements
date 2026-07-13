# Enhancement-188 — Monte Carlo warm-start (`montecarlo … -warm`)

A performance enhancement for the [Enhancement-151](Enhancement-151.md) `montecarlo` yield command. Each Monte Carlo sample re-sources the deck (fresh random `.param` draws) and solves a DC operating point — but ngspice **cold-solves every one**, running the full gmin / source-stepping homotopy from scratch, even though consecutive samples move the operating point only slightly. `montecarlo … -warm` reuses the previous sample's converged solution as the initial guess, cutting the per-sample Newton iteration count by roughly an order of magnitude with an **unchanged yield**.

## The observation

Profiling the MC loop showed the DC solve, not the deck re-source, is the expensive part for non-trivial circuits — and every `op` starts cold. Even two *identical* ops back-to-back each burn the full homotopy: on a Verilog-A diode ladder, a cold `op` takes **~52 Newton iterations** (most of it gmin/source stepping), and repeating it unchanged takes 52 again. ngspice's `CKTop` tries a direct Newton from the caller's `firstmode` and only falls into homotopy if that fails; `DCop` always passes `MODEINITJCT` (cold junction voltages), so the warm information in the previous solution is thrown away.

## The change

`montecarlo … -warm` wraps the sampling loop in `CKTsetWarmStart(1)` / `CKTsetWarmStart(0)`. In `DCop` (`spicelib/analysis/dcop.c`):

- a small buffer (outside the `CKTcircuit`, which `reset` recreates; indexed by equation number, stable across resets of an identical-topology deck) holds the **last converged `CKTrhsOld`**;
- when a valid guess of the right size is available, `DCop` preloads it into `CKTrhsOld` and calls `CKTop` with `MODEINITFLOAT` (use the existing node voltages) instead of `MODEINITJCT`, so the first Newton starts warm;
- if the guess is poor (a big parameter jump), that first `NIiter` simply fails and `CKTop` falls through to the normal cold gmin/source stepping — so the converged point is identical, only a cheap failed attempt is wasted;
- after every converged solve the solution is snapshotted as the next warm start.

The first sample is cold (no prior); the rest warm. When `-warm` is not given, `dcop_warm_enable` is 0 and the path is byte-identical to before (one extra `SMPmatSize` read). Warm-start lives in the shared DC operating-point code, so it works under both Sparse and KLU and composes with `-lhs`.

## Correctness

Warm-start changes only Newton's *starting point*, not the equations, so it converges to the **same** operating point as the cold path to within the solver's convergence tolerance. The example verifies the warm and cold yields are **exactly equal at `reltol=1e-6`**, and agree to within a couple of samples at the default `reltol=1e-3` — a tolerance effect on a metric (`v(3) ≈ 3.8 V`) whose default reltol window (`reltol·|v| ≈ 3.8 mV`) is as wide as the narrow spec band, so an edge sample can flip (it flips between two cold runs with different convergence aids too). Tightening `reltol` removes it.

## Impact and scope

The win is the iteration *count* (~52 → ~4, ≈13×), so the wall-clock benefit scales with how much each Newton iteration costs. Large / hard-converging designs — many compact-model devices, gmin/source-stepping on every cold op, tens of ms per bias point — benefit most. On small circuits the per-sample deck re-source and command dispatch dominate, so the wall-clock speedup is smaller even though the iteration count still drops. It is opt-in and safe; the deck re-source overhead itself is a separate, complementary lever for a future enhancement.

## Verification

[`examples/warmstart_examples/verify_warmstart.py`](../examples/warmstart_examples/verify_warmstart.py) — 5 checks on a random-`is` diode ladder: warm ≡ cold yield **exactly at `reltol=1e-6`**; they agree to within a few samples at the default tolerance; warm cuts the per-sample iteration count ≥3× (measured 52 → 2); `-warm` composes with `-lhs`; and warm ≡ cold under **KLU** (the warm-start hook is in the shared DC-op code). A [`warmstart_demo.cir`](../examples/warmstart_examples/) prints the cold-vs-warm yield and iteration counts side by side. Full example regression: 152/152.
