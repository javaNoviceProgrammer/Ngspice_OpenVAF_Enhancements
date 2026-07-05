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

## Enhancement 32: integer persistent/event-state variables

*July 2026* — Fixed a **compiler crash on integer persistent state**. A variable holds persistent state when its value must survive from one evaluation to the next — read-before-write (`if (V(a,c) > 1.0) m = m + 1;`) or updated inside an event block (`@(cross)`, `@(initial_step)`, ...). Enhancement-7/8 implemented this via per-variable persistent slots in the OSDI instance data, but the slot type was **hardcoded `f64`**: an **integer** persistent variable was stored and read back as a double, feeding integer MIR ops with f64 operands — `LLVM ERROR: Cannot select: f64 = add` (or a segfault). Real-typed persistent variables were unaffected, which is why this survived so long; it was found in a deep-dive TODO sweep, sitting right under the two `todo!("hidden state/event state")` stubs in `osdi/src/inst_data.rs`. The fix types the hidden-state slot from the variable itself (`lltype(var.ty)`, exactly like the opvar path — which the hardcoded `f64` could previously even *clobber*, since the slot map overwrites on duplicate keys), and replaces the two `todo!()` stubs with real state-slot resolution. A companion **ngspice** fix (`src/frontend/outitf.c`) lets integer opvars be **recorded per-timepoint**: `getSpecial()` masked `IF_INTEGER` out of the vector type (every `save @n1[n]` timestep printed `OUTpData: unsupported data type`), so the mask now keeps `IF_INTEGER` and both per-point writers record integer values as reals, like every other plot vector.

- Verified end-to-end through ngspice — an **integer `@(cross)` edge counter** exposed as an opvar: compiles (used to abort the compiler), counts exactly 5 upward 1 V crossings of a 2 V/1 kHz sine over 5 cycles, and its recorded waveform is a clean `0..5` staircase stepping at the analytic crossing times `asin(vth/A)/2πf + k/f` (max error < 10 µs = one timestep); an integer `@(initial_step)` flag reads 1; mixed integer+real initialization inside one `@(initial_step)` block feeds the device equations exactly — see `examples/intstate_examples/`
- Regression-checked: the real-typed running-peak opvar (Enhancement-7 behaviour) and the E-7/E-8 example decks (`variable_persistence`/`cross`/`timer`) are unchanged
- Details: [Enhancement-32.md](enhancements_doc/Enhancement-32.md)

---

## Enhancement 33: array `case` statements + array-literal function arguments

*July 2026* — Retired the compiler's **last `todo!()` hard-panic stubs** (`lower_case`'s array arm and `lower_array` in `hir_lower`) and fixed the four array-expression defects found underneath them by probing what type inference accepts but lowering couldn't handle: a **`case` over an array crashed the compiler** (`not yet implemented` panic — inference happily accepted an array discriminant and demanded array-typed items); an **integer**-array discriminant additionally died with `invalid int operation feq` (whole-array variable references were typed `real` regardless of their true element type); an **array literal passed as a whole-array function input argument compiled but silently bound nothing** — `sum2('{1.0, 2.0})` returned 0 instead of 3, a silent wrong answer; and an array literal passed to an array **output** argument was silently accepted with the writeback skipped, while scalar outputs were always properly rejected. The fix makes array `case` compare **element-wise** (an arm matches iff *all* elements are equal — per-element `feq`/`ieq`/`beq`/`seq` AND-combined into the branch condition; the scalar path is unchanged as the one-element case), for array literals *and* whole-array variables (`case (x)` on an array variable used to be rejected with "requires a bit-select"), real and integer. The laplace-specific array helpers were the general mechanism all along, so they're renamed and shared (`lower_array_elems` / `infere_array_arg`); function inputs accept array literals through the same helper; whole-array variables carry their true element type; array output arguments require a caller variable. Pure front-end change (`hir_ty` + `hir_lower`); no OSDI/ngspice change.

- Verified end-to-end through ngspice — a 2-bit **integer** state-vector `case` (`case (st) '{0,0}: … '{1,0}: … '{1,1}: …`) selects the correct conductance in all three regions of a DC sweep, scaled by a helper summing an array-literal argument (`sum2('{0.25, 0.75}) == 1.0`, was silently 0); a real-array `case` matches exactly; an array literal to an array output argument is rejected with a proper type error — see `examples/arraycase_examples/`
- Regression-checked: every array-consuming feature re-verified (`funcarray` E-18, `arrayout` E-20, `arrayret` E-23, `array`/`mdarray` E-14/15, `cubic_table`/`table_model` E-16/22, `complexpole` E-31 — all ALL PASS), plus `zi_lpf` and scalar `case` behaviour unchanged. With this, the OpenVAF tree contains **no `todo!()`/`unimplemented!()` stubs** in non-test code
- Details: [Enhancement-33.md](enhancements_doc/Enhancement-33.md)

---

## Enhancement 34: `{...}` concatenation & `{n{...}}` replication operators

*July 2026* — Implemented the Verilog-AMS **concatenation** and **replication** operators properly. OpenVAF had conflated the two brace constructs: `{...}` was parsed as just another spelling of the `'{...}` array-**aggregate** literal, so whole arrays could not appear inside braces (`{p, q}` → "requires a bit-select"), the replication form `{n{...}}` did not parse at all, and string operands produced a useless *string array* instead of the LRM's concatenated string. Now `'{...}` remains the aggregate literal (Enhancements 4/14/15, untouched — including nested `'{'{..},..}` for N-D arrays) and `{...}` is the real **concatenation operator**: numeric concats flatten their operands in order — scalars, whole-array variables, aggregate literals, nested concatenations — into one flat array value (`w = {half1, {3{k2}}, 3.0*k2};`); `{n{...}}` repeats the flattened list `n` times (`n` a positive compile-time integer literal, cleanly diagnosed otherwise); and **string operands concatenate into a runtime string** (`{"volt","age"} == "voltage"`, `{2{"ab"}} == "abab"`), lowered through the proven `$swrite`/`$sformat` machinery with the operands passed as `%s` *values* (never format-interpreted). Concats work everywhere an array value is consumed — array assignment, whole-array function arguments, `laplace_*`/`zi_*` coefficient vectors, `case` discriminants/items — because the shared element-flattening helper from Enhancement-33 (`lower_array_elems`) grew one concat arm; the array-assignment path expands into the existing mixed assign/copy element machinery unchanged. Integer *scalars* are cast into real concats like aggregate elements; an integer *array* mixed into a real concat is a type error. Pure front-end change threaded through the whole pipeline (new `CONCAT_EXPR`/`REPLICATION_EXPR` syntax nodes → `Expr::Concat` → typing → lowering); no OSDI/ngspice change.

- Verified end-to-end through ngspice — a 6-tap coefficient vector assembled by concatenation + replication (`w = {half1, {3{k2}}, 3.0*k2}`) gives a DC conductance of exactly `2·(3·k1 + 6·k2)` for two parameter sets (proving flattening, replication, integer casts and a runtime string-concat gate simultaneously); concat as a whole-array function argument, as `laplace_nd` coefficient vectors and as a `case` discriminant; replication of a mixed scalar/array list; `{0{...}}`/non-literal counts are clean diagnostics — see `examples/concat_examples/`
- Behaviour change: nested bare-brace literals (`{{1,2},{3,4}}`) now *flatten* (concatenation semantics); multi-dimensional aggregates use the LRM `'{'{..},'{..}}` form, as every shipped example already did. Audited **both trees**: no other example uses bare braces; all 73+70 example models recompile and **31/31 + 30/30 verify suites pass** with the new compiler
- Details: [Enhancement-34.md](enhancements_doc/Enhancement-34.md)

---

## Enhancement 35: lexer hang on `//` comment at end-of-file

*July 2026* — Fixed a **compiler infinite loop**: a `//` line comment as the last line of a file with **no trailing newline** hung `openvaf-r` forever at 100 % CPU — no diagnostic, stalling any build/CI pipeline that invokes the compiler (files without trailing newlines are extremely common). Both comment forms were otherwise fully supported and torture-tested (line/block/multi-line/mid-expression/trailing comments, code-like text inside comments). Root cause: the lexer's `line_comment` scan loop broke only on `'\n'`, but at end of input the cursor's `first()` returns the `EOF_CHAR` sentinel **forever** while `bump()` no-ops. The fix is a single added arm — `_ if self.is_eof() => break`. An audit of every other scan loop in the lexer (whitespace, identifiers, digits, strings, block comments, `eat_while`) confirmed `line_comment` was the *only* EOF-unsafe loop — which is why an unterminated `/*` was always a clean `unexpected EOF` error rather than a hang. The bug was pre-existing (reproduced with the CI-built binary); found while answering "are one-line and multi-line comments supported?".

- Verified end-to-end through ngspice — the exact-bytes hang reproducer (a file ending in `// eof comment` with no newline) compiles instantly; the comment-torture model simulates with the exact expected current (a commented-out `I(a,c) <+ 999.0;` is ignored); an unterminated `/*` stays a clean error; the backslash-at-EOF corner also terminates. Every compile in the verify suite runs under a 20 s watchdog, so a regression fails fast instead of hanging CI — see `examples/comment_examples/`
- Regression-checked: lexer unit tests 8/8, all 73 example models recompile, spot verify suites unchanged
- Details: [Enhancement-35.md](enhancements_doc/Enhancement-35.md)

---

## Enhancement 36: probe-only branches (ideal ammeter) & flow-only signal-flow systems

