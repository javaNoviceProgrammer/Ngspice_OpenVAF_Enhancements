# Enhancement-54 — correct + node-free noise factors (version11)

This document describes the changes made to **OpenVAF-r** and **ngspice-46**
in the `version11/` directory for the noise "extra node" subsystem — the last
survivor of the old candidate list (`lineralize.rs`'s
"TODO: complex noise power"). The probe turned an optimization task into a
**correctness** one: the extra-node path's noise was silently lost end-to-end.

## What the probe found

Four shapes were tested against analytic PSDs (device + surrounding-resistor
floors):

| shape | before E-54 |
|---|---|
| `white_noise(pwr)` direct | correct (Linear path) |
| `gm * white_noise(pwr)` (op-dependent factor) | extra internal unknown **and NO noise output** |
| `ddt(cc * white_noise(pwr))` (induced-gate idiom) | extra internal unknown **and NO noise output** |
| one wave into two branches (correlation network) | extra internal unknown **and NO noise output** |

The onoise spectrum in all three broken cases equaled exactly the
surrounding resistors' floor — the device contribution had vanished.

## The two correctness defects

1. **`build_implicit_equation` never called `add_noise`**
   (`sim_back/src/dae/builder.rs`). Noise attached to an implicit-equation
   contribution (the `Evaluation::Equation` path: NoiseSrc unknowns and ddt
   correlation networks) was dropped before reaching the DAE's
   `noise_sources` — no OSDI descriptor entry, nothing for the simulator to
   evaluate. Every other `add_contribution` site pairs with `add_noise`.
2. **The late-created react optbarrier was unregistered.** When
   `builid_analog_operators` moves a `ddt()` into a contribution's reactive
   dimension, `update_optbarrier` creates (or rewrites) the react barrier —
   but it was never inserted into `topology.contributes`, so
   `prune_small_signal`'s `as_contribution` lookup could not find it: the
   noise wave's replayed coupling twin was built and then dropped, leaving a
   **hole in the Jacobian** (zero transferred noise). The refreshed
   `psp103_topology.snap` shows the impact on a flagship model: its
   `react_small_signal` couplings went from `F_ZERO` to real values.

With just these two fixes the Equation path produces exact PSDs (verified
against closed-form analytics for all shapes above).

## The optimization: factors instead of extra unknowns

3. **Op-dependent factors stay Linear** — `determine_evaluation` barred
   `fmul`/`fdiv` with op-dependent operands from the Linear path. For a ddt
   chain that check is correct (`g(v)·ddt(q) ≠ ddt(g(v)·q)`), but for a
   NOISE wave the right question is *wave-derivation*: only a product of two
   wave-derived values is nonlinear in the wave; an op-dependent factor is
   replayed into a per-instance value evaluated at the operating point. The
   check now discriminates by `val_visisted` for noise (`gm * white_noise`
   → factor `gm`, no extra unknown) and keeps op-dependence for ddt.
4. **One `ddt()` in a noise chain becomes a jω factor** (the old TODO's
   "complex noise power"). The factor generalizes to `re + jω·im`:
   - `determine_evaluation` admits `TimeDerivative` calls in noise chains
     (not for `ac_stim` — its injection is a complex RHS pair, not a power),
     with a pre-scan rejecting nested ddt ((jω)² needs an ω² real part) and
     post-ddt values feeding phis (replay complexity bound) — those fall
     back to the (now-correct) Equation path;
   - `create_dimension` runs a parallel react replay (`val_map_react`):
     `ddt(x)` moves the argument's replayed flat component into the react
     component; fadd/fsub/fneg/fmul/fdiv/optbarrier propagate both;
   - `Noise`/`NoiseSource` carry `factor_react` through the dae builder
     (mfactor scaling — both components scale identically since they
     multiply the same wave — and switch-branch phi joins);
   - **OSDI 0.7 (ABI change)**: `load_noise(inst, model, freq, dst)` fills
     `[flat, react]` signed power **pairs** per source (stride 2):
     `dst[2i] = fac·|fac|·pwr(f)`, `dst[2i+1] = fac_react·|fac_react|·pwr(f)`
     — the same E-42 sign-carrying fold, and the frequency shaping (flicker
     `pwr/f^exp`, tables) applies to both;
   - **ngspice `osdinoise.c`** groups same-named sources as complex
     amplitudes `(a + jω·b)·T_j` (T = per-source complex transfer): exact
     for a single source (the two components are in quadrature:
     `(a² + ω²b²)|T|²`) and for coherent groups, including anti-phase
     cancellation; the RFSPICE SP path uses `|a|² + ω²|b|²`;
   - registry gate raised to **>= 0.7**.
5. **Operator-ordering hazard fixed** — `analog_operator_evaluations`
   visited callbacks in registration order, and `determine_evaluation`
   mutates the function for Linear results (the dimension replay runs inside
   it). A shared-`FuncRef` ddt evaluated *between* two noise operators
   detached the second wave's path to its contribution mid-flight,
   misclassifying it as `Dead` (source silently lost — caught by the
   anti-phase cancellation test). All noise operators are now processed
   before any ddt operator: noise replays only zero the waves, which is
   exactly what the subsequent ddt pass should see.

## What now works (`noisejw_examples/`, 18 checks, all exact)

See the README: plain control; `gm*white_noise` and `ddt(cc*white_noise)`
**node-free** (were one extra unknown each) with exact flat/ω²-shaped PSDs;
`ddt(k*flicker_noise)` composing `ω²·kf/f^ef`; coherent same-named flat+ddt
mixing `(x² + ω²τ²)`; exact anti-phase cancellation; the formerly-lost
two-branch correlation network (coherent cross-branch sum incl. all resistor
floors); and `m=4` mfactor scaling of the jω case.

`verify_noisejw.py`: 18/18 PASS. Regression: all 50 example verify suites
ALL PASS; crate tests pass (sim_back topology/dae snapshots refreshed —
`factor_react` field + the noise-first ordering + psp103's restored react
couplings).

## Notes

- **OSDI ABI 0.6 → 0.7**: `load_noise`'s dst stride changed; ngspice rejects
  older `.osdi` files — recompile (committed `.osdi` artifacts must be
  regenerated at fold time, per the E-45 rule).
- Real models work around the old limitations with manual noise networks
  (e.g. HiSIM2's internal node `n` with `I(n) <+ V(n) + white_noise(...)`
  coupled via `ci·V(n)` and `ddt(V(n)·sigrat)`); those still compile
  unchanged — but the direct idiom (`ddt(sigrat·white_noise(...))`) is now
  both correct and free.
- `ac_stim` through `ddt` stays on the Equation path (its injection is a
  complex RHS pair, not a power); nested `ddt(ddt(noise))` and op-dependent
  conditionals around post-ddt values also fall back — correct, just not
  node-free.
- The env-gated debug dumps added during this work were kept:
  `OPENVAF_DAE_DEBUG=1` (openvaf: unknowns/residuals/jacobian/noise of each
  compiled module) and `OSDI_NOISE_DEBUG=1` (ngspice: per-source loaded
  powers and complex transfers per frequency).
