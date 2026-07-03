# Enhancement-10 — Verilog-A statistical / random-number system functions (version11)

This document describes the source-code changes made to **OpenVAF-r** in the
`version11/` directory, on top of `version10/` (Enhancement-9, noise sources +
`repeat`/`disable`/`localparam`/`ground`/string-var fixes), to implement the
Verilog-AMS **random-number and statistical-distribution system functions**:

- `$random`, `$arandom`
- `$rdist_uniform`, `$rdist_normal`, `$rdist_exponential`, `$rdist_poisson`,
  `$rdist_chi_square`, `$rdist_t`, `$rdist_erlang` (real-valued)
- `$dist_uniform`, `$dist_normal`, `$dist_exponential`, `$dist_poisson`,
  `$dist_chi_square`, `$dist_t`, `$dist_erlang` (integer-valued)

All work is in `version11/` only; all simulation verification uses
`version11/ngspice-46`'s own locally built binary and
`version11/OpenVAF-master`'s own `openvaf-r`.

## 0. Scope and the starting point

A gap analysis of the version11 baseline showed the random/statistical family
was **fully recognised by the front-end but rejected before codegen**:

- `openvaf/hir_ty/src/builtin.rs` already declares complete, multi-form type
  signatures for every function (seeded / const-seed / named variants), so
  calls type-check.
- But `openvaf/hir_def/src/builtin.rs`'s `is_unsupported()` listed all of them,
  so `hir_ty/src/validation/body.rs` emitted **`UnsupportedFunction`** and the
  build stopped. No MIR lowering and no runtime existed.

So, exactly like Enhancement-9's `noise_table`, the front-end was complete and
the back-end was missing. Enhancement-10 removes the `is_unsupported()` gate,
adds MIR lowering, and adds a small deterministic RNG runtime to the OSDI
standard library. **ngspice-46 needed no changes** — the functions lower to an
ordinary pure callback resolved generically in `general_callbacks`, exactly like
`$simparam`.

## 1. Semantics: deterministic, read-only seed (the key design decision)

The LRM nominally treats the seed as `inout`: each call advances it in place.
In a circuit simulator that model is actively harmful. Analog-block variables in
OpenVAF are persistent hidden state that is **re-read at the start and stored at
the end of *every* `eval()` call** (`osdi/src/eval.rs` calls
`store_hidden_state` unconditionally — once per Newton iteration, not once per
accepted timepoint). An in-place-advancing seed would therefore produce a
*different* random value on every Newton iteration, so any residual built from
it would never converge, and the DC/transient problem would be ill-posed.

Enhancement-10 instead defines each draw as a **pure, deterministic function of
`(seed_value, call-site salt, parameters)`**, with **no writeback**:

- **Reproducible** — the same seed always yields the same value.
- **Stable across the nonlinear solve** — the value does not change between
  Newton iterations or accepted timepoints, so it is safe to use anywhere,
  including directly in a residual. This is what makes it usable in a SPICE
  engine.
- **Per-instance variation** — because the seed can be an instance parameter (or
  any expression), distinct instances draw distinct, independent samples. This
  is the dominant real use case: process/mismatch variation.
- **Independent streams per call site** — the compiler mixes a unique
  per-call-site *salt* (the call `ExprId`) into the generator state, so two
  textual calls with the *same* seed variable are decorrelated (e.g.
  `$rdist_normal(s,0,1) - $rdist_normal(s,0,1)` is not identically zero).

**Documented deviation from the LRM:** the seed is not advanced in place, so
repeatedly calling the *same* call site with the *same* seed value (e.g. drawing
in a loop without changing the seed) returns the same value. To draw a
*sequence*, vary the seed (`$rdist_normal(seed+i, …)`, or advance a seed
variable yourself). This is the standard, convergence-safe interpretation for a
circuit simulator and is sufficient for statistical device modelling.

## 2. Front-end: ungating (`hir_def/src/builtin.rs`)

`is_unsupported()` previously returned `true` for `dist_*`, `rdist_*`, `random`
and `arandom`. Those arms are removed (the file/string-I/O and node-alias
builtins remain unsupported). A comment records that Enhancement-10 owns their
lowering, mirroring the existing note about the Enhancement-6 analog operators.
`validation/body.rs` then falls through to its `_ => ()` arm, so the calls are
accepted and reach lowering.

