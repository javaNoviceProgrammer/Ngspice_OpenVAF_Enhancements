# Enhancement-134 — Harmonic Balance (`hb`)

A new command, **`hb`**, computes the periodic steady state **directly in the
frequency domain** by Newton, instead of integrating in time. Each node voltage is a
truncated Fourier series `v_i(t) = Σ_{k=−K..K} V_{i,k} e^{jkω₀t}`, and the KCL
residual at every node and harmonic is driven to zero. Unlike a transient (or the
`qpss` transient-sampling of E-133), HB needs no settling — it converges on
high-Q/slow-settling circuits in a handful of iterations — and it is the classic
engine for nonlinear RF steady state (power amplifiers, mixers, multipliers).

ngspice shipped only an unimplemented `WITH_HB` stub; this is the real analysis.

```
hb <f0> <K> [points] [maxiter]
```

- **`<f0>`** — the fundamental (drive) frequency.
- **`<K>`** — number of harmonics to solve (0…K, so the system is `(2K+1)·N`).
- **`points`** — time samples per period for the device evaluation (default ~8K).
- **`maxiter`** — Newton iteration cap (default 50).

Output is a labelled spectrum — for every node, the magnitude and phase at each
harmonic `k·f0`. `set hb_verbose` prints the per-iteration residual norm.

## Method

The residual at node/harmonic k is `F_k = I_R,k(V) + [dq/dt]_k − Is_k = 0`, solved by
Newton with the **`(2K+1)N` conversion matrix (E-121) as the exact Jacobian**. Each
iteration:

1. inverse-DFT `V_k` → node voltages `v(t_s)` at P samples over one period;
2. at each sample, drive the device loads at those voltages. **Junction devices
   (diode/BJT/MOS) limit their internal voltage against a stored value**, so a single
   load leaves them pinned at a stale bias (and `MODEINITSMSIG` alone reads the stored
   op-point, ignoring the node voltage — which made real diodes look *linear*). So the
   sample first **settles** the device: repeated `MODEINITFLOAT` loads walk the limited
   junction to the fixed node voltages until the limiter is a no-op, yielding the true
   companion `b` and hence the **actual** resistive current `I_R = G·v − b` (not the
   tangent `G·v`). A following `MODEINITSMSIG` load then reads the settled bias to build
   the small-signal linearization, and an **AC** load at ω=1 gives `C(t)`. Behavioural
   / OSDI devices with no limiting settle on the first pass;
3. DFT `I_R(t_s)`, `G(t)`, `C(t)` → the residual and the conversion-matrix harmonics;
4. dense complex Newton solve (`pss_csolve`) → update `V_k`.

The key that makes **nonlinear reactive** elements work with **no per-device charge
extraction**: the reactive current is `dq/dt = C(v)·v'` by the chain rule, so its
spectrum is exactly the conversion matrix's reactive term `Σ_m jmω₀·C_{k−m}·V_m`
applied to `V` — using the same `C(t)` samples the Jacobian already needs. Nonlinear
charge `Q(v)` (varactors, junction caps) falls out for free; the nonlinearity is in
the sampled `C(t)`.

The independent-source excitation `Is_k` is captured by loading the circuit at zero
node voltage with the sources evaluated at each sample time. Reuses `pac_build_matrix`
(Jacobian) and `pss_csolve` (dense solve) from the PSS/PAC suite; solver-independent
(it drives ordinary DC/AC device loads).

## Verification

`verify_hb.py` drives nonlinear circuits with a tone and compares HB's spectrum
against ngspice's own transient + `fourier` steady-state harmonics (7/7):

- **nonlinear resistor** — fundamental and 3rd harmonic match; Newton converges
  **quadratically** in 3 iterations; even-order products are ~0.
- **nonlinear R + linear C** — the reactive roll-off/phase is captured; still matches
  the transient fourier.
- **built-in diode half-wave rectifier** — a real junction device with internal voltage
  **limiting**; the sharp rectified waveform's DC…3rd harmonics match the transient to
  <0.3 % (this is the hard case the per-sample settling above unlocks).
- **nonlinear C (OSDI varactor)** — a `Q = cj0·(V + γV²)` charge makes a real 2nd
  harmonic (`|V₂| ≈ 1.4e−2`) that a linear cap cannot; HB matches the transient — the
  **full nonlinear-reactive** result, on a compiled Verilog-A device.

Also confirmed by hand: HB reproduces the analytic cubic 3rd harmonic
`|v₃| = R·g₃·|v₁|³/4`, and works under both current- and voltage-source excitation.

## Files changed

| File | Change |
|---|---|
| `ngspice-46/src/spicelib/analysis/dcpss.c` | the HB engine: `hb_extract` (samples `I_R`/`G`/`C` at prescribed voltages) and `HBanalyze` (source spectrum + frequency-domain Newton + spectrum output), reusing `pac_build_matrix` + `pss_csolve` |
| `ngspice-46/src/frontend/com_hb.c` / `.h`, `commands.c`, `com_commands.h`, `Makefile.am` | the `hb` command (parse, build the circuit, run `HBanalyze`) |
| `ngspice-46/src/include/ngspice/cktdefs.h` | `HBanalyze` prototype |
| `examples/hb_examples/` | `verify_hb.py`, `vavar.va` (nonlinear-cap varactor) |

## Scope

Single-tone Harmonic Balance with nonlinear resistive **and** nonlinear reactive
devices, current- or voltage-source driven, built-in and OSDI, verified against the
transient steady state with quadratic Newton convergence. Honest limitations /
follow-ups: strongly-driven circuits (nonlinearity comparable to the linear term)
converge but need many iterations — source-stepping / continuation would fix that;
the dense `(2K+1)N` solve is capped for modest circuits (a sparse block solver would
scale it); and **multi-tone** HB (true incommensurate QPSS, extending E-133 and this
engine to a 2-D harmonic set) is the next step.
