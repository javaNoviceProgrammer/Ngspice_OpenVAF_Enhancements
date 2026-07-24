# Ngspice + OpenVAF Enhancements
**Owner: Dr. Meisam Bahadori**

Using Claude Code AI to enhance the ngspice and openvaf frameworks.

[![Build binaries](https://github.com/javaNoviceProgrammer/Ngspice_OpenVAF_Enhancements/actions/workflows/build-binaries.yml/badge.svg)](https://github.com/javaNoviceProgrammer/Ngspice_OpenVAF_Enhancements/actions/workflows/build-binaries.yml)

Main goals:
- turn ngspice into the most powerful spice simulator ([ngspice vs. Spectre gap analysis](docs/internals/ngspice_internals/ngspice_gaps.md))
- turn openvaf-r into the most powerful verilog-a compiler ([Verilog-A LRM compliance report](docs/compliance/OpenVAF_Verilog-A_LRM_Compliance.md))


## Precursors

Original OpenVAF git repository by Pascal Kuthe:

https://github.com/pascalkuthe/OpenVAF

OpenVAF-Reloaded git repository by Árpád Bűrmen:

https://github.com/arpadbuermen/OpenVAF

Ngspice Homepage:

https://ngspice.sourceforge.io/

---

## The Enhancements

Two hundred and thirty enhancements so far — language features, correctness fixes, systematic audits, and simulator-side workflow tooling, each verified end-to-end by a committed example suite and released with a detailed write-up.

**🗂️ Browse them all in the [live feature catalog](https://javanoviceprogrammer.github.io/Ngspice_OpenVAF_Enhancements/)** — every enhancement grouped into 19 feature areas across the compiler and the simulator, searchable, with each entry linking to its write-up.

**📖 Start with the [User Handbook](docs/handbook/README.md)**, which organizes everything by topic: [getting started](docs/handbook/01-getting-started.md), the [Verilog-A feature matrix](docs/handbook/02-verilog-a-language.md), [ngspice workflows](docs/handbook/03-ngspice-workflows.md), and the [limitations & gotchas](docs/handbook/04-limitations-and-gotchas.md). The whole handbook plus the complete text of every enhancement write-up is also one linked PDF: [docs/Ngspice-OpenVAF-Handbook.pdf](docs/Ngspice-OpenVAF-Handbook.pdf).

**🔧 Want to understand the compiler itself?** [OpenVAF Compiler Internals](docs/internals/openvaf_internals/OpenVAF_compiler_internals.md) ([PDF](docs/internals/openvaf_internals/OpenVAF_compiler_internals.pdf)) is a ground-up, no-prior-knowledge walkthrough of how `openvaf-r` turns a Verilog-A model into a `.osdi` library — every stage of the pipeline (lexing → HIR → MIR → automatic differentiation → LLVM → OSDI), with real dumped IR traced end-to-end on a worked example.

**⚙️ Want to understand the simulator itself?** [ngspice Simulator Internals](docs/internals/ngspice_internals/ngspice_simulator_internals.md) ([PDF](docs/internals/ngspice_internals/ngspice_simulator_internals.pdf)) is the companion guide — a ground-up walkthrough of how `ngspice-46` turns a netlist into a running circuit: the shell/engine split, the netlist parser, the `CKTcircuit`, the `SPICEdev` device interface, the sparse-matrix Newton loop, the analyses, and — crucially — how OpenVAF `.osdi` models plug in as first-class devices, traced end-to-end on a worked RC example.

**🛡️ How robust is the compiler?** [OpenVAF Robustness Campaign](docs/internals/openvaf_internals/OpenVAF_robustness_report.md) ([PDF](docs/internals/openvaf_internals/OpenVAF_robustness_report.pdf)) reports a deep robustness audit of `openvaf-r` — the full production-model corpus, ~50 adversarial inputs, and 4,000 mutation-fuzzing iterations — and the four crash/hang paths it found and fixed (Enhancement-147/-148).

**⏱️ How fast does it compile?** [OpenVAF Compile-Time Analysis](docs/internals/openvaf_internals/OpenVAF_compile_time_analysis.md) ([PDF](docs/internals/openvaf_internals/OpenVAF_compile_time_analysis.pdf)) profiles where `openvaf-r`'s compilation time goes (≈70 % LLVM optimizing one `eval` function), why it's bound to a single core despite already parallelizing, and the compile-vs-simulation-speed trade-off of the `-O` level.

The index: **Doc** links each enhancement's detailed write-up, **Examples** links the folder whose verify script pins the behavior.

<details>
<summary><b>📖 Show the full enhancement table</b> — 320 rows, click to expand</summary>

| # | What it delivered | Tool | Doc | Examples |
|---|---|---|---|---|
| 1 | `absdelay()` transport delay via synthetic-node DAE | openvaf&#8209;r | [doc](enhancements_doc/Enhancement-1.md) | [absdelay](examples/absdelay_examples/) |
| 2 | Indirect branch assignment (`V(out): V(x)==0` — ideal op-amps) | openvaf&#8209;r | [doc](enhancements_doc/Enhancement-2.md) | [indirect_assignment](examples/indirect_assignment_examples/) |
| 3 | Vectored (bus) nets and ports with bit-select access | openvaf&#8209;r | [doc](enhancements_doc/Enhancement-3.md) | [bus](examples/bus_examples/) |
| 4 | `laplace_*` filter operators + array-variable declarations | openvaf&#8209;r | [doc](enhancements_doc/Enhancement-4.md) | [laplace](examples/laplace_examples/), [bessel_filter](examples/bessel_filter_examples/) |
| 5 | Module instantiation (hierarchy via compile-time flattening) | openvaf&#8209;r | [doc](enhancements_doc/Enhancement-5.md) | [instantiation](examples/instantiation_examples/) |
| 6 | Directives, `<<<`/`>>>`, `slew`/`transition`, `zi_*`, `last_crossing` | openvaf&#8209;r | [doc](enhancements_doc/Enhancement-6.md) | [directive](examples/directive_examples/), [shift](examples/shift_examples/), [slew](examples/slew_examples/), [zi](examples/zi_examples/), [last_crossing](examples/last_crossing_examples/) |
| 7 | `@(initial_step)` gating + genuine variable persistence | openvaf&#8209;r | [doc](enhancements_doc/Enhancement-7.md) | [initial_step](examples/initial_step_examples/), [variable_persistence](examples/variable_persistence_examples/) |
| 8 | `generate for`/`genvar` + `cross()`/`above()`/`timer()` events | openvaf&#8209;r | [doc](enhancements_doc/Enhancement-8.md) | [generate](examples/generate_examples/), [cross](examples/cross_examples/), [timer](examples/timer_examples/) |
| 9 | `noise_table(_log)`, `localparam`, `ground`, strings, `repeat`/`disable` | openvaf&#8209;r | [doc](enhancements_doc/Enhancement-9.md) | [noise](examples/noise_examples/), [repeat](examples/repeat_examples/), [disable](examples/disable_examples/) |
| 10 | `$random` + all `$dist_*`/`$rdist_*` distributions | openvaf&#8209;r | [doc](enhancements_doc/Enhancement-10.md) | [rng](examples/rng_examples/) |
| 11 | File I/O (`$fopen`…) + string formatting/parsing (`$sscanf`…) | openvaf&#8209;r | [doc](enhancements_doc/Enhancement-11.md) | [fileio](examples/fileio_examples/), [stringio](examples/stringio_examples/) |
| 12 | `$simprobe` + alias/plusargs builtins | openvaf&#8209;r | [doc](enhancements_doc/Enhancement-12.md) | [alias](examples/alias_examples/) |
| 13 | `limexp()` kept stateless (documented decision); `ddx()` demo | openvaf&#8209;r | [doc](enhancements_doc/Enhancement-13.md) | [ddx](examples/ddx_examples/) |
| 14 | Array literals/aggregates, array parameters, dynamic indexing | openvaf&#8209;r | [doc](enhancements_doc/Enhancement-14.md) | [array](examples/array_examples/) |
| 15 | Multi-dimensional arrays (N-D, per-element param override) | openvaf&#8209;r | [doc](enhancements_doc/Enhancement-15.md) | [mdarray](examples/mdarray_examples/) |
| 16 | `$table_model` 1-D lookup tables (differentiable) | openvaf&#8209;r | [doc](enhancements_doc/Enhancement-16.md) | [table_model](examples/table_model_examples/) |
| 17 | 2-D/3-D `$table_model` (multilinear, exact Jacobian partials) | openvaf&#8209;r | [doc](enhancements_doc/Enhancement-17.md) | [mdtable](examples/mdtable_examples/) |
| 18 | `real x[0:n]` declaration order + arrays in analog functions | openvaf&#8209;r | [doc](enhancements_doc/Enhancement-18.md) | [funcarray](examples/funcarray_examples/) |
| 19 | `do … while` loops | openvaf&#8209;r | [doc](enhancements_doc/Enhancement-19.md) | [dowhile](examples/dowhile_examples/) |
| 20 | Array `output`/`inout` function arguments | openvaf&#8209;r | [doc](enhancements_doc/Enhancement-20.md) | [arrayout](examples/arrayout_examples/) |
| 21 | `paramset` blocks | openvaf&#8209;r | [doc](enhancements_doc/Enhancement-21.md) | [paramset](examples/paramset_examples/) |
| 22 | Natural cubic-spline `$table_model` (control `"3"`) | openvaf&#8209;r | [doc](enhancements_doc/Enhancement-22.md) | [cubic_table](examples/cubic_table_examples/) |
| 23 | Array return values from analog functions | openvaf&#8209;r | [doc](enhancements_doc/Enhancement-23.md) | [arrayret](examples/arrayret_examples/) |
| 24 | `$discontinuity(n)` next-step clamp | openvaf&#8209;r | [doc](enhancements_doc/Enhancement-24.md) | [discontinuity](examples/discontinuity_examples/) |
| 25 | `$simparam$str` (+ ngspice `analysis_name`/`simulator` params) | openvaf&#8209;r | [doc](enhancements_doc/Enhancement-25.md) | [simparamstr](examples/simparamstr_examples/) |
| 26 | `ac_stim` crash fix + correct large-signal baseline | openvaf&#8209;r | [doc](enhancements_doc/Enhancement-26.md) | [acstim](examples/acstim_examples/) |
| 27 | `idtmod()` modulo-integrator fix | openvaf&#8209;r | [doc](enhancements_doc/Enhancement-27.md) | [idtmod](examples/idtmod_examples/) |
| 28 | `idt()` initial condition survives into transient | openvaf&#8209;r | [doc](enhancements_doc/Enhancement-28.md) | [idtic](examples/idtic_examples/) |
| 29 | Port-flow probes `I(<port>)` | openvaf&#8209;r | [doc](enhancements_doc/Enhancement-29.md) | [portflow](examples/portflow_examples/) |
| 30 | Variadic `analysis("ac","tran",…)` | openvaf&#8209;r | [doc](enhancements_doc/Enhancement-30.md) | [analysis](examples/analysis_examples/) |
| 31 | Complex poles/zeros in `laplace_*`/`zi_*` root forms | openvaf&#8209;r | [doc](enhancements_doc/Enhancement-31.md) | [complexpole](examples/complexpole_examples/) |
| 32 | Integer persistent/event-state variables (compiler crash fix) | openvaf&#8209;r | [doc](enhancements_doc/Enhancement-32.md) | [intstate](examples/intstate_examples/) |
| 33 | Array `case` + array-literal function arguments | openvaf&#8209;r | [doc](enhancements_doc/Enhancement-33.md) | [arraycase](examples/arraycase_examples/) |
| 34 | `{…}` concatenation and `{n{…}}` replication operators | openvaf&#8209;r | [doc](enhancements_doc/Enhancement-34.md) | [concat](examples/concat_examples/) |
| 35 | Lexer hang on `//` comment at EOF | openvaf&#8209;r | [doc](enhancements_doc/Enhancement-35.md) | [comment](examples/comment_examples/) |
| 36 | Probe-only branches (ideal ammeters, flow-only disciplines) | openvaf&#8209;r | [doc](enhancements_doc/Enhancement-36.md) | [signalflow](examples/signalflow_examples/) |
| 37 | Operator-correctness audit (`~`, const-folded `>>`, string `?:`) | openvaf&#8209;r | [doc](enhancements_doc/Enhancement-37.md) | [operator](examples/operator_examples/) |
| 38 | Precedence audit vs LRM Table 4-2 (`%` level fix) | openvaf&#8209;r | [doc](enhancements_doc/Enhancement-38.md) | [precedence](examples/precedence_examples/) |
| 39 | Derived natures (`nature X : Parent`, `: electrical.flow`) | openvaf&#8209;r | [doc](enhancements_doc/Enhancement-39.md) | [derivednature](examples/derivednature_examples/) |
| 40 | `$table_model` in any number of dimensions | openvaf&#8209;r | [doc](enhancements_doc/Enhancement-40.md) | [ndtable](examples/ndtable_examples/) |
| 41 | Implicit nets in instance connections | openvaf&#8209;r | [doc](enhancements_doc/Enhancement-41.md) | [implicitnet](examples/implicitnet_examples/) |
| 42 | Correlated (same-named) noise sources sum coherently | openvaf&#8209;r | [doc](enhancements_doc/Enhancement-42.md) | [noisecorr](examples/noisecorr_examples/) |
| 43 | Variable declaration initializers, completed (N-D arrays) | openvaf&#8209;r | [doc](enhancements_doc/Enhancement-43.md) | [varinit](examples/varinit_examples/) |
| 44 | Paramset hidden system parameters (`.$mfactor`) | openvaf&#8209;r | [doc](enhancements_doc/Enhancement-44.md) | [paramsethsp](examples/paramsethsp_examples/) |
| 45 | Net initializers (nodesets) + nature-attribute access | openvaf&#8209;r | [doc](enhancements_doc/Enhancement-45.md) | [netinit](examples/netinit_examples/) |
| 46 | Escaped identifiers + based integer literals | openvaf&#8209;r | [doc](enhancements_doc/Enhancement-46.md) | [escid](examples/escid_examples/) |
| 47 | `` `default_transition `` + `transition()` fixes | openvaf&#8209;r | [doc](enhancements_doc/Enhancement-47.md) | [defaulttransition](examples/defaulttransition_examples/) |
| 48 | String-literal escape sequences (single-pass unescaper) | openvaf&#8209;r | [doc](enhancements_doc/Enhancement-48.md) | [stresc](examples/stresc_examples/) |
| 49 | Hierarchical names + `$root` | openvaf&#8209;r | [doc](enhancements_doc/Enhancement-49.md) | [hiername](examples/hiername_examples/) |
| 50 | Domain-binding validation (LRM 3.6.2.2) | openvaf&#8209;r | [doc](enhancements_doc/Enhancement-50.md) | [domainbind](examples/domainbind_examples/) |
| 51 | Full `ac_stim` AC-RHS injection (OSDI ABI 0.6) | both | [doc](enhancements_doc/Enhancement-51.md) | [acstim](examples/acstim_examples/) |
| 52 | `idt()` assert/reset forms (relaxation oscillators) | openvaf&#8209;r | [doc](enhancements_doc/Enhancement-52.md) | [idtassert](examples/idtassert_examples/) |
| 53 | `@(final_step)` + analysis-phase lists on step events | openvaf&#8209;r | [doc](enhancements_doc/Enhancement-53.md) | [finalstep](examples/finalstep_examples/) |
| 54 | Correct, node-free noise factors (OSDI ABI 0.7) | openvaf&#8209;r | [doc](enhancements_doc/Enhancement-54.md) | [noisejw](examples/noisejw_examples/) |
| 55 | `$finish`/`$stop`/`$fatal` honored + `$discontinuity` step rejection | openvaf&#8209;r | [doc](enhancements_doc/Enhancement-55.md) | [simctrl](examples/simctrl_examples/) |
| 56 | Corpus sweep: CMC default-range idiom + noise crash fix | openvaf&#8209;r | [doc](enhancements_doc/Enhancement-56.md) | [paramrange](examples/paramrange_examples/) |
| 57 | Physics-accuracy validation suite | openvaf&#8209;r | [doc](enhancements_doc/Enhancement-57.md) | [physcheck](examples/physcheck_examples/) |
| 58 | `defparam` hierarchical override | openvaf&#8209;r | [doc](enhancements_doc/Enhancement-58.md) | [defparam](examples/defparam_examples/) |
| 59 | LRM corners: event OR lists, `$realtime`, port concat, recursion diags | openvaf&#8209;r | [doc](enhancements_doc/Enhancement-59.md) | [lrmcorner](examples/lrmcorner_examples/) |
| 60 | Multiple analog blocks — validation | openvaf&#8209;r | [doc](enhancements_doc/Enhancement-60.md) | [multianalog](examples/multianalog_examples/) |
| 61 | Operator-argument audit — `slew` sign fix, `$limit`, `$bound_step` | openvaf&#8209;r | [doc](enhancements_doc/Enhancement-61.md) | [opargs](examples/opargs_examples/) |
| 62 | `.dc @inst[param]` sweeps + `.disto` warning + analyses tutorial | ngspice | [doc](enhancements_doc/Enhancement-62.md) | [analyses](examples/analyses_examples/) |
| 63 | RF analyses: N-port `.sp`, trnoise, PSS + `span.c` NaN fix | ngspice | [doc](enhancements_doc/Enhancement-63.md) | [rfanalyses](examples/rfanalyses_examples/) |
| 64 | Touchstone export: auto-`Rbase`, N-port `wrsnp`, 1-port `.sp` | ngspice | [doc](enhancements_doc/Enhancement-64.md) | [touchstone](examples/touchstone_examples/) |
| 65 | Preprocessor audit — macro-recursion guard | openvaf&#8209;r | [doc](enhancements_doc/Enhancement-65.md) | [preproc](examples/preproc_examples/) |
| 66 | Monte Carlo with OSDI — validation (+ zero-warning build chore) | both | [doc](enhancements_doc/Enhancement-66.md) | [montecarlo](examples/montecarlo_examples/) |
| 67 | Generate audit — genvar fix, nesting, `generate if`/`case` | openvaf&#8209;r | [doc](enhancements_doc/Enhancement-67.md) | [generate](examples/generate_examples/) |
| 68 | The compiler's own integration test suite, enabled (28 models) | openvaf&#8209;r | [doc](enhancements_doc/Enhancement-68.md) | — |
| 69 | Operating-point variables end-to-end — validation | openvaf&#8209;r | [doc](enhancements_doc/Enhancement-69.md) | [opvar](examples/opvar_examples/) |
| 70 | Behavioral-loop audit — precise loop diagnostics | openvaf&#8209;r | [doc](enhancements_doc/Enhancement-70.md) | [analogloop](examples/analogloop_examples/) |
| 71 | Display-task audit — full format surface + `%b` segfault fix | openvaf&#8209;r | [doc](enhancements_doc/Enhancement-71.md) | [display](examples/display_examples/) |
| 72 | Touchstone round 2 — MA/DB, units, Y/Z, `rdsnp` reader | ngspice | [doc](enhancements_doc/Enhancement-72.md) | [touchstone](examples/touchstone_examples/) |
| 73 | The user handbook, its PDF edition, and this README index | both | [doc](enhancements_doc/Enhancement-73.md) | [docs/handbook](docs/handbook/README.md) |
| 74 | OSDI-vs-built-in benchmark (twins at parity) | both | [doc](enhancements_doc/Enhancement-74.md) | [benchmark](examples/benchmark_examples/) |
| 75 | dynamic-physics cross-checks (Cgg AC≡tran) | openvaf&#8209;r | [doc](enhancements_doc/Enhancement-75.md) | [dynphys](examples/dynphys_examples/) |
| 76 | multi-module `.osdi` libraries | ngspice | [doc](enhancements_doc/Enhancement-76.md) | [multimod](examples/multimod_examples/) |
| 77 | ngspice build warnings → 0 (macOS/clang) | ngspice | [doc](enhancements_doc/Enhancement-77.md) | — |
| 78 | `casex`/`casez` don't-care masks | openvaf&#8209;r | [doc](enhancements_doc/Enhancement-78.md) | [casexz](examples/casexz_examples/) |
| 79 | 1M-element benchmark round 2 (BSIM4) | both | [doc](enhancements_doc/Enhancement-79.md) | [benchmark](examples/benchmark_examples/) |
| 80 | temperature physics (`dtemp` alias fix) | openvaf&#8209;r | [doc](enhancements_doc/Enhancement-80.md) | [tempphys](examples/tempphys_examples/) |
| 81 | lifecycle: re-source/reset leak-free | ngspice | [doc](enhancements_doc/Enhancement-81.md) | [lifecycle](examples/lifecycle_examples/) |
| 82 | provenance / compliance docs | both | [doc](enhancements_doc/Enhancement-82.md) | — |
| 83 | transistor-level `opamp741` demo | openvaf&#8209;r | [doc](enhancements_doc/Enhancement-83.md) | [opamp741](examples/opamp741_examples/) |
| 84 | LRM-2023 example sweep (231 examples) | openvaf&#8209;r | [doc](enhancements_doc/Enhancement-84.md) | [lrm](examples/lrm_examples/) |
| 85 | `__FILE__`/`__LINE__` directives | openvaf&#8209;r | [doc](enhancements_doc/Enhancement-85.md) | [filemacro](examples/filemacro_examples/), [partselect](examples/partselect_examples/) |
| 86 | hierarchical branch probes | openvaf&#8209;r | [doc](enhancements_doc/Enhancement-86.md) | [hierbranch](examples/hierbranch_examples/) |
| 87 | block-scoped parameters | openvaf&#8209;r | [doc](enhancements_doc/Enhancement-87.md) | [blockparam](examples/blockparam_examples/) |
| 88 | legacy `generate` syntax | openvaf&#8209;r | [doc](enhancements_doc/Enhancement-88.md) | [legacygen](examples/legacygen_examples/) |
| 89 | array ports + Annex E SPICE compat | openvaf&#8209;r | [doc](enhancements_doc/Enhancement-89.md) | [arrayport](examples/arrayport_examples/), [annexe](examples/annexe_examples/) |
| 90 | multi-bit bus port ordering fix | openvaf&#8209;r | [doc](enhancements_doc/Enhancement-90.md) | [busport](examples/busport_examples/) |
| 91 | param-dependent width + multi-name decls | openvaf&#8209;r | [doc](enhancements_doc/Enhancement-91.md) | [paramwidth](examples/paramwidth_examples/) |
| 92 | parameter freeze | openvaf&#8209;r | [doc](enhancements_doc/Enhancement-92.md) | [paramfreeze](examples/paramfreeze_examples/) |
| 93 | unset-parameter warning | both | [doc](enhancements_doc/Enhancement-93.md) | [paramnonset](examples/paramnonset_examples/) |
| 94 | `pyplot` (matplotlib backend) | ngspice | [doc](enhancements_doc/Enhancement-94.md) | [pyplot](examples/pyplot_examples/) |
| 95 | `pyplot` default filename | ngspice | [doc](enhancements_doc/Enhancement-95.md) | [pyplot](examples/pyplot_examples/) |
| 96 | bare `generate` blocks | openvaf&#8209;r | [doc](enhancements_doc/Enhancement-96.md) | [baregenerate](examples/baregenerate_examples/) |
| 97 | contributing to all-`ground` branches | openvaf&#8209;r | [doc](enhancements_doc/Enhancement-97.md) | [groundcontrib](examples/groundcontrib_examples/) |
| 98 | `pyplot` subplots | ngspice | [doc](enhancements_doc/Enhancement-98.md) | [pyplotpanel](examples/pyplotpanel_examples/) |
| 99 | `pyplot` export formats (png/svg/pdf) | ngspice | [doc](enhancements_doc/Enhancement-99.md) | [pyplotexport](examples/pyplotexport_examples/) |
| 100 | milestone audit | both | [doc](enhancements_doc/Enhancement-100.md) | — |
| 101 | `$clog2` | openvaf&#8209;r | [doc](enhancements_doc/Enhancement-101.md) | [clog2](examples/clog2_examples/) |
| 102 | array parameters | openvaf&#8209;r | [doc](enhancements_doc/Enhancement-102.md) | [paramarray](examples/paramarray_examples/) |
| 103 | `ceil()` non-const fix | openvaf&#8209;r | [doc](enhancements_doc/Enhancement-103.md) | [ceil](examples/ceil_examples/) |
| 104 | `$rtoi`/`$itor` | openvaf&#8209;r | [doc](enhancements_doc/Enhancement-104.md) | [convert](examples/convert_examples/) |
| 105 | `$sscanf` format bases | openvaf&#8209;r | [doc](enhancements_doc/Enhancement-105.md) | [sscanf](examples/sscanf_examples/) |
| 106 | string relational operators | openvaf&#8209;r | [doc](enhancements_doc/Enhancement-106.md) | [stringcmp](examples/stringcmp_examples/) |
| 107 | `$fgetc` | openvaf&#8209;r | [doc](enhancements_doc/Enhancement-107.md) | [fgetc](examples/fgetc_examples/) |
| 108 | `$ungetc` one-char pushback | openvaf&#8209;r | [doc](enhancements_doc/Enhancement-108.md) | [ungetc](examples/ungetc_examples/) |
| 109 | `noise_table` interpolation | openvaf&#8209;r | [doc](enhancements_doc/Enhancement-109.md) | [noisetable](examples/noisetable_examples/) |
| 110 | `.option errpreset` (cons/mod/lib tolerance sets) | ngspice | [doc](enhancements_doc/Enhancement-110.md) | [errpreset](examples/errpreset_examples/) |
| 111 | globalized-Newton line search | ngspice | [doc](enhancements_doc/Enhancement-111.md) | [linesearch](examples/linesearch_examples/) |
| 112 | KLU line search | ngspice | [doc](enhancements_doc/Enhancement-112.md) | [linesearch](examples/linesearch_examples/) |
| 113 | KLU noise + pole-zero | ngspice | [doc](enhancements_doc/Enhancement-113.md) | [analyses](examples/analyses_examples/), [noisejw](examples/noisejw_examples/) |
| 114 | KLU sensitivity | ngspice | [doc](enhancements_doc/Enhancement-114.md) | [analyses](examples/analyses_examples/) |
| 115 | KLU distortion | ngspice | [doc](enhancements_doc/Enhancement-115.md) | [analyses](examples/analyses_examples/) |
| 116 | `KLU`: decoupled-OSDI noise & pole-zero | ngspice | [doc](enhancements_doc/Enhancement-116.md) | [groundcontrib](examples/groundcontrib_examples/), [hierbranch](examples/hierbranch_examples/) |
| 117 | PSS (shooting) productionized | ngspice | [doc](enhancements_doc/Enhancement-117.md) | [rfpss](examples/rfpss_examples/) |
| 118 | PSS under KLU | ngspice | [doc](enhancements_doc/Enhancement-118.md) | [rfpss](examples/rfpss_examples/) |
| 119 | PAC: retain PSS op-point | ngspice | [doc](enhancements_doc/Enhancement-119.md) | [rfpss](examples/rfpss_examples/) |
| 120 | PAC: Jacobian harmonics | ngspice | [doc](enhancements_doc/Enhancement-120.md) | [rfpss](examples/rfpss_examples/) |
| 121 | PAC: conversion matrix | ngspice | [doc](enhancements_doc/Enhancement-121.md) | [rfpss](examples/rfpss_examples/) |
| 122 | `.pac` command (periodic AC sweep) | ngspice | [doc](enhancements_doc/Enhancement-122.md) | [rfpss](examples/rfpss_examples/) |
| 123 | `.pac` finish | ngspice | [doc](enhancements_doc/Enhancement-123.md) | [rfpss](examples/rfpss_examples/) |
| 124 | `.pnoise` | ngspice | [doc](enhancements_doc/Enhancement-124.md) | [rfpss](examples/rfpss_examples/) |
| 125 | `.pxf` | ngspice | [doc](enhancements_doc/Enhancement-125.md) | [rfpss](examples/rfpss_examples/) |
| 126 | cyclostationary noise | ngspice | [doc](enhancements_doc/Enhancement-126.md) | [rfpss](examples/rfpss_examples/) |
| 127 | `.option ptcont` DC homotopy | ngspice | [doc](enhancements_doc/Enhancement-127.md) | [ptcont](examples/ptcont_examples/) |
| 128 | `.option dynorder` (LTE-based Gear order) | ngspice | [doc](enhancements_doc/Enhancement-128.md) | [dynorder](examples/dynorder_examples/) |
| 129 | `sweep` progress bar | ngspice | [doc](enhancements_doc/Enhancement-129.md) | [progressbar](examples/progressbar_examples/) |
| 130 | `optimize` (Nelder-Mead) | ngspice | [doc](enhancements_doc/Enhancement-130.md) | [optimize](examples/optimize_examples/) |
| 131 | transient checkpoint/restart | ngspice | [doc](enhancements_doc/Enhancement-131.md) | [checkpoint](examples/checkpoint_examples/) |
| 132 | `.psp` (PSS-based) | ngspice | [doc](enhancements_doc/Enhancement-132.md) | [psp](examples/psp_examples/) |
| 133 | `qpss` two-tone (transient DFT) | ngspice | [doc](enhancements_doc/Enhancement-133.md) | [qpss](examples/qpss_examples/) |
| 134 | Harmonic Balance (`hb`) | ngspice | [doc](enhancements_doc/Enhancement-134.md) | [hb](examples/hb_examples/) |
| 135 | HB source-stepping continuation | ngspice | [doc](enhancements_doc/Enhancement-135.md) | [hb](examples/hb_examples/) |
| 136 | two-tone QPSS via HB | ngspice | [doc](enhancements_doc/Enhancement-136.md) | [qpss](examples/qpss_examples/) |
| 137 | `qpac` two-tone small-signal | ngspice | [doc](enhancements_doc/Enhancement-137.md) | [qpac](examples/qpss_examples/) |
| 138 | `qpnoise` | ngspice | [doc](enhancements_doc/Enhancement-138.md) | [qpnoise](examples/qpss_examples/) |
| 139 | cyclostationary `qpnoise` | ngspice | [doc](enhancements_doc/Enhancement-139.md) | [qpnoise](examples/qpss_examples/) |
| 140 | oscillator phase noise | ngspice | [doc](enhancements_doc/Enhancement-140.md) | [phasenoise](examples/phasenoise_examples/) |
| 141 | `qpxf` | ngspice | [doc](enhancements_doc/Enhancement-141.md) | [qpxf](examples/qpss_examples/) |
| 142 | QP small-signal freq sweep (`qpac`/`qpnoise`/`qpxf`) | ngspice | [doc](enhancements_doc/Enhancement-142.md) | [sweep](examples/qpss_examples/) |
| 143 | least-squares `optimize` (Levenberg-Marquardt) | ngspice | [doc](enhancements_doc/Enhancement-143.md) | [fit](examples/optimize_examples/) |
| 144 | `optimize -dparam` (`.param` knobs) | ngspice | [doc](enhancements_doc/Enhancement-144.md) | [fit](examples/optimize_examples/) |
| 145 | `optimize -mparam` (`.model` knobs) | ngspice | [doc](enhancements_doc/Enhancement-145.md) | [fit](examples/optimize_examples/) |
| 146 | universal `sweep` command + `.sweep` card | ngspice | [doc](enhancements_doc/Enhancement-146.md) | [sweep](examples/sweep_examples/) |
| 147 | nested `?:` compile time O(2^N)→O(N) | openvaf&#8209;r | [doc](enhancements_doc/Enhancement-147.md) | [nested](examples/nested_cond_examples/) |
| 148 | compiler hardening (parser depth/include) | openvaf&#8209;r | [doc](enhancements_doc/Enhancement-148.md) | [robustness](examples/robustness_examples/) |
| 149 | Latin-Hypercube sampling | ngspice | [doc](enhancements_doc/Enhancement-149.md) | [lhs](examples/lhs_examples/) |
| 150 | high-sigma analysis | ngspice | [doc](enhancements_doc/Enhancement-150.md) | [highsigma](examples/highsigma_examples/) |
| 151 | correlations + yield (Cholesky) | ngspice | [doc](enhancements_doc/Enhancement-151.md) | [yield](examples/yield_examples/) |
| 152 | KLU tuning (ordering/scale/BTF) | ngspice | [doc](enhancements_doc/Enhancement-152.md) | [klu](examples/klu_tuning_examples/) |
| 153 | trust-region optimizer | ngspice | [doc](enhancements_doc/Enhancement-153.md) | [trustregion](examples/trustregion_examples/) |
| 154 | envelope following | ngspice | [doc](enhancements_doc/Enhancement-154.md) | [envelope](examples/envelope_examples/) |
| 155 | RC reduction (`reduce`/TICER) | ngspice | [doc](enhancements_doc/Enhancement-155.md) | [reduce](examples/reduce_examples/) |
| 156 | sparse RC reduction (scales to millions) | ngspice | [doc](enhancements_doc/Enhancement-156.md) | [reduce](examples/reduce_examples/) |
| 157 | device aging (`aging`; static + dynamic) | ngspice | [doc](enhancements_doc/Enhancement-157.md) | [aging](examples/aging_examples/) |
| 158 | power-grid EMIR (IR-drop + EM) | ngspice | [doc](enhancements_doc/Enhancement-158.md) | [emir](examples/emir_examples/) |
| 159 | real compact models (BSIM4/EKV) | both | [doc](enhancements_doc/Enhancement-159.md) | [compactmodels](examples/compactmodels_examples/) |
| 160 | CMC coverage sweep (19 models) | both | [doc](enhancements_doc/Enhancement-160.md) | [cmcsweep](examples/cmcsweep_examples/) |
| 161 | dynamic C-V / fT vs built-in | both | [doc](enhancements_doc/Enhancement-161.md) | [dynmodels](examples/dynmodels_examples/) |
| 162 | `.hb` dot-card | ngspice | [doc](enhancements_doc/Enhancement-162.md) | [hb](examples/hb_examples/) |
| 163 | `.qpss`/`.hbosc`/`.phasenoise` dot-cards | ngspice | [doc](enhancements_doc/Enhancement-163.md) | [qpss](examples/qpss_examples/) · [phasenoise](examples/phasenoise_examples/) |
| 164 | large-signal RF (P1dB/IP3) | both | [doc](enhancements_doc/Enhancement-164.md) | [rfpa](examples/rfpa_examples/) |
| 165 | model noise (flicker/thermal/shot) | both | [doc](enhancements_doc/Enhancement-165.md) | [modelnoise](examples/modelnoise_examples/) |
| 166 | electro-thermal self-heating | both | [doc](enhancements_doc/Enhancement-166.md) | [electrothermal](examples/electrothermal_examples/) |
| 167 | cross-model self-heating (4 classes) | both | [doc](enhancements_doc/Enhancement-167.md) | [cmcselfheat](examples/cmcselfheat_examples/) |
| 168 | LNA noise figure (Friis / noise match) | both | [doc](enhancements_doc/Enhancement-168.md) | [noisefigure](examples/noisefigure_examples/) |
| 169 | interactive syntax highlighting | ngspice | [doc](enhancements_doc/Enhancement-169.md) | [syntaxhl](examples/syntaxhl_examples/) |
| 170 | semantic highlighting (signals/exprs) | ngspice | [doc](enhancements_doc/Enhancement-170.md) | [syntaxhl](examples/syntaxhl_examples/) |
| 171 | KLU pole-zero (complex determinant) | ngspice | [doc](enhancements_doc/Enhancement-171.md) | [klupz](examples/klupz_examples/) |
| 172 | KLU balanced PZ + full pivoting | ngspice | [doc](enhancements_doc/Enhancement-172.md) | [klupz](examples/klupz_examples/) |
| 173 | eigenvalue pole-zero (`pzeig`) | ngspice | [doc](enhancements_doc/Enhancement-173.md) | [pzeig](examples/pzeig_examples/) |
| 174 | `help` command crash fix | ngspice | [doc](enhancements_doc/Enhancement-174.md) | [helpcmd](examples/helpcmd_examples/) |
| 175 | conversion-matrix parametric-term fix | ngspice | [doc](enhancements_doc/Enhancement-175.md) | [rfconv](examples/rfconv_examples/) |
| 176 | driven-mode PSS (~1000x) | ngspice | [doc](enhancements_doc/Enhancement-176.md) | [pssdriven](examples/pssdriven_examples/) |
| 177 | pnoise folding referee + flicker fix | ngspice | [doc](enhancements_doc/Enhancement-177.md) | [pnoisefold](examples/pnoisefold_examples/) |
| 178 | exact cyclostationary folding + HB DC fix | ngspice | [doc](enhancements_doc/Enhancement-178.md) | [cyclofold](examples/cyclofold_examples/) |
| 179 | `.tf`/`.sens`/`.meas` audit + referees | ngspice | [doc](enhancements_doc/Enhancement-179.md) | [stdaudit](examples/stdaudit_examples/) |
| 180 | checkpoint under KLU (cross-solver) | ngspice | [doc](enhancements_doc/Enhancement-180.md) | [checkpoint](examples/checkpoint_examples/) |
| 181 | integrator certified + `ordfix` | ngspice | [doc](enhancements_doc/Enhancement-181.md) | [corenum](examples/corenum_examples/) |
| 182 | `pyplot` autoscale by default | ngspice | [doc](enhancements_doc/Enhancement-182.md) | [pyplot](examples/pyplot_examples/) |
| 183 | `pyplot`: distinct names, deck output, linewidth, backend | ngspice | [doc](enhancements_doc/Enhancement-183.md) | [pyplot](examples/pyplot_examples/) |
| 184 | progress bar reaches 100% | ngspice | [doc](enhancements_doc/Enhancement-184.md) | [progressbar](examples/progressbar_examples/) |
| 185 | autodiff `hypot`/`atan2` derivative fixes | openvaf&#8209;r | [doc](enhancements_doc/Enhancement-185.md) | [vafautodiff](examples/vafautodiff_examples/) |
| 186 | autodiff real-modulo derivative fix | openvaf&#8209;r | [doc](enhancements_doc/Enhancement-186.md) | [vafautodiff](examples/vafautodiff_examples/) |
| 187 | simplifier inverse-function cancellation fixes | openvaf&#8209;r | [doc](enhancements_doc/Enhancement-187.md) | [mathident](examples/mathident_examples/) |
| 188 | warm-start Monte Carlo | ngspice | [doc](enhancements_doc/Enhancement-188.md) | [warmstart](examples/warmstart_examples/) |
| 189 | `sweep -overlay` waveform families | ngspice | [doc](enhancements_doc/Enhancement-189.md) | [sweepwave](examples/sweepwave_examples/) |
| 190 | `sweep -vs` nested multi-knob sweeps | ngspice | [doc](enhancements_doc/Enhancement-190.md) | [nestedsweep](examples/nestedsweep_examples/) |
| 191 | `.ac`/`.sp lin 2` off-by-one fix | ngspice | [doc](enhancements_doc/Enhancement-191.md) | [aclin2](examples/aclin2_examples/) |
| 192 | auto-checkpoint on interrupt (`Ctrl-C`) | ngspice | [doc](enhancements_doc/Enhancement-192.md) | [autosave](examples/autosave_examples/) |
| 193 | `.pnoise` honors `sqrnoise` (V/√Hz) | ngspice | [doc](enhancements_doc/Enhancement-193.md) | [pnoiseunits](examples/pnoiseunits_examples/) |
| 194 | `optimize -method pso` (global) | ngspice | [doc](enhancements_doc/Enhancement-194.md) | [psoopt](examples/psoopt_examples/) |
| 195 | `optimize -method de` (global) | ngspice | [doc](enhancements_doc/Enhancement-195.md) | [deopt](examples/deopt_examples/) |
| 196 | `optimize -method sa` (global) | ngspice | [doc](enhancements_doc/Enhancement-196.md) | [saopt](examples/saopt_examples/) |
| 197 | 100-parameter curve-fit (raised caps) | ngspice | [doc](enhancements_doc/Enhancement-197.md) | [opt100](examples/opt100_examples/) |
| 198 | `stb` loop-gain + phase/gain margin | ngspice | [doc](enhancements_doc/Enhancement-198.md) | [stb](examples/stb_examples/) |
| 199 | N-port Touchstone device (S-param, AC+tran) | both | [doc](enhancements_doc/Enhancement-199.md) | [nport](examples/nport_examples/) |
| 200 | `pre_snp`: built-in Touchstone→OSDI command | both | [doc](enhancements_doc/Enhancement-200.md) | [presnp](examples/presnp_examples/) |
| 201 | `pre_snp` scalability: fast vector fit (N→100) | both | [doc](enhancements_doc/Enhancement-201.md) | [presnp](examples/presnp_examples/) |
| 202 | `.sp` S-param inverse O(N!)→O(N³) | ngspice | [doc](enhancements_doc/Enhancement-202.md) | [spscale](examples/spscale_examples/) |
| 203 | `.meas ac` gain/phase margin + batch `vdb` fix | ngspice | [doc](enhancements_doc/Enhancement-203.md) | [acmargin](examples/acmargin_examples/) |
| 204 | `.option convhelp` convergence ladder | ngspice | [doc](enhancements_doc/Enhancement-204.md) | [convhelp](examples/convhelp_examples/) |
| 205 | `pre_snp` low-rank residue factorization | both | [doc](enhancements_doc/Enhancement-205.md) | [lowrank](examples/lowrank_examples/) |
| 206 | `optimize -center` design centering (yield/Cpk) | ngspice | [doc](enhancements_doc/Enhancement-206.md) | [dcenter](examples/dcenter_examples/) |
| 207 | `eye` diagram / jitter (SerDes) | ngspice | [doc](enhancements_doc/Enhancement-207.md) | [eye](examples/eye_examples/) |
| 208 | `pyplot -eye` eye diagrams | ngspice | [doc](enhancements_doc/Enhancement-208.md) | [pyplot](examples/pyplot_examples/) |
| 209 | `hb` publishes spectrum as nutmeg vectors | ngspice | [doc](enhancements_doc/Enhancement-209.md) | [hb](examples/hb_examples/) |
| 210 | `.pss` dot-card + complex node vectors | ngspice | [doc](enhancements_doc/Enhancement-210.md) | [rfpss](examples/rfpss_examples/) |
| 211 | static-analysis DC-op/import bug fixes | ngspice | [doc](enhancements_doc/Enhancement-211.md) | [codeanalysis](examples/codeanalysis_examples/) |
| 212 | crash hardening: 7 input-handling crashes | ngspice | [doc](enhancements_doc/Enhancement-212.md) | [crashfix](examples/crashfix_examples/) |
| 213 | openvaf crash hardening: 4 compiler panics | openvaf&#8209;r | [doc](enhancements_doc/Enhancement-213.md) | [vafcrash](examples/vafcrash_examples/) |
| 214 | openvaf whole-array coercion crash class (root fix) | openvaf&#8209;r | [doc](enhancements_doc/Enhancement-214.md) | [arraycast](examples/arraycast_examples/) |
| 215 | `$test`/`$value$plusargs` | both | [doc](enhancements_doc/Enhancement-215.md) | [plusargs](examples/plusargs_examples/) |
| 216 | `optimize -method nsga2` Pareto front | ngspice | [doc](enhancements_doc/Enhancement-216.md) | [pareto](examples/pareto_examples/) |
| 217 | `pyplot -hist` histograms | ngspice | [doc](enhancements_doc/Enhancement-217.md) | [pyplothist](examples/pyplothist_examples/) |
| 218 | `pyplot -contour` 2-D maps | ngspice | [doc](enhancements_doc/Enhancement-218.md) | [pyplotcontour](examples/pyplotcontour_examples/) |
| 219 | openvaf preprocessor macro-arg hang + diag cap | openvaf&#8209;r | [doc](enhancements_doc/Enhancement-219.md) | [robustness](examples/robustness_examples/) |
| 220 | openvaf crash hardening r2 (10 panics) | openvaf&#8209;r | [doc](enhancements_doc/Enhancement-220.md) | [vafcrash2](examples/vafcrash2_examples/) |
| 221 | array/bus node ranges (`a[0:1]`) | ngspice | [doc](enhancements_doc/Enhancement-221.md) | [busnodes](examples/busnodes_examples/) |
| 222 | parser fuzz hardening (7 crashes/hangs) | ngspice | [doc](enhancements_doc/Enhancement-222.md) | [parserfuzz](examples/parserfuzz_examples/) |
| 223 | XSPICE a-device model-type check (`MIFgetMod`) | ngspice | [doc](enhancements_doc/Enhancement-223.md) | [xspicemodel](examples/xspicemodel_examples/) |
| 224 | array-node voltages in `print`/`plot` (`v(a[0])`) | ngspice | [doc](enhancements_doc/Enhancement-224.md) | [arraynodeprint](examples/arraynodeprint_examples/) |
| 225 | command/expression evaluator crash hardening (fuzz: 5 bugs — `fft`/`deriv`/`fourier` short-vec, `?:` NULL, `meas` buffer) | ngspice | [doc](enhancements_doc/Enhancement-225.md) | [cmdfuzz](examples/cmdfuzz_examples/) |
| 226 | rawfile `load` crash hardening (fuzz: missing `Flags:` line → NULL deref) | ngspice | [doc](enhancements_doc/Enhancement-226.md) | [rawfuzz](examples/rawfuzz_examples/) |
| 227 | Touchstone `pre_snp` crash hardening (fuzz: huge `.sNp` port count → heap corruption) | ngspice | [doc](enhancements_doc/Enhancement-227.md) | [snpfuzz](examples/snpfuzz_examples/) |
| 228 | OSDI `.osdi` loader crash hardening (fuzz: reject implausible descriptor counts) | ngspice | [doc](enhancements_doc/Enhancement-228.md) | [osdifuzz](examples/osdifuzz_examples/) |
| 229 | `pre_osdi -f` reloads a recompiled `.osdi` model in-session (no restart) | ngspice | [doc](enhancements_doc/Enhancement-229.md) | [osdireload](examples/osdireload_examples/) |
| 230 | openvaf-r crash hardening round 3 (fuzz: 3 panics → clean errors) | openvaf&#8209;r | [doc](enhancements_doc/Enhancement-230.md) | [vafcrash3](examples/vafcrash3_examples/) |
| 231 | wrdata CSV output: set wr_csv + wrdata -csv flag (any position) | ngspice | [doc](enhancements_doc/Enhancement-231.md) | [csv](examples/csv_examples/) |
| 232 | KLU solver-glue correctness hardening (klusmp.c audit: null-checks, real/complex collapse-map, bounds guard) | ngspice | [doc](enhancements_doc/Enhancement-232.md) | [solverfix](examples/solverfix_examples/) |
| 233 | KLU glue deeper audit: finish null-check reorder (2 more sites) + multi-gap collapse-map fix; leak refuted | ngspice | [doc](enhancements_doc/Enhancement-233.md) | [solverfix](examples/solverfix_examples/) |
| 234 | loadpull: PA load-/source-pull, Pout/gain/PAE/efficiency contours on the Smith chart (tran+FFT, pyplot -contour) | ngspice | [doc](enhancements_doc/Enhancement-234.md) | [loadpull](examples/loadpull_examples/) |
| 235 | stb: fix a probe-lookup use-after-free (INPretrieve double-free); probe name now case-insensitive | ngspice | [doc](enhancements_doc/Enhancement-235.md) | [stbfix](examples/stbfix_examples/) |
| 236 | .meas: fix a stack-buffer overflow on long measurement names (sprintf into out_line[1000] → bounded snprintf) | ngspice | [doc](enhancements_doc/Enhancement-236.md) | [measovf](examples/measovf_examples/) |
| 237 | .print/.plot/.four: fix stack-buffer overflows on long vector/node names (fixem, gettoks, vec_basename right-sized) | ngspice | [doc](enhancements_doc/Enhancement-237.md) | [nameovf](examples/nameovf_examples/) |
| 238 | gettoks: fix a NULL-deref crash on a malformed differential token like v(1, (comma, no close paren) | ngspice | [doc](enhancements_doc/Enhancement-238.md) | [malftoken](examples/malftoken_examples/) |
| 239 | expr parser: fix a NULL-deref crash on a one-argument min/max/pow/pwr (arity check in PT_mkfnode) | ngspice | [doc](enhancements_doc/Enhancement-239.md) | [funcarity](examples/funcarity_examples/) |
| 240 | XSPICE s_xfer: fix an out-of-bounds crash on a static-gain transfer function (0-order denominator) | ngspice | [doc](enhancements_doc/Enhancement-240.md) | [sxfer](examples/sxfer_examples/) |
| 241 | fft/spec: fix amplitude normalization for non-power-of-2 records (scaled by padded size N instead of length) | ngspice | [doc](enhancements_doc/Enhancement-241.md) | [fftnorm](examples/fftnorm_examples/) |
| 242 | native n-port device + pre_snp -native: stamp a pole/residue Y-model directly (DC/AC/tran, KLU) with no OpenVAF compile, scaling past the VA->OSDI port wall | ngspice | [doc](enhancements_doc/Enhancement-242.md) | [nport_native](examples/nport_native_examples/) |
| 243 | pre_snp -osdi: emit an explicit ref terminal in the generated Verilog-A so the instance line is identical for both -osdi and -native backends | ngspice | [doc](enhancements_doc/Enhancement-243.md) | [presnp](examples/presnp_examples/) |
| 244 | crash-hardening: fix nport unbound-node SIGABRT (setup node-binding + port-count guards) and pyplot -hist/-contour first-arg use-after-free | ngspice | [doc](enhancements_doc/Enhancement-244.md) | [crashfix2](examples/crashfix2_examples/) |
| 245 | crash-hardening: fix meas stray-`=` NULL deref (strtok) and altermod NULL-param deref (device-letter 2nd token) in core command parsers | ngspice | [doc](enhancements_doc/Enhancement-245.md) | [crashfix3](examples/crashfix3_examples/) |
| 246 | crash-hardening: fix out-of-bounds read in the pwl and pwlts XSPICE code models when x_array and y_array differ in length | ngspice | [doc](enhancements_doc/Enhancement-246.md) | [pwlfix](examples/pwlfix_examples/) |
| 247 | crash-hardening: fix out-of-bounds read/UB in the table2d and table3d XSPICE code models on degenerate or too-small tables (validate axes, clamp interpolation order) | ngspice | [doc](enhancements_doc/Enhancement-247.md) | [tablefix](examples/tablefix_examples/) |
| 248 | crash-hardening: fix out-of-bounds accesses in the CPL coupled-line device (validate conductor count vs the 8-line array bound and the R/L/C/G matrix sizes) | ngspice | [doc](enhancements_doc/Enhancement-248.md) | [cplfix](examples/cplfix_examples/) |
| 249 | crash-hardening: validate URC lump count (reject n<1 or the huge-n memory hang) and reject negative R/L/G/C in the LTRA lossy line | ngspice | [doc](enhancements_doc/Enhancement-249.md) | [tlinefix](examples/tlinefix_examples/) |
| 250 | crash-hardening: fix undefined-behaviour 1<<n shift in the d_lut and d_genlut XSPICE code models by capping the input-port count | ngspice | [doc](enhancements_doc/Enhancement-250.md) | [dlutfix](examples/dlutfix_examples/) |
| 251 | correctness: tighten the harmonic-balance verification -- prove HB converges to the exact steady state (~1e-7 vs a Richardson-extrapolated transient) and enforce a 6x-tighter regression tolerance | ngspice | [doc](enhancements_doc/Enhancement-251.md) | [hb](examples/hb_examples/) |
| 252 | crash-hardening: fix heap out-of-bounds writes in the xfer and file_source XSPICE file-parser code models (multi-record line over-store; timepoint+channels off-by-one) | ngspice | [doc](enhancements_doc/Enhancement-252.md) | [filefix](examples/filefix_examples/) |
| 253 | RF design aid: rfstab command -- two-port stability & gain report (Rollett K, |Delta|, mu/mu-prime factors, MSG/MAG) from .sp S-parameters | ngspice | [doc](enhancements_doc/Enhancement-253.md) | [rfstab](examples/rfstab_examples/) |
| 254 | RF design aid: pyplot -smith -- Smith-chart plotting mode for matplotlib output; draws complex vectors (S11, S22, reflection coefficients) over the unit circle plus constant-R/X grid | ngspice | [doc](enhancements_doc/Enhancement-254.md) | [pyplotsmith](examples/pyplotsmith_examples/) |
| 255 | correctness: prove .disto machine-exact vs Harmonic Balance / QPSS-HB (HD2/HD3/IM3 amplitude convergence) and warn on behavioral B-source nonlinearities that .disto silently ignored | ngspice | [doc](enhancements_doc/Enhancement-255.md) | [distoexact](examples/distoexact_examples/) |
| 256 | DC-solver correctness: fix silent spurious operating point for singular-derivative behavioral sources (B I=sqrt(v), 1/v, ln) -- detect the KCL-residual false-convergence and fall through to gmin/source stepping; confined to the first Newton attempt so all convergence aids are untouched | ngspice | [doc](enhancements_doc/Enhancement-256.md) | [bsrcconv](examples/bsrcconv_examples/) |
| 257 | DC-solver correctness: extend the E-256 false-convergence guard to the TRANSIENT operating point (MODETRANOP), so a .tran of a biased singular-derivative source starts at the true bias instead of a spurious v~0 (which showed a fake startup transient) | ngspice | [doc](enhancements_doc/Enhancement-257.md) | [bsrcconv](examples/bsrcconv_examples/) |
| 258 | DC-solver correctness: extend the false-convergence guard to the .dc sweep cold-start point (which solves via a direct NIiter, bypassing CKTop); generalize the guard to any first-attempt op solve so .op/.tran-op/.dc are all covered | ngspice | [doc](enhancements_doc/Enhancement-258.md) | [bsrcconv](examples/bsrcconv_examples/) |
| 259 | correctness proof: transient integration accuracy -- prove TRAP/Gear2/BE hit their theoretical order (dt^2/dt^2/dt^1), TRAP conserves LC energy while BE is dissipative, breakpoints/RLC/nonlinear-charge match closed-form analytics (both solvers) | ngspice | [doc](enhancements_doc/Enhancement-259.md) | [integaccuracy](examples/integaccuracy_examples/) |
| 260 | correctness proof: LTE step-controller accuracy on a stiff circuit -- the adaptive local-truncation-error stepper delivers accuracy that tracks reltol (error shrinks monotonically ~reltol^0.6, no plateau) as it resolves the fast mode then coarsens for the slow tail | ngspice | [doc](enhancements_doc/Enhancement-260.md) | [integaccuracy](examples/integaccuracy_examples/) |
| 261 | autodiff correctness: guard the `sqrt()` derivative singularity -- `dI/dV` of `K*sqrt(V)` was raw `+inf` at the `V=0` initial guess, NaN-poisoning the Jacobian so the DC op failed outright (while identical `pow(V,0.5)` converged). Emit the regularized `1/(2*sqrt(V+a))` (a=1e-18): finite at `V=0`, exact for `V>0`, composes through downstream operators, matches ngspice's B-source `sqrt` | openvaf&#8209;r | [doc](enhancements_doc/Enhancement-261.md) | [vafsqrtguard](examples/vafsqrtguard_examples/) |
| 262 | autodiff correctness: extend the E-261 guard to `pow(V,Y)`, `0<Y<1` -- the base derivative `Y*V^(Y-1)` is the same `+inf` at `V=0` (an `inf*0` form in the shared pow chain rule), so scaled/combined fractional `pow` NaN-failed the DC op (pow's block-split guard only protected a bare terminal pow). Cache the derivative of `pow(V+a,Y)`: finite at `V=0`, exact for `V>0`, composes; remove the block-split guard (`atan2` unaffected) | openvaf&#8209;r | [doc](enhancements_doc/Enhancement-262.md) | [vafsqrtguard](examples/vafsqrtguard_examples/) |
| 263 | robustness: three compiler panics found by a fuzzing campaign (mutation + structured + valid-pathological) turned into clean errors -- nested `ddt`/`idt`/`absdelay` produced an undefined init-cache value (crashed `sim_back`/OSDI); `ddx(V,5)` with a non-probe unknown crashed `hir_lower` (the type check's diagnostic was dead code); a malformed module with an empty AST item list but a recorded instantiation crashed the hierarchy-flatten pass | openvaf&#8209;r | [doc](enhancements_doc/Enhancement-263.md) | [vafcrash4](examples/vafcrash4_examples/) |
| 264 | large instance arrays: the E-5/-49/-86 module-flatten pass was O(N&#178;) in the instance count (hierarchical-name resolution re-scanned every instance prefix per token, per port binding, per instance; each scope deep-cloned the absolute-reference map), so a big array looked like a hang -- now O(N) via a precomputed ancestor set (O(1) prefix test), a dot-free early-out, and an `Rc`-shared reference map (16k instances ~100s -> ~1s); and deep per-node fan-in (thousands of distinct contributions on one node -> a deep recursive chain) that overflowed the OSDI codegen's rayon-worker stack (SIGABRT) now runs on a pool with a generous worker stack. No generated-code change | openvaf&#8209;r | [doc](enhancements_doc/Enhancement-264.md) | [vafhang](examples/vafhang_examples/) |
| 265 | robustness: a malformed `laplace_*`/`zi_*` coefficient argument crashed the compiler instead of erroring. The num/den type check accepted anything its array-literal / array-variable cases missed and returned the type without requiring a real value, so a bare net reference (`laplace_nd(1,1,p)`), a branch, or a string reached `hir_lower` and panicked resolving a net as a value; an empty direct denominator (`'{}`) separately crashed the state-space realization (`den[len-1]`). Now `infere_laplace` requires a real coefficient and rejects an empty direct denominator (empty numerators and empty pole lists stay legal), giving the normal type-mismatch diagnostic -- shared `case`/concat inference untouched | openvaf&#8209;r | [doc](enhancements_doc/Enhancement-265.md) | [vaflaplace](examples/vaflaplace_examples/) |
| 266 | announce the direct linear solver once, not on every analysis. `CKTsetup`/`CKTpzSetup` printed `Using SPARSE 1.3 as Direct Linear Solver` (or the KLU line) unconditionally per analysis, so `sweep` -- and Monte Carlo / `optimize`, which re-run the analysis per point -- reprinted it every iteration (a 5-point sweep, 5 times). An announce-on-change helper (`CKTannounceSolver`, process-wide state) prints it only when the active solver changes: multi-point runs announce once, a single analysis is unchanged, a `.option klu`/`sparse` switch re-announces, and KLU detection in the HB/benchmark suites still sees the line | ngspice | [doc](enhancements_doc/Enhancement-266.md) | [solverannounce](examples/solverannounce_examples/) |
| 267 | `sweep` records array/bus nodes under their natural names. A node named `ph[0]` (E-221) was stored as `ph_0_` in the sweep plot: the result-vector name builder mapped every non-alphanumeric char to `_` over the WHOLE name to sanitize the appended `_<knob>_<value>` float suffix, clobbering the base name's brackets. Now only the appended suffix is sanitized (`sw_append_sanitized`), so bus nodes keep `ph[0]`, `ph[1]`, ...; and a bare `-output ph[0:3]` expands to `ph[0] ph[1] ph[2] ph[3]` (matching netlist bus expansion). Values unchanged | ngspice | [doc](enhancements_doc/Enhancement-267.md) | [sweepbus](examples/sweepbus_examples/) |
| 268 | wildcard model-parameter knob `@*[param]`: set a model parameter on EVERY loaded model that has it, IN PLACE (`altermod`, no deck re-source), so one `sweep @*[wavelength] ...` co-varies a shared parameter across several `.model` cards. Model params are a device-type property, so one `parmlookup` per type decides membership; matching models are set via `doset`; unrelated types/models are skipped; `@*[<absent>]` warns. Also works standalone (`altermod @*[wavelength]=1.55u`). Avoids the `.param`+`reset` idiom that re-sources the deck each point | ngspice | [doc](enhancements_doc/Enhancement-268.md) | [sweepwild](examples/sweepwild_examples/) |
| 270 | robustness (ASan/UBSan fuzz find): `sweep` now validates its numeric bounds. The `<start> <stop> <step>` / `lin/dec/oct <N> <a> <b>` parser read bounds with `sw_num`, which silently returns 0 for a non-numeric token -- so a typo'd bound (`sweep r1 1k xk 1k`) became a 0 endpoint -> 100000-point runaway (apparent hang), an overflowing bound (`1e400`->inf) fed an `(int)floor(...)` cast -> UB (UBSan: inf outside int), and an absurd finite count (tiny step `1n 1u 1e-30`, huge `lin 999999999`, wide `dec` range) ran 100000 analyses or a multi-GB alloc. `sw_isfinitenum` now requires a finite bound (rejects non-numeric + inf/NaN), a requested count above `SW_MAXPTS` is a clean error not a silent clamp-and-run, and the count is bounded before the cast; valid sweeps unchanged | ngspice | [doc](enhancements_doc/Enhancement-270.md) | [sweepbounds](examples/sweepbounds_examples/) |
| 271 | robustness (ASan/UBSan fuzz find): the `let` command read one byte before its buffer on an empty or all-whitespace left-hand side. `com_let` NUL-terminates the destination vector name at the first `[`, so `let [[ = ...` leaves an empty name; the trailing-space trim `for (q=p+strlen(p)-1; *q<=' ' && p<=q; q--)` then started at `q=p-1` and dereferenced `*q` BEFORE the `p<=q` guard could short-circuit -- a heap read one byte before the allocation (ASan heap-buffer-overflow). Fixed by testing the bound first (`p<=q && *q<=' '`); an empty name falls through to the existing bad-variable-name error. No valid `let` affected | ngspice | [doc](enhancements_doc/Enhancement-271.md) | [letoob](examples/letoob_examples/) |
| 272 | robustness (ASan/UBSan fuzz find): `alter <dev> = <value>` and the `sweep` knob path SEGV'd (shipped build, not just ASan) on an m-named device. `com_alter_common` supports altering a device's principal value with no named parameter, leaving `param` NULL; a binned-MOS guard `if ((dev[0]=='m') && (eq(param,"w") || eq(param,"l")))` then ran `strcmp(NULL,...)`. Reached directly (`alter mfoo = 5`) and via `sweep` (`sw_run_cmd` synthesizes the alter; `sweep mag(v(b)) ...` takes the m-prefixed `mag(...)` as the knob). Fixed by guarding `param` first (`param && (dev[0]=='m') && ...`); a NULL param skips the bin check, non-NULL path unchanged. Pre-existing (crashing inputs use no `@*` wildcard) | ngspice | [doc](enhancements_doc/Enhancement-272.md) | [alternull](examples/alternull_examples/) |
| 273 | robustness (ASan/UBSan fuzz find): cmaths expression operators cast a `double` operand to `int` with a plain cast -- UB for a non-finite/out-of-range value. `cx_mod` (the `%` op) made `1e30 % 5` trip UBSan and return a garbage `2` on the shipped build; `cx_vector`/`cx_cvector`/`cx_unitvec` set the length with `(int)fabs(arg)`, so `vector(1e30)`/`unitvec(1e30)` saturated to ~INT_MAX and ran away allocating+filling it (a multi-GB alloc + billion-iteration loop = a hang, shipped build). Fixed by range-checking before every cast: `%` errors via the existing `out of range for mod`, the vector builders reject a non-representable length (shared `cx_veclen`). Valid exprs unchanged (`17 % 5 = 2`, `vector(4) = [0,1,2,3]`) | ngspice | [doc](enhancements_doc/Enhancement-273.md) | [mathcast](examples/mathcast_examples/) |
| 274 | robustness (ASan/UBSan fuzz find): vector indexing `v[expr]` (evaluate.c op_ind) rounded the index with `(int)floor(value+0.5)` -- UB for a non-finite/out-of-range index (`v(a)[1e308]`, inf, NaN). The resulting index was already clamped to `[0,majsize-1]`; only the cast was unsafe. Fixed with `idx_floor()` clamping the value to int range (NaN->0) before the cast; valid indices unchanged | ngspice | [doc](enhancements_doc/Enhancement-274.md) | [idxcast](examples/idxcast_examples/) |
| 275 | robustness (ASan/UBSan fuzz find): `ifft()` on a REAL input vector read 2x past its buffer. `cx_ifft` (cmath4.c) always cast `data` to `ngcomplex_t*`; a real `double[length]` input read as `length` complex elements ran off the end (heap-buffer-overflow READ). `cx_fft` (E-225) distinguishes real/complex; ifft did not. Fixed: build a complex array (imag=0) for real input + free it, plus a length>=2 guard; valid complex ifft unchanged | ngspice | [doc](enhancements_doc/Enhancement-275.md) | [ifftreal](examples/ifftreal_examples/) |
| 276 | robustness (ASan/UBSan fuzz find): `rnd()` (cx_rnd, cmath2.c) built a modulus with `(int)floor(operand)` -- UB for a non-finite/out-of-range operand (`rnd(1e30)`, inf, NaN). Same class as E-273, which had not covered cx_rnd. Fixed with a `cx_rnd_i()` clamp before the cast; in-range operands unchanged | ngspice | [doc](enhancements_doc/Enhancement-276.md) | [rndcast](examples/rndcast_examples/) |
| 277 | robustness + correctness (ASan/UBSan fuzz find): `deriv()` of a COMPLEX vector both overran the heap and returned a wrong result. The complex branch of `cx_deriv` (cmath4.c) diverged from its correct real branch in three places -- data window `c_indata[j+i+base]` misaligned from the fit scale `scale+i-degree+base` (read past the end), real-part output loop `i+degree/2` vs `i-degree/2`, and tail `scale[j+base]`/`c_outdata[j+base]` vs `j`. Fixed by aligning to the real branch: overflow gone AND complex deriv now correct (`deriv(t+2t*i)=1+2i`); real deriv unchanged | ngspice | [doc](enhancements_doc/Enhancement-277.md) | [derivcx](examples/derivcx_examples/) |
| 278 | robustness (ASan/UBSan fuzz find): the transform functions `integ`/`deriv`/`ifft` (cmath4.c) overran the heap on a vector whose length != its plot scale. A synthetic vector (vector(n)/unitvec(n)) carries the current plot's scale, whose length need not match: data LONGER than the scale read it out of bounds (integ/deriv of unitvec(200)); data much SHORTER overran ifft's Green's datax buffer (sized from the input length, output loop writes scale-length points). Only cx_fft was guarded (E-225). Fixed: integ/deriv reject data longer than the scale (shorter, as from fft, stays valid); ifft grows N to cover the output length. fft->ifft roundtrip + valid integ/deriv unchanged | ngspice | [doc](enhancements_doc/Enhancement-278.md) | [scaleguard](examples/scaleguard_examples/) |
| 279 | robustness (systematic audit, not fuzz): the remaining unguarded `(int)floor(x+0.5)` casts of a user value -- UB outside int range -- in `com_let.c` (index expr), `options.c` (`set numdgt`/`rawfileprec`/`measureprec`, e.g. `set numdgt=1e30`), `com_measure2.c` (`meas ... rise/fall/cross`); plus the last unguarded scale-dependent transform `cx_mtimeavg`, whose window walks the scale for j<length-1 so `mtimeavg(unitvec(200))` read past the scale. Fixed with a clamping helper per file before each cast and the E-278 length-vs-scale guard; in-range values unchanged | ngspice | [doc](enhancements_doc/Enhancement-279.md) | [castguard](examples/castguard_examples/) |
| 280 | memory corruption from a typo: an out-of-range SINGLE index in an indexed `let` assignment wrote past the vector. `get_index_values` validated `low>high` and `high>=n_elem_this_dim` INSIDE the range (`v[lo:hi]`) branch only -- the single-index path returned unchecked, so `let vx[100] = 1` on a 66-element vector walked into the byte-offset arithmetic and did a heap-buffer-overflow WRITE (a huge index also overflowed `index*n_byte_elem` in int). The range form was rejected correctly all along. Fixed by moving both checks so a single index is validated too; reads still clamp (E-274), valid assignments unchanged | ngspice | [doc](enhancements_doc/Enhancement-280.md) | [letidxoob](examples/letidxoob_examples/) |
| 281 | robustness (ASan fuzz find): `deriv()` over-read on a PARTIAL block. `cx_deriv` walks the input in blocks of `grouping` (= v_dims[0]); for an ordinary vector that equals v_length so the fit window always fits, but a vector whose declared dimension differs from its length -- as from a binary op on unequal-length operands, e.g. `min(v(b),ac.v(b))` (66-pt real + 5-pt complex -> length 66, dims[0] 5) -- leaves a partial last block where `base` reaches length-1 while the window spans base+grouping-1, reading past the input. Fixed by bounding the inner loop with `i+base<length` in both branches (a no-op when grouping==length); ordinary and complex derivatives unchanged | ngspice | [doc](enhancements_doc/Enhancement-281.md) | [derivgroup](examples/derivgroup_examples/) |
| 282 | robustness (audit lead): `asciiplot` read past its axis-label buffer on a 3-digit exponent. `ft_agraf` sizes the label lines as `maxy+margin+FUDGE+1` (FUDGE=7) and budgets the exponent width by formatting **0.0**, which always has a 2-digit exponent -- so the layout assumes two digits. Real data can need three (denormal / very large values give `1.00e-320`, 9 chars vs 8), so the last label's memcpy overwrote the line's terminating NUL and the following `out_printf("%s\n%s\n", line2, line1)` walked off the heap allocation (ASan heap-buffer-overflow READ of size 82 on an 81-byte region). Fixed by remembering the allocation bound (`maxy` is reassigned later), clamping the label copy, and re-asserting the terminator; rendering byte-identical for ordinary data | ngspice | [doc](enhancements_doc/Enhancement-282.md) | [plotlabel](examples/plotlabel_examples/) |
| 283 | robustness (extreme-data fuzz): the plot coordinate math cast non-finite doubles to `int` (UB). Plotting extreme data drives `mylog10()`, which returns +/-inf for zero / denormal / overflowed values, and divisions by a range that can be zero: `agraf.c` (the decade `(int)floor(mylog10(...))` and the `lmt`/`hmt` limits, where `tenpowmag` itself can be 0 or inf), `points.c` `ft_findpoint()` (fraction is 0/0 for a degenerate range), `display.c` (four screen-coordinate casts, log/linear x/y). Fixed with per-site clamping -- decade bounded by `DBL_MAX_10_EXP`, point fraction sanitised and clamped to [0,1], screen coordinates clamped into the viewport. Rendering byte-identical for ordinary data | ngspice | [doc](enhancements_doc/Enhancement-283.md) | [plotcoord](examples/plotcoord_examples/) |
| 284 | usability (reported from real use): a Verilog-A parameter `L_um` would not sweep as `@*[[L_um]]` and ngspice reported `'l_um'`, which reads like the mixed-case name was mangled by case-insensitive netlist tokens. Case is a red herring -- the OSDI lookup IS case-insensitive (`@*[L_UM]` resolves `L_um`); the real cause is a LEVEL mismatch, since `@*[[p]]`/`@#*[p]` is the INSTANCE wildcard while a plain `parameter real L_um` is a MODEL parameter (an instance parameter needs `(* type = "instance" *)`). New probe `if_hasparam_wildcard` lets a wildcard that matched nothing check the other level and name the form that works, both directions; and `sweep`'s banner now classifies from the name token, so an instance wildcard is no longer labelled `model param` | ngspice | [doc](enhancements_doc/Enhancement-284.md) | [wildparam](examples/wildparam_examples/) |
| 285 | robustness (extreme-data fuzz): the output paths indexed one vector by ANOTHER's length, and treated a complex vector's NULL real data as real. A vector's own length need not equal its plot scale's (any synthetic vector, `let y = vector(8)` on a 66-point tran plot, carries the plot's scale), and a complex vector has `v_realdata == NULL`. `plotit.c` passed `v->v_realdata` with the SCALE's length to `ft_interpolate` (reading past a shorter vector) and passed NULL for a complex vector -- a hard SEGV on the shipped build (`asciiplot sqrt(-1*vector(10))`, rc=139); `agraf.c` used X-scale-bounded `lower`/`upper` to index each vector; `gnuplot.c` (wrdata) bounded by `scale->v_length` but indexed `v->v_realdata[i]`; `com_measure2.c` read `d->v_realdata[i]` on the tran/dc path with no NULL check its ac/sp branches already had (twice). Fixed by clamping each index to the vector it addresses, skipping the transient resampling for non-real vectors, and taking the real part for a complex measure input; plot and wrdata output byte-identical | ngspice | [doc](enhancements_doc/Enhancement-285.md) | [veclenmix](examples/veclenmix_examples/) |
| 286 | robustness (assertions-enabled replay): constant-folding an integer division by zero killed the compiler. `q = 5 / 0;` exited openvaf-r with an internal error and no `.osdi`, while a RUNTIME zero divisor had always been accepted -- the folder evaluated `lhs / rhs` inside the compiler process, so the compiler was what died (`i32::MIN / -1` likewise). The neighbouring arms folded add/sub/mul with CHECKED arithmetic and shifted by unconstrained distances, so `2147483647 + 1` and `1 << 40` did not match what the generated code computes (LLVM emits plain wrapping arithmetic; a shift outside `0..32` is poison) -- the `const_eval == codegen` invariant. Fixed by returning `Option`: decline the undefined cases and leave the instruction on exactly the runtime path, and fold add/sub/mul with `wrapping_*` | openvaf&#8209;r | [doc](enhancements_doc/Enhancement-286.md) | [vafcodegen](examples/vafcodegen_examples/) |
| 287 | robustness (assertions-enabled replay): a const-folded branch orphaned a block, leaving a stale phi edge -- broken SSA. A noise operator in an `if` CONDITION is zero outside noise analysis, so the optimizer folds the branch; `const_fold_terminator` then cleans the phis INSIDE the dead successor, but the phis that go stale are in ITS successors, which keep an edge labelled with the orphaned block naming a value only reachable through the deleted edge. `simplify_bb` does collect such orphans -- but only on a later sweep, and this branch (unlike its `then_dst == else_dst` sibling three lines above) never set `local_changed`, so no later sweep ran. The MIR verifier being a `debug_assert!`, release builds carried the malformed function forward. Fixed by flagging the change; monotone, so termination is unaffected | openvaf&#8209;r | [doc](enhancements_doc/Enhancement-287.md) | [vafcodegen](examples/vafcodegen_examples/) |
| 288 | robustness (assertions-enabled replay): `hypot` was declared with ONE parameter and called with two, so any `hypot(x,y)` with a non-constant argument emitted a module LLVM rejects. Its neighbours `atan2` and `llvm.pow.f64` are declared correctly; `hypot` is the odd one out because its Windows-name special case sits outside the `ifn!` macro block. Invisible in release because the module verifier is a `debug_assert!`. On arm64 the malformed call still produced the right number (the extra argument lands in the register the callee reads anyway) -- invalid IR LLVM is licensed to miscompile elsewhere, not a demonstrated wrong answer here. Fixed by declaring it binary | openvaf&#8209;r | [doc](enhancements_doc/Enhancement-288.md) | [vafcodegen](examples/vafcodegen_examples/) |
| 289 | robustness (assertions-enabled replay): `llvm.ctlz` is an OVERLOADED LLVM intrinsic and must carry its type suffix, but was registered and looked up under the bare name -- invalid IR for every `$clog2` with a non-constant argument. The neighbouring overloaded entries are all spelled correctly (`llvm.pow.f64`, `llvm.sqrt.f64`, `llvm.ceil.f64`, `llvm.lround.i32.f64`). Found by replaying the committed example corpus through an assertions-enabled compiler: `clog2_demo.va`, a model that had been shipping and simulating correctly, was rejected. Fixed by using `llvm.ctlz.i32` in both the registration and the lookup | openvaf&#8209;r | [doc](enhancements_doc/Enhancement-289.md) | [vafcodegen](examples/vafcodegen_examples/) |
| 290 | correctness (assertions-enabled replay): `$temperature` read as an operator ARGUMENT used the wrong struct-GEP type -- the FIELD type (`double`) instead of the instance-data struct -- so LLVM computed the offset as a flat `5*sizeof(double)` rather than `offsetof(instance, temperature)`. Field 5 is TEMPERATURE and fields 0..4 are the param-given bitfield, the two Jacobian pointer arrays, the node mapping and the collapse flags, whose combined size is essentially never 40 bytes, so the load landed on unrelated bytes -- and the shipped compiler died with SIGSEGV (exit 139) optimizing `ac_stim("ac", $temperature, 0)`. Same wrong type on the operating-point-variable read path. Only a DIRECT operator argument takes this path (a computed `tk = $temperature;` lowers to an eval-output slot and was always right), which is why ordinary models never tripped it. Fixed at both sites; the model now reads back 300.15 K | openvaf&#8209;r | [doc](enhancements_doc/Enhancement-290.md) | [vafcodegen](examples/vafcodegen_examples/) |
| 291 | robustness (assertions-enabled replay): `max`/`min`/`abs` in a `case` DEFAULT arm left a block unsealed ("block N is not sealed"). Those three lower through `make_cond` to real control flow, unlike `pow` which emits one instruction; `lower_case` leaves its per-item fall-through block to be sealed by an `ensured_sealed()` that seals whatever block the builder is positioned in, so when the default arm's body opens blocks of its own the seal lands on ITS merge block and the fall-through block is never sealed. Sharp discriminator: the same call in an ITEM arm, or `pow` in the default arm, was always fine. Fixed by sealing that block where it is created -- the branch just emitted is its only predecessor -- and the case still picks the right arm | openvaf&#8209;r | [doc](enhancements_doc/Enhancement-291.md) | [vafcodegen](examples/vafcodegen_examples/) |
| 292 | robustness (fuzz): small-signal pruning indexed a key its own replay never inserted ("no entry found for key"). Whether a contribution can move into its own dimension is decided twice -- `collect_linear_contributes` classifies it as linear, while the replay in `create_dimension` is what actually builds the value and records it -- and the replay deliberately declines some shapes (an `fmul` whose BOTH operands depend on the dimension, an opcode hitting its catch-all), so the two can disagree. Fixed by treating the disagreement as what it is: pruning is best-effort ("where possible"), so give up on that value, resolving its invalid placeholder so none survives, instead of crashing | openvaf&#8209;r | [doc](enhancements_doc/Enhancement-292.md) | [vafcodegen](examples/vafcodegen_examples/) |
| 293 | correctness (fuzz): one analog operator nested DIRECTLY inside another (`ddt(ddt(x))`) crashed the compile, while anything in between (`ddt(2*ddt(x))`) always worked. An operator materialized as an implicit equation deletes its own instruction, but a later linear contribution holds its dimension values in the `Evaluation::Linear` triples -- OUTSIDE the data-flow graph, where `replace_uses` cannot reach them -- and with direct nesting that stored dimension IS the deleted result, so everything derived from it surfaced as `invalid argument` when the init function was validated. Fixed by retargeting the pending entries onto the implicit unknown the inner operator became, which is also the correct second-derivative formulation: in AC the current magnitude now tracks `omega^2` across four decades and `ddt(2*ddt(V))` comes out at exactly 2x. Transient chained `ddt` is unusable under ngspice's DEFAULT trapezoidal integration but fine under Gear -- use `.options method=gear` (error 5e-5 vs 24 at 100 us). Not a divergence: consecutive steps alternate about the correct value (a non-decaying Nyquist-rate ring, amplitude roughly constant in h), which is trapezoidal ringing -- trapezoidal is A-stable but not L-stable, Gear is L-stable. Pre-existing and bit-identical to the old compiler, so E-293 neither causes nor cures it | openvaf&#8209;r | [doc](enhancements_doc/Enhancement-293.md) | [vafcodegen](examples/vafcodegen_examples/) |
| 294 | robustness (assertions-enabled replay): a `Branch`→`Jump` rewrite left the condition in the use list. A `Branch` carries one value operand, a `Jump` none, so overwriting the instruction in place leaves the condition's use record naming operand 0 of an instruction that now has zero operands -- reading it indexes an empty slice. Two of the four rewrite sites did this (`simplify_bb`'s empty-exit-block rewrite, both arms, and `dead_code_aggressive`'s dead-block rewrite); the two in `const_fold_terminator` already zapped or detached first. Reached only by a narrow shape -- `$fatal` makes its arm an EMPTY EXIT block and the condition must be a PARAMETER compare -- so one module in the corpus hit it. Fixed by zapping the terminator first. The stale entry produced no wrong `.osdi` and no release build could be made to fail on it: a broken invariant with a latent release-crash hazard, and the last blocker to a clean assertions-enabled corpus run | openvaf&#8209;r | [doc](enhancements_doc/Enhancement-294.md) | [vafcodegen](examples/vafcodegen_examples/) |
| 295 | verification (no source change): regression guards for the two correctness blind spots a ~150-check campaign identified -- the campaign itself found ZERO defects. (a) The FULL 4x4 multi-terminal conductance AND capacitance matrices: the autodiff suite biased only 2-terminal devices and read one off-diagonal, leaving the KCL-derived source row and an untouched terminal's zero row/column untested. (b) Per-instance parameter-slot readback -- 13 interleaved model/instance parameters of mixed types, 3 instances, 2 model cards, 39 readbacks -- the guard for the E-290 offset class, which prior tiny-model oracles could not see. Both MUTATION-TESTED: the product-rule mutation fails `[matrix]` while `[cross]`/`[regression]`/`[multipoint]` all still pass, and a reader/writer slot mismatch makes a parameter read its neighbour's value. Not added because already covered: flicker 1/f, the correlated-noise summation rule, and 2-D table interpolation | openvaf&#8209;r | [doc](enhancements_doc/Enhancement-295.md) | [vafcodegen](examples/vafcodegen_examples/) |
| 296 | feature (pyplot polish): seven `set` variables for finer `pyplot` figures without editing the generated Python -- `pyplot_grid` (on/off/x/y), `pyplot_legend` (off or a matplotlib location, underscore form since `set` keeps one word), `pyplot_markers` (a cycling marker ON the line so overlaid traces read in greyscale), `pyplot_axhline`/`pyplot_axvline` (SI-aware reference lines), `pyplot_dpi`, `pyplot_transparent`. All additive: with none set the output is byte-identical to before | ngspice | [doc](enhancements_doc/Enhancement-296.md) | [pyplotmore](examples/pyplotmore_examples/) |
| 297 | feature (pyplot): `pyplot -fft <sig>` plots the one-sided amplitude spectrum, turning fft-then-plot into one command. Transient data is adaptively sampled, so the emitted script resamples onto a uniform grid (np.interp) before the rfft -- a raw FFT over non-uniform samples would be wrong. Scaled by 2/sum(window) so a pure tone reads back its amplitude (verified: a 2.0@1kHz + 0.5@3kHz tone reads 2.0 and 0.5). Options `pyplot_fft_window`/`_db`/`_points`/`_logf` (logf, not `xlog`, which would validate the t=0 time scale and abort) | ngspice | [doc](enhancements_doc/Enhancement-297.md) | [pyplotmore](examples/pyplotmore_examples/) |
| 298 | feature (pyplot): `-bode`/`-nyquist`/`-polar` complex-aware AC views. An ordinary `pyplot v(out)` on AC data silently keeps only the REAL part (0.5 not 0.7071 at -3 dB); these keep the full complex value -- `-bode` = mag(dB)/phase(deg) vs log-f stacked, `-nyquist` = imag vs real, `-polar` = mag at phase. Verified against the exact RC first-order values: -3.01 dB and -45 deg at fc | ngspice | [doc](enhancements_doc/Enhancement-298.md) | [pyplotmore](examples/pyplotmore_examples/) |
| 299 | feature (pyplot): cross-run overlay of different-length runs (`pyplot tran1.v(out) tran2.v(out)`) now sizes the data table by the LONGEST scale, so a finer second run is no longer truncated to the first run's length; `set pyplot_cursor` adds a hover crosshair (matplotlib's built-in Cursor widget, no extra package, window-only); pan/zoom/save and the `.data` export were already provided | ngspice | [doc](enhancements_doc/Enhancement-299.md) | [pyplotmore](examples/pyplotmore_examples/) |
| 300 | feature (pyplot, on request): `set pyplot_mplcursors` selects the `mplcursors` package -- data cursors that snap to a trace and show its (x,y) on hover -- as the interactive-cursor backend, turning the cursor on by itself; unset, the E-299 `matplotlib.widgets.Cursor` crosshair remains the default. The emitted script imports mplcursors in a try/except and FALLS BACK to the built-in Cursor if the package is absent where it runs, so a deck stays portable. Window-only (not emitted for a hardcopy), like `pyplot_cursor`. mplcursors lives in the interpreter named by `pyplot_python` | ngspice | [doc](enhancements_doc/Enhancement-300.md) | [pyplotmore](examples/pyplotmore_examples/) |
| 301 | feature (pyplot, on request): make `pyplot_cursor` the SINGLE master switch for the interactive cursor -- off by default, the only thing that enables any cursor. Previously (E-300) `pyplot_mplcursors` turned the cursor on by itself, so there was no one "off" knob; now `pyplot_mplcursors` only SELECTS the backend when the cursor is on, and does nothing on its own. The enable condition went from `pyplot_cursor OR pyplot_mplcursors` to `pyplot_cursor` alone -- predictable, and matching every other optional pyplot behaviour | ngspice | [doc](enhancements_doc/Enhancement-301.md) | [pyplotmore](examples/pyplotmore_examples/) |
| 302 | BUG (found by closed-form oracle): `.meas avg` did not clip its averaging window to `[from,to]` -- it trapezoid-summed only the SAMPLES inside the window and divided by their span, dropping the partial interval at each end, while `rms`/`integ` already interpolate to the exact bounds. So ngspice's own numbers disagreed: `avg`=1.27114 vs `integ`/dur=1.27324 (closed form 1.2732395) on the same window, and the echoed `to=` was the first sample OUTSIDE it. O(dt/window) error, ~1.6e-3 here, now ~4e-7. Guarded to AVG so min/max are untouched; the `dc` path is deliberately excluded (descending sweeps) and is byte-identical | ngspice | [doc](enhancements_doc/Enhancement-302.md) | [measwindow](examples/measwindow_examples/) |
| 303 | BUG (completes 302): `.meas dc avg` truncated its window the same way -- averaging over the first-to-last sweep point INSIDE `[from,to]` rather than the requested bounds (0.270250 vs closed form 0.2708333). E-302 had excluded `dc` because a sweep may DESCEND and enters its window at the high end, where an unguarded clip extrapolates. Fixed direction-agnostically by clipping at the ACTUAL crossing between the previous raw sample and the current one, so it works ascending and descending and never fires on a sweep that does not cross. Echoed window corrected too. Still open, in a different function: on a descending sweep `integ`/`rms` return 0.0 with `from= nan` (an i-1 == -1 out-of-bounds read) | ngspice | [doc](enhancements_doc/Enhancement-303.md) | [measwindow](examples/measwindow_examples/) |
| 304 | BUG, memory safety (completes 303): on a DESCENDING dc sweep `.meas dc integ`/`rms` returned 0.0 with `from= nan`, or nothing. `measure_rms_integral` assumes an ascending scale, so the first sample was already above `to`, the end-clip fired at i==0 and interpolated against index i-1 == -1 -- a heap-buffer-overflow AddressSanitizer flags at com_measure2.c:195 -- then broke with a one-element array so the integration sums ran zero times. Fixed by walking samples in order of increasing scale (the identity for ascending data, so tran/ac are byte-identical) with the bounds guard on the traversal position, not the raw index. integ 0.0 -> 0.135416 (closed form 0.135416667), rms -> 0.307458. Two dead out-of-range reads in the tail removed | ngspice | [doc](enhancements_doc/Enhancement-304.md) | [measwindow](examples/measwindow_examples/) |
| 305 | feature: `wcd` -- worst-case-distance / most-probable-failure-point high-sigma, the named remainder of the statistical suite. E-150 `highsigma` uses direction-free scaled-sigma IS; this works in standardised normal space and finds the closest point of the failure region, reporting that distance beta and the first-order probability Phi(-beta) -- the sigma number a designer quotes. Hasofer-Lind/Rackwitz-Fiessler search, cost bounded at a few iterations of (1+ndim) sims instead of the 1e6-1e9 samples plain MC needs to SEE a 4.5-6 sigma event. `-is N` refines it with mean-shift IS centred on the MPFP (986 failures seen in 2000 shifted samples). Dimensionality is discovered, not declared. Verified vs the analytic Gaussian tail: beta exact at 3/4/5/6 sigma, 2-D MPFP on the symmetric point | ngspice | [doc](enhancements_doc/Enhancement-305.md) | [wcd](examples/wcd_examples/) |
| 306 | BUG (the E-241 twin, found by continuing that oracle campaign): E-241 fixed an amplitude normalisation that divided by the ZERO-PADDED transform size instead of the input length, in the `fft` COMMAND (com_fft.c). The identical mistake survived in cmath4.c `cx_fft`, the vector-expression function reached by `let F = fft(v)`. E-241's own discriminator, the DC bin: command reads 2.000000, expression read 1.953613 = 2.0*4001/4096. Not a convention question -- `cx_fft` holds two implementations (real and complex input) and in BOTH the FFTW branch already used `length` while Green's used padded `N`, a few lines apart. `ifft(fft(x))` 2.3e-02 -> 1.1e-16 confirms it from a direction the fix did not aim at. Every Green-kernel caller audited; 1-f noise cannot pad by construction | ngspice | [doc](enhancements_doc/Enhancement-306.md) | [fftexpr](examples/fftexpr_examples/) |
| 307 | CRASH, openvaf-r (found by grammar-based fuzzing of the middle/back end): a `ddt` whose result reaches NO contribution survives dead-code elimination, but `sim_back/topology/lineralize.rs` did `assert!(noise, "ddt should have been deadcode eliminated")` -- a plain assert, not debug_assert, so the SHIPPED compiler crashed ("OpenVAF encountered a problem and has crashed!") on valid Verilog-A. 5 of 3000 seeds hit it; ablation isolates the trigger to ddt + a probe-only branch + if/else + case with no contributions. Fixed by returning `Evaluation::Dead` unconditionally (the branch already taken for the noise case: result -> zero, uses retargeted). A contributing ddt is numerically unchanged. A 2nd, pre-existing ICE surfaced (builder.rs:143, var read before a loop that is its only writer) -- documented, not fixed | openvaf&#8209;r | [doc](enhancements_doc/Enhancement-307.md) | [vafdeadop](examples/vafdeadop_examples/) |
| 308 | CRASH, openvaf-r (2nd from the same fuzz campaign as 307): a variable read BEFORE a loop that is its only writer leaves the loop-carried phi with an incoming value no reachable block defines. A pass drops that value on the dead path but keeps the phi edge, so codegen reached `BuilderVal::get()` on a still-`Undef` value and hit `unreachable!("attempted to read undefined value")` (mir_llvm/builder.rs:143) -- a SHIPPED crash. Fix (provably correct): every reachable block is built before phi completion, so a still-Undef phi input names a value NO reachable block defines (a dead path) -> lower it to LLVM `undef` of the phi's type, not a panic. A LIVE loop-carried accumulator still reads back exactly N*g, proving the undef touches only dead inputs. 8000-seed re-fuzz shows 0 of this and the E-307 crash; a 3rd, rarer pre-existing ICE (packed_option.rs:60) documented, not fixed | openvaf&#8209;r | [doc](enhancements_doc/Enhancement-308.md) | [vafuninitloop](examples/vafuninitloop_examples/) |
| 309 | CRASH, openvaf-r (3rd and final from the same fuzz campaign as 307/308): global value numbering re-queues the USERS of an instruction whose class changed, via `inst_to_dfs[user].unwrap_unchecked()`. But DFSMapping::populate only numbers instructions reachable through cfg_postorder, so a user in an UNREACHABLE block has no DFS id -> unwrap_unchecked panics at packed_option.rs:60 under debug-assertions, and in release returns the reserved sentinel used as an out-of-range BitSet index -- a SHIPPED crash either way (~1/8000). Fix: skip users with no DFS id (they are not in the GVN work list, so re-queuing is a no-op), matching how `get_rank` already tolerates the same None. A CSE-heavy model GVN optimises still gives the exact I = 4*V*g + (V*g)^2. 12000-seed re-fuzz shows 0 of this and the 307/308 crashes | openvaf&#8209;r | [doc](enhancements_doc/Enhancement-309.md) | [vafgvnunreach](examples/vafgvnunreach_examples/) |
| 310 | BUG, openvaf-r (resolves the item 307-309 left open): `simplify_cfg`'s const-branch fold orphaned a block that still had live results; the orphan sweep leaves it (its values are referenced), so a successor phi kept an edge naming a value only reachable through the deleted edge -- an SSA-invalid phi that tripped `debug_assert!(cx.func.validate())` at sim_back/lib.rs. NOT a shipped crash (debug_assert) and PROVEN not a miscompile: a sanitised convergent reproducer gives output bit-identical (0.000e+00) to a valid-MIR reference. Fixed by declining the fold in exactly that case (single_predecessor(dead_dst)==bb with live results) -- always output-preserving, so corpus output is bit-identical (34/34 pairs). 15000-seed re-fuzz: 0 asserts; 332-model corpus 0 validate panics. The last known openvaf-r defect | openvaf&#8209;r | [doc](enhancements_doc/Enhancement-310.md) | [vafcfgphi](examples/vafcfgphi_examples/) |
| 311 | BUG/feature (found oracle-checking rare `.meas` modes): `param`/`expr` measurements worked as a `.meas` dot-card but FAILED from a `.control` `meas` command (`no such function as ...`). do_measure's 2nd pass handles param/expr via nupa_eval; the interactive `meas` bypasses it and calls get_measure2 directly, which has no param/expr case. Fix: com_meas evaluates a param/expr measurement with the ordinary vector evaluator (prior results a1/a2 are single-valued vectors, so it's `let name=(expr)`), re-lexed via cp_lexer. Works unquoted, quoted-no-spaces, and braces-with-spaces; normal meas types byte-identical. Known limitation left: single-quotes-with-internal-spaces is mangled by the .control shell UPSTREAM of meas (use braces) | ngspice | [doc](enhancements_doc/Enhancement-311.md) | [measparam](examples/measparam_examples/) |
| 269 | instance wildcard knob `@#*[param]` (alias `@*[[param]]`): the E-268 counterpart for INSTANCE parameters -- set `param` on EVERY device instance that has it, in place (`alter`/`altermod`, no re-source), so one `sweep @#*[scale] ...` co-varies an instance parameter across all instances. `if_setparam_wildcard_instance` walks each type's models -> `GENinstances` and sets via `doset(dev=inst)` -> `setInstanceParm` (one `parmlookup do_model=0` per type gates membership). `@*[param]`=models, `@#*[param]`/`@*[[param]]`=instances; concrete `@dev[param]` unchanged; absent-param warns. Model wildcard also verified to cover `.model` cards inside subcircuits | ngspice | [doc](enhancements_doc/Enhancement-269.md) | [sweepwild](examples/sweepwild_examples/) |
| 312 | BUG (found oracle-checking XSPICE s_xfer transient vs closed form): every integrating code model (s_xfer, int, d_dt, ...) was first-order O(h) in transient, not O(h²) like native storage elements. Two causes. (a) cm_static_integrate's trapezoidal order-2 arm was a self-flagged backward-Euler stand-in (WARNING - This code needs to be redone). Fixed to the real rule y(n)=y(n-1)+(h/2)(u(n)+u(n-1)); the previous integrand lives in the spare state double cm_analog_alloc already reserves, rotated through CKTstates for free. (b) s_xfer fed its controller-canonical loop back from the PREVIOUS timestep (cm_analog_get_ptr i,1 = lagged/explicit), capping it at O(h) alone; now reads current-iteration states (offset 0) = implicit. Both TRAP and Gear now O(h²); verified vs scipy lsim across 1st/resonant/Butterworth/stiff/zero TFs, plus a self-contained order test (error ratio ~2 pre-fix -> ~4 post-fix) that fails on the pre-fix binary. 246-example regression green both solvers | ngspice | [doc](enhancements_doc/Enhancement-312.md) | [sxferorder](examples/sxferorder_examples/) |
| 313 | BUG x2 (grammar fuzz of the middle/back end, E-307–310 family): two builtin argument type-coercion gaps in hir_ty, both emitted silently by the release compiler. (a) file/string format tasks ($fdisplay/$fwrite/$fstrobe/$fmonitor/$fdebug/$swrite/$sformat) were never type-checked — only the console tasks reached infere_display — so a %g/%e/%f/%r fed an integer kept its int value while the format callback types the param as double: a raw i32 to a double param = invalid LLVM IR (verifier is a debug_assert, off in release), and the callback reads the int's bits as a double = garbage (a $sformat→$sscanf round-trip of 5 read back 2.47e-323). Fix: add the file/string tasks to the infere_display dispatch (it scans for string-literal formats, so the fd/dest prefix is skipped). (b) ddx(integer,…) crashed: infere_ddx recorded the must-be-real cast on the ddx call (already Real) not the argument, so needs_cast saw src==dst==Real and the release aborted. Fix: record it on the argument. Output-preserving: 419-model corpus byte-identical MIR, 0/419 changed; 15000-module re-fuzz clean. Deferred: while(1) infinite-loop CFG crash (needs a design decision) | openvaf&#8209;r | [doc](enhancements_doc/Enhancement-313.md) | [vafargcoerce](examples/vafargcoerce_examples/) |
| 314 | ROBUSTNESS x2 (grammar fuzz, E-307–313 family): const-eval / literal-materialization. (a) two hand-rolled integer const evaluators used unchecked i32 arithmetic — elaborate.rs's E-91 bus-width folder (+/-/negate; its * was already checked) and const_eval.rs's MIR const-fold (Ineg, which E-286 missed making the binary ops wrapping) — so `localparam integer k=2147483647+1` or `-(1<<31)` aborted the overflow-checked build (release wrapped silently). Fixed: checked (elaborate, declines the fold like its *) / wrapping_neg (const_eval). (b) `{N{…}}` replication materializes N copies at COMPILE time; `{'d999999999{"x"}}` (~1e9) allocated gigabytes and HUNG the shipped compiler on ~1 line of source. Fixed: cap the count at 2^20 in concat_rep_count, reject an abusive count with a clean diagnostic. Output-preserving: checked/wrapping ≡ plain on non-overflow, cap only rejects >2^20; 419-corpus MIR unchanged, 248-example regression green | openvaf&#8209;r | [doc](enhancements_doc/Enhancement-314.md) | [vafconstlit](examples/vafconstlit_examples/) |
| 317 | CRASH, openvaf-r (grammar fuzz, E-307-314 family): an `idt(_,IC)`/`idtmod` (integrator with initial condition) inside a statically-false branch crashed codegen. `ceil(0)>1` is always false but ceil() is not const-folded, so the dead branch survives into MIR; its guarded idt-IC state is never used, so codegen prunes the branch CONDITION as dead — yet the Branch instruction survives into osdi::setup::setup_instance, and reading its now-Undef condition hit unreachable!() in the LLVM builder (mir_llvm/builder.rs:143), a shipped crash (exit 101). Same Undef-value class as E-308 (which handled the phi-input case); this is the branch-condition case. Fix: lower an Undef branch condition as constant false (the guarded code is dead either way). Output-preserving: 419-corpus MIR bit-identical (only the reproducer, which was crashing, changes). Deferred from the same hunt: an assertions-only PHI-type mismatch (uninit integer default typed f64) and a .tran convergence livelock | openvaf&#8209;r | [doc](enhancements_doc/Enhancement-317.md) | [vafidtcfg](examples/vafidtcfg_examples/) |
| 315 | CRASH x3 (command/netlist fuzz, E-222–228 / E-270–285 family): three shipped ngspice analysis crashes on adversarial-but-valid input, each now a clean error. [6] .tf on a singular circuit (dangling inductor `l1 2 3 1`, floating nodes) — tfanal.c ignored CKTop's return, so SMPsolve asserted IS_FACTORED on an unfactored matrix (spsolve.c:137, SIGABRT); fixed by propagating the error. [7] a second .pz over a URC device — CKTic zeroed a NULL CKTrhs (the loop vectorises to memset), SIGSEGV; fixed by returning cleanly when the RHS vectors are unallocated. [8] .disto with no distortion sources (a plain resistor) — distoan.c's output section left OUTpBeginPlot's result unchecked, so OUTattributes(NULL acPlot) crashed (SIGSEGV at +268, 0x28); fixed by checking the result at each of the 5 output plots. Legitimate .tf/.pz/.disto unaffected (guards fire only on the failure paths) | ngspice | [doc](enhancements_doc/Enhancement-315.md) | [ngcrashanalysis](examples/ngcrashanalysis_examples/) |
| 316 | BUG (oracle-checking .meas, E-302/303/304 sibling): `.meas AVG` ended one timestep short of `to`. measure_minMaxAvg's final window-clip (E-302) guarded the whole accumulation with `!AlmostEqualUlps(svalue, to, 100)`, so when the first out-of-window sample fell within 100 ULPs of `to` the entire final trapezoid [sprev,to] (a full timestep) was dropped — AVG's window echoed to=6.4599e-4 vs INTEG's 6.4624e-4 (exactly one 2.5e-7 step apart), so AVG != INTEG/(to-from) by ~1.6%. INTEG/RMS always add the final point (interpolating only on overshoot); fix makes AVG match — the guard now gates only the interpolation, not the accumulation. AVG==INTEG/dur (rel 1.6e-6). measwindow(44)/measparam still pass; MIN/MAX unaffected | ngspice | [doc](enhancements_doc/Enhancement-316.md) | [measavgwin](examples/measavgwin_examples/) |
| 318 | BUG (correctness campaign, oracle-checking transient sources): the SFFM and AM voltage sources returned 0 for time<=TD (vsrcload.c), dropping the DC offset VO at the operating point (common TD=0) and over the whole pre-delay window, injecting a spurious startup transient. Decisive oracle — the same quantity two other ways: the SIN case in the same function holds its quiescent value at time<=0, and ngspice's own current-source SFFM (isrcload.c) has no such zeroing (the two SFFM implementations disagreed); SIN/PULSE/EXP/PWL all preserve their offset. Fix: hold the waveform's time=0 value — SFFM=VO+VA*sin(phasec+MDI*sin(phasem)), AM=VO+(VMO+VMA*sin(phasem))*sin(phasec) (=VO for zero phases). No example uses SFFM/AM, so nothing else changes; current-source untouched | ngspice | [doc](enhancements_doc/Enhancement-318.md) | [sffmoffset](examples/sffmoffset_examples/) |
| 319 | BUG (correctness campaign, RF steady-state oracle): the transient-form QPSS (`qpss expr f1 f2 [periods] [maxorder]`, vs the `... hb K1 K2` form) leaked the fundamental into every mixing bin. It computed each 2-D harmonic by a trapezoidal integral of v(t)exp(-j2pi f t) over the raw transient grid's last period — a window not exactly the beat period T, non-uniform, with non-periodic endpoints — so the DC/fundamental leaked ~tstep/T into every bin. A LINEAR two-tone RC (every product must be 0) read ~5.8e-4*|dominant line| (~-45dB), scaling linearly with the DC line; confirmed vs the HB-form (~1e-16) and a plain .tran+DFT. Fix: resample the last period onto a uniform grid over exactly [wend-T,wend) + rectangular-rule DFT (exact for commensurate tones); floor drops ~4 decades to ~-122dB. Real products unchanged (qpss_examples strong IM3 3.75e-4 still matches to 4 digits; single-tone (2,0) matches HB to 5). HB-form untouched | ngspice | [doc](enhancements_doc/Enhancement-319.md) | [qpssleak](examples/qpssleak_examples/) |
| 320 | PERF: sweeping a netlist `.param` no longer forces a full circuit reset (re-parse + subckt-expand + CKTsetup + matrix reorder) at every point. When the swept param feeds only addressable top-level device/model VALUES, `com_sweep` re-evaluates each dependent value against the retained numparam table (new nupa_eval_expr / nupa_recompute_params) and pushes it into the live circuit via a resolved setInstanceParm — no reset. ~11x on a large circuit where the param feeds few devices, 2.6x when it feeds every device; each @dev[param] resolved once, identical expressions evaluated once per point. A conservative classifier disarms to the exact reset path on any subckt-body / structural (node, name, .if, .temp, analysis card, .option, .ic, .nodeset, subckt call) / derived-param use, so a sweep's result can only get faster, never change. sweep command; instance values fast, model values via altermod fallback | ngspice | [doc](enhancements_doc/Enhancement-320.md) | [paramfastsweep](examples/paramfastsweep_examples/) |

</details>

---

## VA_TEST — real-world compile corpus

`VA_TEST/` holds the public **VA-Models** collection as a compile-regression corpus: the industry-standard compact models (BSIM4/6/BULK/CMG/IMG/SOI, PSP 102/103/104, PSP-HV, HiCUM L0/L2, MEXTRAM 504/505, VBIC, EKV 2.6/3, ASM-HEMT, EPFL-HEMT, Angelov, MVSG, diode_cmc, r2/r3_cmc, L-UTSOI, MOSVAR, IGBT, …) — 124 `.va` files in total. `python3 VA_TEST/compile_all.py` compiles every file with the committed `openvaf-r` and regenerates [VA_TEST/compile_report.md](VA_TEST/compile_report.md); **all 92 standalone models compile** (the remaining 32 files are `` `include `` fragments — macro bodies and module-body pieces — reported separately since they aren't standalone modules).

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

Each platform directory also ships ngspice's **XSPICE code models** under
`codemodels/*.cm` with a portable `scripts/spinit`. Export
`SPICE_LIB_DIR="$PWD/bin/<os>/<arch>"` and ngspice loads them at startup so the
`A`-device code-model library (`gain`, `summer`, oscillators, ADC/DAC bridges,
…) is available — see [handbook §3.8](docs/handbook/03-ngspice-workflows.md).
The example scripts set `SPICE_LIB_DIR` automatically.

### Running on Linux

The binaries are built on Ubuntu 22.04, so they run on any distro with **glibc ≥ 2.35** (Ubuntu 22.04+, Debian 12+; an error like ``version `GLIBC_2.39' not found`` means the binary in your checkout predates this baseline — pull the latest). They are dynamically linked against standard system libraries. Install them with your package manager if missing:

**Ubuntu / Debian:**
```bash
sudo apt-get install libreadline8 libx11-6 libxaw7 libxft2 libxext6   # ngspice
sudo apt-get install libllvm18                                        # openvaf-r (Ubuntu 24.04+ / Debian 13+)
```

On Ubuntu 22.04 / Debian 12, whose repos stop at older LLVM versions, get `openvaf-r`'s LLVM 18 runtime from [apt.llvm.org](https://apt.llvm.org/):
```bash
wget https://apt.llvm.org/llvm.sh && chmod +x llvm.sh && sudo ./llvm.sh 18
```

**Fedora / RHEL:**
```bash
sudo dnf install readline libX11 libXaw libXft libXext   # ngspice
sudo dnf install llvm18-libs                             # openvaf-r
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
brew install readline ncurses     # for ngspice
brew install llvm@18              # for openvaf-r (runtime: libLLVM + libunwind)
```

> `openvaf-r` links LLVM dynamically, so it needs Homebrew's `llvm@18` at
> runtime — without it you'll see
> `Library not loaded: .../opt/llvm@18/lib/libunwind.1.dylib` (Intel Macs
> resolve it under `/usr/local/opt`, Apple Silicon under `/opt/homebrew/opt`).

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

---

## Where next? — ngspice vs. a commercial simulator

With the Verilog-A / OSDI device side now on par with commercial tools, the
remaining gaps are all on the **simulator** side. [ngspice vs. Spectre — feature
gap analysis](docs/internals/ngspice_internals/ngspice_gaps.md)
([PDF](docs/internals/ngspice_internals/ngspice_gaps.pdf)) is a category-by-category
✅/⚠️/❌ table, grounded in the ngspice-46 source, showing where ngspice already
matches Spectre (standard analog analyses, core numerics) and where the gaps are
(the RF periodic suite — HB/Pnoise/PAC/PXF/envelope — plus fast-SPICE scale,
high-sigma statistics, and reliability/aging). It closes with a prioritized view
of where to invest next.

A companion note, [KLU vs. Sparse 1.3 solver
notes](docs/internals/ngspice_internals/ngspice_solver_notes.md)
([PDF](docs/internals/ngspice_internals/ngspice_solver_notes.pdf)), documents this
build's two linear solvers: Sparse 1.3 is the **default** and runs everything,
while KLU (opt-in via `.option klu`) matches it on DC/AC/transient but **rejects
noise and pole-zero** and is less robust on stiff transient edges — verified by a
solver-by-solver sweep of the whole example suite.

For the statistical side, [Statistical simulation in
ngspice](docs/internals/ngspice_internals/ngspice_statistics.md)
([PDF](docs/internals/ngspice_internals/ngspice_statistics.pdf)) is a complete,
plotted guide to the whole suite — the random `.param` functions, ordinary Monte
Carlo, Latin-Hypercube sampling (`mcsample`), high-sigma rare-event estimation
(`highsigma`), native process/mismatch correlations (`mccorr`/`mvnorm`), and the
packaged yield command (`montecarlo`) — with worked examples and figures
generated from real ngspice runs.

Not every idea survives measurement. [OSDI/Verilog-A device bypass — an
investigation](docs/internals/ngspice_internals/ngspice_osdi_bypass.md)
([PDF](docs/internals/ngspice_internals/ngspice_osdi_bypass.pdf)) records a full,
correct prototype of element bypass (latency exploitation) for OSDI devices that
was **built, measured, and then reverted**: it delivered no speedup (often a
slowdown), because the per-device Jacobian/residual extraction a *safe* bypass
test needs is not free for a monolithic OSDI `eval()`, and freezing device
linearizations inflated the Newton iteration count enough to erase the eval
savings — and on some circuits broke convergence outright. This mirrors ngspice's
own choice to ship `.option bypass` disabled by default.