*July 2026* — Implemented the LRM's **0V-source (ideal ammeter) semantics for probe-only branches**, which simultaneously completes support for **flow-only signal-flow disciplines**. A branch that is *probed* but never *contributed* to — `x = I(p,n);`, or a declared `branch (p,n) sense;` used only inside `I(sense)` — read **0 and conducted nothing**: the "ammeter" was an open circuit, silently breaking its series path. Per the LRM such a branch must behave as a **short** (a potential source of 0 V) whose current is the probed value — the ideal-ammeter idiom, the basis of CCCS-on-a-sense-branch current mirrors, and the mechanism flow-only (`current` discipline) signal-flow nets ride on (an input port only *probes* its net's flow, so entire current-signal chains produced 0). Root cause: the topology only materialises branches from *contributions* (it is keyed off the `IsVoltageSrc` outputs), so probe-only branches never reached the DAE — the same failure family as Enhancement-29's port-flow stub. The fix is a new `build_probe_only_branches()` pass in the DAE builder (E-29's port-flow pass is its direct template) that synthesises, for every probed-but-unmaterialised branch current, exactly the system a zero-valued voltage source gets: `residual[I(br)] = −V(hi,lo)` (nature Potential, i.e. `V(hi,lo) = 0`) with `I(br)` injected into the Kirchhoff rows of both nodes. It runs before the derivative machinery, so the Jacobian comes out of the ordinary autodiff path. Pure `sim_back` change; no OSDI/ngspice change. (Inherent caveat: paralleling several probe-only branches across the *same* node pair is degenerate — parallel ideal 0 V sources — exactly as paralleling ideal voltage sources is.)

- Verified end-to-end through ngspice across all four system styles: the **ammeter shorts and reads** (a series 2 V/1 kΩ loop conducts its full 2 mA — it used to be open — with a transimpedance readout of exactly 2 V); it reads **displacement current** in AC (series 1 nF at ω=10⁶ → exactly `j·1 V`); a **CCCS current mirror** on a probe-only sense branch (3 mA → 6 mA); the potential-only (`voltage` discipline) signal-flow gain chain (`1.5 × 3 × 2 = 9 V`, already worked, now regression-locked); and the flow-only (`current` discipline) chain `1 mA → ×5 → 1 kΩ = 5 V` exactly (used to be 0), with the probed signal net at exactly 0 V — textbook signal-flow semantics — see `examples/signalflow_examples/`
- Regression-checked: all 32 example verify suites ALL PASS; `sim_back` snapshot tests unchanged at their pre-existing baseline
- Details: [Enhancement-36.md](enhancements_doc/Enhancement-36.md)

---

## Enhancement 37: operator-correctness audit + fixes

*July 2026* — A systematic **operator-correctness audit** covering the arithmetic, relational, logical, bitwise/shift, ternary and concatenation operator families — 60+ individual checks in five self-checking modules, each failing check contributing a distinct power of two to a score emitted on a signal-flow output, so `v(out) == 0` means every check passes and any nonzero value is a **bitmask pinpointing exactly which check failed**. The audit found (and this enhancement fixes) three real defects: **`~x` (bitwise NOT) was lowered as arithmetic negation** — `~12` evaluated to −12 instead of −13, silent wrong answers in any bit-manipulating model (fixed to the `inot` opcode, whose constant-fold was already correct); **constant folding of `>>` sign-extended** — the MIR and the LLVM runtime path correctly distinguish logical `Ishr`/`LShr` from arithmetic `Iashr`/`AShr`, but the constant folder computed both with Rust's signed `>>`, so `-16 >> 2` folded to −4 instead of the zero-filled `1073741820` and a *constant* `>>` disagreed with the identical *runtime* expression (fixed by folding through `u32`); and **the ternary operator rejected string operands** — `cond ? "a" : "b"` was a type error (fixed by appending a `(String, String) → String` signature to the SELECT list; the existing `phi` lowering handled strings unchanged). Everything else checked out exactly correct: integer truncation-toward-zero and `%` sign rules, real fmod and `**` with negative exponents/bases, all relationals with 0/1 results, `&& || !`, `& | ^ ~^ ^~`, shift edge cases, precedence, nested ternaries, concat/replication. Pure `hir_lower`/`mir_opt`/`hir_ty` change; no OSDI/ngspice change.

- Verified end-to-end through ngspice — the audit compiles (string ternaries used to error), all five operator-family scores read exactly 0, and the three formerly-broken cases are asserted directly (`~12 == -13`, `-16 >> 2 == 1073741820`, `(1>0) ? "yes" : "no" == "yes"`) — see `examples/operator_examples/`
- Regression-checked: all 33 example verify suites ALL PASS and all 75 example models recompile (the fixes touch shared lowering and constant-evaluation paths, so the full sweep matters)
- Details: [Enhancement-37.md](enhancements_doc/Enhancement-37.md)

---

## Enhancement 38: operator-precedence audit + fixes

*July 2026* — A systematic **operator-precedence audit** against the Verilog-AMS precedence table (LRM Table 4-2): the parser's Pratt binding-power table reviewed entry-by-entry, associativity verified structurally, and all of it locked down empirically with **28 bitmask checks covering every adjacent level pair**. One observable defect found and fixed: **`%` bound tighter than `*` and `/`** — the LRM puts all three on one left-associative level, so `6*7%4` parsed as `6*(7%4)` and evaluated to **18** instead of the LRM's `(6*7)%4 = 2` (and `42/5%3` gave 21 instead of 2) — silent wrong answers in any model mixing `*`/`/` with `%`. Subtle detail: `a%b*c` was accidentally correct (only `*`-then-`%` orderings misgrouped), which is why the Enhancement-37 operator audit missed it. Also fixed: `~^`/`^~` were split from `^` (LRM: one level) — provably unobservable for xor/xnor chains (each xnor contributes exactly one global inversion regardless of grouping), corrected for LRM exactness. Confirmed already correct: **left associativity** for every binary operator (including `2**3**2 == (2**3)**2 == 64` per LRM 4.1.3, which mandates left-to-right for everything except the conditional), **ternary right-associativity** (`a?b:c?d:e == a?b:(c?d:e)`), **unary binding above `**`** (`-2**2 == (-2)**2 == 4` — the classic Verilog difference from C/Python), and the full level ladder `unary > ** > */% > +- > shifts > relational > ==/!= > & > ^/~^ > | > && > || > ?:`. One-file parser change; no other pipeline stage touched.

- Verified end-to-end through ngspice — all 28 precedence/associativity checks read exactly 0 (any failure names itself in the bitmask), and the marquee fix case is asserted directly (`6*7%4 == 2`, was 18) — see `examples/precedence_examples/`
- Behaviour-change audit: no example in either tree contains an affected `*`/`/`-then-`%` grouping (grep-verified), and all 34 example verify suites ALL PASS — with the Enhancement-37 operator audit doubling as a semantics regression lock
- Details: [Enhancement-38.md](enhancements_doc/Enhancement-38.md)

---

## Enhancement 39: derived natures & deriving natures from disciplines

*July 2026* — Made **derived natures** — `nature X : Parent;` and `nature X : electrical.flow / electrical.potential;` (LRM 3.4.1.3) — actually work. A derived nature inherits every attribute (units, access, abstol, `ddt_nature`/`idt_nature`) it does not override, and the **complete inheritance machinery has existed in `hir_ty::NatureTy` all along** (parent chains, base-nature resolution, units/ddt/idt inheritance, attribute lookup through parents, access-function compatibility by units) — but it was **entirely unreachable**, blocked by three small boundary bugs: (1) the parser emitted a `NAME_REF` node for the `: parent` clause while the AST accessor (`NatureDecl::parent()`) looks for a `Path` child, so **the parent link was silently always `None`** — the canonical `nature TightCurrent : Current; abstol = 1e-15;` tolerance-tightening pattern rejected the inherited access function ("illegal access of branch"); (2) `nature X : electrical.flow;` **did not parse at all** ("unexpected token '.'"), with a second gate behind it — the syntax validation whitelisted only `ddt_nature`/`idt_nature` as qualified nature-path segments; (3) a discipline-qualified `ddt_nature`/`idt_nature` attribute value **hard-panicked the OSDI nature-descriptor builder** ("Nature's ddt must be a nature reference"). The fixes: parse the parent as a **path** (one grammar line lights up the whole dormant subsystem), whitelist `potential`/`flow` in the nature-path validation, and resolve discipline-qualified `ddt_nature`/`idt_nature` references through the discipline to the underlying nature's descriptor index instead of panicking. This continues a recurring OpenVAF pattern the feature probes keep exposing: *scaffolded-but-unwired at a node-kind boundary* (port flows E-29, array `case` E-33, probe-only branches E-36, nature parents now).

- Verified end-to-end through ngspice — a 5-module matrix with **exact runtime conductances** proving inherited access functions genuinely resolve: inherited `I` via `: Current` (1 mS), natures derived from `electrical.flow`/`electrical.potential` (2 mS), a derived nature with its **own** access name `I2` (5 mS), a **two-level** derivation chain `FineCurrent : MidCurrent : Current` (3 mS), and a `ddt_nature = electrical.potential` module whose OSDI descriptor builds and loads (used to panic) — see `examples/derivednature_examples/`
- Regression-checked: all 35 example verify suites ALL PASS and all 77 example models recompile (the parser change makes every file reparse)
- Details: [Enhancement-39.md](enhancements_doc/Enhancement-39.md)

---

## Enhancement 40: N-dimensional `$table_model`

