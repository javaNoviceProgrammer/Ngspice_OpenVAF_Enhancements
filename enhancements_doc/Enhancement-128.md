# Enhancement-128 — LTE-based dynamic integration-order control

An efficiency enhancement to the transient integrator: `.option dynorder` selects the
Gear integration order per step from the local-truncation-error (LTE) limit, so
higher-order Gear is used on smooth stretches and far larger timesteps are taken at
the same accuracy. Off by default; bounded by the standard `maxord` knob.

## The gap

ngspice already has all the machinery for high-order Gear (BDF): `NIcomCof` computes
the integration coefficients for orders 1–6, and `CKTtrunc`/`CKTterr` estimate the
LTE-limited timestep at any order. But the stock order controller in `dctran.c` only
ever toggles the order between **1 and 2** — once at order 2 it never climbs, so
orders 3–6 are dead code in every ordinary transient. On smooth problems that leaves
a large efficiency gain on the table: the LTE-limited step grows like `tol^{1/(p+1)}`
with order `p`, so a high order permits dramatically bigger steps at a fixed accuracy.

## The method

Each accepted timestep, with `dynorder` on, the controller evaluates the **raw**
LTE-limited step (via `CKTtrunc`, given a large trial input so its 2× growth cap does
not mask the per-order difference) at the current order and its immediate neighbours,
and moves toward the order that permits the largest step. Four guards keep the
higher orders — where BDF is only conditionally stable and the divided-difference LTE
estimate is delicate — from ever wrecking the answer:

- **neighbours only** (`±1`), never a greedy global maximum — the order cannot
  oscillate (oscillation makes the LTE history inconsistent and triggers a cascade of
  step rejections; this was the failure mode of a first, greedy implementation);
- **hysteresis** — a neighbour must beat the current order's LTE step by `1.2×` to
  win, otherwise the order is kept;
- **a settling hold** — after any order change the order is held for a few steps so
  the BDF divided differences (which assume a roughly constant step) can rebuild
  before another change is considered;
- **an order-dependent growth cap** — the step is *not* grown the same step the order
  is raised, and on subsequent steps the growth cap tightens with order (2× at order
  ≤3 down to 1.3× at order 6), because a large step jump at high order corrupts the
  very divided differences the LTE relies on.

The whole path is gated on `.option dynorder` and bounded by `maxord`; with the
default `maxord = 2` it cannot exceed the stock order-2 behaviour, so enabling it on
an ordinary deck is inert.

## Robustness on stiff transients

High-order Gear is the wrong tool inside a violent transient (a large fast slew, the
first microseconds after a breakpoint). Left unchecked, the controller would climb to
a high order there and the timestep would collapse to zero ("Timestep too small").
Two guards, both gated on `dynorder`, make it degrade gracefully instead:

- **post-breakpoint hold** — a breakpoint (a pulse edge, a source transition) already
  resets the order to 1; the controller now also *holds* it low for the next few steps
  (`maxord + 2`), so it does not race back up to a high order inside the
  post-discontinuity transient before it has settled;
- **rejection-rate order drop** — a leaky bucket (`+2` per LTE-rejected step, `−1` per
  accepted step) detects a *sustained* high rejection rate — the signature of a stiff
  region where the current order overreaches — and walks the order back down. A single
  isolated rejection, normal on a smooth high-order run, decays away and leaves the
  order (and its efficiency) untouched.

The stress case is the transistor-level µA741 follower driven by a big ±5 V square
wave ([Enhancement-83](Enhancement-83.md)): the output slew-rate-limits for tens of
microseconds. With these guards dynamic-order control **completes** that slew under
both linear solvers and lands on the same answer as fixed low-order Gear (−3.31499 V
vs −3.31538 V), where without them it collapsed the step at the pulse edge.

## Verification

Three circuits, checked under **both** Sparse 1.3 (default) and KLU
(`verify_dynorder.py`; the heavy reference sweeps run under Sparse, KLU runs the fast
subset):

- **RC discharge** (`V(0)=1`, `RC=1 ms`; analytic `V(8 ms)=e^{-8}`). At matched
  tolerance dynorder (`maxord=3`) reaches the stock controller's accuracy in **≥2×
  fewer steps** (163 vs 664 rows at `reltol=1e-8`, both ≈0.04 % error), and its error
  is **monotone** in tolerance — the higher-order controller never blows up. Across
  the Pareto frontier the step saving at matched accuracy is **3–5×**.

- **Parallel-RLC ringdown** — a smooth 5.03 kHz sinusoid. dynorder (`maxord=4`) uses
  **420 steps vs the stock controller's 3734** (a **8.9×** reduction) and is
  simultaneously **more accurate** against a tight reference (0.13 % vs 0.34 %),
  because the stock 1↔2 toggle never uses order 3–4 even when `maxord=4`. Higher order
  pays off twice on smooth dynamics.

- **Nonlinear diode rectifier** — diode switching makes frequent breakpoints that
  reset the order to 1, so the benefit is modest, but dynorder's final value matches
  the stock controller to **5 significant figures**: a switching circuit must not be
  perturbed.

Plus a safety check that `.option dynorder` at the default `maxord=2` is
result-neutral versus a plain run. All checks pass under both solvers (10/10 Sparse,
6/6 KLU).

## Files changed

| File | Change |
|---|---|
| `ngspice-46/src/include/ngspice/optdefs.h`, `tskdefs.h`, `cktdefs.h` | `OPT_DYNORDER` / `TSKdynorder` / `CKTdynorder` + `CKTorderCnt` (history depth), `CKTorderHold` (settling), `CKTorderRej` (rejection-rate bucket), `CKTorderMaxUsed` (diagnostic) |
| `ngspice-46/src/spicelib/analysis/cktsopt.c`, `cktntask.c`, `cktdojob.c` | wire `.option dynorder` through the task → circuit (off by default) |
| `ngspice-46/src/spicelib/analysis/dctran.c` | the neighbour + hysteresis + settling-hold + growth-cap order selector, replacing the stock 1↔2 toggle when `dynorder` is set; the stiff-transient guards (post-breakpoint hold, rejection-rate order drop); order-history resets at init and breakpoints; a `set ngdebug` summary of the highest order used |
| `examples/dynorder_examples/` | `dynorder_demo.cir`, `verify_dynorder.py` |
| `examples/opamp741_examples/verify_opamp741.py` | dynorder robustness regression: the stiff µA741 slew under `dynorder` completes and matches fixed Gear-2 |

## Scope

`dynorder` is a general transient-efficiency aid: on smooth problems it delivers
3–9× fewer timesteps at matched-or-better accuracy by using Gear orders the stock
controller never reaches, and it is provably inert on ordinary (default `maxord=2`)
decks and result-neutral on nonlinear switching circuits. The robust operating range
is `maxord` 3–4; higher `maxord` is more aggressive (and, like all BDF beyond order 2,
less robust at loose tolerance — the same reason stock ngspice caps its default Gear
order at 2). Automatic engagement (turning it on when the dynamics are detected as
smooth) and a per-device rather than whole-circuit order are natural follow-ups.
