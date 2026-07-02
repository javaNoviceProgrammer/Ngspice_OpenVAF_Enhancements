# Enhancement-6 — Missing Basic Verilog-A Features in OpenVAF-r (version7)

This document describes every source-code change made to **OpenVAF-r** in
the `version7/` directory, on top of `version6/` (Enhancement-5, module
instantiation), following a deep gap analysis of the compiler against the
Verilog-A/Verilog-AMS LRM across five categories: operators, scale factors,
keywords, math functions, and compiler directives.

## 0. Gap analysis summary

A systematic audit (five parallel research passes over the OpenVAF-r source)
found:

| Category | Verdict |
|---|---|
| Scale factors (`T,G,M,K/k,m,u,n,p,f,a`) | Complete — all 10 correct. |
| Math functions (`ln,exp,sqrt,sin,...,hypot,limit,clog2`) | Complete. |
| Operators | Essentially complete for the analog-only LRM subset (`**`, `^~`/`~^`, `<<`/`>>`, `<+` all present). `===`/`!==`, `{}` concat/replication, reduction ops, `++`/`--`, compound assign are digital/SystemVerilog constructs with no semantic in a pure-analog compiler — correctly out of scope. `<<<`/`>>>` were lexed but dead — **fixed in this enhancement (§2)**. |
| Keywords | `generate`/`genvar` blocks entirely unimplemented (out of scope here — comparable in size to a whole enhancement on its own). `cross`/`above`/`timer` missing entirely (deferred — see §6). `zi_*`, `last_crossing`, `slew`, `transition` were parsed/type-checked but explicitly stubbed as unsupported — **implemented in this enhancement (§4-5)**. |
| Compiler directives | Only 9 of ~17 standard directives worked; everything else hard-failed compilation with `MacroNotFound` instead of being ignored — **fixed in this enhancement (§1)**. |

Sections below cover what was actually implemented, in the order it was
done.

---

## 1. Compiler directives (`openvaf/preprocessor`)

Real foundry/vendor `.va` files routinely carry boilerplate directives that
this compiler previously treated as **undefined macro calls**, hard-failing
the whole compilation. Added recognition (and correct token-consumption) for:

`` `undefineall ``, `` `celldefine ``, `` `endcelldefine ``,
`` `default_discipline ``, `` `default_nettype ``, `` `unconnected_drive ``,
`` `nounconnected_drive ``, `` `timescale ``, `` `line ``, `` `pragma ``.

### 1.1 Design

- `openvaf/preprocessor/src/parser.rs`: new `CompilerDirective` enum
  variants, matched by literal text in `compiler_directive()`.
- Two new `Parser` helpers:
  - `skip_rest_of_line(&mut self, err)` — for directives whose argument
    grammar isn't worth parsing precisely (`` `timescale ``, `` `line ``,
    `` `pragma ``, `` `unconnected_drive ``, `` `default_nettype ``): scans
    the raw source for the next `\n` and discards every token up to it.
    Robust regardless of how the argument text happens to tokenize, since
    Verilog/Verilog-AMS directives with inline arguments are always
    terminated by end-of-line, not by `;`.
  - `bump_directive_and_capture_ident(&mut self, err) -> Option<&str>` — for
    `` `default_discipline `` (captures the discipline name, then falls
    through to `skip_rest_of_line`).
- `openvaf/preprocessor/src/processor.rs`: `Processor` gained a
  `default_discipline: Option<&'a str>` field, set by the new directive but
  **not yet wired into net-discipline resolution** — doing that fully would
  mean threading it through `hir_def`'s name-resolution/discipline-inference
  code (every net currently requires an explicit discipline; see
  `hir_ty/src/validation.rs:699`, `"no discipline for net"`), which is a
  separate, larger feature. Recording it at least means the directive no
  longer breaks compilation.