*July 2026* — Lifted `$table_model`'s **3-dimension cap**: lookup tables of **any dimension** now work. The probe "are multi-dimensional tables supported?" verified 1-D (linear + cubic, inline + file), 2-D (bilinear + bicubic) and 3-D (trilinear) as exact — but a 4-D call failed at the *signature* level (`expected at most 2 arguments but found 6`), even though the self-describing grid-file reader and the recursive multilinear interpolation (Enhancement-17) were **already fully dimension-general**; only the hard-coded 1/2/3-D signature list and the signature-matched dispatch capped it (the LRM sets no bound). The fix makes `$table_model` **variadic**: a dedicated inference arm owns *every* call — the 1-D inline-array and small file forms resolve against the listed signatures unchanged, while N-D file forms get the exact `[Real × ndim, Literal(String)(, Literal(String))]` signature **synthesised from the argument shapes** (trailing string literals = data file + optional control string). Owning all argument counts matters twice: the generic varargs fallthrough *resizes* listed signatures to the call's arity, which **truncates** longer signatures and made plain 2-argument inline calls ambiguous (caught by the full regression sweep mid-implementation); and a 5-argument call is ambiguous *by arity alone* — 3-D + file + ctrl vs 4-D + file — which the shape scan disambiguates. The lowering now dispatches on argument shapes rather than the resolved signature; the grid-file format is unchanged and all partial derivatives still flow through autodiff into the Jacobian. Pure `hir_ty` + `hir_lower` change.

- Verified end-to-end through ngspice — the demo grids hold **multilinear** functions, which multilinear interpolation reproduces *exactly* at any off-grid point, so every check asserts **analytic equality**: 4-D exact at two off-grid points (`f4(1.5,0.25,0.75,0.4) = 7.9625`), 4-D *without* a control string (the ambiguous 5-argument arity) exact, **5-D exact** (`6.5625`), and the 1-D inline form regression-locked — see `examples/ndtable_examples/`
- Regression-checked: all 36 example verify suites ALL PASS — including `table_model`/`mdtable`/`cubic_table`, which lock the 1–3-D behaviour now re-routed through the new shape-based dispatch
- Details: [Enhancement-40.md](enhancements_doc/Enhancement-40.md)

---

## Enhancement 41: implicit nets in instance connections

*July 2026* — Implemented **implicit nets**: a plain identifier used in a module-instance port connection that names nothing declared in the enclosing module is implicitly declared as a scalar net — the idiom every netlist-style module relies on (`res2 r1(in, mid); res2 r2(mid, out);` previously errored `'mid' was not found in the current scope`, forcing every internal wiring node to be declared manually). The Verilog-A subtlety, worked out against the LRM appendix: full Verilog-AMS gives implicit nets their discipline via the `` `default_discipline`` directive, which the **Verilog-A appendix excludes** — but implicit nets themselves remain part of Verilog-A, their discipline coming from discipline resolution. Enhancement-41 implements exactly that reconciliation: the implicit net's discipline is **derived from the connected port** (what resolution yields for compatible ports; fallback `electrical`), the directive stays ignored per the appendix, two connections implying **conflicting** disciplines are a hard error (`implicit net 'mid' is connected to ports of conflicting disciplines 'electrical' and 'thermal' — declare it explicitly`), and implicit declaration remains **structural-only** (an undeclared identifier inside `V()`/`I()` access is still a clean scope error). Implemented in the Enhancement-5 module-instantiation elaboration pass: the implicit net becomes a **local of the module its instantiation appears in**, so it takes that module's instance prefix like every other local — the subtle correctness point being that two flattened instances of the same submodule keep their internal implicit nets **distinct** (no accidental cross-instance shorts); declarations are synthesised once and prepended to the module's rendered body. Both positional and named (`.n(mid)`) connection forms work. One-file change (`hir/src/elaborate.rs`); no OSDI/ngspice change.

- Verified end-to-end through ngspice — two `ser2k` submodules, each with its **own implicit internal net `w`**, chained through an implicit top-level `mid` (mixing positional and named forms): the DC resistance reads exactly **4 kΩ**, proving `mid` joined the instances *and* the nested `w` nets stayed distinct after flattening (a cross-instance short would read 2 kΩ); conflicting-discipline connections rejected with a clear message; `V(ghost, c)` still a clean scope error — see `examples/implicitnet_examples/`
- Regression-checked: all 37 example verify suites ALL PASS, all 79 example models recompile, and the `instantiation`/`generate` decks (the heavy users of the elaboration pass) run unchanged
- Details: [Enhancement-41.md](enhancements_doc/Enhancement-41.md)

---

## Enhancement 42: correlated (same-named) noise sources

*July 2026* — Implemented **noise-source correlation by name**: per Verilog-AMS LRM 4.6.4, noise functions carrying the same name argument model the **same physical source** — perfectly correlated — so their contributions to the noise output must sum as complex **amplitudes**, `|Σ f_k·√pwr_k·T_k|²`, not as powers `Σ f_k²·pwr_k·|T_k|²`. Previously the name only *labelled* the per-source output vectors and every source was independent: a same-named pair read `√2`× instead of `2`×, and even a **negated** contribution of the same source (`<+ -white_noise(S,"n")`, anti-phase, must cancel) *added* power. (The investigation also retired the three stale `// TODO noise` markers in the OSDI crate — the code below them was already complete; correlation was the real leftover.) The fix is two-sided. **OpenVAF** (`osdi/src/load.rs`): the contribution factor is now folded into the loaded noise power as `fac·|fac|` instead of `fac²` — identical magnitude, but the power **carries the factor's sign** (supporting fix: `llvm.fabs.f64` was never registered in `mir_llvm`'s intrinsic table). **ngspice** (`src/osdi/osdinoise.c`): the noise loop records each source's complex transfer `T_k` (adjoint solution) first, then groups same-named sources **within the instance** and sums signed amplitudes `sign(pwr)·√|pwr|·T_k` coherently before squaring. A uniquely-named source reduces *exactly* to the classic `|pwr|·|T|²` — independent sources are bit-identical to before — and grouping is per-instance by construction, so identical names in different instances stay uncorrelated, as they must. The group total is reported on the group's first `onoise_<inst>_<name>` vector (members read 0). Unnamed noise functions keep their compiler-synthesised unique names and can never group accidentally; partial correlation composes naturally from shared + private named sources.

