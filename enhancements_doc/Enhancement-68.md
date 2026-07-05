# Enhancement-68 — enabling openvaf's own integration test suite (version11)

This document describes Enhancement-68: bringing the fork's dormant
integration test suite — 28 tests over real compact models (BSIM3/4/6,
BSIMBULK, BSIMCMG/IMG/SOI, HiSIM family, MEXTRAM, PSP102/103, HICUM,
EKV, ASMHEMT, diode_cmc, plus the live `$limit`/`noise` numeric tests) —
to life for the first time in this project. Test-infrastructure only:
**the shipped compiler binary is unchanged** (every edit is in test
harness code, test-only loaders, or snapshot data).

## Why it never ran

1. The upstream `vacask` test legs need the **`external/vacask` git
   submodule** (codeberg.org/arpadbuermen/VACASK), which was never
   initialized — and the mini_harness **panicked** on the missing
   directory, taking the whole suite down ("reading test data must
   succeed: NotFound").
2. The remaining tests are gated behind `RUN_DEV_TESTS=1`.
3. Once those hurdles were cleared, the suite's own **OSDI loader was
   frozen at ABI 0.4** ("invalid version v0.7") — this project's three
   ABI bumps (0.5: `OsdiNode.nodeset`, E-45; 0.6: the `ac_stim`
   descriptor tail, E-51; 0.7: the stride-2 signed-pair `load_noise`
   convention, E-54) had never been ported to the test-side structs.

## The fixes (all test-side)

- **`tests/load/osdi_0_4.rs`**: synced to the authoritative OSDI 0.7
  layout (mirroring ngspice's completed `osdi.h`): `OsdiNode.nodeset`,
  the new `OsdiAcStimSource` struct, and the descriptor tail
  (`num_ac_stim_src`/`ac_stim_sources`/`load_ac_stim`).
  **`tests/load/mod.rs`**: version gate 0.4 → 0.7 (the loader matches
  exactly that layout).
- **`tests/mock_sim/mod.rs`**: the noise buffer is stride-2 per source
  since OSDI 0.7 (`[flat, jω-routed]` signed pairs); `read_noise(i)`
  reads `dense[2i]`. The `noise` test's expected values were already
  correct — the test model's factors are all positive, so the flat
  densities are numerically identical under the new convention.
- **`lib/mini_harness`**: a missing test-data directory now **skips its
  tests with a note** instead of panicking the harness (general
  robustness; the suite is fully self-contained after the VACASK
  removal below).
- **13 snapshot files regenerated** (`test_data/osdi/*.snap`) and
  reviewed line by line: every diff is a known feature of this project —
  `flow(<port>)` DAE unknowns (E-29 port-flow probes), `flow(a,b)`
  probe-only branches (E-36), implicit-equation nodes, and their
  Jacobian entries. No parameter metadata or physics changes.

## The VACASK legs were removed outright

VACASK is **AGPL-3.0**, so its device library cannot be vendored here —
and rather than carrying half-alive test legs that depend on cloning an
external repository, the 34 upstream `vacask`/`vacask_spice`/
`vacask_spice_sn` harness entries (and their 34 stale snapshots) were
**removed**. The suite is now fully self-contained: the 26 in-tree
`integration_tests/` models plus the two live numeric tests. (During
development the VACASK legs were run once against a temporary clone —
they passed — before removal.)

## Bonus: the whole dormant dev-test surface is green

`RUN_DEV_TESTS=1` also un-ignores long-dormant harness tests in other
crates — parser (41), syntax (40), hir_lower (30) — **all passing**, so
the project's regression now runs them too.

## Running

```bash
RUN_DEV_TESTS=1 cargo test --release -p openvaf \
    --features openvaf/llvm18 --test integration
```

28 passed; `$limit` and `noise` are live numeric tests against the mock
simulator, the rest are descriptor snapshots + operating-point sanity
checks per model.

## Regression

All example verify suites pass (the integration suite is now part of the
local regression runner); crate tests pass with and without
`RUN_DEV_TESTS`; the VA_TEST corpus compiles 92/92. The compiler binary
is byte-unchanged by this enhancement.