- `` `undefineall `` clears `self.macros` for real.
- Everything else is a documented no-op (matches how real simulators treat
  directives they don't implement — ignorable, not fatal).

### 1.2 Tests

`openvaf/preprocessor/src/tests.rs::misc_directives` exercises all ten new
directives in one file, asserting zero diagnostics and that the expanded
output contains only the real module body (golden file
`test_data/misc_directives_expanded.va`).

---

## 2. `<<<` / `>>>` arithmetic shift operators

### 2.1 A pre-existing lexer bug

While wiring these up, found that `openvaf/lexer/src/lib.rs`'s three-symbol
match arms for `ShlA`/`ShrA` only called `self.bump()` **once** instead of
twice, so `<<<` tokenized as a 2-character `ShlA` token followed by a stray
`<` — a real, independent bug, not something introduced by this work:

```rust
// before (only consumes 2 of the 3 characters):
'<' if self.first() == '<' && self.second() == '<' => {
    self.bump();
    ShlA
}
// after:
'<' if self.first() == '<' && self.second() == '<' => {
    self.bump();
    self.bump();
    ShlA
}
```
Same fix applied to `ShrA`. Verified via a standalone lexer harness
(`Literal / Whitespace / ShlA len=3 / ...` instead of `len=2` + stray `Lt`).

### 2.2 Wiring

- `openvaf/parser/src/grammar/expressions.rs`: `<<<`/`>>>` added to the
  Pratt-parser precedence table at the same tier as `<<`/`>>`.
- `openvaf/syntax/src/ast/expr_ext.rs`: new `BinaryOp::ArithmeticLeftShift` /
  `ArithmeticRightShift` variants, `op_details()`/`Display` updated.
- `openvaf/syntax/veriloga.ungram`: `BinExpr` operator list updated
  (documentation; codegen for this node's accessors is hand-written, not
  ungram-generated).
- `sourcegen/src/mir_instructions.rs` + regenerated
  `openvaf/mir/src/instructions/generated.rs` /
  `openvaf/mir/src/builder/generated.rs`: new `Opcode::Iashr` (arithmetic —
  sign-extending — right shift). `<<<` reuses `Opcode::Ishl`: per the LRM,
  arithmetic and logical **left** shift are identical (both always
  zero-fill); only right shift differs (logical zero-fills, arithmetic
  sign-extends).
- `openvaf/hir_ty/src/inference.rs`, `openvaf/hir_lower/src/expr.rs`: type
  inference and MIR lowering for the two new `BinaryOp` variants.
- `openvaf/mir_llvm/src/builder.rs`: `Opcode::Iashr` → `LLVMBuildAShr`
  (vs. `Opcode::Ishr` → `LLVMBuildLShr`).
- `openvaf/mir_interpret/src/lib.rs`, `openvaf/mir_opt/src/const_eval.rs`,
  `openvaf/mir_opt/src/simplify.rs`, `openvaf/mir_autodiff/src/lib.rs`,
  `openvaf/mir_autodiff/src/builder.rs`: the six other places that pattern-
  match `Opcode` exhaustively (or via `unreachable!()`/`matches!()`, which
  the compiler doesn't flag as non-exhaustive) needed the new variant added
  too — found by running actual `.va` files through each optimization pass,
  not just `cargo check` (several of these use wildcard `_ => unreachable!()`
  arms that compile fine but panic at runtime on an unhandled opcode).

### 2.3 Verification

`4 <<< 1` constant-folds to `8` (same as `<<`); `-4 >>> 1` constant-folds to
`-2` (arithmetic/sign-extending), confirmed via `--dump-mir` showing the
correctly-folded `0x1.8p2 = 6.0` for `(4<<<1) + (-4>>>1)`.

---

## 3. `slew()` / `transition()` — compile-time rate-limited tracking loop

Previously lowered as a literal identity passthrough
(`self.lower_expr(args[0])`) and gated behind `is_unsupported()` specifically
to stop that silently-wrong stub from reaching users.

### 3.1 Numerical approach

The LRM's `slew()` is an ideal (non-smooth, "bang-bang") rate limiter: track
the input exactly whenever possible, else ramp at the bound. That's not
directly expressible as a well-posed continuous residual — a naive
`dy/dt = clamp(dx/dt, -neg, pos)` formulation leaves the DC operating point
undetermined (any `y` satisfies `dy/dt = 0` at DC). Instead:

```
dy/dt = clamp(K * (x - y), -max_neg_rate, max_pos_rate)      (K = 1e9, large)
```

a saturating tracking loop — well-posed at DC (`y = x` uniquely, since `K` is
large), and reproduces the rate-limited ramp whenever `x` moves faster than
the bound allows, converging to the ideal limiter as `K → ∞`. Implemented as
an ordinary `idt`-style implicit equation (`ImplicitEquationKind::Slew(u32)`)
— no simulator/OSDI changes needed, same category as `laplace_*`.

`transition(x, td, trise, tfall[, tol])` = `slew(absdelay(x, td), 1/trise,
1/tfall)`: the delay stage reuses `absdelay`'s exact mechanism (factored out
into a new shared `lower_delay` helper), the rate stage reuses the same
tracking loop (`ImplicitEquationKind::Transition(u32)`). `trise`/`tfall` are
transition *times* per the LRM; converting to a rate via `rate = 1/t`
assumes a unit-amplitude transition — exact for the common comparator-style
0/1 input, an approximation for arbitrary-amplitude inputs.

New code: `openvaf/hir_lower/src/expr.rs` (`lower_slew`, `lower_transition`,
`lower_delay`, `lower_rate_limited_track`), new `ImplicitEquationKind::Slew`/
`Transition` variants (`openvaf/hir_lower/src/lib.rs`), `hir/src/lib.rs`
gained a `pub use hir_ty::types::Signature;` re-export (needed to name the
signature type from `hir_lower`, which doesn't depend on `hir_ty` directly).
`is_unsupported()` flag removed for both (`openvaf/hir_def/src/builtin.rs`).

### 3.2 Verification

Real ngspice transient simulation (`slew(V(ctrl), 1e6, 2e6)` driven by a
pulse source): measured rise rate over the ramp = exactly 1e6 V/s, fall rate
= exactly 2e6 V/s (to 3+ significant figures), matching the specified bounds.

---

## 4. `zi_nd` / `zi_np` / `zi_zd` / `zi_zp` — bilinear-transform reuse of `laplace_*`

Unlike `laplace_*`, a z-domain filter is inherently a **sampled-data**
system — exact semantics need the simulator to hold the output between
samples taken every `T` seconds, which needs dedicated per-timestep/
breakpoint support that doesn't exist in this codebase (and is a
substantially different, simulator-runtime-level project — see §6).

Instead, this applies the standard **bilinear (Tustin) transform**,
`z^-1 = (1 - sT/2)/(1 + sT/2)`, to convert the z-domain transfer function
into an equivalent **continuous** s-domain transfer function, then reuses
the exact same `laplace_state_space` state-space realization already built
for `laplace_*`. This exactly preserves the filter's pole/zero mapping and
DC/near-DC behavior; it does not reproduce true zero-order-hold/aliasing
behavior near the Nyquist rate (`1/T`) — a documented approximation, not
full LRM fidelity.

### 4.1 Implementation

`openvaf/hir_lower/src/expr.rs`:
- `lower_zi(kind, args)` — extracts `num`/`den` (roots or coefficients, same
  four-way `nd`/`np`/`zd`/`zp` convention as `laplace_*`, reusing
  `lower_laplace_array_arg`/`laplace_roots_to_poly` unchanged), then calls
  `bilinear_transform` on each and feeds the result into the existing
  `laplace_state_space`.
- `bilinear_transform(poly, n, half_t)` — for a degree-`n` z-domain
  polynomial `P(w)` (`w = z^-1`, LRM's ascending-power convention),
  `P(w) * (1+x)^n = Σ_k p_k * (1-x)^k * (1+x)^(n-k)`, a degree-`n` polynomial
  in `x = s·T/2` whose coefficients are fixed, compile-time-known integer
  linear combinations of the `p_k` — the `(1-x)^k(1+x)^(n-k)` binomial
  expansion depends only on `n`/`k`/`i`, not any runtime value, so those
  combination weights are plain `f64` constants (`binomial_bilinear_weight`,
  computed via a multiplicative `binomial(n,k)` helper, no factorial
  overflow risk for realistic filter orders). The `x^i → s^i` conversion
  (`× (T/2)^i`) uses runtime `Value` arithmetic since `T` may be an arbitrary
  expression, not just a literal.

### 4.2 Verification

Two independent checks:
1. **Hand-derived closed form**: for `den=[1,-1]` (a z-domain pole at `z=1`,
   i.e. an ideal digital accumulator `H(z)=1/(1-z^-1)`), the bilinear
   transform maps this to a pure continuous integrator (`den_s=[0,T]`) — an
   exact property of Tustin's method (a DC pole maps to a DC pole exactly).
   Derived by hand and matches what the code produces.
2. **Real ngspice simulation**: a first-order z-domain lowpass (`a1 =
   e^(-T/τ)`, `b0 = 1-a1`, `τ=10µs`, `T=1µs`) settled to the correct DC gain
   (1.0) with ~61.4% rise at `t=τ` (theoretical: 63.2% for an ideal RC —
   the small deviation is the expected/documented bilinear frequency-warping
   effect at a 10:1 `T:τ` ratio).

`is_unsupported()` flag removed for all four (`openvaf/hir_def/src/builtin.rs`).

---

## 5. `last_crossing(expr[, dir])` — OSDI ABI extension + ngspice-46 patch

Unlike `zi_*`, `last_crossing` genuinely needs the simulator's own
accepted-timepoint history — the crossing time is a function of the whole
past trajectory of `expr`, not derivable from its instantaneous value —
so this **does** require extending the OSDI ABI and patching the bundled
`ngspice-46/` simulator, following the exact precedent set by `absdelay()`'s
own OSDI extension (`OsdiAbsDelayInfo`, documented in
`openvaf/osdi/header/osdi_0_4_enhancement1.h`).

### 5.1 ABI design — `openvaf/osdi/header/osdi_0_4_enhancement2.h`

An additive, backward-compatible extension (old simulators ignore the new
symbols; models without `last_crossing()` don't export them), mirroring
`OsdiAbsDelayInfo`'s (`y_node`, `z_node`, `offset`) shape:

```c
typedef struct OsdiLastCrossingInfo {
  uint32_t y_node;      /* synthetic input node y_synth (the watched expr) */
  uint32_t z_node;      /* crossing-time output node z                     */
  uint32_t dir_offset;  /* byte offset of `dir` in per-instance OSDI data  */
} OsdiLastCrossingInfo;
```
exported as `OSDI_LAST_CROSSING_COUNTS[OSDI_NUM_DESCRIPTORS]` /
`OSDI_LAST_CROSSING_INFOS[Σcounts]`, same indexing convention as
`OSDI_ABSDELAY_*`.

Lowered the same way as `absdelay`: `eq_y` (`V(y_synth) = expr`, a normal
compiler-stamped resistive residual so the simulator can read `expr`'s
converged value each accepted timepoint) and `eq_z` (the crossing time,
`V(z)`, stamped entirely by the simulator). **Key simplification vs.
`absdelay`**: `V(z)` has **zero Jacobian sensitivity to `V(y_synth)` almost
everywhere** (crossing time is locally constant in time between crossings,
jumping only at a new crossing — a measure-zero event for Newton iteration),
so unlike `absdelay` the simulator never needs a `J[z,y]` coupling term,
only `J[z,z] = -1` and the crossing-time RHS.

### 5.2 Compiler side

- `openvaf/hir_lower/src/lib.rs`: `ImplicitEquationKind::LastCrossingInput`/
  `LastCrossingOutput`, `PlaceKind::LastCrossingDirection` (`Real`-typed,
  mirroring `AbsDelayTime`), `HirInterner::last_crossing_equations: Vec<(eq_y,
  eq_z)>`.
- `openvaf/hir_lower/src/expr.rs`: `lower_last_crossing` — same shape as the
  `absdelay` block, minus the `tdmax`/interpolation logic (not needed —
  the simulator side does the crossing search). **Correctness bug found and
  fixed during testing**: `dir` is `Val(Integer)` per the LRM signature but
  the storage place is `Real`-typed like all other simulator-read fields —
  needed an explicit `ifcast` before `def_place`, or the raw integer bit
  pattern gets reinterpreted as garbage double data on the C side (caught by
  the crossing time staying stuck at 0.0 in a real ngspice run — see §5.4).
- `openvaf/sim_back/src/context.rs`, `openvaf/hir_lower/src/ctx.rs`:
  `LastCrossingDirection` added to the same "always emit, exempt from
  dead-output collapsing" bucket as `AbsDelayTime`.
- `openvaf/osdi/src/inst_data.rs`, `openvaf/osdi/src/lib.rs`,
  `openvaf/osdi/src/eval.rs`: `last_crossing_dirs: Vec<EvalOutputSlot>` field
  and `store_last_crossing_dirs`/`last_crossing_dir_offset` methods, mirrored
  line-for-line from `delay_times`/`store_delay_times`/`delay_time_offset`;
  `OSDI_LAST_CROSSING_COUNTS`/`INFOS` export block mirrored from the
  `OSDI_ABSDELAY_*` block.

### 5.3 ngspice-46 side (`ngspice-46/src/osdi/`, `ngspice-46/src/include/ngspice/osdiitf.h`)

- `osdiitf.h`: `OsdiRegistryEntry` gained `num_last_crossings`/
  `last_crossing_infos`, mirroring `num_absdelays`/`absdelay_infos`.
- `osdidefs.h`: `OsdiLastCrossingInfo` struct; `OsdiExtraInstData` gained
  `crossing_hist`/`crossing_hist_cap` (waveform history, same pattern as
  `delay_hist`), `crossing_time` (cached last-known crossing time per slot,
  persists across `accept()` calls, initialized to `0.0` = "no crossing
  observed yet"), and `crossing_jac_z`/`_csc`/`_cx` (single matrix pointer
  per slot — no `_y` counterpart needed, since no y-coupling).
- `osdiregistry.c`: reads `OSDI_LAST_CROSSING_COUNTS`/`INFOS` at `.osdi` load
  time, mirroring the `OSDI_ABSDELAY_*` block exactly.
- `osdisetup.c`: allocates the single `J[z,z]` matrix entry per slot
  (`SMPmakeElt`) and the history buffer at instance setup; KLU CSC/complex
  rebinding mirrored from the absdelay blocks (both `OSDIbindCSC` and
  `OSDIupdateCSC`).
- `osdiload.c`: new `last_crossing_stamp()` — unlike `absdelay_stamp_dc`/
  `_tran`, valid in **both** DC/OP and TRAN modes unconditionally (no
  y-coupling means no DC-vs-TRAN distinction is needed): `J[z,z] += -1`,
  `RHS[z] += -crossing_time[k]`. Also calls the existing (now shared, not
  absdelay-only) `absdelay_ensure_timepoints(ckt)` when in TRAN mode — a
  real bug found during testing (§5.4): the shared `ckt->CKTtimePoints`/
  `CKTtimeIndex` accepted-timepoint timeline was previously only initialized
  from inside `absdelay_stamp_tran`, so a circuit using `last_crossing` but
  *no* `absdelay` would never get that timeline set up at all, and
  `OSDIaccept` would silently no-op forever.
- `osdiaccept.c`: new `last_crossing_accept()` — commits `V(y_synth)` into
  `crossing_hist` at each accepted timepoint (same pattern as `delay_hist`),
  then checks whether the just-completed step contains a zero-crossing
  matching the requested direction (`dir>0`: rising, `dir<0`: falling,
  `dir==0`: either), and if so linearly interpolates the crossing time
  within that step and updates the cache. Left unchanged (not reset to 0) if
  no new qualifying crossing is found, so `V(z)` keeps returning the time of
  the *last* crossing, per the LRM.
- `osdiacld.c` (AC): `J[z,z] += -1`, no frequency-dependent term — the
  crossing time has no well-defined small-signal AC sensitivity.

### 5.4 Bugs found and fixed while verifying against real ngspice

1. **`dir` type mismatch** (compiler side, §5.2): fixed by adding the
   missing `ifcast`.
2. **`CKTtimePoints` never initialized without `absdelay`** (ngspice side,
   §5.3): fixed by calling `absdelay_ensure_timepoints(ckt)` from
   `last_crossing_stamp` too, guarded by `is_tran` (the call is idempotent).

Both were caught by running an actual transient simulation and observing the
output stay stuck at `0.0` instead of tracking crossings — a reminder that
`cargo check`/unit tests alone would not have caught either bug (both compile
cleanly; both are runtime logic errors only visible under real simulation).

### 5.5 Verification

Real ngspice-46 (built from `ngspice-46/build` in this directory, **not**
the system-wide ngspice) transient simulation: a 100kHz sine wave (period
10µs) watched with `last_crossing(V(ctrl), 1)` (rising crossings only).
Result: `V(a)` correctly stays `0.0` until the first rising crossing at
`t=10µs`, then jumps to `1.0000148e-5` (0.015% from the theoretical 1.0e-5)
and holds constant until the next rising crossing at `t=20µs`, where it
updates to `2.0000148e-5`. Also re-ran the pre-existing `absdelay_examples/
absdelay.va` 5-stage delay-line example through the patched simulator to
confirm no regression in the shared C code paths (`osdiload.c`/`osdisetup.c`/
`osdiaccept.c`/`osdiacld.c`/`osdiregistry.c` all touched by this change) —
output still ramps up starting at exactly `t=10ns`, matching the expected
5×2ns delay unchanged.

---

## 6. Known limitations / deferred work

- **`cross(expr, dir[, tol[, accuracy]])`, `above(expr[, tol[, accuracy]])`,
  `timer(t0[, period])`** remain unimplemented. Per the LRM these are valid
  **only** as arguments to `@(...)` event-control statements (unlike
  `last_crossing`, which is an ordinary value-returning expression) — so
  implementing them needs new `@()` event-control grammar/HIR semantics
  (currently only `@(initial_step)`/`@(final_step)` are supported) on top of
  further OSDI/ngspice breakpoint-scheduling support, a different and
  larger category of work than everything in this enhancement. The
  `last_crossing` infrastructure built here (§5) — waveform history,
  crossing detection/interpolation — is directly reusable for `cross`'s
  underlying detection logic; `timer` could likely reuse/extend the existing
  `bound_step`/`OsdiExtraInstData` mechanism for periodic breakpoint
  requests. Recommended as its own follow-up enhancement.
- **`generate`/`genvar`** blocks are entirely unimplemented (no grammar
  anywhere in `parser/src/grammar/`) — comparable in scope to the module
  instantiation work in Enhancement-5, and out of scope for this pass.
- **`` `default_discipline ``** is parsed and captured (no longer breaks
  compilation) but not wired into net-discipline inference — every net still
  requires an explicit discipline declaration.