- Verified end-to-end through ngspice with exact analytic checks (PSD 1e-12 sources on unity-transfer chains): same-named pair **2e-6** (was 1.414e-6), distinct names 1.414e-6 (unchanged), anti-phase same-named pair **0** (cancellation), scaled factors `|2+1|`·1e-6 = **3e-6**, same name across two *instances* independent (2.828e-6), `white_noise`+`flicker_noise` under one name group across kinds (2e-6 at 1 Hz), per-source vectors report the group total on the group's first source — see `examples/noisecorr_examples/`
- Regression-checked two ways: all 39 example verify suites ALL PASS (including the Enhancement-9 `noise_table` suite), **and** a golden-reference replay of all 20 deck-based example folders — every model recompiled, ~70 DC/AC/transient decks rerun, **72 stored outputs bit-identical** (max diff 0.0)
- Also in this release: two stale-example fixes surfaced by that replay — the `cross_examples` AC decks/references were internally inconsistent (the demo modules were rewritten to expose the event counter on `V(out)`, whose small-signal response is exactly 0, but the decks still took `db()` of it and the references still held the old pass-through's unity-gain data; decks now record raw `v(out)` and the references are regenerated), and the `bessel_filter_examples` decks' hardcoded absolute paths are now relative
- Details: [Enhancement-42.md](enhancements_doc/Enhancement-42.md)

---

## Enhancement 43: variable initializers, completed

*July 2026* — Completed **declaration initializers** (`real x = 2.5;`, evaluated once at simulation start per the LRM). Scalar initializers already worked — including constant expressions over parameters that re-evaluate against model-card overrides, and correct **init-once** semantics (an unwritten variable read becomes a hidden-state input seeded from the initializer gated on the initial step, so `integer cnt = 10;` with an `@(cross)` increment starts at 10 and *counts*, never re-initializing per evaluation). Three defects fixed, all in `hir_def`. **(1) Array declaration initializers were rejected**: an array variable expands into per-element scalar variables, and each element's body collected the *whole* `'{...}` aggregate — hence "expected real value but found real[0:3] value" repeated once per element. `Var` now carries its flat row-major `array_index` (mirroring `Param::array_index`) and each element's body takes just its own literal leaf — which makes **1-D, 2-D, and N-D initializers** (`real m[0:1][0:2] = '{'{...},'{...}};`) work, with integer-leaf casts, parameter-dependent leaves tracking overrides, and function-local arrays covered by the same path. **(2) An analog-function argument without a type declaration crashed the compiler**: `input v;` with no `real v;` yielded `Type::Err`, which hit `unreachable!("unknown cast found Real -> Err")` at the first cast (this masqueraded as a "function-local initializer crash" during probing — the initializer was innocent). Untyped arguments now default to `real`, matching the untyped-return default. **(3) Wrong-arity initializers crashed the compiler — array *parameters* included** (a pre-existing E-14 latent bug): the uncovered elements lowered as `Expr::Missing` and died with "invalid HIR: Missing". Both expansion sites now count the literal's leaves and emit a named diagnostic — `array initializer for 'x' has 2 elements but the array has 3` — covering too-few, too-many, and scalar-on-array forms for variables and parameters alike.

- Verified end-to-end through ngspice with exact analytic checks: scalar/param-dependent/string initializers (`y = 2*p+1` tracks `p=10`), the init-once counter (10 → 14 across four rising crossings), 1-D real + integer / 2-D / 3-D arrays with parameter-dependent leaves (66 + 4·s, tracking `s`), an array element initialized to 100 and event-updated from there, function-local scalar + array initializers with an untyped argument (7.25, used to ICE), and four wrong-arity forms rejected cleanly — see `examples/varinit_examples/`
- Regression-checked: all 39 example verify suites ALL PASS; `hir_def`/`hir_ty`/`hir_lower`/`hir`/`syntax`/`parser` crate tests pass
- Details: [Enhancement-43.md](enhancements_doc/Enhancement-43.md)

---

## Enhancement 44: paramset hierarchical system parameters

*July 2026* — Implemented **hierarchical system parameters in paramsets** (`.$mfactor = 8;`, LRM 6.4 — the canonical "quad device" idiom; previously a parse error, "unexpected token system function identifier"). The probe first established that the six hierarchical system parameters were already fully working at the *instance* level: readable in expressions with exact LRM defaults, settable per-instance in ngspice (`m=` for `$mfactor` via the OSDI layer's standard alias, `_xposition=` … for the rest — ngspice rewrites the `$` prefix to `_` since `$` starts a netlist comment), and `$mfactor` semantics exact (flow contributions ×m, potential contributions invariant, noise PSD ×m, correct across flattened sub-instances). What was missing was the paramset side. E-44 parses the form (a SYSFUN token in the override's NAME_REF), stores each override as a hidden **real localparam named `$paramset$<name>`** in the Enhancement-21 twin module — deliberately *not* `$mfactor`, which would hijack ngspice's `m=` alias since localparams appear in the OSDI descriptor — evaluated by the ordinary override machinery, so expressions over the paramset's own card parameters work (`.$mfactor = nf;` tracks `nf` from the model card). A new `sim_back` pass, modeled on the hidden-state use-rewrite and running **after the DAE build** (so the automatic mfactor flow/noise scaling and the derivative code exist and get rewritten), replaces every use of the system parameter with the **composed** value, following the LRM hierarchy rules: multiplicative for `$mfactor`/`$hflip`/`$vflip`, additive for `$xposition`/`$yposition`/`$angle` — `m=3` on a `.$mfactor = 8` paramset yields an effective 24. Unknown system functions (`.$vt = 1;`) get a named diagnostic. Supporting fix: the pass creates new MIR values, so the output-values bitset is re-grown (its `contains` check in the init-cache dead-code pass indexes by value and paniced otherwise).

- Verified end-to-end through ngspice with exact analytic checks: the quad idiom reads 250 Ω effective (2 kΩ / 8); netlist `m=3` composes to 24× (−12 mA); all six parameters read composed values with instance overrides composing on top (× m, + positions, × flips: 24755.09 exactly); `.$mfactor = nf` tracks a model-card `nf=2`; noise through a `.$mfactor = 4` paramset measures identical to netlist `m=4` (5e-4); `.$vt` rejected cleanly — see `examples/paramsethsp_examples/`
- Regression-checked: all 40 example verify suites ALL PASS; `sim_back`/`hir_def`/`hir_lower`/`parser`/`syntax` crate tests pass (the `sim_back` MIR snapshots, stale since ~E-36 and failing identically on the committed pre-E-44 sources, were refreshed against the behavior verified bit-identical by E-42's 72-output golden replay)
- Details: [Enhancement-44.md](enhancements_doc/Enhancement-44.md)

---

## Enhancement 45: net initialization (nodesets) + net attribute access

*July 2026* — Implemented two LRM features that were both completely missing. **(1) Net attribute access** (LRM 5.5.3): `net.potential.abstol` / `net.flow.abstol` / `branch.potential.abstol` — every spelling failed with "expected a scope but found node/branch". The scaffolded-but-unwired pattern struck a third time: nameres had branch-attribute arms, but only in the cross-scope resolver — the module-body entry rejected non-scope qualifiers first, so even the branch form was unreachable from where models use it. The fix adds `NodeId`/`BranchId` arms at that entry with two new `ResolvedPath` variants and a net → discipline → nature → attribute lookup through Enhancement-39's inheritance-aware machinery; lowering needed nothing (`NatureAttr` reads already lower to the attribute's constant). The LRM's own `twocap` example (`I(a,b) <+ c*ddt(V(a,b), a.potential.abstol);`) compiles verbatim. **(2) Net nodeset initializers** (LRM 3.6.3.2): `electrical a = 5.0;` (and the bus form `electrical [0:2] b = '{0.5,-1.0,2.0};`) — the constant initializer is a **nodeset** value for the net's potential, an initial Newton-Raphson guess. The value travels net declaration → item tree → a new `double nodeset` field in the OSDI node descriptor (NAN = none) → ngspice, which applies it at instance setup (landing on a pre-existing `// TODO nodeset?` marker) for internal nodes and connected terminals — an explicit netlist `.nodeset` wins. The Enhancement-5 flattening now preserves initializers on submodule nets (its re-renderer dropped them). Non-constant initializers get a named diagnostic. **Breaking ABI note**: the `OsdiNode` array stride changed, which `OSDI_DESCRIPTOR_SIZE` cannot detect, so the **OSDI version is bumped to 0.5** and ngspice's loader requires it — stale `.osdi` files are rejected with "Recompile the model with the matching openvaf-r" instead of being misread; every committed example `.osdi` in this repo was regenerated.

- Verified end-to-end through ngspice with a bistable `x = tanh(5x)` node (solutions 0, ±0.999909): no initializer → 0; `= 1.0`/`= -1.0` internal-net initializers select the ± branch; a **port** initializer nodesets the connected terminal and netlist `.nodeset` overrides it; bus leaves apply per bit (weighted sum 90.99); an initializer inside a flattened submodule survives; attribute access reads exactly (1e6·`q.potential.abstol` + 1e12·`q.flow.abstol` + 1e6·`br.potential.abstol` = 3.0); non-constant initializers and unknown attributes are clean diagnostics — see `examples/netinit_examples/`
- Regression-checked: all 41 example verify suites ALL PASS; crate tests (`hir_def`/`hir`/`hir_ty`/`hir_lower`/`sim_back`/`osdi`/`parser`/`syntax`) 57/57
- Details: [Enhancement-45.md](enhancements_doc/Enhancement-45.md)

---

## Enhancement 46: escaped identifiers + integer literal bases

*July 2026* — Implemented **integer literal bases** (LRM A.8.7) and completed **escaped identifiers** (LRM A.9.3). Front-end only. **(1) Based literals were entirely missing**: `'h1F`, `'o17`, `'b1010`, `'d42`, sized `8'hFF`, signed `8'shFF` were all "encountered unexpected token" — the lexer contained only a commented-out sketch of based-number tokenization — and the LRM-legal underscore separator (`1_000_00`) **crashed the compiler** (the lexer ate `_` into the token; value parsing didn't strip it). The lexer now tokenizes `[size]'[s]<base><digits>` with digits validated per base while lexing (an invalid digit or a bare `'h` is an ordinary parse error, never a silently-zero literal), value parsing masks to the declared size (clamped 1..=32), sign-extends from the size's MSB under `s`, wraps to the 32-bit `integer` type (`'hFFFFFFFF` = −1), and `_` separators are stripped in every number form including reals. **(2) Escaped identifiers were half-wired**: the lexer already emitted `EscapedIdent` tokens, but `Name::resolve` stripped the identifier's *last character* along with the backslash — `\foo` never named the same thing as plain `foo`, and the compiler's own `std.va` def-map snapshot had quietly baked in `logi` for the escaped `\logic` discipline, hiding the bug (snapshots refreshed). The Enhancement-5 flattening also re-rendered instance-prefixed names unescaped, breaking any escaped net inside a submodule ("unexpected token '-'"); a `render_name` helper now re-escapes substitution values that aren't plain identifiers, and the renderer gained the `EscapedIdent` substitution arm. Keyword spellings (`\module`) work as names.

- Verified end-to-end through ngspice: one module using every literal form sums to **0.1443252345 V exactly** (hex/octal/binary/decimal, size mask + sign extension, 32-bit wrap, separators in ints/based digits/reals); escaped nets/variables/parameters with specials (`\2wire`, `\value#`, `\r+val`); `\mid` ≡ `mid` as one net; an escaped net inside a flattened submodule re-escapes correctly (2k series exact); `\module` as a net name; four malformed literal forms rejected cleanly — see `examples/escid_examples/`
- Regression-checked: all 42 example verify suites ALL PASS; 65/65 crate tests (`lexer`/`tokens`/`syntax`/`parser`/`hir_def`/`hir`/`hir_ty`/`hir_lower`/`sim_back`)
- Details: [Enhancement-46.md](enhancements_doc/Enhancement-46.md)

---

## Enhancement 47: `default_transition + transition() fixes

*July 2026* — Implemented the **`` `default_transition``** compiler directive (LRM: the default rise/fall time for `transition()` filters that omit those arguments; 0 = instantaneous without a directive). It was the only directive from a nine-directive probe that didn't work — `` `define``/`` `undef``/`` `ifdef``/`` `ifndef``/`` `else``/`` `elsif``/`` `endif``/`` `include`` all verified exact — and it hard-errored as an undeclared macro, unlike `` `default_discipline`` which the preprocessor deliberately captures. The preprocessor now recognizes it, parses the value (SI suffixes and `_` separators), and carries it on the `Preprocess` result (last directive wins, file-level granularity; a directive inside a false `` `ifdef`` is never processed, so conditional guards work for free) to a `CompilationDB` accessor consumed by the `transition()` lowering for the no-args and delay-only forms; explicit rise/fall arguments always win. **Two pre-existing defects fixed along the way.** (1) The TRANSITION signature table was one argument short per entry — a 3-argument `transition(s, td, trise)` resolved to the wrong signature and **crashed the compiler** reading `args[3]` out of bounds (confirmed on the released binary); 4-argument calls only worked by accident through the tol signature; the true 5-argument tol form did not resolve at all. (2) The slew/transition tracking loop's clamp has a zero derivative when saturated, so the DC Jacobian diagonal vanished — a **singular operating point** (garbage transient without `uic`) whenever the input started a full swing away from the filter state, e.g. a timer-driven comparator high at t=0. Per the LRM the filter is a static identity in DC, so the residual now selects on the integration-enable parameter: `y − x` in DC (never singular, exact semantics), rate-limited tracking in transient — with a bonus exact-unity AC transfer instead of a spurious pole at 10⁹ rad/s.

- Verified end-to-end through ngspice: bare `transition(s)` under `` `default_transition 1u`` ramps over exactly 1 µs (half-cross at 0.5 µs) with a clean DC operating point (no `uic`, no singular matrix); the delay-only form stacks delay + default ramp; explicit rise times win; all five arities compile and run (weighted plateau 0.875 exact, including the previously-crashing 3-argument form); without the directive the bare form stays instantaneous; a directive inside a false `` `ifdef`` is ignored — see `examples/defaulttransition_examples/`
- Regression-checked: all 43 example verify suites ALL PASS; 71/71 crate tests (`preprocessor`/`hir_def`/`hir`/`hir_ty`/`hir_lower`/`sim_back`/`lexer`/`syntax`/`parser`)
- Details: [Enhancement-47.md](enhancements_doc/Enhancement-47.md)

---

## Enhancement 48: string literal escape sequences

*July 2026* — Completed **string literal escape handling** per LRM 2.7.1 (`\n`, `\t`, `\\`, `\"`, and `\ddd` — a character by one to three octal digits). The probe found the four basics worked but **octal escapes were unsupported** (`"\101\102\103"` printed literally instead of `ABC`) and **overlapping sequences were corrupted**: the unescaper chained sequential `str::replace` calls with `\n` handled *before* `\\`, so `"a\\nb"` — a literal backslash followed by `n` — came out as a backslash plus a **real newline** (the classic overlapping-escape bug). `StrLit::unescaped_value` is now a single left-to-right pass covering the full LRM set: greedy 1–3-digit octal escapes (out-of-range degrades to the replacement character), the pre-existing backslash-newline line-continuation extension preserved unchanged, and unknown escapes passed through verbatim. The consumer audit confirmed every string path already routes through this one function — `$strobe`/`$display`/`$swrite` format strings, string values and comparisons, attribute strings, `initial_step` phase names, lint names — so the fix applies uniformly with no second unescape path to drift.

- Verified end-to-end through ngspice: the `$strobe` rendering matrix (tab/newline/backslash/quote exact, the previously-corrupted `\\n` round-trip printing a literal backslash-n, octal `ABC` and digit forms) and compile-time consistency (`"\101\102" == "AB"` true, overlap-safe self-equality, unknown escapes comparing consistently — the check module reads exactly 7) — see `examples/stresc_examples/`
- Regression-checked: all 44 example verify suites ALL PASS; `syntax`/`hir_def`/`basedb`/`hir_lower`/`sim_back` crate tests 52/52
- Details: [Enhancement-48.md](enhancements_doc/Enhancement-48.md)

---

## Enhancement 49: $root + hierarchical names, transition() input

*July 2026* — Implemented **hierarchical names** (LRM 6.6) and fixed a user-reported `transition()` defect. The probe found `$root`-anchored paths and single-level block paths already working, plus three defects. **(1) References into flattened instances didn't resolve**: after the Enhancement-5 elaboration flattens `rdiv u1(a, c);` into prefixed locals (`u1__m`), parent-side references (`V(u1.m)`, `u1.r`) failed with "'u1' was not found in the current scope". Every rendering scope now carries an **instance-chain map** (all reachable chains — `u1`, `u1.u2`, `u1[2]` — mapped to their composed flattening prefixes), and a token-level scanner rewrites `chain.member` occurrences to the flattened names: deep chains compose, instance-array elements are disambiguated from bus selects by chain lookup, bus selects after the member stay in place, escaped names re-escape, and the top scope's alias entries plus `$root.` stripping make `$root.<top>.u1.u2.m`, `<top>.u1.u2.m` and `u1.u2.m` resolve identically. **(2) Nested named-block paths failed** (`outer.inner.w` — "'w' was not found in 'inner'"): after the resolver redirected into a nested block's def map, the *final* name lookup still probed the original map (`self.scopes` instead of `current_map.scopes` — a one-token aliasing bug that only multi-segment paths hit). **(3) `transition()` typed its input Integer**, rejecting the LRM's canonical comparator (`real vcout; ... transition(vcout, td, tr, tf)`); per LRM 4.5.7 the input is Real (integers still promote implicitly). The accompanying audit of **every** builtin signature table caught one more defect — `DIST_2_ARG_CONST_SEED` typed its middle argument Real while its three siblings say Integer — making signature tables a three-time defect class (E-40 varargs truncation, E-47 arity shortfall, E-49 argument types), now fully audited.

- Verified end-to-end through ngspice with exact checks: a two-level hierarchy read through plain, `$root`-anchored and top-qualified spellings (hierarchical parameter + deep net probes sum to **557 exactly**); nested named-block paths (**3.75 exactly**, previously an error); and the LRM comparator compiling and switching (+1/0 on the sine halves) — see `examples/hiername_examples/`
- Regression-checked: all 45 example verify suites ALL PASS; 57/57 crate tests
- Details: [Enhancement-49.md](enhancements_doc/Enhancement-49.md)

---

## Enhancement 50: domain binding validation

*July 2026* — Enforced the one missing rule of **discipline domain bindings** (LRM 3.6.2.2). The probe found `domain` substantially implemented: `domain continuous;`/`domain discrete;` parse and are stored on the discipline (the std header's own `ddiscrete`/`logic` disciplines exercise `domain discrete` in every compilation), nature-bound disciplines default to the continuous domain, the domain participates in discipline-compatibility checks (domainless treated permissively per LRM 3.6.2.3), discrete-domain nets are rejected in analog accesses, and a custom continuous discipline with natures compiles and simulates exactly. The gap: *"It is an error for a discipline to have a domain binding of discrete if it has nature bindings"* was accepted silently. `validate_discipline_decl` now tracks the `domain discrete` binding and the first unqualified `potential`/`flow` nature binding (qualified attribute overwrites like `potential.abstol = …` correctly don't count) and emits a two-label error — "the domain is bound discrete here" / "… but a nature is bound here" — with a help note citing the rule and both remedies.

- Verified end-to-end through ngspice: a custom `domain continuous` discipline with natures simulates exactly (−1 mA through its 1k contribution); a natureless `domain discrete` discipline stays accepted; the discrete-plus-natures case is rejected with the named diagnostic (was silent); a discrete net in an analog access stays a clean error — see `examples/domainbind_examples/`
- Regression-checked: all 47 example verify suites ALL PASS; `syntax`/`basedb`/`hir_def`/`hir_ty` crate tests 24/24
- Details: [Enhancement-50.md](enhancements_doc/Enhancement-50.md)

---

## Enhancement 51: full ac_stim AC injection

*July 2026* — Completed **`ac_stim`** (LRM 4.6.3), the small-signal AC stimulus source deferred since Enhancement-26 (which fixed the compiler crash and the correct large-signal 0 but injected nothing). `ac_stim([name][, mag[, phase]])` now injects `mag∠phase` (phase in **radians**) into the AC solve when the analysis name matches (default `"ac"`), staying exactly 0 in DC/transient and under non-matching names. The implementation rides the **noise-source pipeline** end to end: a dedicated callback per call site flows through the existing small-signal-network extraction (branch + factor exist for AC while the large-signal residual stays 0) into the shared source records, then **partitions** at the OSDI level — the noise descriptor arrays keep only genuine noise sources (their load functions use filtered indexing, leaving noise analysis untouched) while ac_stim sources get appended descriptor fields (`num_ac_stim_src`/`ac_stim_sources`/`load_ac_stim`, the latter filling `factor·mag·e^{jφ}` pairs from eval-cached values, so operating-point-dependent magnitudes work). ngspice's AC load injects them into the complex RHS with the residual-convention sign (`(G+jωC)x = −residual_stim`, calibrated so `V(out) <+ ac_stim()` reads exactly +1∠0). `mfactor` follows deterministic-signal laws — current stimuli scale linearly, voltage stimuli are invariant — unlike noise's sqrt(m). **Breaking ABI note**: the descriptor grew appended fields, so the **OSDI version is bumped to 0.6** and ngspice's loader requires it (stale `.osdi` files get the recompile message); ngspice's `osdi.h` had only ever declared a *prefix* of the descriptor and gained the full field tail. All committed example `.osdi` binaries were regenerated.

- Verified end-to-end through ngspice with exact analytic checks: `V(out) <+ ac_stim()` = **1∠0**; `ac_stim("ac", 2, π/2)` = **j2**; `ac_stim("sp")` inactive in AC; a current stimulus into 1k reads **−1000** (contribution sign); an internal stimulus driving an RC lowpass reads exactly **0.5−0.5j at the pole** (0.7071∠−45°) and 0.01 at 100·fc — the classic embedded AC test bench; DC/transient invariance (the E-26 checks) unchanged; `m=3` scales a current stimulus ×3 linearly — see `examples/acstim_examples/`
- Regression-checked: all 47 example verify suites ALL PASS (the noise and correlated-noise suites confirm the noise/ac_stim partition is airtight); 28/28 crate tests
- Details: [Enhancement-51.md](enhancements_doc/Enhancement-51.md)

---

## Enhancement 52: idt() assert/reset forms

*July 2026* — Fixed the **`idt(expr, ic, assert[, tol|nature])` reset forms** — the Enhancement-28 leftover, completing the integrator family (E-27 `idtmod`, E-28 initial conditions, E-52 reset). Per the LRM, while `assert` is nonzero the integral is reset to `ic` and held, resuming from `ic` on release. The probe found externally-driven resets already working (E-28's ic-seeding had quietly helped), but a **self-referential reset** (`idt(1.0, 0.0, V(out) > 1.0)`) rang chaotically and ran away to ~400 V on a 1 V/s ramp: the previous lowering's reactive residual (the integrator's stored charge) **jumped** from the integrated value to `ic` at the reset onset — the exact impulse failure mode E-27 documented for `idtmod`'s state wrap — feeding back into its own reset condition. The fix keeps the charge **smooth** (reactive residual = the output, always — continuous at onset and release), implements reset as a stiff first-order decay to `ic` (τ = 10 µs), and emits a **conditional `bound_step`** only while the decay is active, holding the trapezoidal method in its deadbeat region so the stiff mode cannot ring — then releases it once settled, so an assert held for seconds simulates at full speed. (An unbounded τ = 1 ns decay was tried first: trap's ±1 stiff-mode amplification produced −0.25 undershoot and a 40% period error in the oscillator test.) DC/IC-phase pinning and the E-28 charge handoff are preserved; a non-hysteretic self-reset correctly settles at the threshold (a sliding equilibrium — oscillation requires hysteresis).

- Verified end-to-end through ngspice with exact checks: the externally-reset integrator ramps 0.5→1.5, holds at 0.5, resumes to 1.5; an op-dependent integrand with the reset active at the operating point (and the tol form) holds 0.25 then ramps at 2 V/s; the self-referential reset stays **bounded at exactly the threshold** (was ~400 V); and a **relaxation oscillator** built from `idt` + hysteretic cross-event reset runs at peaks 1.0, valleys at `ic`, no undershoot, period exactly 1 s — see `examples/idtassert_examples/`
- Regression-checked: all 47 example verify suites ALL PASS; 28/28 crate tests
- Details: [Enhancement-52.md](enhancements_doc/Enhancement-52.md)

---

## VA_TEST — real-world compile corpus

`VA_TEST/` holds the public **VA-Models** collection as a compile-regression corpus: the industry-standard compact models (BSIM4/6/BULK/CMG/IMG/SOI, PSP 102/103/104, PSP-HV, HiCUM L0/L2, MEXTRAM 504/505, VBIC, EKV 2.6/3, ASM-HEMT, EPFL-HEMT, Angelov, MVSG, diode_cmc, r2/r3_cmc, L-UTSOI, MOSVAR, IGBT, …) — 124 `.va` files in total. `python3 VA_TEST/compile_all.py` compiles every file with the committed `openvaf-r` and regenerates [VA_TEST/compile_report.md](VA_TEST/compile_report.md); **all 92 standalone models compile** (the remaining 32 files are `` `include `` fragments — macro bodies and module-body pieces — reported separately since they aren't standalone modules).

---

## Enhancement 53: `@(final_step)` and analysis-phase lists on step events

*July 2026* — Implemented the **`@(final_step)` event** and **analysis-phase lists** on both step events (`@(initial_step("tran","ac"))`, LRM 5.10.2) — the last visibly missing Verilog-A (LRM Annex C) feature. `@(final_step)` had been Enhancement-7's documented fail-safe no-op (firing needs "the analysis is over" knowledge the per-iteration eval loop doesn't have), and the parsed phase lists were silently dropped, so `@(initial_step("ac"))` fired during a transient run. Three fixes: **(1)** a new `ParamKind::IsFinalStep` gates the body on `EVAL_FLAG_IS_FINAL_STEP` (bit 1<<21 — an additive flag like E-7's, **not** an OSDI ABI change), and a new `OSDIfinalStep()` in ngspice issues one dedicated `eval()` per OSDI instance at the converged final solution — without loading the results into the matrix — from the successful end of every analysis (`dctran.c`, `dcop.c`, `dctrcurv.c`, `acan.c`, `noisean.c`); **(2)** phase lists now AND the step flag with the same per-name `analysis()` matcher Enhancement-30 built, OR-ed across names; **(3)** an AC/noise job's operating-point phase now carries its analysis *name* flag (ngspice consults the running job's type — `CKTmode` alone can't distinguish an AC job's op from a standalone op; only the name bit is added, not the reactive `CALC_*` bits, which would wrongly enable integration at an op), so `@(initial_step("ac"))` fires in AC runs and `analysis("ac")` holds through the whole AC analysis per LRM 4.6.1. An op fires **both** events (a single point is first and last); failed or interrupted analyses never fire `final_step`.

- Verified end-to-end through ngspice with 23 exact checks across all five analysis types: `final` fires exactly once at t = tstop seeing the converged solution; a dc sweep's `final` sees the last sweep point (V = 2.0 exact); the full phase-filter matrix (incl. a multi-name list); and the LRM's classic use case — a peak tracked across the whole transient, reported exactly once at the end — see `examples/finalstep_examples/`
- Regression-checked: all 49 example verify suites ALL PASS; 28/28 crate tests
- Details: [Enhancement-53.md](enhancements_doc/Enhancement-53.md)

---

## Enhancement 54: correct and node-free noise factors

*July 2026* — What began as the old "noise extra-node optimization" TODO turned into a **correctness fix**: the probe showed that every noise source routed through the extra-unknown path — an op-dependent factor (`gm * white_noise(...)`), a noise wave through `ddt()` (the induced-gate-noise idiom), or one wave shared by two branches (a correlation network) — produced an extra internal node **and no noise output at all** (the spectrum equaled exactly the surrounding resistors' floor). Two silent-loss defects were fixed: `build_implicit_equation` never attached its contribution's noise to the DAE (the source never reached the OSDI descriptor), and the react optbarrier created when `ddt()` moves to the reactive dimension was never registered, so the small-signal pruning dropped the wave's coupling — a hole in the Jacobian (the refreshed PSP103 snapshot shows real `react_small_signal` couplings restored on a flagship model). On top of the now-correct baseline, the optimization: op-dependent factors and one `ddt()` per noise chain stay **linear — no extra matrix unknown**. The factor generalizes to `re + jω·im`; `load_noise()` fills `[flat, react]` signed power pairs per source and ngspice's grouping sums complex amplitudes `(a + jω·b)·T` — exact for single sources and coherent same-named groups (LRM 4.6.4), including anti-phase cancellation. An operator-ordering hazard (a shared ddt evaluated between two noise operators silently dropped the second source) was also fixed — all noise operators now process before any ddt.

- **OSDI ABI 0.6 → 0.7** (`load_noise` dst stride 1 → 2): ngspice's registry now requires >= 0.7 — older `.osdi` files must be recompiled; all 88 committed `.osdi` artifacts in this repo were regenerated
- Verified end-to-end through ngspice with 18 exact closed-form checks (resistor floors measured via noiseless twin modules): node-free `gm`-factored and ω²-shaped induced noise, `ω²·kf/f^ef` flicker composition, coherent flat+jω mixing `(x² + ω²τ²)`, exact anti-phase cancellation, the formerly-lost cross-branch correlation network, and `m=4` mfactor scaling — see `examples/noisejw_examples/`
- Regression-checked: all 50 example verify suites ALL PASS; 28/28 crate tests (topology/dae snapshots refreshed)
- Details: [Enhancement-54.md](enhancements_doc/Enhancement-54.md)

---

## Enhancement 55: simulation-control tasks honored + `$discontinuity` step rejection

*July 2026* — The "small OSDI TODOs" audit bundle turned into four real defect fixes around the **simulation-control system tasks**. The probe showed: `$finish` was **ignored entirely** (its return flag was never checked in the load path — the transient ran to its full stop time); `$stop` **broke timestep control** (its `E_PAUSE` returned mid-Newton-iteration was treated as a step failure, grinding the step down in a rejection loop); `$fatal` under an op-dependent condition was **silently deleted at compile time** (its argument-free `SetRetFlag`/print calls looked op-independent, were hoisted to instance-init, and sat there in an unreachable block — root cause: the shared post-dominator tree roots at the `exit` sink, so taint propagation never control-tainted the fatal arm); and `$fatal`'s `E_PANIC` was **swallowed** by the transient's nonconvergence retry. Fixes: `$finish`/`$stop` requests are latched per timepoint attempt (`point_eval_flags`, OR-ed across all Newton iterations, reset per attempt) and honored at the **accepted-point boundary** — `$finish` fires `@(final_step)` and ends the analysis cleanly (transient and DC sweeps), `$stop` pauses resumably; side-effecting callbacks under op-dependent control now stay in eval (control dependence computed by arm-reachability, exact for early-exit arms) while parameter-only `$fatal` still validates at setup; `E_PANIC` aborts the transient with a clear error. On top: **`$discontinuity(n>=0)` now rejects the event step** — a new additive return flag (`EVAL_RET_FLAG_DISCONT`, **not** an ABI break) makes `OSDItrunc` request `delta/8` (with a `20·CKTdelmin` termination floor), so the integrator bisects onto the event instead of extrapolating across it (E-24's next-step clamp is kept). Two documented decisions: the `Opcode::Exit` `todo!()` was dead code (Exit is handled by the terminator path — now `unreachable!`), and runtime `is_voltage_src` OSDI exposure is deferred until a consumer exists.

- Verified end-to-end with 17 checks: `$finish` ends the transient exactly at the requesting point with `@(final_step)` firing there; `$stop` pauses cleanly; `$fatal` prints its message and aborts (was silently deleted) or rejects the instance at setup (parameter validation); a DC-sweep `$finish` ends the sweep at the requesting value; and the `$discontinuity` A/B twins show the event step ≥ 4× smaller with a sharper, no-later jump — see `examples/simctrl_examples/`
- Regression-checked: all 51 example verify suites ALL PASS; 28/28 crate tests
- Details: [Enhancement-55.md](enhancements_doc/Enhancement-55.md)

---

## Enhancement 56: end-to-end corpus sweep — CMC default-range idiom + noise crash fix

*July 2026* — The first **end-to-end sweep** of the `VA_TEST/` corpus: all 92 standalone industry models compiled and run through ngspice op/AC/transient/noise on a bench generated from each model's OSDI descriptor (the corpus had only ever been compile-tested). Three real defects found and fixed. **(1) Parameter defaults were range-checked**: CMC-standard models declare a default *outside* the parameter's own range as the "feature disabled" state — `diode_cmc`'s `CORECOVERY = 0.0 from (0.0:1.0]`, FBH-HBT's `Fb = 0.0 from (0.0:inf)` — and expect ranges to bind only user-*given* values; OpenVAF validated defaults too, rejecting the stock CMC models (diode_cmc, bsimcmg-110, psphv, fbh_hbt, the hisim family) at setup with "Parameter … is out of bounds". Defaults are now exempt while given values are still fully validated (`from` ranges and `exclude` constraints). **(2) A singular AC matrix during noise analysis crashed ngspice with a SIGABRT** — `noisean.c` ignored `NIacIter`'s return and the noise adjoint solve then asserted on the unfactored matrix; it now aborts cleanly ("AC solution failed at … Hz"), and the noise analysis honors Enhancement-55's deferred `$finish`/`$stop` raised at its operating point. **(3)** A `$fatal`/`$finish` raised during *setup* (models rejecting their configuration by design, e.g. HiSIM's `$port_connected`/`COSUBNODE` guards) surfaced as ngspice's baffling "impossible error - can't occur" — now "a Verilog-A device rejected its configuration during setup". Every remaining sweep failure was triaged to by-design model behavior with documented workarounds (HiSIM config guards; `vbic_4T_et_cf` floats internal nodes at `RCX=0` — use `.option rshunt`; EPFL-HEMT bias sensitivity; FBH-HBT divides by its own disabled default `Fb=0` — give `fb>0`). A sweep-harness lesson worth recording: ngspice control scripts *continue past aborted analyses*, so completion must be detected from data, not echo markers.

- Verified with 13 end-to-end checks including the real corpus reproducers: out-of-range defaults accepted with exact solutions, three forms of given-value rejection still enforced, the hisimsoi noise-crash reproducer aborts cleanly (was SIGABRT), and the stock CMC `diode_cmc` runs op/AC/noise at defaults — see `examples/paramrange_examples/`
- Corpus after the fixes: **83/92 models fully green** end-to-end (the rest by-design, documented); all 88 noise runs crash-free
- Regression-checked: all 52 example verify suites ALL PASS; 28/28 crate tests
- Details: [Enhancement-56.md](enhancements_doc/Enhancement-56.md)

---

## Enhancement 57: physics-accuracy validation suite

*July 2026* — A permanent, quantitative **physics regression suite** (`examples/physcheck_examples/`): where Enhancement-56's sweep asked *does it run*, this validates *the numbers* — industry models from `VA_TEST/` must reproduce **analytic device laws** through the whole toolchain (lowering, autodiff Jacobians, the AC path, the noise pipeline). Five laws: the CMC resistor's thermal noise is **identical to a built-in ngspice resistor** (< 10⁻⁶ — a constants-free 4kT/R identity); `diode_cmc` follows the **60 mV/decade** junction law with ideality 1.004–1.009 in its ideal region (below ~0.9 V the model's recombination/TAT components dominate by design — a documented trap for naive low-bias checks); the MEXTRAM 505 **Gummel plot** shows n = 1.012–1.017 and a textbook β curve; PSP103's **AC-derived g_m/g_ds equal the numeric derivatives of the DC curves to ~10⁻⁵** — cross-validating the autodiff Jacobian against the residual on a flagship compact model; and JUNCAP200's C(V) obeys the **junction grading law self-consistently** to ~10⁻⁴. No toolchain defects were found — the deliverable is the guard itself, plus `plot_physcheck.py`, which renders all five laws as PNG plots (committed under `examples/physcheck_examples/plots/`).

- 13 checks, ALL PASS (skipped gracefully if the corpus is absent); all 53 example verify suites ALL PASS
- No compiler or ngspice source changes in this enhancement
- Details: [Enhancement-57.md](enhancements_doc/Enhancement-57.md)

---

## Enhancement 58: `defparam` hierarchical parameter override

*July 2026* — Implemented **`defparam`** (the legacy Verilog-2001 compile-time hierarchical parameter override, LRM 2.6). It was a reserved word with **no grammar rule**, so `defparam u1.r = 2e3;` failed with the misleading `'defparam' was not found in the current scope` (the idiomatic `#(.r(2e3))` / `#(2e3)` instance overrides already worked). The implementation is front-end only and lives entirely in the elaboration pass: a new `DEFPARAM_KW` keyword and parser rule produce a `DEFPARAM` syntax node that is deliberately **not** a typed `ModuleItem` — the typed iterator every later compiler stage walks simply skips it, so hir_def/hir_ty/lowering needed zero changes. Each `defparam` target resolves through the **same instance-chain rewrite Enhancement-49 built** for hierarchical references (`u1.u2.r → u1__u2__r` — exactly the flattened name the parameter receives when its instance is inlined, making the mechanism depth-agnostic), and the flattened parameter's default is rewritten through the existing `#()` hole mechanism — checked first, giving `defparam` the **higher precedence over instance `#(...)` overrides** the LRM requires. Multi-assignment forms and override expressions referencing the enclosing module's parameters work; an unresolved target is a **hard error naming the original source path**.

- Verified end-to-end through ngspice with exact op-point conductances: a basic override (1 kΩ → 2 kΩ), a two-level `u1.u2.r` target plus a multi-assignment `defparam` overriding an instance `#(.r(5e3))` down to 2 kΩ, an expression-valued override (`2.0*scale`), and the unresolved-target diagnostic — see `examples/defparam_examples/`
- Regression-checked: all 54 example verify suites ALL PASS; 28/28 crate tests; the VA_TEST corpus still compiles
- Details: [Enhancement-58.md](enhancements_doc/Enhancement-58.md)

---

## Enhancement 59: LRM-corner probe — event OR lists, `$realtime`, port concatenation, recursion diagnostics

*July 2026* — A fresh **16-corner probe battery** over never-exercised Verilog-A (LRM Annex C) constructs: 12 corners validated as already correct (away-from-zero integer rounding, `$vt(300)`, aliasparam + `$param_given` through the alias, string-parameter `case`, `above()` in DC, grounded branch declarations, `ddx` w.r.t. a flow probe, parameter-dependent `laplace_nd` coefficients, `$mfactor` reads, `branch.potential.abstol`, integer `min`/`max`/`abs`, integer function output args) and **four gaps found and fixed**. **(1) Event OR lists** (`@(cross(...) or cross(...))`, `@(initial_step or timer(t))` — LRM 5.10.3) did not parse: new `or` keyword, a looped event grammar, an `Event::Or` HIR variant, and a select-based `bool_or` fold of the members' fired flags at lowering (a raw `ior` ICEs MIR const-eval, which has no Bool arm). Verified property: the OR body fires **exactly** when any member fires — the OR counter equals the sum of the single-event counters. **(2) `$realtime`** (LRM 9.7.2) was rejected; it now lowers to the same `Abstime` parameter as `$abstime` (identical in the continuous-time analog context). **(3) Net concatenation in port connections** (`u1({a,c})` onto a vectored port — LRM 6.5) bound the whole `{a,c}` text to *every* bit; the elaboration pass now expands the concat **bit-by-bit** (leftmost element = port msb, each side in its own declared `[msb:lsb]` order; a whole-bus element contributes all its bits; width mismatch is a hard error), working positionally, named, and nested through instance levels. **(4) Recursion diagnostics**: a direct self-call surfaced as the puzzling `expected a function but found variable` (inside a function its own name resolves to the return variable) and **mutual recursion (`f1→f2→f1`) crashed the compiler with a stack overflow** in the recursive inliner — both are now clean errors, the mutual case reporting the full call cycle via a call-graph DFS in body validation.

- Verified end-to-end through ngspice: OR-counter ≡ sum of single-event counters, `$realtime ≡ $abstime` through a transient, exact port-concat op current through two concat forms, both recursion cases as clean errors, plus a self-checking bitmask module pinning 8 of the validated corners at score 255/255 — see `examples/lrmcorner_examples/`
- Regression-checked: all 55 example verify suites ALL PASS; crate tests pass; the VA_TEST corpus still compiles 92/92
- Details: [Enhancement-59.md](enhancements_doc/Enhancement-59.md)

---

## Enhancement 60: multiple analog blocks — validation

*July 2026* — Probed **multiple `analog` / `analog initial` blocks per module** (Verilog-AMS LRM 6.2: several blocks behave as if concatenated into a single block in source order) and found the feature **fully supported by construction**: hir_def's body collection iterates *every* analog block of a module into `entry_stmts` in document order — literally the as-if-concatenated semantics — and every downstream stage (type inference, lowering, autodiff, the DAE builder, OSDI) consumes that list. Nine corners probed, **zero defects**: contribution accumulation across blocks (exactly 3 mS), a module variable written in block 1 and read in block 3, `$strobe` source-order execution, an `analog function` declared *between* blocks, module declarations after a block that uses them, events split across blocks (`cross` in one, `final_step` in another), `ddt()` of a charge computed in an earlier block, a multi-block module surviving instance flattening (the E-5 elaboration re-render — series current exact to 12 digits), and two `analog initial` blocks composing in order. Also confirmed correct: duplicate *named* child blocks (`begin : work` twice) are a clean duplicate-declaration error, and V-then-I contributions across blocks match the single-block switch-branch behavior. Like Enhancement-57, the deliverable is the validation itself — a pinned example suite guarding the behavior.

- 6 checks, ALL PASS — see `examples/multianalog_examples/`
- **No compiler or ngspice source changes in this enhancement**; the Enhancement-59 full regression (55 suites, crate tests, 92/92 corpus) stands
- Details: [Enhancement-60.md](enhancements_doc/Enhancement-60.md)

---

## Enhancement 61: operator-argument audit — `slew` sign-convention fix

*July 2026* — A **full-argument-form audit** of the analog operators (LRM 4.5) and events (LRM 5.10): 22 probe forms covering every optional-argument spelling — `cross`/`above` with `time_tol`/`expr_tol`, `timer` with period and tolerance, `absdelay` with `maxdelay`, `transition` 4/5-arg, `slew` 2/3-arg, the trailing tolerance args of `ddt`/`idt`/`idtmod`/`laplace_*`/`zi_*`, `$bound_step`, `$limit` (built-in `"pnjlim"`, user functions, user functions with extra arguments), and `ac_stim` with magnitude and phase — each verified **at runtime**, since compiling proves nothing about whether a trailing argument is honored. **One real defect found and fixed: `slew` ignored its input entirely.** The LRM (4.5.15) defines `max_neg_slew_rate` as a *negative* number; the lowering negated it assuming a positive magnitude, so the LRM-conformant `slew(x, 1e6, -1e6)` produced a **positive lower clamp bound** — the tracking loop `dy/dt = clamp(K·(x−y), lo, hi)` was forced to +1e6 unconditionally and the output ramped unboundedly past any target (`transition` shares the loop but converts rise/fall *times* to always-positive rates, which is why it worked). Fixed with sign-robust `|max_pos|` / `−|max_neg|` bounds — exact for conformant inputs, tolerant of the legacy positive-magnitude spelling. Everything else verified working with quantitative evidence: `timer`'s **period** fires exactly 5× in 1 µs; `$bound_step` genuinely bounds the solver (120 → 416 evals); `$limit` is **genuinely engaged** — the stiff 5 V/1 Ω exponential diode converges directly where the raw model needs gmin stepping, for both `"pnjlim"` and user limiting functions; `ac_stim` magnitude *and* phase are exact (j1000); the integrator/filter tolerance args are numerically exact hints. Bonus: the `slew`/`transition`/`absdelay` operator family gets its **first runtime verification ever** (the old example folders had no verify scripts).

- Verified with 16 end-to-end checks — the fixed `slew` step response (holds, rate-limits both edges asymmetrically, stops at the target), toleranced events, `$limit` convergence, `$bound_step`, `ac_stim`, exact AC values for `ddt`/`idt`/`idtmod`, and the `transition` ramp — see `examples/opargs_examples/`
- Regression-checked: all 57 example verify suites ALL PASS; crate tests pass; the VA_TEST corpus compiles 92/92
- Details: [Enhancement-61.md](enhancements_doc/Enhancement-61.md)

---

## Enhancement 62: ngspice analysis coverage — `.dc @inst[param]` sweeps + `.disto` warning

*July 2026* — An **analysis-coverage probe** of OSDI (Verilog-A) devices across every ngspice analysis beyond op/dc/ac/tran/noise, comparing against built-in twins. Already exact and now pinned: **`.tf`** (transfer function 0.75, output impedance 750 Ω, input impedance 2 kΩ on an OSDI divider), **`.pz`** (the OSDI RC pole at −1/(RC) is bit-identical to the built-in RC; the *nonlinear* pz failure hits built-in diode circuits identically — an ngspice quirk, not an OSDI gap), **`.sens`** DC (dV/dR matches the analytic divider derivatives) and AC (dV/dacmag = H at the pole frequency), **`.dc temp`** sweeps (`$temperature` per point, °C→K exact), and the **`alter`/`altermod`/instance-line/`print @n1[r]`** machinery via `(* type="instance" *)`. **Two real gaps found and fixed in ngspice: (1) `.dc @inst[param]` sweeps** — the sweep code hardcoded Vsource/Isource/Resistor/temp, so sweeping any device parameter was a fatal error; a new generic sweep type resolves `@inst[param]` through the device's own `DEVparam`/`DEVask` tables and refreshes per point via `DEVtemperature` (for OSDI exactly the `alter` path), working for OSDI instance-kind parameters, built-in devices, and **nested** with other sweep variables, with the original value restored afterwards. **(2) `.disto` silently reported zero distortion for OSDI devices** — the distortion kernel needs per-device Taylor coefficients the OSDI ABI cannot provide (first derivatives only), and ngspice skipped such devices without a word: an OSDI diode measured exactly 0.0 where the identical built-in diode measured 1.8e-6; ngspice now prints a prominent warning naming each affected OSDI device type. The example folder doubles as a **tutorial**: nine standalone commented decks (one per analysis, each stating its expected numbers), a walk-through README, and `plot_analyses.py` rendering the sweep results to committed PNGs (parameter sweep and temp sweep vs analytic 1/R, the nested-sweep I = V/r curve family, and an RC Bode plot with the `.pz` pole and `.sens ac` point marked).

- Verified with 19 end-to-end checks (exact `.tf`/`.pz`/`.sens`/temp values, the new sweeps incl. nesting and built-in parity, alter precedence, the disto warning) — see `examples/analyses_examples/`
- Regression-checked: all 58 example verify suites ALL PASS with the rebuilt ngspice; no compiler change
- Details: [Enhancement-62.md](enhancements_doc/Enhancement-62.md)

---

## Enhancement 63: RF analyses — S-parameters, transient noise, PSS + `span.c` NaN fix

*July 2026* — Round 2 of the analysis-coverage work: the RF-flavored ngspice analyses probed with OSDI devices against built-in twins. **`.sp` S-parameters are exact**: a series OSDI resistor gives the textbook S11 = S21 = 0.5, a frequency-dependent OSDI RC two-port is *bit-identical* to the built-in twin over three decades, and the analysis is **fully N-port** (a 3-port junction reproduces Sii = −1/3 / Sij = +2/3; 3-/4-port OSDI resistor stars give the analytic 1/3 and 1/4 exactly — only the `donoise` NF/SOpt block, an inherently two-port concept, requires exactly 2 ports). **`.sp donoise` exposed a stock ngspice defect via parity testing**: the OSDI noisy resistor gives NF = 10·log₁₀(1 + R/Z0) = 4.7712 dB exactly, but the identical built-in circuit returned **NaN** — `span.c`'s noise-parameter extraction takes `sqrt(Ycor² + Gu/Rn)` where the uncorrelated noise conductance `Gu` is analytically *zero* for fully-correlated single-source topologies, and floating-point rounding could land the argument at −1e-18. Clamped to the physical range: the built-in now reads 10·log₁₀(3) to eight digits and multi-source circuits are unchanged. **Transient noise** (`TRNOISE` sources) propagates through OSDI devices correctly — device-*internal* noise doesn't enter `.tran` for built-ins either (parity, documented). **PSS** (`.pss`, experimental, compile-time `--enable-pss`): OSDI devices are **full citizens** — the linear OSDI RC converges to the analytic fundamental 1/√(1+(ωRC)²) matching the built-in twin to 7 digits, and a mildly-driven OSDI diode converges in 2 shooting iterations (the built-in twin wanders longer); strongly nonlinear rectifiers defeat the shooting method for built-ins and OSDI alike. The verify suite auto-detects PSS support and SKIPs cleanly on binaries built without it (the README shows the build recipe).

- Verified with 15 end-to-end checks (12 + 3 PSS) — see `examples/rfanalyses_examples/`
- Regression-checked: all 59 example verify suites ALL PASS with the rebuilt ngspice; no compiler change
- Details: [Enhancement-63.md](enhancements_doc/Enhancement-63.md)

---

## Enhancement 64: Touchstone export — auto-`Rbase`, N-port `wrsnp`, 1-port `.sp`

*July 2026* — Made S-parameter results exportable to industry-standard **Touchstone v1** files, following directly from Enhancement-63's findings. Three fixes, all ngspice-side. **(1) `wrs2p` was unusable out of the box**: it demanded a vector named `Rbase` (the reference resistance for the `# Hz S RI R <Rbase>` option line) that no code ever created — every call failed with `No Rbase vector given` unless the user knew the undocumented `let Rbase = 50` incantation, and a wrong value silently mislabeled the file. The `.sp` analysis now **publishes `Rbase` into its plot** (read from port 1's `z0`), so the writers work with no manual step; a user-defined `let Rbase` still overrides, and the reader handles the plot's complex data robustly. **(2) New `wrsnp` command** (with `wrs2p` dispatching to the same handler): Touchstone v1 for **any port count** — N ≥ 3 in the spec's row-major layout with at most four complex pairs per data line and each matrix row starting on a new line; a 1-port is one pair per line; the classic 2-port `S11 S21 S12 S22` column order is preserved, and `wrsnp` on a 2-port produces a byte-identical file to `wrs2p`. **(3) 1-port `.sp` analyses now run at all**: the "we need at least two ports" hard error was over-strict (a 1-port is a plain reflection measurement and the matrix machinery is N-general) — and it was hiding a real crash: the complex-matrix `cadjoint()` had no 1×1 base case, so its cofactor loop allocated negative-sized minors and ngspice died with `malloc: can't allocate -8 bytes`. The adjugate of `[a]` is `[1]`, making `cinverse` of a 1×1 equal `1/a`; a 100 Ω load on a 50 Ω port now writes a proper `.s1p` with S11 = 1/3 exactly.

- Verified with 11 end-to-end checks — auto-`Rbase` header + file-vs-plot value identity, the `wrs2p`/`wrsnp` byte-identity, `let Rbase` override, 1-port/.s1p (crash-fix pin), `.s3p` row-major layout with exact star values, `.s5p` wrap-at-4-pairs — see `examples/touchstone_examples/`
- Regression-checked: all 60 example verify suites ALL PASS with the rebuilt ngspice; no compiler change
- Details: [Enhancement-64.md](enhancements_doc/Enhancement-64.md)

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
