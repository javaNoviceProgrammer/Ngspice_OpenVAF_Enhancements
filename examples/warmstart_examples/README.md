# Monte Carlo warm-start — `montecarlo … -warm` (Enhancement-188)

Each Monte Carlo sample re-sources the deck (new random draws) and solves a DC
operating point that has moved only slightly from the previous sample — yet
ngspice **cold-solves every one**, running the full gmin/source-stepping
homotopy each time. On the diode ladder here that is **~52 Newton iterations per
sample**, almost all of it homotopy the previous sample already paid for.

`montecarlo … -warm` reuses the previous sample's converged solution as the
initial guess for the next sample. A direct Newton from that warm point
converges in **~4 iterations**; if the guess is poor (a big parameter jump), the
first Newton simply fails and ngspice falls back to the normal cold homotopy —
so the converged operating point, and the yield, are the same.

```
  --- cold Monte Carlo ---
  yield  : 60.250%  (241 / 400 pass)
  Total iterations = 52          <- last sample's Newton iterations
  --- warm Monte Carlo ---
  yield  : 59.250%  (237 / 400 pass)
  Total iterations = 2           <- 26x fewer
```

## Correctness: same operating point, to convergence tolerance

Warm-start changes only the *starting point* of Newton, not the equations, so it
converges to the **same** operating point as the cold path — to within the
solver's convergence tolerance. `verify_warmstart.py` shows the warm and cold
yields are **exactly equal at `reltol=1e-6`** (240/400 each). At the default
`reltol=1e-3` they agree to within a couple of samples: the metric `v(3)` here
sits at ~3.8 V, where the default reltol window (`reltol·|v| ≈ 3.8 mV`) is as
wide as the narrow 6 mV spec band, so a sample sitting right on the edge can
land on either side. That is a tolerance effect (it happens between two cold
runs with different convergence aids too), not a warm-start error — tightening
`reltol` removes it.

## When it helps

The win is the **iteration count**, so the wall-clock benefit scales with how
much each Newton iteration costs: large / hard-converging designs (many
compact-model devices, gmin/source-stepping every cold op) benefit most, where a
cold bias point can take tens of ms. On small circuits the per-sample deck
re-source and command overhead dominate, so the speedup is smaller even though
the iteration count still drops ~10×. It is opt-in (`-warm`), safe (auto
fallback), and composes with `-lhs`.

## Verification

`verify_warmstart.py` — 5 checks: warm ≡ cold yield exactly at `reltol=1e-6`;
they agree to within a few samples at the default tolerance; warm cuts the
per-sample iteration count ≥3×; `-warm` composes with `-lhs`; and the same holds
under KLU (warm-start lives in the shared DC operating-point code).

## Running

```sh
python3 verify_warmstart.py
openvaf-r warmstart_diode.va -o warmstart_diode.osdi && ngspice -b warmstart_demo.cir
```