- **Scale-factor/identifier disambiguation** (`1nsec` lexing as `1n` + `sec`
  instead of being rejected per the LRM) — a pre-existing minor edge case,
  noted but not fixed (out of scope, low real-world impact).

---

## 7. Diff summary

| File | Kind of change |
|---|---|
| `openvaf/preprocessor/src/parser.rs` | New `CompilerDirective` variants, `skip_rest_of_line`/`bump_directive_and_capture_ident` helpers |
| `openvaf/preprocessor/src/processor.rs` | Dispatch for 10 new directives, `default_discipline` field |
| `openvaf/preprocessor/src/tests.rs`, `test_data/misc_directives*` | New regression fixture |
| `openvaf/lexer/src/lib.rs` | Bug fix: `ShlA`/`ShrA` three-symbol tokens now consume all 3 characters |
| `openvaf/parser/src/grammar/expressions.rs` | `<<<`/`>>>` precedence |
| `openvaf/syntax/src/ast/expr_ext.rs`, `openvaf/syntax/veriloga.ungram` | `BinaryOp::ArithmeticLeftShift`/`ArithmeticRightShift` |
| `sourcegen/src/mir_instructions.rs`, `openvaf/mir/src/instructions/generated.rs`, `openvaf/mir/src/builder/generated.rs` | New `Opcode::Iashr` |
| `openvaf/hir_ty/src/inference.rs`, `openvaf/hir_lower/src/expr.rs` | Type-check + lowering for arithmetic shift, `slew`/`transition`/`zi_*`/`last_crossing` |
| `openvaf/mir_llvm/src/builder.rs` | `Iashr` → `LLVMBuildAShr` |
| `openvaf/mir_interpret/src/lib.rs`, `openvaf/mir_opt/src/const_eval.rs`, `openvaf/mir_opt/src/simplify.rs`, `openvaf/mir_autodiff/src/lib.rs`, `openvaf/mir_autodiff/src/builder.rs` | `Iashr` handling in constant-fold/const-eval/autodiff passes |
| `openvaf/hir_lower/src/lib.rs` | New `ImplicitEquationKind`/`PlaceKind` variants for slew/transition/last_crossing |
| `openvaf/hir_lower/src/ctx.rs` | `LastCrossingDirection` init value |
| `openvaf/hir/src/lib.rs` | `Signature` re-export, `SLEW_*`/`TRANSITION_*`/`LAST_CROSSING_*` signature re-exports |
| `openvaf/sim_back/src/context.rs` | `LastCrossingDirection` output-collapsing exemption |
| `openvaf/hir_def/src/builtin.rs` | `is_unsupported()` flag removed for `slew`, `transition`, `zi_nd/np/zd/zp`, `last_crossing` |
| `openvaf/osdi/src/inst_data.rs`, `openvaf/osdi/src/lib.rs`, `openvaf/osdi/src/eval.rs` | `OsdiLastCrossingInfo` export, mirrored from `OsdiAbsDelayInfo` |
| `openvaf/osdi/header/osdi_0_4_enhancement2.h` | New OSDI ABI extension document |
| `ngspice-46/src/include/ngspice/osdiitf.h`, `ngspice-46/src/osdi/osdidefs.h`, `osdiregistry.c`, `osdisetup.c`, `osdiload.c`, `osdiaccept.c`, `osdiacld.c` | `last_crossing` runtime support (history, crossing detection, matrix stamping), mirrored from the `absdelay` implementation |
| `bin/macos/apple-silicon/ngspice` | Rebuilt from the patched `ngspice-46/build` tree |

No changes to `openvaf/osdi`'s `OsdiDescriptor` layout or `OSDI_DESCRIPTOR_SIZE`
(binary-compatible, additive-only extension, same guarantee as Enhancement
1's `absdelay` extension).
