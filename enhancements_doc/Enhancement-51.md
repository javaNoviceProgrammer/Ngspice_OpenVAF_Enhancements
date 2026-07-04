# Enhancement-51 — full ac_stim AC injection (version11)

This document describes the changes made to **OpenVAF-r** and **ngspice-46**
in the `version11/` directory to complete **`ac_stim`** (LRM 4.6.3) — the
small-signal AC stimulus source, deferred since Enhancement-26 (which fixed
the compiler crash and the correct large-signal 0, but injected nothing).

## Semantics (LRM 4.6.3)

`ac_stim([analysis_name][, mag[, phase]])` — zero during large-signal
analyses and on small-signal analyses whose name doesn't match
`analysis_name` (default `"ac"`); when the analysis matches, a source with
magnitude `mag` (default 1) and phase `phase` (radians, default 0).

## Implementation (the noise-source mold)

- **hir_lower**: `ac_stim` lowers to a dedicated `CallBackKind::AcStim`
  callback per call site (exactly like `white_noise`), carrying the analysis
  name and `[mag, phase]` values; the named signatures take the analysis name
  as a string literal per the LRM BNF.
- **sim_back**: the callback rides the existing noise extraction — the
  linearizer classifies it into the small-signal network (so the branch
  exists with its factor while the large-signal residual stays 0), and
  `NoiseSourceKind::AcStim { mag, phase }` flows through the shared
  `NoiseSource` records with hi/lo/factor. **mfactor** scales the stimulus
  *linearly* for current sources and leaves voltage stimuli invariant —
  deterministic-signal laws, unlike noise's sqrt(m).
- **OSDI (ABI 0.6)**: the sources are **partitioned** out of the noise
  arrays (which stay aligned with `load_noise`'s slots via filtered
  indexing) into appended descriptor fields — `num_ac_stim_src`,
  `ac_stim_sources` (`{analysis, nodes}`), and a generated
  `load_ac_stim(inst, model, dst)` that fills `[re, im]` pairs =
  `factor·mag·cos/sin(phase)` from eval-cached values (op-dependent
  magnitudes work). ngspice's descriptor view also gained the previously
  undeclared tail fields it now needs to reach the appended ones.
  **Breaking**: OSDI version bumped to 0.6; the loader rejects older `.osdi`
  files with the recompile message.
- **ngspice** (`osdiacld.c`): after loading the AC Jacobian, each instance's
  active sources (analysis name `"ac"`) add `−re/−im` at node 1 and
  `+re/+im` at node 2 of the complex RHS — the sign follows the residual
  convention `(G+jωC)x = −residual_stim`, calibrated so `V(out) <+ ac_stim()`
  reads exactly +1∠0.

## What now works (`acstim_examples/`, all exact)

| case | result |
|---|---|
| `V(out) <+ ac_stim();` | AC v(out) = **1∠0 exactly** |
| `ac_stim("ac", 2.0, π/2)` | **j2** (phase in radians) |
| `ac_stim("sp")` | inactive in AC (0), per LRM name matching |
| `I(out) <+ ac_stim();` into 1k | **−1000** (contribution sign convention) |
| internal stimulus + RC lowpass | **0.5−0.5j at fc** (0.7071∠−45°), 0.01 at 100·fc — an embedded AC test bench measuring the model's own transfer |
| large-signal invariance | DC/transient unchanged (the E-26 checks still pass) |
| `m=3` on a current stimulus | ×3 linearly |

`verify_acstim.py`: 9/9 PASS (2 original + 7 new). Regression: all 47 example
verify suites ALL PASS (noise + correlated-noise suites confirm the
partition is airtight); crate tests 28/28.

## Notes

- ngspice's only OSDI small-signal analysis is AC, so `"ac"` is the only
  active name; other names are stored and stay inactive (LRM-conformant).
- Noise analysis is unaffected: ac_stim sources never enter the noise
  descriptor arrays or `osdinoise.c`'s loops.
