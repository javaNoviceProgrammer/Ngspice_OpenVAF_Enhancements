# Ngspice + OpenVAF Enhancements
**Owner: Dr. Meisam Bahadori**

Using Claude Code AI to enhance the ngspice and openvaf frameworks.

[![Build binaries](https://github.com/javaNoviceProgrammer/Ngspice_OpenVAF_Enhancements/actions/workflows/build-binaries.yml/badge.svg)](https://github.com/javaNoviceProgrammer/Ngspice_OpenVAF_Enhancements/actions/workflows/build-binaries.yml)

Main goals:
- turn ngspice into the most powerful spice simulator
- turn openvaf-r into the most powerful verilog-a compiler


## Precursors

Original OpenVAF git repository by Pascal Kuthe:

https://github.com/pascalkuthe/OpenVAF

OpenVAF-Reloaded git repository by Árpád Bűrmen:

https://github.com/arpadbuermen/OpenVAF

Ngspice Homepage:

https://ngspice.sourceforge.io/

---

## Enhancement 1: `absdelay()` support for Verilog-A / OSDI

*June 2026* — Implements the Verilog-A `absdelay(signal, td)` operator end-to-end through the OSDI flow, using the **synthetic-node DAE approach** in OpenVAF and ngspice.

- Verified for DC, AC, and Transient analysis
- Verified for both SPARSE and KLU solvers
- Details: [Enhancement-1.md](enhancements_doc/Enhancement-1.md)

**KLU vs SPARSE benchmark** (DC / AC / Transient across circuit sizes):

![Benchmark](./examples/absdelay_examples/benchmark/results/benchmark.png)

---

## Enhancement 2: Indirect branch assignment for Verilog-AMS

*June 2026* — Implements the Verilog-AMS **indirect branch assignment** construct (`<lhs> : <rhs> == <expr>;`) in OpenVAF, enabling ideal/abstract behavioral models such as the LRM's ideal op-amp. One new DAE unknown + implicit equation is added per statement, fully reusing the existing branch-contribution and residual machinery — no ngspice/OSDI changes were needed.

- Verified for DC, AC, and Transient analysis (unity-gain buffer built from the ideal op-amp)
- Verified for no regressions against the Enhancement-1 `absdelay` examples
- Details: [Enhancement-2.md](enhancements_doc/Enhancement-2.md)

**DC / AC / Transient results** for the ideal op-amp unity-gain buffer:

<p align="center">
  <img src="./examples/indirect_assignment_examples/dc.png" width="32%" alt="DC sweep">
  <img src="./examples/indirect_assignment_examples/ac.png" width="32%" alt="AC response">
  <img src="./examples/indirect_assignment_examples/tran.png" width="32%" alt="Transient response">
</p>

---

## Enhancement 3: Vectored/bus-style net declarations for Verilog-A

*June 2026* — Implements Verilog-AMS **vectored net declarations** (bus syntax) in OpenVAF: `<discipline> [msb:lsb] name;` for nets and ports, with bit-select access (`bus[i]`) in branch declarations and `V()`/`I()` branch-access calls. A bus expands into independent scalar nodes at name-resolution time, so the feature is purely a front-end (parser/HIR) concern — no DAE, MIR, or OSDI changes were needed.

- Verified for DC, AC, and Transient analysis (a 4-tap fractional buffer driven through a `[0:3]` bus output port)
- Verified for no regressions against the Enhancement-1 `absdelay` and Enhancement-2 indirect-branch-assignment examples
- Details: [Enhancement-3.md](enhancements_doc/Enhancement-3.md)

**DC / AC / Transient results** for the 4-tap bus-output buffer:

<p align="center">
  <img src="./examples/bus_examples/dc.png" width="32%" alt="DC sweep">
  <img src="./examples/bus_examples/ac.png" width="32%" alt="AC response">
  <img src="./examples/bus_examples/tran.png" width="32%" alt="Transient response">
</p>

---

## Enhancement 4: Laplace transform filter operators, and array-variable declarations, for Verilog-A

*June 2026* — Implements Verilog-A's four **Laplace transform filter** analog operators (`laplace_nd`/`laplace_np`/`laplace_zd`/`laplace_zp`) by converting a transfer function `H(s) = num(s)/den(s)` into an exact controllable-canonical-form state-space realization at compile time, reusing the same implicit-equation/residual machinery `idt()` already uses — no new DAE primitive, and no `sim_back`/`osdi` changes were needed. Along the way, two latent front-end gaps were found and fixed: array-literal expressions (`'{...}'`/`{...}`) were fully scaffolded but never actually parsed, and the array-literal type-checker had a bug that made every array literal type-check as a bare scalar. As a follow-up, **array-variable declarations** (`real [msb:lsb] x;`) were also added, reusing Enhancement-3's bit-select machinery almost unchanged.

- Verified for DC, AC, and Transient analysis (a first-order RC-style low-pass filter, `H(s) = 1/(1+tau*s)`, realized with no actual resistor/capacitor in the model) — exact `-3dB`/`-45°` at the corner frequency, `-20dB`/decade rolloff, and `63.2%` step response at `t=tau`
- Verified all four `laplace_*` forms (coefficient and pole/zero) agree exactly on two equivalent transfer functions
- Verified array-variable declare/write/read end-to-end with a 5-tap weighted-sum model
- Verified for no regressions against the Enhancement-1/2/3 examples
- Verified against a **real 5th-order analog Bessel low-pass filter**, cross-checked against the identical transfer function's analytical response computed independently in Python (`scipy.signal`) — numerical-noise-level agreement (max AC gain error 5.6e-7 dB, max phase error 7.2e-7°, max step-response error 6.6e-6 V). This also surfaced (and fixed) a compiler crash on large bare-integer-shaped literals.
- Details: [Enhancement-4.md](enhancements_doc/Enhancement-4.md)

**DC / AC / Transient results** for the Laplace low-pass filter:

<p align="center">
  <img src="./examples/laplace_examples/dc.png" width="32%" alt="DC sweep">
  <img src="./examples/laplace_examples/ac.png" width="32%" alt="AC response">
  <img src="./examples/laplace_examples/tran.png" width="32%" alt="Transient response">
</p>

**Simulated vs. analytical** results for the 5th-order Bessel filter:

<p align="center">
  <img src="./examples/bessel_filter_examples/ac_compare.png" width="48%" alt="AC response comparison">
  <img src="./examples/bessel_filter_examples/tran_compare.png" width="48%" alt="Step response comparison">
</p>

---

## Enhancement 5: Module instantiation for Verilog-A

*July 2026* — Implements Verilog-A **module instantiation** (one module placing other modules as sub-circuit elements on its own nets), which had zero support anywhere in the compiler beforehand. Every layer downstream of the parser (name resolution, type inference, MIR lowering, the DAE builder, OSDI codegen) is architected around exactly one flat module per compiled artifact, so hierarchy is resolved as a **compile-time text-flattening elaboration pass**: instantiated modules are recursively inlined — alpha-renamed per instance, with ports bound to the caller's nets and parameters bound to the caller's overrides — into an ordinary, hand-written-looking flat module *before* the rest of the pipeline ever runs, requiring **zero changes** to `hir_ty`/`hir_lower`/`mir*`/`sim_back`/`osdi`.

- Full feature set: named (`.p(net)`) and positional (`(net)`) port connections, including open/unconnected ports; named (`.r(1e3)`) and positional (`#(1e3)`) parameter overrides; instance arrays (`resistor rarr[0:3](...)`); arbitrary nesting depth; cyclic instantiation is a clean compile error, not a stack overflow
- Bus-typed ports and per-element instance-array slicing: a matching-width bus in the caller's scope is sliced bit-by-bit / element-by-element onto a target bus port or array instantiation, falling back to plain broadcast otherwise
- Works across an `` `include `` boundary with no special-casing — a module can instantiate a target declared in a different file, since `` `include `` is resolved by the preprocessor before the elaboration pass ever inspects the parse tree
- Verified for DC, AC, and Transient analysis on a hierarchical resistor network (nested instantiation, both override forms, an instance array) — matches an independent analytical resistor-network computation to ~1e-9 (solver precision)
- Verified a module that both instantiates sub-modules *and* has its own directly-written `analog` block — the inlined instance equations and the module's own contribution combine correctly under all three analyses
- Verified for no regressions against the Enhancement-1/2/3/4 examples
- Details: [Enhancement-5.md](enhancements_doc/Enhancement-5.md)

**DC / AC / Transient results** for the hierarchical resistor-divider network:

<p align="center">
  <img src="./examples/instantiation_examples/dc.png" width="32%" alt="DC sweep">
  <img src="./examples/instantiation_examples/ac.png" width="32%" alt="AC response">
  <img src="./examples/instantiation_examples/tran.png" width="32%" alt="Transient response">
</p>

---

## Enhancement 6: Missing basic Verilog-A features

*July 2026* — A systematic gap analysis against the Verilog-A/AMS LRM across operators, scale factors, keywords, math functions, and compiler directives, followed by implementing everything found tractable in one pass: ten **compiler directives** (`` `default_discipline ``, `` `celldefine ``/`` `endcelldefine ``, `` `unconnected_drive ``/`` `nounconnected_drive ``, `` `timescale ``, `` `line ``, `` `pragma ``, `` `undefineall ``, `` `default_nettype ``) that previously hard-failed compilation as undefined macro calls; the `<<<`/`>>>` **arithmetic shift** operators (plus a real pre-existing lexer bug fix); `slew()`/`transition()`, realized as a saturating rate-limited tracking loop needing no simulator changes; `zi_nd/np/zd/zp()`, realized via a **bilinear (Tustin) transform** to an equivalent continuous transfer function reusing the existing `laplace_*` machinery; and `last_crossing()`, which genuinely needed simulator history — an additive, backward-compatible **OSDI ABI extension** (following the `absdelay()` extension's precedent) plus a matching `ngspice-46` runtime patch (waveform history, crossing detection/interpolation, matrix stamping).

- All five features verified against real ngspice DC/AC/Transient simulation, not just compile checks — see `examples/directive_examples/`, `examples/shift_examples/`, `examples/slew_examples/`, `examples/transition_examples/`, `examples/zi_examples/`, `examples/last_crossing_examples/`
- `slew()`: AC response lands exactly on the predicted first-order tracking-loop pole (`K/2π ≈ 159MHz`); transient measured rise/fall rates match the specified bounds to 3+ significant figures
- `zi_nd()`: AC response shows the expected `-3dB` corner *and* the documented bilinear frequency-warping artifact near the Nyquist rate; transient step response matches an RC step response closely
- `last_crossing()`: transient output steps to the correct crossing times (e.g. `1.0000148e-5` vs theoretical `1.0e-5`, 0.015% error) on a 100kHz sine wave — two real bugs (an `int`/`real` cast bug and a shared-timeline initialization bug) were found only by testing against actual simulation, both compiled cleanly and were only visible at runtime
- Verified for no regressions against the full existing test suite — bit-exact/floating-point-noise-level unchanged DC, AC, and transient results
- Deferred: `cross()`/`above()`/`timer()` need new `@()` event-control grammar (not just an OSDI extension), and `generate`/`genvar` blocks are unimplemented — both out of scope here, noted as follow-up work
- Details: [Enhancement-6.md](enhancements_doc/Enhancement-6.md)

**AC response** for the `zi_nd()` z-domain lowpass filter (bilinear-transform realization):

<p align="center">
  <img src="./examples/zi_examples/dc_plot.png" width="32%" alt="DC sweep">
  <img src="./examples/zi_examples/ac_plot.png" width="32%" alt="AC response">
  <img src="./examples/zi_examples/tran_plot.png" width="32%" alt="Transient response">
</p>

**Transient result** for `last_crossing()` tracking rising zero-crossings of a 100kHz sine wave:

<p align="center">
  <img src="./examples/last_crossing_examples/tran_plot.png" width="60%" alt="last_crossing transient result">
</p>

---

## Enhancement 7: `@(initial_step)` event gating and variable persistence

*July 2026* — While scoping `cross()`/`above()`/`timer()` (deferred from Enhancement 6), found and fixed a foundational, pre-existing gap those operators — and a large fraction of real-world Verilog-A models — depend on: `@(initial_step)`/`@(final_step)` event-control statements didn't gate anything at all (the guarded statement ran on *every* evaluation, forever), and ordinary `real`/`integer` analog-block variables didn't persist their value across evaluations either, with zero event-control involved. Fixed both: a new `ParamKind::IsInitialStep` simulator-provided flag with real conditional lowering for event-control statements, and genuine per-instance storage (`hidden_state`) for variable values across evaluations, backed by a two-pass MIR build to correctly identify which variables need it without regressing dead-code elimination.

- Both fixes verified against real ngspice DC/AC/Transient simulation — see `examples/initial_step_examples/`, `examples/variable_persistence_examples/`
- `@(initial_step)`: verified via `--dump-mir` (a real conditional branch, not dead code) and a real ngspice run showing the gating flag set exactly once per instance
- Variable persistence: a self-referential accumulator (`accum = accum + 1.0;`) now genuinely accumulates across transient timepoints instead of resetting to its default every evaluation
- Verified for no regressions against the full existing test suite — bit-exact/floating-point-noise-level unchanged DC, AC, and transient results
- Known limitation (documented, not fixed): an *explicit* `@(initial_step)` statement that writes to a variable can crash the compiler — narrow edge case, redundant now that plain declared initializers get correct once-only gating automatically
- Deferred to Enhancement 8: `cross()`/`above()`/`timer()` event operators and `generate`/`genvar` blocks — both remain fully unimplemented
- Details: [Enhancement-7.md](enhancements_doc/Enhancement-7.md)

**Transient result** for the variable-persistence fix — a self-referential accumulator with genuine, sustained persistence across timepoints:

<p align="center">
  <img src="./examples/variable_persistence_examples/tran_plot.png" width="60%" alt="variable persistence transient result">
</p>

---

## Enhancement 8: `generate for`/`genvar` and `cross()`/`above()`/`timer()` event-control

*July 2026* — Implements the two features deferred from Enhancement 7. **`generate for`/`genvar`** (structural/declarative loop-based generation of nets, instances, variables, and parameters) is added as a new grammar production plus a text-level elaboration pass mirroring Enhancement 5's module-instantiation flattening, needing zero downstream (`hir_ty`/`mir*`/`sim_back`/`osdi`) changes. **`cross()`/`above()`/`timer()`** extend `@(...)`'s existing event-control grammar with real eval-granularity edge/timer detection (a persistent "previous value" slot, the same mechanism as Enhancement 7's variable persistence) — the original plan called for an OSDI ABI extension and `ngspice` breakpoint-forcing (`CKTsetBreak`), but this was descoped during implementation once eval-granularity detection proved sufficient, so **no OSDI ABI or `ngspice` C-side changes were needed** for the event functions themselves.

Verifying the event functions' primary real-world use case — accumulating a persistent counter on each firing (`count = count + 1.0;` inside the event body) — surfaced a chain of three pre-existing, general compiler bugs (confirmed present in the unmodified pre-Enhancement-7 baseline, not introduced by this work), all now found and fixed: a dangling-reference bug in the CFG-simplifier's unreachable-block removal, a multi-exit post-dominance bug in the dominator-tree builder, and a block-merge bug that could corrupt which block the DAE builder treated as the function's true exit. A fourth, unrelated `ngspice` parsing bug was also found and fixed along the way: a multi-parameter `.model` card override silently dropped its first parameter.

- `generate for`/`genvar`: verified via `--dump-mir` equivalence against a hand-written unrolled version (identical MIR/DAE shape) and a bit-exact ngspice DC sweep match on a `generate`-built resistor ladder — see `examples/generate_examples/`
- `cross()`/`above()`/`timer()`: verified via `--dump-unopt-mir` (genuine conditional branches on the edge-detection condition, not dead code) and real ngspice DC/AC/transient runs — see `examples/cross_examples/`, `examples/timer_examples/`
- All three event functions now demonstrate genuine persistent-counter accumulation across firings (not just `$strobe` reporting), confirming the compiler-bug chain above is fully fixed
- Verified for no regressions against the full existing test suite — bit-exact/floating-point-noise-level unchanged DC, AC, and transient results
- Details: [Enhancement-8.md](enhancements_doc/Enhancement-8.md)

**DC sweep** for `generate for`-built vs. hand-written resistor ladders (bit-exact match):

<p align="center">
  <img src="./examples/generate_examples/dc.png" width="60%" alt="generate for DC sweep">
</p>

**DC / AC / Transient results** for `above()`'s persistent firing counter:

<p align="center">
  <img src="./examples/cross_examples/above_dc.png" width="32%" alt="above() DC sweep">
  <img src="./examples/cross_examples/above_ac.png" width="32%" alt="above() AC response">
  <img src="./examples/cross_examples/above_tran.png" width="32%" alt="above() transient response">
</p>

**DC / AC / Transient results** for `cross()`'s persistent firing counter:

<p align="center">
  <img src="./examples/cross_examples/cross_dc.png" width="32%" alt="cross() DC sweep">
  <img src="./examples/cross_examples/cross_ac.png" width="32%" alt="cross() AC response">
  <img src="./examples/cross_examples/cross_tran.png" width="32%" alt="cross() transient response">
</p>

**DC / AC / Transient results** for `timer()`'s persistent tick counter:

<p align="center">
  <img src="./examples/timer_examples/timer_dc.png" width="32%" alt="timer() DC sweep">
  <img src="./examples/timer_examples/timer_ac.png" width="32%" alt="timer() AC response">
  <img src="./examples/timer_examples/timer_tran.png" width="32%" alt="timer() transient response">
</p>

---

## Enhancement 9: Verilog-A noise tables, language fixes, and `repeat`/`disable` loops

*July 2026* — Completes the Verilog-A **noise-source** family: **`noise_table()`/`noise_table_log()`** are implemented end-to-end — reading the frequency/power data from an inline real array or a two-column data file, and generating `log10`-domain piecewise-linear, endpoint-clamped interpolation in the OSDI `load_noise` codegen — where before they read no data and hit an `unimplemented!()` in the backend. `white_noise()`/`flicker_noise()` already worked and are included as verified reference examples. **No OSDI ABI or `ngspice` C-side changes were needed**: ngspice's existing OSDI `.noise` path drives the new interpolation transparently.

Several unrelated language gaps found along the way are also fixed. **`localparam`** is now non-overridable per the LRM (it previously behaved exactly like `parameter`), while derived localparams (`localparam G = 1/R`) still correctly track their inputs; the **`electrical ground gnd;`** net-declaration ordering now parses (only `ground electrical gnd;` did before); **`slew`/`transition`/`last_crossing`/`zi_*`** — implemented back in Enhancement 6 — were re-enabled after Enhancement 8's `builtin.rs` regeneration had silently re-added their "unsupported" gate; and an **uninitialized `string` variable** now defaults to `""` instead of crashing the compiler. Two new statements are added: the **`repeat (count)`** loop, and **`disable <named_block>;`** — Verilog-A's early-exit mechanism, from which both loop `break` and `continue` are built (the language has no `break`/`continue` keywords).

- `noise_table`/`noise_table_log`: verified against closed-form analytics through ngspice `.noise` analysis (interpolated power spectral density matches to floating-point-noise level), alongside `white_noise`/`flicker_noise` — see `examples/noise_examples/`
- `localparam`, `ground`, `string` variables, `repeat`, `disable`: each verified end-to-end through ngspice — see `examples/localparam_examples/`, `examples/ground_examples/`, `examples/vartype_examples/`, `examples/repeat_examples/`, `examples/disable_examples/`
- Verified for no regressions against the full existing test suite and every prior example folder (clean release build of `openvaf-r` + `ngspice`, compile + simulate, with bit-exact reproduction of committed results)
- Details: [Enhancement-9.md](enhancements_doc/Enhancement-9.md)

**Noise spectral densities** for `white_noise`, `flicker_noise`, `noise_table`, and `noise_table_log`, each vs. its closed-form analytical prediction:

<p align="center">
  <img src="./examples/noise_examples/noise_spectra.png" width="70%" alt="noise source spectra vs analytics">
</p>

---

## Enhancement 10: Verilog-AMS random and statistical-distribution functions

*July 2026* — Implements the full random/statistical system-function family: **`$random`/`$arandom`** and every **`$dist_*`/`$rdist_*`** distribution (uniform, normal, exponential, poisson, chi-square, student-t, erlang), via MIR lowering to pure `osdi_rng_*` runtime functions (a splitmix64 core) — **no `ngspice` changes**. Each draw is a deterministic function of `(seed, per-call-site salt)` with *no* in-place seed advance: reproducible, stable across the nonlinear solve (an advancing seed would change every Newton iteration and break DC/transient convergence), and giving independent per-instance variation — the right semantics for statistical device modelling.

- Every distribution verified against its closed-form moments (mean/variance) over thousands of instances, plus reproducibility, stream independence, and `$random` integrality — see `examples/rng_examples/` (`verify_rng.py`, 24/24)
- DC/AC/transient Monte-Carlo demo: an RC filter whose gain/R/C are perturbed by `$rdist_normal`, with plots
- Details: [Enhancement-10.md](enhancements_doc/Enhancement-10.md)

---

## Enhancement 11: File I/O and string-formatting system functions

*July 2026* — Implements the Verilog-AMS **file I/O** functions — **`$fopen`/`$fclose`/`$fdisplay`/`$fwrite`/`$fstrobe`/`$fmonitor`/`$fdebug`/`$fflush`/`$ftell`/`$fseek`/`$rewind`/`$feof`** — and the **string/reading** functions — **`$swrite`/`$sformat`/`$sscanf`/`$fgets`/`$fscanf`/`$ferror`**. File output reuses the existing `$display` `snprintf` machinery (generalised with a `PrintDst` sink) backed by a small module-global descriptor table in the OSDI stdlib; `$swrite`/`$sformat` format into a string variable, and `$sscanf`/`$fscanf` parse whitespace-delimited fields by target-variable type — **no `ngspice` changes**. (Two codegen traps fixed along the way: a shadowed-`fun` bug in the print callback, and an LLVM IPO mis-specialisation of the descriptor table, cured with a `volatile` table.)

- File output verified end-to-end — a parameter/`I=V/R`-table export exercising `%g`/`%d`/`%h`/`%s`, newline-less `$fwrite`, `$ftell`, and a `$rewind`/`$fseek` overwrite — see `examples/fileio_examples/` (9/9)
- String/reading verified — `$sformat`/`$swrite`, `$sscanf`, file round-trips via `$fgets`/`$fscanf`, and `$ferror` — see `examples/stringio_examples/` (6/6)
- Details: [Enhancement-11.md](enhancements_doc/Enhancement-11.md)

---

## Enhancement 12: Connectivity-alias, probe, and plusarg functions

*July 2026* — Implements the **last** previously-unsupported system functions — **`$simprobe`**, **`$analog_node_alias`/`$analog_port_alias`**, and **`$test$plusargs`/`$value$plusargs`** — so `hir_def::is_unsupported()` is now empty (every Verilog-AMS system function compiles). None of these has an underlying mechanism in the OSDI/ngspice target (no command-line plusargs, no generic simulator probe, no runtime hierarchical node aliasing), so each lowers to its LRM "mechanism-unavailable" fallback as a compile-time constant (`false` / `0` / the supplied default). A model that uses them now compiles and runs predictably instead of being rejected — with **no runtime callback and no `ngspice` change**.

- Each function verified to return its documented fallback (including `$simprobe` returning a supplied default) — see `examples/alias_examples/` (6/6)
- Details: [Enhancement-12.md](enhancements_doc/Enhancement-12.md)

---

## Enhancement 13: `limexp()` — kept stateless (a documented decision)

*July 2026* — Investigated the `limexp()` limited exponential. The existing **stateless** implementation — `exp(x)` below `ln(1e30)`, continued along its tangent above to bound the derivative and prevent overflow — is exact and correct in every analysis, and is **kept, unchanged**. A stateful prev-iteration step-limiting version was implemented and then **reverted**: it produces wrong DC values, because keeping the converged value correct *while* limiting requires SPICE's limiting-RHS correction, and OpenVAF only applies that to circuit *unknowns* — not to `limexp`'s derived argument (e.g. `V/Vt`). This enhancement documents the decision (with the failing evidence) so it isn't re-attempted.

- Along the way, the already-supported **`ddx()`** symbolic-derivative operator was demonstrated across DC/AC/transient: a nonlinear resistor exports its `ddx`-computed conductance, which matches the closed-form derivative exactly and governs the small-signal AC response — see `examples/ddx_examples/`
- Details: [Enhancement-13.md](enhancements_doc/Enhancement-13.md)

---

## Enhancement 14: array literals / aggregates

*July 2026* — Completed Verilog-A **array** support beyond element-at-a-time access. Adds **whole-array aggregate assignment** (`c = '{v0, v1, v2};` and array-to-array copy `c = d;`), **array-valued parameters** (`parameter real [0:3] w = '{...};`) that expand into one scalar OSDI parameter per element — each with its own default and **individually overridable from SPICE** (`.model m dev(w[2]=0.9)`) — and **dynamic (non-constant) indexing** `c[i]` for array variables, lowered to a runtime select over the element variables.

- Fixed a pre-existing infinite-loop bug in `Type::base_type` (it looped on `self` instead of the cursor) that hung the compiler on any array type check — e.g. assigning an array literal to a scalar; such mismatches now report a clean diagnostic
- Verified end-to-end through ngspice — array-parameter defaults, full and partial per-element override, aggregate assignment, copy, and dynamic read/write all match their closed-form values — see `examples/array_examples/`
- Details: [Enhancement-14.md](enhancements_doc/Enhancement-14.md)

---

## Enhancement 15: multi-dimensional arrays

*July 2026* — Generalised the (1-D) arrays of Enhancement 14 to **any number of dimensions**: N-D declaration for variables and parameters (`real [0:1][0:2] m;`), **constant and dynamic indexing** `m[i][j]`, **nested aggregate literals** (`acc = '{'{a, b}, '{c, d}};`), and N-D array parameters whose elements (`w[0][0]`, `w[0][1]`, …) each carry a default and are **individually overridable from SPICE** (`.model m dev(w[1][1]=0.9)`). Kept the whole-array-expanded-to-scalars model, so no OSDI ABI change and no ngspice change were needed; a dynamic index lowers to a runtime flat-position select over the elements.

- The bit-select representation became multi-index (`m[i][j]` carries all its `[..]` clauses) and array declarations carry a per-dimension size list, while all existing 1-D net/array code stayed unchanged
- Verified end-to-end through ngspice — 2-D parameter defaults, per-element 2-D override, nested-literal aggregate assignment, and dynamic 2-D read/write — see `examples/mdarray_examples/`; every prior example (including 1-D arrays, vectored nets, and `generate`) still passes
- Details: [Enhancement-15.md](enhancements_doc/Enhancement-15.md)

---

## Enhancement 16: `$table_model` lookup tables

*July 2026* — Implemented the Verilog-AMS **`$table_model`** system function (1-D), which previously carried an explicit `// TODO TABLE_MODEL`. `$table_model(x, <data>[, "control"])` interpolates a value from a tabulated grid — the data coming from an inline `'{x0,y0, x1,y1, ...}` array or a two-column data file — with piecewise-**linear** interpolation and **constant** (clamp) or **linear** extrapolation. Unlike `noise_table` (which only feeds the noise PSD), `$table_model` is used in the **main device equations**, so it is lowered to plain **differentiable MIR arithmetic**: `mir_autodiff` then yields the per-segment slope as the Jacobian entry for free — no OSDI ABI change and no ngspice change needed.

- Verified end-to-end across **DC, AC and transient**: a transfer table interpolates bit-exactly; a file-based nonlinear resistor converges to the analytic nonlinear DC operating point (~5e-10 V); its AC small-signal conductance equals the analytic table slope (~1e-18 S); and its transient output tracks the table instantaneously — see `examples/table_model_examples/` (with DC/AC/transient PNG plots)
- Scope is 1-D linear interpolation; multi-dimensional tables and higher-degree (spline) interpolation are the natural follow-up (as 1-D arrays in Enhancement 14 were extended to N-D in Enhancement 15)
- Details: [Enhancement-16.md](enhancements_doc/Enhancement-16.md)

---

## Enhancement 17: multi-dimensional `$table_model`

*July 2026* — Generalised the (1-D) `$table_model` of Enhancement 16 to **2-D and 3-D** tables: `$table_model(x1, x2[, x3], "grid_file"[, "control"])` interpolates a value from an N-dimensional grid by **multilinear** (bilinear / trilinear) interpolation. The elegant part is that N-D interpolation is built as **recursive 1-D interpolation** — peel the outermost axis, interpolate each of its slices over the remaining axes, then interpolate those results — so one routine handles any N and, being ordinary differentiable MIR, `mir_autodiff` supplies **all** the partial derivatives (e.g. a table-based MOSFET's `gm` *and* `gds`) with no special support. No OSDI ABI change and no ngspice change.

- Verified end-to-end through ngspice with a **table-based MOSFET** `I(Vgs, Vds)`: the drain current matches a bilinear reference to machine precision (~1e-19 A), and both `gm = dId/dVgs` and `gds = dId/dVds` match the surface partials (~1e-16 S) — so the 2-D Jacobian is exact. Bilinear reproduces `x·y` and trilinear reproduces `x·y·z` exactly; the 1-D case is unchanged — see `examples/mdtable_examples/` (with an I-V surface plot)
- Multi-dimensional data comes from a self-describing grid file (`ndim`, axis sizes, axis coordinates, row-major values); supported dimensionality is 1-D/2-D/3-D, with higher-degree (spline) interpolation as future work
- Details: [Enhancement-17.md](enhancements_doc/Enhancement-17.md)

---

## Enhancement 18: array declaration syntax + arrays in analog functions

*July 2026* — Two related array-usability features. **(1) Standard declaration syntax:** the LRM *name-then-range* form `real x[0:n];` (and multi-dimensional `real m[0:1][0:2];`, per-variable) is now accepted alongside the existing *range-then-name* `real [0:n] x;` — real-world models written for other simulators use the former. **(2) Arrays in `analog function`s:** array **local variables** and whole **array arguments** are now supported inside analog functions (previously rejected as *"array-variable declarations are only supported at module body scope"*). A whole array is passed by name (`dot(coeffs, taps)`); the callee's element variables are bound from the caller's, and because the callee body is lowered inline as ordinary MIR, the Jacobian flows through the function automatically. No OSDI ABI change and no ngspice change.

- Verified end-to-end through ngspice — a polynomial stage `V(out) = 0.5·V(in) + 0.3·V(in)²` evaluated inside an array-argument function (Horner's rule, indexing the array argument with a loop variable): DC matches the closed form (~1e-16) and the AC gain matches `poly'(bias)` (~1e-16), i.e. the derivative flows through the array-argument function — see `examples/funcarray_examples/`
- Array arguments are input-only (element pass-by-value); array `output` writeback and array return values remain future work
- Details: [Enhancement-18.md](enhancements_doc/Enhancement-18.md)

---

## Enhancement 19: `do ... while` loop

*July 2026* — Implemented the Verilog-AMS **`do <statement> while (condition);`** loop, previously a parse error (`do` was lexed as an identifier). It is a **post-test** loop — the body runs once *before* the condition is first tested, so it always executes at least once — and completes OpenVAF's loop constructs (`for`, `while`, and `repeat` already worked). A new `do` keyword and `do-while` statement kind are threaded through the whole front-end (tokens → parser → AST → HIR → lowering); the lowering enters the body block unconditionally and tests the condition at the end of each iteration.

- Verified end-to-end through ngspice — a `do` loop reports its iteration count as a gain; across the loop count `n` (overridden per `.model`) the count equals `max(n, 1)`, and in particular **`n = 0` still runs the body once**, the defining behaviour that distinguishes `do-while` from `while` — see `examples/dowhile_examples/`
- Details: [Enhancement-19.md](enhancements_doc/Enhancement-19.md)

---

## Enhancement 20: array `output`/`inout` function arguments

*July 2026* — Completed Enhancement 18's array-argument support, which was **input-only**: a whole array could be passed *into* an `analog function` but the function could not write one back. Array **`output`** and **`inout`** arguments now write their results into the caller's array on return — previously such an argument compiled but silently did nothing (a correctness gap). Enhancement 18 already bound the callee's element variables from the caller at entry and recorded the caller's array elements for *any* array argument; the only missing piece was the **exit writeback**, so this is a focused one-function change in `hir_lower` that copies each callee element variable back to the caller's array element after the (inlined) body runs. `inout` gets both the entry bind and the exit writeback; `input` is unaffected. No OSDI ABI change and no ngspice change.

- Verified end-to-end through ngspice — `make_taps` fills a geometric tap array via an **output** array argument and `normalize` scales it in place via an **inout** array argument; the gain is the sum of the normalized taps, which is `1` for any `ratio` (swept, overridden per `.model`), so `V(out) = V(in)` — a value that holds only if *both* writebacks reach the caller's array — see `examples/arrayout_examples/`
- The array passed to an `output`/`inout` argument must be a writable array **variable**; array **return values** (a function whose return type is an array) remain future work
- Details: [Enhancement-20.md](enhancements_doc/Enhancement-20.md)

---

## Enhancement 21: Verilog-AMS `paramset` blocks

*July 2026* — Implemented Verilog-AMS **`paramset`** blocks, previously a hard parse error. A `paramset <name> <target_module>;` defines a named, instantiable model (`.model foo <name>`) that has the same terminals and analog behaviour as the target module but with selected parameters **bound** to expressions — the Verilog-AMS way of shipping a *model library* (one behavioural module, several named pre-configured variants), able to *compute* the bound values from the paramset's own card parameters. The elegant part is the lowering: a paramset becomes a synthetic **twin module** that *shares the target's declaration AST* (so its ports and body are the target's, resolved through the twin's own scope), adds the paramset's own parameters, and rewrites each bound parameter into a `localparam` whose value is the override expression. Because item identity is `(scope, index)`, the twin re-interns the shared items as fresh ids under its own scope — a fully independent module that reuses the target's behaviour — so type inference, autodiff, and OSDI emission all treat it as ordinary. No OSDI ABI change and no ngspice change.

- Verified end-to-end through ngspice — one behavioural module `conductor = g0·(1 + k·V)` and three paramsets (`res_1k`, `res_kohm`, `varistor`): constant bindings and card-parameter-driven binding expressions take effect, an unbound parameter stays settable while a bound one is driven by the paramset, a **bound** parameter is **not** settable from the card, the derivative flows through the paramset (AC `gm = g0·(1+2·k·V)` is exact — the autodiff Jacobian runs on the shared body), and the base module still works independently — see `examples/paramset_examples/`
- The target module must be declared in the same file; multiple same-named paramsets with instance-based *selection* (and `aliasparam`/statement selection) remain future work — each paramset maps to exactly one model
- Details: [Enhancement-21.md](enhancements_doc/Enhancement-21.md)

---

## Enhancement 22: natural cubic-spline `$table_model`

*July 2026* — Extended `$table_model` with **natural cubic-spline** interpolation (control code `"3"`), complementing the piecewise-linear (Enhancement 16, 1-D) and multilinear (Enhancement 17, 2-D/3-D) interpolation. A cubic spline is **C¹** — its derivative is continuous — so a table-based compact model's `gm`/`gds` are **smooth**, instead of the staircase derivative that piecewise-linear interpolation produces. The interpolation degree is chosen entirely by the control string, so this is a lowering-only change: no new builtin signature, no OSDI ABI change, and no ngspice change. The elegant part is that a natural spline's per-point second derivatives (the "moments") solve a tridiagonal system that is **linear in the grid values and fixed by the grid alone** — so the moment vector is a compile-time-precomputed linear operator, each moment becomes a constant-weighted sum of the (possibly runtime) grid values, and the whole spline lowers to ordinary differentiable MIR with no runtime solve. `mir_autodiff` then supplies the exact, continuous Jacobian for free, and the same recursive-1-D scheme as Enhancement 17 yields the exact tensor-product natural spline for N-D.

- Verified end-to-end through ngspice, each check contrasting cubic with linear on the same data: cubic tracks `sin(V)` ~46× better than linear at off-grid points; across a grid node the cubic `gm` matches `|cos(V)|` on both sides (continuous) while the linear `gm` **jumps** ~10× more (a direct test that the autodiff Jacobian through the cubic MIR is continuous); a natural spline reproduces straight-line data exactly; and a 2-D tensor-product cubic reproduces `sin(x)·cos(y)` accurately — see `examples/cubic_table_examples/`
- Natural boundary conditions only; a control code applies cubic to all axes (per-axis interpolation degree, and other end conditions, remain future work); the existing linear tables are unchanged
- Details: [Enhancement-22.md](enhancements_doc/Enhancement-22.md)

---

## Enhancement 23: array return values from analog functions

*July 2026* — Added **array return values** to `analog function`s (`analog function real[0:n] f;`, with `c = f(...)` copying the whole returned array into the destination), completing the array-in-functions arc: Enhancement 18 (array **arguments**, input) → Enhancement 20 (array **output/inout** arguments) → Enhancement 23 (array **return values**). Previously `analog function real[0:n] f;` was a parse/resolve error. The design reuses the earlier array machinery: the return array is modelled as a function-scoped array variable named after the function, so its element variables `f[i]` register in the function's `var_arrays` (exactly like an array argument's) and the body's `f[i] = …` resolves via the existing bit-select paths. At the call site `c = f(...)`, inference records the array-returning call and lowering **inlines the function body** (writing the return elements) then copies them into the destination — so, as for every user function, the body is ordinary MIR and the autodiff Jacobian flows through the return automatically. No OSDI ABI change and no ngspice change.

- Verified end-to-end through ngspice — a cubic polynomial device `I = c0 + c1·V + c2·V² + c3·V³` built two ways: `polyret` (a function returns the power array `{1,V,V²,V³}`, summed at the call site) and `polyret_arg` (the returned array is fed straight into an array-**argument** function, composing E-23 with E-18). For both, across a bias sweep, the DC current matches the closed form (~1e-9) and the AC conductance matches the exact derivative `gm = c1 + 2·c2·V + 3·c3·V²` (~1e-9) — the Jacobian flows through the array return — see `examples/arrayret_examples/`
- An array-returning call is only valid as the whole right-hand side of an array assignment (not a sub-expression); a length mismatch is a clean compile-time type error
- Details: [Enhancement-23.md](enhancements_doc/Enhancement-23.md)

---

## Enhancement 24: `$discontinuity(n)` simulator support

*July 2026* — Gave real effect to **`$discontinuity(n)`** (n ≥ 0), previously a no-op (only the internal `$discontinuity(-1)` used by device limiting did anything). `$discontinuity(n)` announces a discontinuity of degree *n* in the branch constitutive relations at the current point, so the transient simulator **limits the timestep** there instead of extrapolating a large step across the event — affecting *only* timestep control, never the computed solution. The natural vehicle, an OSDI eval **return flag** (like `$finish`/`$stop`), turned out not to be honoured by ngspice's timestep control, so this is implemented over the proven **`bound_step`** eval output that ngspice's `OSDItrunc` already reads: `$discontinuity(n)` writes a **negative sentinel** to the `bound_step` slot, and `OSDItrunc` interprets it (rather than as a literal step bound) as "a discontinuity occurred here" and clamps the next timestep to the last accepted step. **This is the first enhancement that also modifies the ngspice source** (`src/osdi/osditrunc.c`); no OSDI ABI change.

- Verified end-to-end through ngspice — a conductance switch (`I = g·V(a,b)`, `g` jumps at `V(a,b)=vth`) announces `$discontinuity(0)` while in the switched region: the same transient produces far more (finer) timepoints with the announcement on than off — i.e. the discontinuity actually limits the timestep — while the DC operating point is identical either way — see `examples/discontinuity_examples/` (with a timestep-refinement plot)
- The degree `n` is treated uniformly (any n ≥ 0 ⇒ "limit the step here"); `$discontinuity` and `$bound_step` share the `bound_step` slot (a negative value is the discontinuity sentinel, a positive value an explicit bound); requires the accompanying ngspice build
- Details: [Enhancement-24.md](enhancements_doc/Enhancement-24.md)

---

## Enhancement 25: `$simparam$str(name)` support

*July 2026* — Made **`$simparam$str(name)`** (the string counterpart of the numeric `$simparam`) actually work; it was previously unusable due to **three independent defects**, two in OpenVAF and one in ngspice. (1) The builtin was **mis-typed** as returning a real, so any string use — assigning to a `string` variable, comparing to a string literal, `%s` in `$strobe` — was a type error; fixed to return a string. (2) The runtime lookup in `stdlib.c` was **bugged**: it iterated the *numeric* parameter list and returned the *name* instead of the value (reading past the end of the string list); fixed to walk the string list and return its value. (3) ngspice's OSDI layer exposed **no** string parameters at all; `get_simparams` now provides `"analysis_name"` (`"dc"`/`"ac"`/`"tran"`/`"noise"`, matching the `analysis()` convention) and `"simulator"` (`"ngspice"`). This is the second enhancement to also modify the ngspice source (`src/osdi/osdiload.c`); no OSDI ABI change. The numeric `$simparam(name[, default])` was already supported and is unchanged.

- Verified end-to-end through ngspice — a model that sets its conductance from `$simparam$str("analysis_name")` (read into a `string` variable and compared): `g_dc` in dc/op, `g_ac` in ac, `g_tran` in tran; running each analysis and checking the terminal current confirms the correct string is returned in each case (which never worked before) — see `examples/simparamstr_examples/`
- Provides `"analysis_name"` and `"simulator"` (other string params such as `"cwd"` remain future work); an unknown name raises a fatal "unknown $simparam_str"; requires the accompanying ngspice build
- Details: [Enhancement-25.md](enhancements_doc/Enhancement-25.md)

---

## Enhancement 26: `ac_stim(...)` baseline (crash fix + correct large-signal semantics)

*July 2026* — Baseline support for **`ac_stim([name][, mag][, phase])`**, the Verilog-AMS small-signal AC stimulus source. `ac_stim` type-checked but any **contributing** use (`I(a,b) <+ ... + ac_stim(...)`) fell through to an `unreachable!()` in the lowering and **crashed the compiler**. This adds the missing lowering arm: per the LRM, `ac_stim` evaluates to **0 in the large-signal (DC/transient) domain** and injects `mag∠phase` only during small-signal AC analysis, so returning `0` is the correct large-signal value and stops the crash — a model using `ac_stim` (in any of its four signature forms) now compiles and simulates. One-line change; no OSDI ABI change and no ngspice change.

- Verified end-to-end through ngspice — the model compiles (it previously crashed `openvaf-r`), and DC/transient currents equal `g·V(a,b)` and are identical with the `ac_stim` terms included vs excluded, i.e. `ac_stim` correctly contributes 0 in the large-signal domain — see `examples/acstim_examples/`
- **Scope:** this is the baseline (crash fix + correct large-signal value). The actual small-signal **AC injection** (`ac_stim` contributing `mag∠phase` to the AC right-hand side) is a separate, ABI-touching subsystem — parallel to the noise path (new OSDI AC-RHS mechanism + ngspice complex-RHS stamping) — deferred to a dedicated follow-up
- Details: [Enhancement-26.md](enhancements_doc/Enhancement-26.md)

---

## Enhancement 27: `idtmod(...)` modulo-integrator fix

*July 2026* — Fixed **`idtmod(expr, ic, modulus[, offset])`**, the Verilog-AMS modulo time-integrator (the standard VCO/PLL phase integrator). It compiled and integrated correctly for the *first period*, but the modulo **wrap** was broken by two bugs. **(1)** At the wrap the old lowering forced the state to `min` *and zeroed the reactive (state) residual* — but the transient integrator derives the branch current from that residual's history, so at the wrap it saw `≈ (0 − q_{n-1})/dt` with `q_{n-1} ≈ modulus`, an enormous term that drove the state to `~q/dt`; the result **got stuck** (a VCO froze at ~0.297) or **diverged** (a sawtooth shot to ~−799). **(2)** The offset form read `args[2]` (the *modulus*) as the offset instead of `args[3]`. The fix integrates the DAE **state unbounded** (plain integration, like `idt`, with no discontinuity for the integrator to trip over) and wraps only the **returned value** — `offset + floor_mod(∫expr − offset, modulus)` — and reads the offset from the right argument. `hir_lower`-only; no OSDI ABI change and no ngspice change.

- Verified end-to-end through ngspice — a VCO (a modulo-1 phase driving `sin(2π·phase)`) tracks `sin(2π·freq·t)` to ~1e-4 across three periods (it used to freeze after one), and a sawtooth `idtmod(1, 0, 2, off)` wraps correctly into `[off, off+2)` for both `off=0` and `off=5` (~1e-16), exercising the fixed offset argument — see `examples/idtmod_examples/`
- Plain `idt` (no modulus) is unchanged and still exact; the DAE state integrates unbounded, so over very long runs (many millions of wraps) the wrapped output loses a little floating-point resolution — a bounded-state modulo integrator would need simulator-side breakpoint support OSDI does not expose, but the unbounded-state form is correct and no longer diverges
- Details: [Enhancement-27.md](enhancements_doc/Enhancement-27.md)

---

## Enhancement 28: `idt(...)` initial-condition fix

*July 2026* — Fixed the **initial condition of `idt(expr, ic)`** in transient analysis. `idt` integrated correctly and its IC was honoured at the DC operating point (`.op` returned `ic`), but the IC was **silently lost in transient**: the integrator restarted from 0, so `idt(rate, ic)` gave `rate·t` instead of `ic + rate·t`, and `idt(0, ic)` drifted from `ic` to 0 (the LRM says the IC *"is used as the starting value for transient analysis"*). Root cause: `idt` lowers to an implicit DAE `resist + d/dt(react) = 0` whose reactive residual is the integrator's stored charge; during the IC/DC phase the old lowering used `[val − ic, 0]` — the resistive term pinned `val = ic` but the stored charge was **0**, so when transient integration turned on (`react = val`) it continued from 0 charge. The fix stores the charge as `ic` (`[val − ic, ic]`), so the DC point has `val = ic` *and* charge `= ic` and the transient continues from `ic` (the state is continuous because `val = ic` at the boundary). One-value change in `hir_lower`; no OSDI ABI change and no ngspice change.

- Verified end-to-end through ngspice — an ideal integrator `v = ic + rate·t`: the DC operating point equals `ic`, the transient ramp `idt(1, 3)` gives `3 + t` (~1e-4, used to give `t`), and with `rate = 0` the integrator holds at `ic` (`idt(0, 7)` stays at 7, used to drift to 0) — see `examples/idtic_examples/`
- `ddt` (all three forms) was confirmed already correct; the mid-transient `idt(x, ic, assert)` **reset** form (a runtime reset to `ic`) is a separate state-jump discontinuity (like the raw `idtmod` wrap) and remains unaddressed; `idt(x)` with no IC still has an unconstrained DC point
- Details: [Enhancement-28.md](enhancements_doc/Enhancement-28.md)

---

## Enhancement 29: port-branch flow access `I(<port>)`

*July 2026* — Made the **port-branch flow probe `I(<port>)`** functional. `I(<p>)` is the current flowing **into** the module through terminal `p` — used to build current-controlled sources (CCCS/CCVS) and to monitor terminal currents. The front-end already parsed, type-checked and lowered it (`ParamKind::Current(CurrentKind::Port)`), so models *compiled*, but the value was **always 0 at run time**: it was an unfinished stub (`CurrentKind::Port => { // TODO? }` in `sim_back`, and a hard-coded `const_real(0.0)` in the OSDI eval), so `I(out) <+ 10·I(<in>)` produced `i(out) = 0`. The fix gives port flow a **real DAE unknown with a defining equation**, reusing the machinery that already backs named/unnamed branch-current probes: a new `build_port_flow_equations()` (called first in `finish()`) synthesises, for each probed port, `residual[Current(Port(p))] = residual[KCL(p)] − I(<p>)` — i.e. by Kirchhoff's law the current into port `p` equals the net device current out of node `p`. It **mirrors node p's resistive *and* reactive residual**, so the solved value includes displacement (capacitive) current for free. The `CurrentKind::Port` special-cases are then dropped from `build_input_unknown_pairs` (it registers as an ordinary model input) and from the OSDI eval (it reads its solved value like any current). Pure `sim_back` + `osdi` change; the OSDI descriptor already named the unknown `flow(<node>)`.

- Verified end-to-end through ngspice — a CCCS `I(out,com) = k·I(<in>)` with an `rin‖cin` input load: resistive DC gives `i(vout) = −k·vin/rin` (−20 mA for k=10, vin=2, rin=1k; was **0** before the fix), the gain scales (`i(vout)/i(vin) = k` for k ∈ {1, 5, 25, 100}), and in AC the port flow carries both the in-phase (`1/rin`) and quadrature (`ω·cin`) parts with `|i(vout)| = k·|i(<in>)|` — proving displacement current flows through the probe. Resistive, reactive and mixed loads all work — see `examples/portflow_examples/`
- Gotcha (ngspice, not OpenVAF): do **not** name a module `cccs`, `vccs` or `vcvs` — those collide with ngspice's built-in controlled-source device types and crash `.model` setup; just use a different module name (the demo uses `portflow_cccs`)
- Details: [Enhancement-29.md](enhancements_doc/Enhancement-29.md)

---

## Enhancement 30: variadic `analysis(...)`

*July 2026* — Added the **multi-argument list form** of the Verilog-AMS `analysis()` system function (LRM 4.7.1). `analysis()` returns true if the current analysis matches **any** name in a list — e.g. `analysis("ic", "dc")` or `analysis("ac", "noise")` (recognised names: `ac`, `dc`, `tran`, `ic`, `static`, `noise`, `nodeset`). The single-argument form already worked end-to-end (the stdlib `analysis()` reads `sim_info->flags`, which ngspice sets correctly for op/dc/ac/tran/noise), but the builtin was declared with exactly one signature, so the list form was rejected at compile time (`invalid argument count: expected 1 arguments but found 2`) — you had to chain `analysis("ac") || analysis("tran")` by hand. The fix makes `analysis` a **varargs** builtin in `hir_ty` (one mandatory string, no upper bound, like `$display`/`$limit`) and, in `hir_lower`, emits the analysis callback for **each** argument and **bitwise-OR**s the results. OR (not a sum) matters: at an operating point both `"static"` and `"dc"` return 1, so a sum would exceed 1 — the OR clamps the result to a proper 0/1. Pure front-end change; no OSDI ABI change and no ngspice change.

- Verified end-to-end through ngspice — a conductance that is `g_static` at the DC operating point and `g_dynamic` for the dynamic analyses, selected by one list-form call `if (analysis("ac","tran","noise")) g = g_dynamic;`: the list form now compiles, DC gives `g_static`, AC and tran give `g_dynamic`, and `analysis("static","dc","ic")` at `.op` returns exactly 1 (OR, not a sum). Single-argument `analysis()` is unchanged and regression-checked — see `examples/analysis_examples/`
- Details: [Enhancement-30.md](enhancements_doc/Enhancement-30.md)

---

## Enhancement 31: complex poles/zeros in laplace/zi root forms

*July 2026* — Added **complex conjugate poles and zeros** to the root-based Laplace / z-domain filter forms — `laplace_np`, `laplace_zd`, `laplace_zp` and the `zi_*` counterparts. Per the Verilog-AMS LRM the pole/zero vectors of these forms hold **(real, imaginary) pairs** (element `2k` is the real part and `2k+1` the imaginary part of root `k`), so a complex conjugate pair is `'{re, +im, re, -im}` and a real root is `'{re, 0}`. OpenVAF expanded the vector as a list of **individual real roots**, so complex poles/zeros — i.e. every resonant / underdamped second-order section — were impossible: a Q=5 resonant low-pass built with `laplace_np` and the correct complex pole pair produced **−242 dB of garbage** (the imaginary parts were read as extra real roots, one in the right-half-plane). The fix rewrites the single shared helper `laplace_roots_to_poly` to consume the vector as `(re, im)` pairs and form `Π_k (s − (re_k + j·im_k))` with full complex arithmetic (each coefficient carried as a `(re, im)` pair of MIR values), returning the real coefficients — the imaginary parts cancel for physical, conjugate-paired inputs. A lone trailing element is still treated as a real root, so single-real-root models keep working. One helper is shared by all six root forms (`laplace_*` and `zi_*`), so this covers every one of them; pure `hir_lower` change, no OSDI/ngspice change.

- Verified end-to-end through ngspice — a resonant low-pass via `laplace_np` (complex conjugate poles) matches the `laplace_nd` polynomial baseline to `0.00 dB` and shows a real resonant peak of **+18.06 dB at exactly 1 MHz** (= 20·log₁₀(Q=8), impossible with real-only roots); a notch via `laplace_zd` (imaginary-axis complex zeros ±j·ω₀) matches `laplace_nd` to `0.00 dB` with a −290 dB null; `laplace_zp` and `zi_np` (complex) were spot-checked too — see `examples/complexpole_examples/`
- Behaviour change: an even-length vector now means half as many roots — `'{-1e6, -3e6}` was two real poles, now one complex pole `−1e6−3e6j`. `examples/laplace_examples/laplace_variants.va` was updated to the paired form (single-real args like `'{-2e6}` are unaffected)
- Details: [Enhancement-31.md](enhancements_doc/Enhancement-31.md)

---

## Prebuilt Binaries

Binaries are built by CI and committed to `bin/`:

| Platform | Directory | Binaries |
|---|---|---|
| Linux x86-64 | `bin/linux/intel/` | `ngspice`, `openvaf-r` |
| Linux ARM64 | `bin/linux/arm/` | `ngspice`, `openvaf-r` |
| macOS Apple Silicon (M1/M2/M3) | `bin/macos/apple-silicon/` | `ngspice`, `openvaf-r` |
| macOS Intel | `bin/macos/intel/` | `ngspice`, `openvaf-r` |
| Windows x86-64 | `bin/windows/intel/` | `ngspice.exe`, `openvaf-r.exe` |

### Running on Linux

The binaries are dynamically linked against standard system libraries. Install them with your package manager if missing:

**Ubuntu / Debian:**
```bash
sudo apt-get install libreadline8 libx11-6 libxaw7 libxft2 libxext6
```

**Fedora / RHEL:**
```bash
sudo dnf install readline libX11 libXaw libXft libXext
```

After that, mark the binaries executable and run:
```bash
chmod +x bin/linux/intel/ngspice bin/linux/intel/openvaf-r
./bin/linux/intel/ngspice
```

### Running on macOS

The binaries are dynamically linked against **XQuartz** (X11) and **Homebrew** readline/ncurses. Both must be installed before running.

**1. Install XQuartz** (provides the X11 window system for ngspice plots):

Download and install from [https://www.xquartz.org](https://www.xquartz.org), then **log out and log back in** so the X11 libraries at `/opt/X11` are on the dynamic linker path.

**2. Install Homebrew dependencies:**
```bash
brew install readline ncurses
```

**3. Mark binaries executable and run:**
```bash
# Apple Silicon (M1/M2/M3)
chmod +x bin/macos/apple-silicon/ngspice bin/macos/apple-silicon/openvaf-r
./bin/macos/apple-silicon/ngspice

# Intel Mac
chmod +x bin/macos/intel/ngspice bin/macos/intel/openvaf-r
./bin/macos/intel/ngspice
```

> **Note:** macOS may show a security warning ("cannot be opened because the developer cannot be verified"). Go to **System Settings → Privacy & Security** and click **Allow Anyway**, or run:
> ```bash
> xattr -d com.apple.quarantine bin/macos/apple-silicon/ngspice
> xattr -d com.apple.quarantine bin/macos/apple-silicon/openvaf-r
> ```

### Running on Windows

The Windows binaries come **bundled with all required MinGW runtime DLLs** (`libreadline8.dll`, `libtermcap-0.dll`, `libstdc++-6.dll`, `libwinpthread-1.dll`, etc.) in the same directory. No MSYS2, MinGW, or other runtime installation is required — just keep all files in `bin\windows\intel\` together.

Simply run from that directory:
```
bin\windows\intel\ngspice.exe
bin\windows\intel\openvaf-r.exe
```

> **Note:** Windows may show a SmartScreen warning on first run ("Windows protected your PC"). Click **More info → Run anyway**.

> **Note:** `openvaf-r.exe` is a command-line tool. Run it from **Command Prompt** or **PowerShell**, not by double-clicking.

---

## CI Build Details

Builds run on push to `main` (source changes only; binary commits are skipped) or manually via **Actions → Build binaries → Run workflow**.

| Runner | Target | Notes |
|---|---|---|
| `ubuntu-latest` | `bin/linux/intel/` | LLVM 18 from apt |
| `ubuntu-24.04-arm` | `bin/linux/arm/` | LLVM 18 from apt |
| `macos-14` | `bin/macos/apple-silicon/` | LLVM 18 via Homebrew, XQuartz |
| `macos-26-intel` | `bin/macos/intel/` | LLVM 18 via Homebrew, XQuartz; macOS 26 "Tahoe" image, currently in beta. GitHub has signaled Intel macOS runners will be retired entirely in 2027. |
| `windows-latest` | `bin/windows/intel/` | LLVM 18 official tarball, ngspice via MSYS2/MinGW (static) |

See [`.github/workflows/build-binaries.yml`](.github/workflows/build-binaries.yml) for the full workflow.