## 3. MIR lowering (`hir_lower`)

### 3.1 The callback (`callbacks.rs`)

A single new `CallBackKind::Rng(RngFun)` variant is added, where `RngFun`
enumerates the nine distinct underlying generators (`Random`, `Uniform`,
`UniformInt`, `Normal`, `Exponential`, `Poisson`, `ChiSquare`, `StudentT`,
`Erlang`). It is a pure callback (`has_sideeffects: false`) whose MIR call
arguments are `(seed: int, salt: int, params…: real)`; `RngFun` maps to the
runtime function name and its real-parameter count. Because the salt is passed
as an *argument* rather than stored in the kind, all call sites of one `RngFun`
share a single interned callback (efficient), while their distinct salt
arguments keep them uncorrelated and un-CSE'd.

### 3.2 Dispatch (`expr.rs`)

Each builtin lowers to `lower_rng`, which reads the seed value, appends the
call `ExprId` as the salt constant, appends the (real) distribution parameters,
and emits the callback. Return-type handling follows OpenVAF's **signature
table**, which types every `$dist_*`/`$rdist_*` as `Real` and only
`$random`/`$arandom` as `Integer`:

- `$random`/`$arandom` → `ficast` the real callback result to an integer MIR
  value.
- `$rdist_*` → return the real result directly.
- `$dist_*` → the LRM defines these as integer-valued, so round to the nearest
  integer (`rng_round_real` = `floor(x + 0.5)`) but keep the value **real**
  (its OpenVAF type is `Real`; returning an int MIR value here would be
  reinterpreted bit-for-bit and yield garbage — this was a real bug caught in
  testing).

Two robustness details:

- `lower_num_as_real` coerces integer distribution parameters to real using the
  *post-lowering* type (from `needs_cast`), because the parameter type is
  signature-dependent — at least one upstream const-seed signature even mixes a
  `Val(Real)` into an otherwise-integer form. Driving the coercion by the actual
  lowered type avoids a double cast.
- Autodiff already treats any non-`ddx` `Call` as zero-derivative
  (`mir_autodiff::is_zero_call`), so a random value feeding a residual is
  correctly constant with respect to the unknowns — no special-casing needed.

## 4. Runtime (`osdi/src/compilation_unit.rs`, `osdi/stdlib.c`)

`general_callbacks` resolves `CallBackKind::Rng(fun)` to the matching
`osdi_rng_*` C function (built type `(i32, i32, double…) -> double`, no
prepended state). Because both `eval()` and the `setup`/init function call
`general_callbacks`, the functions work in the analog block, in `@(initial_step)`
and in instance/parameter initialisation.

`stdlib.c` gains the nine `osdi_rng_*` functions plus `extern` declarations for
`sqrt`/`exp`/`cos` (the file is compiled `-DNO_STD`, so like the pre-existing
`log` these resolve against the host libm at OSDI load — no ngspice change). The
core generator is **splitmix64** seeded by an avalanche hash of `(seed, salt)`;
each uniform advances a *local* 64-bit state, so multi-uniform distributions
(normal via Box-Muller, chi-square/student-t as sums of squared normals, erlang
as a sum of exponentials, poisson via Knuth) draw independent underlying
uniforms within one call. Everything is a pure function of `(seed, salt)`.

## 5. Build-system fix (`osdi/build.rs`) — necessary for the runtime to load

The versionN workflow copies the whole `target/` directory from the previous
version. `osdi/build.rs` located `stdlib.c` via `stdx::project_root()`, which
bakes `CARGO_MANIFEST_DIR` at `stdx`'s compile time; the copied build-script
binary therefore still pointed at an **older checkout's** `stdlib.c`
(`.../version6/…` was observed), so edits to `version11/…/stdlib.c` were silently
ignored and the new `osdi_rng_*` symbols were missing at load
(`stdlib function osdi_rng_uniform is missing`). Fixed by reading the fresh,
per-invocation `CARGO_MANIFEST_DIR` env var instead — it always points at the
crate being built. This is a general robustness fix for the copy-the-target
workflow, not specific to this feature.

## 6. Verification (`rng_examples/`)

