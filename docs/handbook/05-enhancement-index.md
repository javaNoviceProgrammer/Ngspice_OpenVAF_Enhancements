# 5 · Enhancement index

One line per enhancement, in order. **Doc** links the detailed write-up in
`enhancements_doc/`; **Examples** links the folder whose verify script pins
the behavior (the result plots live in the example folders). This same
table is the enhancement index of the top-level
[README](../../README.md).

| # | What it delivered | Doc | Examples |
|---|---|---|---|
| 1 | `absdelay()` transport delay via synthetic-node DAE | [doc](../../enhancements_doc/Enhancement-1.md) | [absdelay](../../examples/absdelay_examples/) |
| 2 | Indirect branch assignment (`V(out): V(x)==0` — ideal op-amps) | [doc](../../enhancements_doc/Enhancement-2.md) | [indirect_assignment](../../examples/indirect_assignment_examples/) |
| 3 | Vectored (bus) nets and ports with bit-select access | [doc](../../enhancements_doc/Enhancement-3.md) | [bus](../../examples/bus_examples/) |
| 4 | `laplace_*` filter operators + array-variable declarations | [doc](../../enhancements_doc/Enhancement-4.md) | [laplace](../../examples/laplace_examples/), [bessel_filter](../../examples/bessel_filter_examples/) |
| 5 | Module instantiation (hierarchy via compile-time flattening) | [doc](../../enhancements_doc/Enhancement-5.md) | [instantiation](../../examples/instantiation_examples/) |
| 6 | Directives, `<<<`/`>>>`, `slew`/`transition`, `zi_*`, `last_crossing` | [doc](../../enhancements_doc/Enhancement-6.md) | [directive](../../examples/directive_examples/), [shift](../../examples/shift_examples/), [slew](../../examples/slew_examples/), [zi](../../examples/zi_examples/), [last_crossing](../../examples/last_crossing_examples/) |
| 7 | `@(initial_step)` gating + genuine variable persistence | [doc](../../enhancements_doc/Enhancement-7.md) | [initial_step](../../examples/initial_step_examples/), [variable_persistence](../../examples/variable_persistence_examples/) |
| 8 | `generate for`/`genvar` + `cross()`/`above()`/`timer()` events | [doc](../../enhancements_doc/Enhancement-8.md) | [generate](../../examples/generate_examples/), [cross](../../examples/cross_examples/), [timer](../../examples/timer_examples/) |
| 9 | `noise_table(_log)`, `localparam`, `ground`, strings, `repeat`/`disable` | [doc](../../enhancements_doc/Enhancement-9.md) | [noise](../../examples/noise_examples/), [repeat](../../examples/repeat_examples/), [disable](../../examples/disable_examples/) |
| 10 | `$random` + all `$dist_*`/`$rdist_*` distributions | [doc](../../enhancements_doc/Enhancement-10.md) | [rng](../../examples/rng_examples/) |
| 11 | File I/O (`$fopen`…) + string formatting/parsing (`$sscanf`…) | [doc](../../enhancements_doc/Enhancement-11.md) | [fileio](../../examples/fileio_examples/), [stringio](../../examples/stringio_examples/) |
| 12 | `$simprobe`/aliases/plusargs as LRM fallbacks (last unsupported builtins) | [doc](../../enhancements_doc/Enhancement-12.md) | [alias](../../examples/alias_examples/) |
| 13 | `limexp()` kept stateless (documented decision); `ddx()` demo | [doc](../../enhancements_doc/Enhancement-13.md) | [ddx](../../examples/ddx_examples/) |
| 14 | Array literals/aggregates, array parameters, dynamic indexing | [doc](../../enhancements_doc/Enhancement-14.md) | [array](../../examples/array_examples/) |
| 15 | Multi-dimensional arrays (N-D, per-element param override) | [doc](../../enhancements_doc/Enhancement-15.md) | [mdarray](../../examples/mdarray_examples/) |
| 16 | `$table_model` 1-D lookup tables (differentiable) | [doc](../../enhancements_doc/Enhancement-16.md) | [table_model](../../examples/table_model_examples/) |
| 17 | 2-D/3-D `$table_model` (multilinear, exact Jacobian partials) | [doc](../../enhancements_doc/Enhancement-17.md) | [mdtable](../../examples/mdtable_examples/) |
| 18 | `real x[0:n]` declaration order + arrays in analog functions | [doc](../../enhancements_doc/Enhancement-18.md) | [funcarray](../../examples/funcarray_examples/) |
| 19 | `do … while` loops | [doc](../../enhancements_doc/Enhancement-19.md) | [dowhile](../../examples/dowhile_examples/) |
| 20 | Array `output`/`inout` function arguments | [doc](../../enhancements_doc/Enhancement-20.md) | [arrayout](../../examples/arrayout_examples/) |
| 21 | `paramset` blocks | [doc](../../enhancements_doc/Enhancement-21.md) | [paramset](../../examples/paramset_examples/) |
| 22 | Natural cubic-spline `$table_model` (control `"3"`) | [doc](../../enhancements_doc/Enhancement-22.md) | [cubic_table](../../examples/cubic_table_examples/) |
| 23 | Array return values from analog functions | [doc](../../enhancements_doc/Enhancement-23.md) | [arrayret](../../examples/arrayret_examples/) |
| 24 | `$discontinuity(n)` next-step clamp | [doc](../../enhancements_doc/Enhancement-24.md) | [discontinuity](../../examples/discontinuity_examples/) |
| 25 | `$simparam$str` (+ ngspice `analysis_name`/`simulator` params) | [doc](../../enhancements_doc/Enhancement-25.md) | [simparamstr](../../examples/simparamstr_examples/) |
| 26 | `ac_stim` crash fix + correct large-signal baseline | [doc](../../enhancements_doc/Enhancement-26.md) | [acstim](../../examples/acstim_examples/) |
| 27 | `idtmod()` modulo-integrator fix | [doc](../../enhancements_doc/Enhancement-27.md) | [idtmod](../../examples/idtmod_examples/) |
| 28 | `idt()` initial condition survives into transient | [doc](../../enhancements_doc/Enhancement-28.md) | [idtic](../../examples/idtic_examples/) |
| 29 | Port-flow probes `I(<port>)` | [doc](../../enhancements_doc/Enhancement-29.md) | [portflow](../../examples/portflow_examples/) |
| 30 | Variadic `analysis("ac","tran",…)` | [doc](../../enhancements_doc/Enhancement-30.md) | [analysis](../../examples/analysis_examples/) |
| 31 | Complex poles/zeros in `laplace_*`/`zi_*` root forms | [doc](../../enhancements_doc/Enhancement-31.md) | [complexpole](../../examples/complexpole_examples/) |
| 32 | Integer persistent/event-state variables (compiler crash fix) | [doc](../../enhancements_doc/Enhancement-32.md) | [intstate](../../examples/intstate_examples/) |
| 33 | Array `case` + array-literal function arguments | [doc](../../enhancements_doc/Enhancement-33.md) | [arraycase](../../examples/arraycase_examples/) |
| 34 | `{…}` concatenation and `{n{…}}` replication operators | [doc](../../enhancements_doc/Enhancement-34.md) | [concat](../../examples/concat_examples/) |
| 35 | Lexer hang on `//` comment at EOF | [doc](../../enhancements_doc/Enhancement-35.md) | [comment](../../examples/comment_examples/) |
| 36 | Probe-only branches (ideal ammeters, flow-only disciplines) | [doc](../../enhancements_doc/Enhancement-36.md) | [signalflow](../../examples/signalflow_examples/) |
| 37 | Operator-correctness audit (`~`, const-folded `>>`, string `?:`) | [doc](../../enhancements_doc/Enhancement-37.md) | [operator](../../examples/operator_examples/) |
| 38 | Precedence audit vs LRM Table 4-2 (`%` level fix) | [doc](../../enhancements_doc/Enhancement-38.md) | [precedence](../../examples/precedence_examples/) |
| 39 | Derived natures (`nature X : Parent`, `: electrical.flow`) | [doc](../../enhancements_doc/Enhancement-39.md) | [derivednature](../../examples/derivednature_examples/) |
| 40 | `$table_model` in any number of dimensions | [doc](../../enhancements_doc/Enhancement-40.md) | [ndtable](../../examples/ndtable_examples/) |
| 41 | Implicit nets in instance connections | [doc](../../enhancements_doc/Enhancement-41.md) | [implicitnet](../../examples/implicitnet_examples/) |
| 42 | Correlated (same-named) noise sources sum coherently | [doc](../../enhancements_doc/Enhancement-42.md) | [noisecorr](../../examples/noisecorr_examples/) |
| 43 | Variable declaration initializers, completed (N-D arrays) | [doc](../../enhancements_doc/Enhancement-43.md) | [varinit](../../examples/varinit_examples/) |
| 44 | Paramset hidden system parameters (`.$mfactor`) | [doc](../../enhancements_doc/Enhancement-44.md) | [paramsethsp](../../examples/paramsethsp_examples/) |
| 45 | Net initializers (nodesets) + nature-attribute access | [doc](../../enhancements_doc/Enhancement-45.md) | [netinit](../../examples/netinit_examples/) |
| 46 | Escaped identifiers + based integer literals | [doc](../../enhancements_doc/Enhancement-46.md) | [escid](../../examples/escid_examples/) |
| 47 | `` `default_transition `` + `transition()` fixes | [doc](../../enhancements_doc/Enhancement-47.md) | [defaulttransition](../../examples/defaulttransition_examples/) |
| 48 | String-literal escape sequences (single-pass unescaper) | [doc](../../enhancements_doc/Enhancement-48.md) | [stresc](../../examples/stresc_examples/) |
| 49 | Hierarchical names + `$root` | [doc](../../enhancements_doc/Enhancement-49.md) | [hiername](../../examples/hiername_examples/) |
| 50 | Domain-binding validation (LRM 3.6.2.2) | [doc](../../enhancements_doc/Enhancement-50.md) | [domainbind](../../examples/domainbind_examples/) |
| 51 | Full `ac_stim` AC-RHS injection (OSDI ABI 0.6) | [doc](../../enhancements_doc/Enhancement-51.md) | [acstim](../../examples/acstim_examples/) |
| 52 | `idt()` assert/reset forms (relaxation oscillators) | [doc](../../enhancements_doc/Enhancement-52.md) | [idtassert](../../examples/idtassert_examples/) |
| 53 | `@(final_step)` + analysis-phase lists on step events | [doc](../../enhancements_doc/Enhancement-53.md) | [finalstep](../../examples/finalstep_examples/) |
| 54 | Correct, node-free noise factors (OSDI ABI 0.7) | [doc](../../enhancements_doc/Enhancement-54.md) | [noisejw](../../examples/noisejw_examples/) |
| 55 | `$finish`/`$stop`/`$fatal` honored + `$discontinuity` step rejection | [doc](../../enhancements_doc/Enhancement-55.md) | [simctrl](../../examples/simctrl_examples/) |
| 56 | Corpus sweep: CMC default-range idiom + noise crash fix | [doc](../../enhancements_doc/Enhancement-56.md) | [paramrange](../../examples/paramrange_examples/) |
| 57 | Physics-accuracy validation suite | [doc](../../enhancements_doc/Enhancement-57.md) | [physcheck](../../examples/physcheck_examples/) |
| 58 | `defparam` hierarchical override | [doc](../../enhancements_doc/Enhancement-58.md) | [defparam](../../examples/defparam_examples/) |
| 59 | LRM corners: event OR lists, `$realtime`, port concat, recursion diags | [doc](../../enhancements_doc/Enhancement-59.md) | [lrmcorner](../../examples/lrmcorner_examples/) |
| 60 | Multiple analog blocks — validation | [doc](../../enhancements_doc/Enhancement-60.md) | [multianalog](../../examples/multianalog_examples/) |
| 61 | Operator-argument audit — `slew` sign fix, `$limit`, `$bound_step` | [doc](../../enhancements_doc/Enhancement-61.md) | [opargs](../../examples/opargs_examples/) |
| 62 | `.dc @inst[param]` sweeps + `.disto` warning + analyses tutorial | [doc](../../enhancements_doc/Enhancement-62.md) | [analyses](../../examples/analyses_examples/) |
| 63 | RF analyses: N-port `.sp`, trnoise, PSS + `span.c` NaN fix | [doc](../../enhancements_doc/Enhancement-63.md) | [rfanalyses](../../examples/rfanalyses_examples/) |
| 64 | Touchstone export: auto-`Rbase`, N-port `wrsnp`, 1-port `.sp` | [doc](../../enhancements_doc/Enhancement-64.md) | [touchstone](../../examples/touchstone_examples/) |
| 65 | Preprocessor audit — macro-recursion guard | [doc](../../enhancements_doc/Enhancement-65.md) | [preproc](../../examples/preproc_examples/) |
| 66 | Monte Carlo with OSDI — validation (+ zero-warning build chore) | [doc](../../enhancements_doc/Enhancement-66.md) | [montecarlo](../../examples/montecarlo_examples/) |
| 67 | Generate audit — genvar fix, nesting, `generate if`/`case` | [doc](../../enhancements_doc/Enhancement-67.md) | [generate](../../examples/generate_examples/) |
| 68 | The compiler's own integration test suite, enabled (28 models) | [doc](../../enhancements_doc/Enhancement-68.md) | — |
| 69 | Operating-point variables end-to-end — validation | [doc](../../enhancements_doc/Enhancement-69.md) | [opvar](../../examples/opvar_examples/) |
| 70 | Behavioral-loop audit — precise loop diagnostics | [doc](../../enhancements_doc/Enhancement-70.md) | [analogloop](../../examples/analogloop_examples/) |
| 71 | Display-task audit — full format surface + `%b` segfault fix | [doc](../../enhancements_doc/Enhancement-71.md) | [display](../../examples/display_examples/) |
| 72 | Touchstone round 2 — MA/DB, units, Y/Z, `rdsnp` reader | [doc](../../enhancements_doc/Enhancement-72.md) | [touchstone](../../examples/touchstone_examples/) |
| 73 | This handbook, its PDF edition, and the README index | [doc](../../enhancements_doc/Enhancement-73.md) | [docs/handbook](README.md) |
| 74 | Performance benchmark — OSDI-vs-built-in twins at parity (RC ladder 0.99×), flagship compile times | [doc](../../enhancements_doc/Enhancement-74.md) | [benchmark](../../examples/benchmark_examples/) |
| 75 | Dynamic physics validation — reactive paths cross-checked (Cgg AC ≡ transient, charge conservation, tran-sine ≡ .ac) | [doc](../../enhancements_doc/Enhancement-75.md) | [dynphys](../../examples/dynphys_examples/) |
| 76 | Multi-module `.osdi` libraries — audit + registration fixes (duplicate warning, double-load skip, stock `.model` segfault) | [doc](../../enhancements_doc/Enhancement-76.md) | [multimod](../../examples/multimod_examples/) |
| 77 | ngspice zero-warning build (33 → 0) — SDK macro clashes, `%Id`→`%zu` (readable plot-memory errors), codemodel `dynamic_lookup` | [doc](../../enhancements_doc/Enhancement-77.md) | — |
| 78 | `casex`/`casez` — don't-care digits in item literals as comparison masks (priority-encoder idiom) | [doc](../../enhancements_doc/Enhancement-78.md) | [casexz](../../examples/casexz_examples/) |
