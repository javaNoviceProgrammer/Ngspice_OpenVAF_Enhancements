# Enhancement-154 — Envelope Following (`envelope` command)

The [gap analysis](../docs/internals/ngspice_internals/ngspice_gaps.md) listed
**Envelope Following** as the one remaining ❌ in the RF / periodic-steady-state
suite. It is the analysis for circuits whose amplitude or phase modulates *slowly*
over *many* carrier periods — a ringing resonator, a settling PLL, a modulated power
amplifier — where a plain `.tran` must grind through every fast carrier cycle. This
enhancement adds it.

It also closes a genuine [shelved result](../docs/internals/ngspice_internals/): an
earlier forward-Euler attempt worked on overdamped settling but **blew up** on
resonators, and was reverted. The fix (an implicit, monodromy-based envelope step)
is implemented here.

## What it does

```
envelope <node> <fc> <tstop> [nppp N] [m M0] [maxm Mmax] [reltol t] [settle ts]
```

`envelope` samples the circuit state once per carrier period `T = 1/fc` and
integrates the *slow* drift of those samples, jumping `M` periods at a time. It
builds a plot named `envelope` holding the observable's amplitude `<node>_amp`
(fundamental `2|V1|`), mean `<node>_dc`, and in-phase / quadrature `<node>_re` /
`<node>_im`, versus (slow) time.

## The method — why it must be implicit

The exact per-period map is `X_{n+1} = phi(X_n)`, where `phi(x)` integrates the
DAE one carrier period from state `x`. Treating the period index `n` as continuous,
the envelope obeys `dX/dn ~ phi(X) - X`. A **naive forward-Euler** jump

```
X_{n+M} = X_n + M*(phi(X_n) - X_n)
```

is **unstable** on high-Q / oscillatory circuits: `phi`'s Jacobian (the one-period
*monodromy*) has eigenvalues on the unit circle, so `I + M*(Phi - I)` amplifies and
the envelope diverges — exactly the failure that shelved the first attempt. This
analysis uses the **implicit backward-Euler** jump

```
X_{n+M} = X_n + M*(phi(X_{n+M}) - X_{n+M})
G(Y) = Y - X_n - M*(phi(Y) - Y) = 0,     Newton:  [(1+M) I - M*Phi] dY = -G
```

with `Phi = dphi/dY` the monodromy, finite-differenced (one extra period-integration
per state). The implicit step is A-stable, so it tracks a resonator's envelope
without blowing up, and its fixed point is `phi(X)=X` — the true steady state. The
step size `M` is chosen by a step-doubling local-truncation-error control (one jump
of `M` vs two of `M/2`), like transient step control: small `M` on the fast part of
the envelope, large `M` once it is slowly varying.

## Implementation notes

- **`spicelib/analysis/envelope.c`** (new): the `EFanalysis()` engine — the
  self-starting one-period map `phi`, the finite-difference monodromy, the implicit
  envelope Newton (a small dense LU), and the adaptive-`M` march.
- The one-period map reuses the transient primitives (`NIcomCof` + `NIiter` per
  fixed sub-step, the `dctran` state rotation) on a fixed grid of `nppp` points, in
  **trapezoidal** mode — backward-Euler numerically *damps* a high-Q resonance, so
  it must not be used for the bulk integration.
- `phi` is **self-starting** (a true function of the sampled node vector): a
  frozen-history approach was tried and *plateaued* — a stale-amplitude history
  dragged the ring-up to a false low fixed point. The self-start's first sub-step is
  backward-Euler (the only self-starting method), sub-divided into small steps to
  keep its numerical damping negligible, after which trapezoidal takes over.
- The monodromy is a dense `N×N` solve (`N` = matrix size), capped for modest
  circuits — like the PAC / HB conversion-matrix solves.
- **`frontend/com_envelope.c`** (new): the `envelope` command — parses the arguments,
  runs a short settling transient to initialize the state machine, calls
  `EFanalysis()`, and emits the `envelope` plot (nutmeg vector API).
- Solver-independent (it drives the shared transient kernel); verified identical
  under both linear solvers.

## Verification

`examples/envelope_examples/verify_envelope.py`, under **both** linear solvers:

- the `envelope` command returns a plottable envelope with **far fewer samples than
  carrier periods** (26 samples for ~3000 periods on the demo);
- **correctness** — on a high-Q (`Q ~ 3160`) RLC tank rung up by an on-resonance
  carrier, the EF amplitude tracks a full `.tran` (same fundamental-Fourier measure)
  across the whole ring-up to **< 3 %**;
- **steady state** — EF converges to the transient's steady-state amplitude (< 0.5 %);
- **stability** — the resonator is tracked over 3000 periods and stays **bounded**
  (the implicit step; an explicit envelope jump diverges here);
- a **moderate-Q** tank (`Q ~ 316`) is tracked to **~1.6 %**.

`envelope_demo.cir` rings up the high-Q tank and plots the envelope.

## Scope and follow-ups

Envelope following pays off when the envelope is *much* slower than the carrier
(high-Q resonators, PLLs, modulated RF): there `M` stays large and EF covers
thousands of carrier periods with a few dozen period-solves — several times faster
than the full transient on the `Q ~ 3160` demo. When the envelope is only a little
slower than the carrier (a fast ring-up), `M` is forced small and a full `.tran` is
competitive; EF is still correct there, just not faster. Accuracy is set mainly by
`nppp` (default 128) and `reltol` (default 0.01). Natural follow-ups: a second-order
*non-dissipative* self-start (to lower `nppp` and the residual restart bias), monodromy
reuse across the step-doubling sub-jumps, and a sparse monodromy solve for larger
circuits. **With this, every analysis in the RF / periodic-steady-state suite is
present.**
