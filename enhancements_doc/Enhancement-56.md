# Enhancement-56 — VA_TEST end-to-end sweep: CMC default-range idiom + noise crash (version11)

This document describes the changes made to **OpenVAF-r** and **ngspice-46**
in the `version11/` directory as the outcome of the first **end-to-end**
sweep of the VA_TEST corpus: all 92 standalone industry models compiled and
run through ngspice op/AC/tran/noise with a generated bias bench, checking
for crashes, aborted analyses, and NaNs (the corpus had previously only been
compile-tested).

## Sweep-harness lesson

ngspice control scripts **continue past aborted analyses**, so echo markers
after an analysis prove nothing — the first sweep's "92/92 clean" was a
false positive. Failure detection must be data-based ("No. of Data Rows"
per completed analysis, "simulation(s) aborted", return codes).

## The fixes

### 1. Parameter DEFAULTS exempt from range validation (compiler)

CMC-standard models declare a default **outside** the parameter's own range
as the "feature disabled" state and expect the range to bind only
user-**given** values:

```verilog
parameter real CORECOVERY = 0.0 from (0.0:1.0];   // diode_cmc
parameter real Fb         = 0.0 from (0.0:inf);   // FBH-HBT
```

`insert_param_init` (`hir_lower/src/parameters.rs`) lowered the default and
then range-checked it exactly like a given value, so the stock CMC models
(diode_cmc, bsimcmg-110, fbh_hbt, psphv fragments, hisim family, …) were
rejected at setup with "Parameter … is out of bounds". The not-given branch
no longer checks; the given branch still validates both `from` ranges and
`exclude` constraints (verified: the excluded bound, an exclude-list value,
and a beyond-range value are all still rejected when given).

### 2. Setup rejection diagnostics (ngspice)

A `$fatal`/`$finish` raised during **setup** is a model rejecting its
parameters/configuration (HiSIM validates `$port_connected` combinations
against `COSUBNODE`/`COBCNODE` and calls `$finish(0)` by design). ngspice
surfaced that as `E_PANIC`'s baffling **"impossible error - can't occur"**.
`osdisetup.c::handle_init_info` now reports *"a Verilog-A device rejected
its configuration during setup ($finish raised)"* — right next to the
model's own `$write` message, which was always printed.

### 3. Noise-analysis singular-matrix crash (ngspice)

`noisean.c` **ignored `NIacIter`'s return value** in the frequency loop: on
a singular AC matrix the factorization fails, and the noise adjoint solve
(`SMPcaSolveTransposed` → `spSolveTransposed`) then hit
`Assertion failed: IS_FACTORED(Matrix)` — a hard **SIGABRT** (reproduced
with hisimsoi rejecting an all-terminals bench). The return is now checked:
*"AC solution failed at … Hz; aborting the noise analysis."* The noise
analysis additionally honors E-55's deferred `$finish`/`$stop` raised during
its internal operating point (a model that "wanted out" no longer keeps
evaluating in a degenerate state).

## Sweep verdicts (everything else triaged, not defects)

| model | symptom | verdict |
|---|---|---|
| hisimhv ×2, hisimsoi-140 | setup rejected | model's own `$finish` config guard: 6 nodes connected needs `COSUBNODE`/`COBCNODE=1` — clean diagnostics now |
| hisimsoi ×3 | noise SIGABRT | crash fixed (above); the underlying singularity is the same config guard |
| vbic_4T_et_cf | singular `cx`/`si` in AC | the model contributes **nothing** to those nodes at `RCX=0`/`RS=0` (defaults) by design; commercial simulators' node-gmin covers it — use `.option rshunt=1e12` |
| EPFL_HEMT | op nonconvergence | bench sensitivity: converges fine at a realistic bias (Vd=0.5, Vg=0.3: Id=127 mA, all analyses pass) |
| FBH_HBT | tran "timestep too small" | the model divides by its own disabled-default (`ddt(V(nii)/(2π·Fb))` with `Fb=0` → infinite capacitance); give `fb>0` — reachable at all only thanks to fix 1 |

Final sweep result: **83/92 module-runs fully green** (op+AC+tran; the
setup-rejected CMC models — diode_cmc, bsimcmg-110, psphv, fbh_hbt's op/AC —
are all cured); the 9 remaining are exactly the by-design/bench cases
tabulated above. All 88 noise runs are **crash-free** (the three previous
SIGABRTs now abort cleanly with diagnostics).

## What now works (`paramrange_examples/`, 13 checks)

See the README: out-of-range defaults accepted with exact solutions, given
values still validated (three rejection forms), the hisimsoi noise-crash
reproducer aborts cleanly, and the stock CMC diode_cmc runs op/AC/noise at
defaults with a positive noise spectrum.

`verify_paramrange.py`: 13/13 PASS. Regression: all 52 example verify
suites ALL PASS; 28/28 crate tests.

## Notes

- The default-exemption matches industry practice (and the LRM's intent
  that constraints describe *valid user input*); a model wanting a hard
  default-check can still assert in its analog block.
- The sweep harness (`e56_sweep.py`, `e56_noise_sweep.py`) generates the
  bench from the OSDI descriptor (terminal count/names via a `dlopen`
  dumper); models with thermal terminals get nonsense biases by
  construction — physics-corrected re-runs were used for the triage
  verdicts above.