`rng_demo.va` fixes `V(p,n)` to a single draw selected by a `dist` model
parameter and stream-selected by `seed`. Since each draw is a stable,
reproducible function of `(seed, call site)`, instantiating N devices with seeds
`1..N` and running one `.op` yields N i.i.d. samples. `verify_rng.py` compiles
with this version's `openvaf-r`, builds the deck, runs this version's `ngspice`
as a subprocess (a bare heredoc misbehaves in some shells — a known project
note), parses the node voltages and checks, for N = 4000 samples each:

| check | result |
|---|---|
| `$rdist_uniform[-2,6)` mean/std vs `(2, √(64/12))` | PASS |
| `$rdist_normal(3,2)` mean/std | PASS |
| `$rdist_exponential(4)` mean/std (= mean) | PASS |
| `$rdist_poisson(5)` mean/std (var = mean) | PASS |
| `$rdist_chi_square(4)` mean/std (= k, √(2k)) | PASS |
| `$rdist_erlang(k=3,mean=6)` mean/std | PASS |
| `$rdist_t(5)` mean≈0, std≈√(5/3) | PASS |
| `$random` sign balance, magnitude spread, integrality | PASS |
| `$dist_uniform(0,6)` fair-die: faces {0…6}, mean≈3 | PASS |
| `$dist_normal(5,2)` integer-valued, mean≈5, Sheppard-corrected std | PASS |
| reproducibility (same seeds → identical) & independence | PASS |

`24/24 checks PASS`. Touched-crate unit tests pass (`sim_back` 24/24; `hir_ty`,
`hir_lower`, `hir_def` data-tests unchanged).

`plot_mc.py` additionally exercises **all three analysis types** on a Monte-Carlo
RC low-pass (`rc_mc.va`), whose gain/R/C are perturbed per instance by
`$rdist_normal` (three independent streams from one seed via the call-site salt).
A single ngspice job runs `.dc`, `.ac` and `.tran` over N=30 randomized instances
and produces `mc_dc.png` (random DC gains, 1.00 ± 0.17), `mc_ac.png` (spread of
Bode magnitudes / cutoffs about fc ≈ 159 Hz) and `mc_tran.png` (spread of 1 V step
responses about τ = 1 ms), each overlaid on the nominal response. This confirms
the draws are stable within and across DC/AC/transient solves — the convergence
property §1 is built around.

## 7. Diff summary

| File | Kind of change |
|---|---|
| `openvaf/hir_def/src/builtin.rs` | Removed the `is_unsupported()` entries for `random`/`arandom`/`dist_*`/`rdist_*` (they now lower), with an explanatory note (§2) |
| `openvaf/hir_lower/src/callbacks.rs` | New `RngFun` enum (9 generators, `stdlib_name()`/`num_real_params()`) + pure `CallBackKind::Rng(RngFun)` variant and its `FunctionSignature` (§3.1) |
| `openvaf/hir_lower/src/lib.rs` | Re-export `RngFun` |
| `openvaf/hir_lower/src/expr.rs` | Lowering for all 16 builtins: `lower_rng` (seed + call-site salt + real params → callback), `lower_rng_seed`, `lower_num_as_real`, `rng_round_real`; `Real`/`Integer` return handling (§1, §3.2) |
| `openvaf/osdi/src/compilation_unit.rs` | `general_callbacks` resolves `CallBackKind::Rng(fun)` to the `osdi_rng_*` runtime function with the right LLVM type (§4) |
| `openvaf/osdi/stdlib.c` | Nine deterministic `osdi_rng_*` runtime functions (splitmix64 core, Box-Muller / Knuth / sums) + `extern sqrt/exp/cos` (§4) |
| `openvaf/osdi/build.rs` | Locate `stdlib.c` via the per-invocation `CARGO_MANIFEST_DIR` instead of `stdx::project_root()`, so a copied `target/` cannot make the build read another checkout's `stdlib.c` (§5) |
| `rng_examples/` | New analytically-verified example suite: `rng_demo.va` + `verify_rng.py` (all 16 functions, 24/24 moment/integrality checks) and `rc_mc.va` + `plot_mc.py` (DC/AC/transient Monte-Carlo → `mc_dc.png`/`mc_ac.png`/`mc_tran.png`), `README.md` (§6) |
