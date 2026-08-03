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

Four hundred and nine enhancements so far — language features, correctness fixes, systematic audits, and simulator-side workflow tooling, each verified end-to-end by a committed example suite and released with a detailed write-up.

**🗂️ Browse them all in the [live feature catalog](https://javanoviceprogrammer.github.io/Ngspice_OpenVAF_Enhancements/)** — every enhancement grouped into 19 feature areas across the compiler and the simulator, searchable, with each entry linking to its write-up.

**📖 Start with the [User Handbook](docs/handbook/README.md)**, which organizes everything by topic: [getting started](docs/handbook/01-getting-started.md), the [Verilog-A feature matrix](docs/handbook/02-verilog-a-language.md), [ngspice workflows](docs/handbook/03-ngspice-workflows.md), and the [limitations & gotchas](docs/handbook/04-limitations-and-gotchas.md). The whole handbook plus the complete text of every enhancement write-up is also one linked PDF: [docs/Ngspice-OpenVAF-Handbook.pdf](docs/Ngspice-OpenVAF-Handbook.pdf).

**🔧 Want to understand the compiler itself?** [OpenVAF Compiler Internals](docs/internals/openvaf_internals/OpenVAF_compiler_internals.md) ([PDF](docs/internals/openvaf_internals/OpenVAF_compiler_internals.pdf)) is a ground-up, no-prior-knowledge walkthrough of how `openvaf-r` turns a Verilog-A model into a `.osdi` library — every stage of the pipeline (lexing → HIR → MIR → automatic differentiation → LLVM → OSDI), with real dumped IR traced end-to-end on a worked example.

**⚙️ Want to understand the simulator itself?** [ngspice Simulator Internals](docs/internals/ngspice_internals/ngspice_simulator_internals.md) ([PDF](docs/internals/ngspice_internals/ngspice_simulator_internals.pdf)) is the companion guide — a ground-up walkthrough of how `ngspice-46` turns a netlist into a running circuit: the shell/engine split, the netlist parser, the `CKTcircuit`, the `SPICEdev` device interface, the sparse-matrix Newton loop, the analyses, and — crucially — how OpenVAF `.osdi` models plug in as first-class devices, traced end-to-end on a worked RC example.

**🛡️ How robust is the compiler?** [OpenVAF Robustness Campaign](docs/internals/openvaf_internals/OpenVAF_robustness_report.md) ([PDF](docs/internals/openvaf_internals/OpenVAF_robustness_report.pdf)) reports a deep robustness audit of `openvaf-r` — the full production-model corpus, ~50 adversarial inputs, and 4,000 mutation-fuzzing iterations — and the four crash/hang paths it found and fixed (Enhancement-147/-148).

**⏱️ How fast does it compile?** [OpenVAF Compile-Time Analysis](docs/internals/openvaf_internals/OpenVAF_compile_time_analysis.md) ([PDF](docs/internals/openvaf_internals/OpenVAF_compile_time_analysis.pdf)) profiles where `openvaf-r`'s compilation time goes (≈70 % LLVM optimizing one `eval` function), why it's bound to a single core despite already parallelizing, and the compile-vs-simulation-speed trade-off of the `-O` level.

The index: **Doc** links each enhancement's detailed write-up, **Examples** links the folder whose verify script pins the behavior.

<details>
<summary><b>📖 Show the full enhancement table</b> — 331 rows, click to expand</summary>

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
| 225 | harden `fft`/`deriv`/`fourier`/`meas`/`?:` evaluator against fuzz crashes | ngspice | [doc](enhancements_doc/Enhancement-225.md) | [cmdfuzz](examples/cmdfuzz_examples/) |
| 226 | rawfile `load` crash hardening (fuzz: missing `Flags:` line → NULL deref) | ngspice | [doc](enhancements_doc/Enhancement-226.md) | [rawfuzz](examples/rawfuzz_examples/) |
| 227 | Touchstone `pre_snp` crash hardening (fuzz: huge `.sNp` port count → heap corruption) | ngspice | [doc](enhancements_doc/Enhancement-227.md) | [snpfuzz](examples/snpfuzz_examples/) |
| 228 | OSDI `.osdi` loader crash hardening (fuzz: reject implausible descriptor counts) | ngspice | [doc](enhancements_doc/Enhancement-228.md) | [osdifuzz](examples/osdifuzz_examples/) |
| 229 | `pre_osdi -f` reloads a recompiled `.osdi` model in-session (no restart) | ngspice | [doc](enhancements_doc/Enhancement-229.md) | [osdireload](examples/osdireload_examples/) |
| 230 | openvaf-r crash hardening round 3 (fuzz: 3 panics → clean errors) | openvaf&#8209;r | [doc](enhancements_doc/Enhancement-230.md) | [vafcrash3](examples/vafcrash3_examples/) |
| 231 | wrdata CSV output: set wr_csv + wrdata -csv flag (any position) | ngspice | [doc](enhancements_doc/Enhancement-231.md) | [csv](examples/csv_examples/) |
| 232 | harden KLU solver-glue (null-checks, collapse-map, bounds) | ngspice | [doc](enhancements_doc/Enhancement-232.md) | [solverfix](examples/solverfix_examples/) |
| 233 | fix KLU glue null-check order and collapse-map gaps | ngspice | [doc](enhancements_doc/Enhancement-233.md) | [solverfix](examples/solverfix_examples/) |
| 234 | `loadpull` PA load/source-pull contours on Smith chart | ngspice | [doc](enhancements_doc/Enhancement-234.md) | [loadpull](examples/loadpull_examples/) |
| 235 | fix `stb` probe-lookup use-after-free; case-insensitive probes | ngspice | [doc](enhancements_doc/Enhancement-235.md) | [stbfix](examples/stbfix_examples/) |
| 236 | fix `.meas` stack overflow on long measurement names | ngspice | [doc](enhancements_doc/Enhancement-236.md) | [measovf](examples/measovf_examples/) |
| 237 | fix `.print`/`.plot`/`.four` overflow on long node names | ngspice | [doc](enhancements_doc/Enhancement-237.md) | [nameovf](examples/nameovf_examples/) |
| 238 | fix NULL-deref on malformed `v(1,` differential token | ngspice | [doc](enhancements_doc/Enhancement-238.md) | [malftoken](examples/malftoken_examples/) |
| 239 | fix NULL-deref on 1-arg `min`/`max`/`pow`/`pwr` | ngspice | [doc](enhancements_doc/Enhancement-239.md) | [funcarity](examples/funcarity_examples/) |
| 240 | fix XSPICE `s_xfer` OOB on static-gain transfer function | ngspice | [doc](enhancements_doc/Enhancement-240.md) | [sxfer](examples/sxfer_examples/) |
| 241 | fix `fft` amplitude norm for non-power-of-2 records | ngspice | [doc](enhancements_doc/Enhancement-241.md) | [fftnorm](examples/fftnorm_examples/) |
| 242 | native N-port device via `pre_snp -native` (direct Y stamp, no OSDI) | ngspice | [doc](enhancements_doc/Enhancement-242.md) | [nport_native](examples/nport_native_examples/) |
| 243 | `pre_snp -osdi` emits ref terminal for identical instance line | ngspice | [doc](enhancements_doc/Enhancement-243.md) | [presnp](examples/presnp_examples/) |
| 244 | fix `nport` unbound-node abort and `pyplot -hist`/`-contour` UAF | ngspice | [doc](enhancements_doc/Enhancement-244.md) | [crashfix2](examples/crashfix2_examples/) |
| 245 | fix `meas` stray-`=` and `altermod` NULL-param derefs | ngspice | [doc](enhancements_doc/Enhancement-245.md) | [crashfix3](examples/crashfix3_examples/) |
| 246 | fix OOB read in `pwl`/`pwlts` code models on mismatched arrays | ngspice | [doc](enhancements_doc/Enhancement-246.md) | [pwlfix](examples/pwlfix_examples/) |
| 247 | fix OOB/UB in `table2d`/`table3d` XSPICE models on degenerate tables | ngspice | [doc](enhancements_doc/Enhancement-247.md) | [tablefix](examples/tablefix_examples/) |
| 248 | fix OOB in `CPL` coupled-line device on excess conductors | ngspice | [doc](enhancements_doc/Enhancement-248.md) | [cplfix](examples/cplfix_examples/) |
| 249 | validate `URC` lump count and reject negative R/L/G/C in `LTRA` | ngspice | [doc](enhancements_doc/Enhancement-249.md) | [tlinefix](examples/tlinefix_examples/) |
| 250 | fix UB `1<<n` shift in `d_lut`/`d_genlut` by capping input ports | ngspice | [doc](enhancements_doc/Enhancement-250.md) | [dlutfix](examples/dlutfix_examples/) |
| 251 | prove HB converges to exact steady state; tighten tolerance | ngspice | [doc](enhancements_doc/Enhancement-251.md) | [hb](examples/hb_examples/) |
| 252 | fix heap OOB writes in `xfer`/`file_source` file parsers | ngspice | [doc](enhancements_doc/Enhancement-252.md) | [filefix](examples/filefix_examples/) |
| 253 | `rfstab` two-port stability report (K, Delta, mu, MSG/MAG) | ngspice | [doc](enhancements_doc/Enhancement-253.md) | [rfstab](examples/rfstab_examples/) |
| 254 | `pyplot -smith` Smith-chart view for S-params | ngspice | [doc](enhancements_doc/Enhancement-254.md) | [pyplotsmith](examples/pyplotsmith_examples/) |
| 255 | prove `.disto` exact vs HB; warn on B-source nonlinearities | ngspice | [doc](enhancements_doc/Enhancement-255.md) | [distoexact](examples/distoexact_examples/) |
| 256 | fix DC false-convergence on singular-derivative B-sources | ngspice | [doc](enhancements_doc/Enhancement-256.md) | [bsrcconv](examples/bsrcconv_examples/) |
| 257 | extend DC false-convergence guard to `.tran` op point | ngspice | [doc](enhancements_doc/Enhancement-257.md) | [bsrcconv](examples/bsrcconv_examples/) |
| 258 | extend false-convergence guard to `.dc` sweep cold-start | ngspice | [doc](enhancements_doc/Enhancement-258.md) | [bsrcconv](examples/bsrcconv_examples/) |
| 259 | verify TRAP/Gear2/BE integration order and energy behavior | ngspice | [doc](enhancements_doc/Enhancement-259.md) | [integaccuracy](examples/integaccuracy_examples/) |
| 260 | verify LTE step-controller accuracy tracks `reltol` on stiff circuit | ngspice | [doc](enhancements_doc/Enhancement-260.md) | [integaccuracy](examples/integaccuracy_examples/) |
| 261 | regularize `sqrt()` derivative singularity at V=0 in autodiff | openvaf&#8209;r | [doc](enhancements_doc/Enhancement-261.md) | [vafsqrtguard](examples/vafsqrtguard_examples/) |
| 262 | regularize fractional `pow(V,Y)` derivative singularity at V=0 | openvaf&#8209;r | [doc](enhancements_doc/Enhancement-262.md) | [vafsqrtguard](examples/vafsqrtguard_examples/) |
| 263 | harden 3 fuzz-found compiler panics (`ddt`/`ddx`/empty module) to clean errors | openvaf&#8209;r | [doc](enhancements_doc/Enhancement-263.md) | [vafcrash4](examples/vafcrash4_examples/) |
| 264 | instance-array flatten O(N^2)->O(N) plus fix codegen stack overflow | openvaf&#8209;r | [doc](enhancements_doc/Enhancement-264.md) | [vafhang](examples/vafhang_examples/) |
| 265 | fix `laplace_*`/`zi_*` bad-coefficient and empty-denominator crash | openvaf&#8209;r | [doc](enhancements_doc/Enhancement-265.md) | [vaflaplace](examples/vaflaplace_examples/) |
| 266 | announce linear solver once per multi-point run, not every analysis | ngspice | [doc](enhancements_doc/Enhancement-266.md) | [solverannounce](examples/solverannounce_examples/) |
| 267 | `sweep` keeps bus-node names as `ph[0]` not `ph_0_` | ngspice | [doc](enhancements_doc/Enhancement-267.md) | [sweepbus](examples/sweepbus_examples/) |
| 268 | wildcard model-param knob `@*[param]` sets every model in place | ngspice | [doc](enhancements_doc/Enhancement-268.md) | [sweepwild](examples/sweepwild_examples/) |
| 269 | `@#*[param]` instance-wildcard knob sets param on all instances | ngspice | [doc](enhancements_doc/Enhancement-269.md) | [sweepwild](examples/sweepwild_examples/) |
| 270 | `sweep` validates numeric bounds (reject non-numeric/inf/overflow) | ngspice | [doc](enhancements_doc/Enhancement-270.md) | [sweepbounds](examples/sweepbounds_examples/) |
| 271 | fix `let` out-of-bounds read on empty left-hand side | ngspice | [doc](enhancements_doc/Enhancement-271.md) | [letoob](examples/letoob_examples/) |
| 272 | fix `alter`/`sweep` NULL-param SEGV on m-named device | ngspice | [doc](enhancements_doc/Enhancement-272.md) | [alternull](examples/alternull_examples/) |
| 273 | fix cmaths `%`/`vector`/`unitvec` double-to-int cast UB | ngspice | [doc](enhancements_doc/Enhancement-273.md) | [mathcast](examples/mathcast_examples/) |
| 274 | fix vector index `v[expr]` non-finite cast UB | ngspice | [doc](enhancements_doc/Enhancement-274.md) | [idxcast](examples/idxcast_examples/) |
| 275 | fix `ifft()` heap over-read on real-input vector | ngspice | [doc](enhancements_doc/Enhancement-275.md) | [ifftreal](examples/ifftreal_examples/) |
| 276 | fix `rnd()` non-finite operand cast UB | ngspice | [doc](enhancements_doc/Enhancement-276.md) | [rndcast](examples/rndcast_examples/) |
| 277 | fix `deriv()` complex-vector over-read and wrong result | ngspice | [doc](enhancements_doc/Enhancement-277.md) | [derivcx](examples/derivcx_examples/) |
| 278 | fix `integ`/`deriv`/`ifft` over-read when length != plot scale | ngspice | [doc](enhancements_doc/Enhancement-278.md) | [scaleguard](examples/scaleguard_examples/) |
| 279 | guard remaining `(int)floor` user-value casts (`let`/`set`/`meas`) | ngspice | [doc](enhancements_doc/Enhancement-279.md) | [castguard](examples/castguard_examples/) |
| 280 | fix OOB write on out-of-range single index in `let` assignment | ngspice | [doc](enhancements_doc/Enhancement-280.md) | [letidxoob](examples/letidxoob_examples/) |
| 281 | fix `deriv()` heap over-read on a partial last block | ngspice | [doc](enhancements_doc/Enhancement-281.md) | [derivgroup](examples/derivgroup_examples/) |
| 282 | fix `asciiplot` axis-label over-read on 3-digit exponent | ngspice | [doc](enhancements_doc/Enhancement-282.md) | [plotlabel](examples/plotlabel_examples/) |
| 283 | fix plot-coordinate UB casting non-finite doubles to int | ngspice | [doc](enhancements_doc/Enhancement-283.md) | [plotcoord](examples/plotcoord_examples/) |
| 284 | `@*[[p]]` wildcard names the working instance-vs-model form | ngspice | [doc](enhancements_doc/Enhancement-284.md) | [wildparam](examples/wildparam_examples/) |
| 285 | fix plot/wrdata/`.meas` OOB and complex-vector NULL deref | ngspice | [doc](enhancements_doc/Enhancement-285.md) | [veclenmix](examples/veclenmix_examples/) |
| 286 | fix const-fold int div-by-zero crash; wrapping arith matches codegen | openvaf&#8209;r | [doc](enhancements_doc/Enhancement-286.md) | [vafcodegen](examples/vafcodegen_examples/) |
| 287 | fix const-fold branch leaving stale phi edge (broken SSA) | openvaf&#8209;r | [doc](enhancements_doc/Enhancement-287.md) | [vafcodegen](examples/vafcodegen_examples/) |
| 288 | fix `hypot` declared unary but called binary (invalid IR) | openvaf&#8209;r | [doc](enhancements_doc/Enhancement-288.md) | [vafcodegen](examples/vafcodegen_examples/) |
| 289 | fix `$clog2` invalid IR (`llvm.ctlz` missing type suffix) | openvaf&#8209;r | [doc](enhancements_doc/Enhancement-289.md) | [vafcodegen](examples/vafcodegen_examples/) |
| 290 | fix `$temperature` operator-arg wrong struct offset (SIGSEGV) | openvaf&#8209;r | [doc](enhancements_doc/Enhancement-290.md) | [vafcodegen](examples/vafcodegen_examples/) |
| 291 | fix `max`/`min`/`abs` in `case` default leaving block unsealed | openvaf&#8209;r | [doc](enhancements_doc/Enhancement-291.md) | [vafcodegen](examples/vafcodegen_examples/) |
| 292 | fix small-signal pruning crash on missing linear-contrib key | openvaf&#8209;r | [doc](enhancements_doc/Enhancement-292.md) | [vafcodegen](examples/vafcodegen_examples/) |
| 293 | fix `ddt(ddt(x))` directly-nested analog-operator crash | openvaf&#8209;r | [doc](enhancements_doc/Enhancement-293.md) | [vafcodegen](examples/vafcodegen_examples/) |
| 294 | fix `Branch`-to-`Jump` rewrite leaving stale condition use | openvaf&#8209;r | [doc](enhancements_doc/Enhancement-294.md) | [vafcodegen](examples/vafcodegen_examples/) |
| 295 | add regression guards for 4x4 matrices and param-slot readback | openvaf&#8209;r | [doc](enhancements_doc/Enhancement-295.md) | [vafcodegen](examples/vafcodegen_examples/) |
| 296 | `pyplot` figure styling via 7 `set` vars (grid, legend, dpi) | ngspice | [doc](enhancements_doc/Enhancement-296.md) | [pyplotmore](examples/pyplotmore_examples/) |
| 297 | `pyplot -fft` one-sided amplitude spectrum | ngspice | [doc](enhancements_doc/Enhancement-297.md) | [pyplotmore](examples/pyplotmore_examples/) |
| 298 | `pyplot -bode`/`-nyquist`/`-polar` complex AC views | ngspice | [doc](enhancements_doc/Enhancement-298.md) | [pyplotmore](examples/pyplotmore_examples/) |
| 299 | `pyplot` overlay sizes to longest run + `pyplot_cursor` crosshair | ngspice | [doc](enhancements_doc/Enhancement-299.md) | [pyplotmore](examples/pyplotmore_examples/) |
| 300 | `pyplot_mplcursors` selects mplcursors hover-cursor backend | ngspice | [doc](enhancements_doc/Enhancement-300.md) | [pyplotmore](examples/pyplotmore_examples/) |
| 301 | `pyplot_cursor` single master switch for interactive cursor | ngspice | [doc](enhancements_doc/Enhancement-301.md) | [pyplotmore](examples/pyplotmore_examples/) |
| 302 | `.meas avg` clips window to [from,to] | ngspice | [doc](enhancements_doc/Enhancement-302.md) | [measwindow](examples/measwindow_examples/) |
| 303 | `.meas dc avg` clips window to [from,to] | ngspice | [doc](enhancements_doc/Enhancement-303.md) | [measwindow](examples/measwindow_examples/) |
| 304 | fix `.meas dc integ`/`rms` OOB on descending dc sweep | ngspice | [doc](enhancements_doc/Enhancement-304.md) | [measwindow](examples/measwindow_examples/) |
| 305 | `wcd` worst-case-distance / MPFP high-sigma analysis | ngspice | [doc](enhancements_doc/Enhancement-305.md) | [wcd](examples/wcd_examples/) |
| 306 | fix `fft()` vector-expr amplitude scaled by padded size | ngspice | [doc](enhancements_doc/Enhancement-306.md) | [fftexpr](examples/fftexpr_examples/) |
| 307 | fix compiler crash on `ddt` reaching no contribution | openvaf&#8209;r | [doc](enhancements_doc/Enhancement-307.md) | [vafdeadop](examples/vafdeadop_examples/) |
| 308 | fix codegen crash on var read before its only-writer loop | openvaf&#8209;r | [doc](enhancements_doc/Enhancement-308.md) | [vafuninitloop](examples/vafuninitloop_examples/) |
| 309 | fix GVN crash re-queuing users in unreachable block | openvaf&#8209;r | [doc](enhancements_doc/Enhancement-309.md) | [vafgvnunreach](examples/vafgvnunreach_examples/) |
| 310 | fix `simplify_cfg` const-fold leaving SSA-invalid phi | openvaf&#8209;r | [doc](enhancements_doc/Enhancement-310.md) | [vafcfgphi](examples/vafcfgphi_examples/) |
| 311 | `.control meas` supports `param`/`expr` measurements | ngspice | [doc](enhancements_doc/Enhancement-311.md) | [measparam](examples/measparam_examples/) |
| 312 | fix XSPICE integrating code models to true O(h^2) transient | ngspice | [doc](enhancements_doc/Enhancement-312.md) | [sxferorder](examples/sxferorder_examples/) |
| 313 | type-check `$fwrite`/`$sformat` format args, fix `ddx(int)` crash | openvaf&#8209;r | [doc](enhancements_doc/Enhancement-313.md) | [vafargcoerce](examples/vafargcoerce_examples/) |
| 314 | fix const-fold int overflow abort and cap `{N{...}}` replication | openvaf&#8209;r | [doc](enhancements_doc/Enhancement-314.md) | [vafconstlit](examples/vafconstlit_examples/) |
| 315 | clean-error `.tf`/`.pz`/`.disto` crashes on degenerate circuits | ngspice | [doc](enhancements_doc/Enhancement-315.md) | [ngcrashanalysis](examples/ngcrashanalysis_examples/) |
| 316 | fix `.meas avg` dropping final timestep before `to` | ngspice | [doc](enhancements_doc/Enhancement-316.md) | [measavgwin](examples/measavgwin_examples/) |
| 317 | fix `idt`-IC codegen crash in statically-false branch | openvaf&#8209;r | [doc](enhancements_doc/Enhancement-317.md) | [vafidtcfg](examples/vafidtcfg_examples/) |
| 318 | fix SFFM/AM voltage sources dropping DC offset before TD | ngspice | [doc](enhancements_doc/Enhancement-318.md) | [sffmoffset](examples/sffmoffset_examples/) |
| 319 | fix `qpss` transient-form spectral leakage into mixing bins | ngspice | [doc](enhancements_doc/Enhancement-319.md) | [qpssleak](examples/qpssleak_examples/) |
| 320 | `sweep` of a `.param` updates values in place, no full reset | ngspice | [doc](enhancements_doc/Enhancement-320.md) | [paramfastsweep](examples/paramfastsweep_examples/) |
| 321 | extend `.param` fast-sweep to subcircuit-internal device values | ngspice | [doc](enhancements_doc/Enhancement-321.md) | [paramfastsweep](examples/paramfastsweep_examples/) |
| 322 | `optimize` reuses `.param` fast-path, no per-eval reset | ngspice | [doc](enhancements_doc/Enhancement-322.md) | [optimize](examples/optimize_examples/) |
| 323 | arm `optimize` fast-path for small OSDI fits (weight OSDI 30x) | ngspice | [doc](enhancements_doc/Enhancement-323.md) | [optimize](examples/optimize_examples/) |
| 324 | fix `$fatal` stranding code in an unreachable block (2 shipped crashes) | openvaf&#8209;r | [doc](enhancements_doc/Enhancement-324.md) | [vaffatalcfg](examples/vaffatalcfg_examples/) |
| 325 | bound materialized size of `{n{...}}` (string arity hang, 2^40 u32 wrap) | openvaf&#8209;r | [doc](enhancements_doc/Enhancement-325.md) | [vafconcatsize](examples/vafconcatsize_examples/) |
| 326 | fix shipped SIGSEGV: cross-namespace `Value` compare mis-typed init cache slots | openvaf&#8209;r | [doc](enhancements_doc/Enhancement-326.md) | [vafinitcache](examples/vafinitcache_examples/) |
| 327 | fix `ddx` crash on reverse-oriented or ground unknowns (now compile) | openvaf&#8209;r | [doc](enhancements_doc/Enhancement-327.md) | [vafddxunknown](examples/vafddxunknown_examples/) |
| 328 | fix crash: dynamic array index used directly as a contribution RHS | openvaf&#8209;r | [doc](enhancements_doc/Enhancement-328.md) | [vafdynidx](examples/vafdynidx_examples/) |
| 329 | fix crash: GRAVESTONE phi operand in the small-signal network builder | openvaf&#8209;r | [doc](enhancements_doc/Enhancement-329.md) | [vafssngravestone](examples/vafssngravestone_examples/) |
| 330 | fix compiler hang: `ddx` in a runtime loop now a clean LRM 4.5.1 error | openvaf&#8209;r | [doc](enhancements_doc/Enhancement-330.md) | [vafddxloop](examples/vafddxloop_examples/) |
| 331 | fix crash: `BitSet::contains` panicked outside its domain (dense rows) | openvaf&#8209;r | [doc](enhancements_doc/Enhancement-331.md) | [vafbitsetdomain](examples/vafbitsetdomain_examples/) |
| 332 | fix wrong charge: summing 3+ `ddt()` terms dropped all but one | openvaf&#8209;r | [doc](enhancements_doc/Enhancement-332.md) | [vafddtsum](examples/vafddtsum_examples/) |
| 333 | fix crash: integer division by a literal zero SIGTRAPped the simulator | openvaf&#8209;r | [doc](enhancements_doc/Enhancement-333.md) | [vafdivzero](examples/vafdivzero_examples/) |
| 334 | fix crash: `INT_MIN/-1` and out-of-range shifts also SIGTRAPped (E-333 gap) | openvaf&#8209;r | [doc](enhancements_doc/Enhancement-334.md) | [vafintub](examples/vafintub_examples/) |
| 335 | fix wrong answers: `!=` vs NaN, runtime shift masking, fast-math folds on doubles | openvaf&#8209;r | [doc](enhancements_doc/Enhancement-335.md) | [vafieee](examples/vafieee_examples/) |
| 336 | fix OSDI binding: param `M` taken as multiplier, case collisions, stale Jacobian count | both | [doc](enhancements_doc/Enhancement-336.md) | [osdiparam](examples/osdiparam_examples/) |
| 337 | keep `x*0` fold: removing it shifted HiSIM2 drain current 10x (E-335 overreach) | openvaf&#8209;r | [doc](enhancements_doc/Enhancement-337.md) | [vafmulzero](examples/vafmulzero_examples/) |
| 338 | fix hang: 64-bit bus range overflowed the width guard (7.6 GB in 9 s) | ngspice | [doc](enhancements_doc/Enhancement-338.md) | [busoverflow](examples/busoverflow_examples/) |
| 339 | fix crash: `v()` with 3+ node names double-freed (print/let/pyplot) | ngspice | [doc](enhancements_doc/Enhancement-339.md) | [vfuncarity](examples/vfuncarity_examples/) |
| 340 | fix nondeterminism: implicit-net declaration order came from HashMap walk | openvaf&#8209;r | [doc](enhancements_doc/Enhancement-340.md) | [vafdeterminism](examples/vafdeterminism_examples/) |
| 341 | fix crash: `sweep -analysis reset/remcirc` freed the circuit mid-loop | ngspice | [doc](enhancements_doc/Enhancement-341.md) | [sweepanalysis](examples/sweepanalysis_examples/) |
| 342 | fix crash: rawfile `Option: plots` use-after-free; `unset plots` double free | ngspice | [doc](enhancements_doc/Enhancement-342.md) | [usrvarown](examples/usrvarown_examples/) |
| 343 | perf: sweep no longer O(N&#178;) -- 26.6x at 16k points; `cp_getvar` built all 5 usrvars per call | ngspice | [doc](enhancements_doc/Enhancement-343.md) | [sweepscale](examples/sweepscale_examples/) |
| 344 | perf: `.model` params join the fast `.param` sweep's direct set -- now as cheap as instance params | ngspice | [doc](enhancements_doc/Enhancement-344.md) | [modelparamset](examples/modelparamset_examples/) |
| 345 | perf: sweep is now LINEAR -- plot naming no longer walks the plot list; 87x at 64k points | ngspice | [doc](enhancements_doc/Enhancement-345.md) | [plotname](examples/plotname_examples/) |
| 346 | fix: fast `.param` path froze random draws reset re-drew; adds the Monte Carlo tier | ngspice | [doc](enhancements_doc/Enhancement-346.md) | [mcfastpath](examples/mcfastpath_examples/) |
| 347 | fix: SSA re-builder no longer mints an Invalid phi operand (assertions build clean) | openvaf&#8209;r | [doc](enhancements_doc/Enhancement-347.md) | [ssavalid](examples/ssavalid_examples/) |
| 348 | fix crash: `.pss` segfaulted on a short argument list, and on `harmonics 0` at full arity | ngspice | [doc](enhancements_doc/Enhancement-348.md) | [pssargs](examples/pssargs_examples/) |
| 349 | fix crash: a mistyped node name on `tf`/`pz`/`noise`/`sens`/`pss` killed the process | ngspice | [doc](enhancements_doc/Enhancement-349.md) | [nodetypo](examples/nodetypo_examples/) |
| 350 | fix: a sweep now restores its `.param`; repeat sweeps no longer disarm the fast path | ngspice | [doc](enhancements_doc/Enhancement-350.md) | [sweeprestore](examples/sweeprestore_examples/) |
| 351 | fix crash: `sens` killed ngspice on any OSDI model with an internal node | ngspice | [doc](enhancements_doc/Enhancement-351.md) | [osdisens](examples/osdisens_examples/) |
| 352 | `.disto` for Verilog-A devices via OSDI 0.8 Taylor tensors; no variable-count limit | both | [doc](enhancements_doc/Enhancement-352.md) | [osdidisto](examples/osdidisto_examples/) |
| 353 | `.disto` now works for models using `$limit`, i.e. every production compact model | openvaf-r | [doc](enhancements_doc/Enhancement-353.md) | [limitdisto](examples/limitdisto_examples/) |
| 359 | `.disto` rebuilt: tensors differenced from the analytic Jacobian in ngspice, so compile time and object size return to baseline | ngspice | [doc](enhancements_doc/Enhancement-359.md) | [osdidisto](examples/osdidisto_examples/) |
| 360 | fix: a second Verilog-A model no longer silences the first in `.disto` (per-model tensor cache) | ngspice | [doc](enhancements_doc/Enhancement-360.md) | [osdidisto](examples/osdidisto_examples/) |
| 361 | fix: ASan/UBSan in `.disto` — out-of-bounds read of the solution vector, and `(int)NaN` point count on degenerate sweeps | ngspice | [doc](enhancements_doc/Enhancement-361.md) | [osdidisto](examples/osdidisto_examples/) |
| 362 | fuzzing analysis-card sweep parameters: 7 fixes — counts cast to int reaching allocators, and an unbounded `.dc` sweep | ngspice | [doc](enhancements_doc/Enhancement-362.md) | [sweepguard](examples/sweepguard_examples/) |
| 363 | fix: two compiler crashes from cross-feature fuzzing — a block merged into itself (`case` in a `do-while`), and array parameters never instance-renamed | openvaf-r | [doc](enhancements_doc/Enhancement-363.md) | [vafcfg](examples/vafcfg_examples/) |
| 364 | transient noise for OSDI devices — Verilog-A `white_noise`/`flicker_noise` injected into `.tran`, activating automatically when the deck has a `trnoise` source | ngspice | [doc](enhancements_doc/Enhancement-364.md) | [trnoise](examples/trnoise_examples/) |
| 365 | fix: `pz` left device matrix bindings dangling, so a following `hb` returned a silently wrong result (and read freed memory) | ngspice | [doc](enhancements_doc/Enhancement-365.md) | [pzhb](examples/pzhb_examples/) |
| 366 | fix: two more sites of the E-365 stale-binding class — `pz` then `qpss`, and a KLU NULL check that reported the NULL then dereferenced it | ngspice | [doc](enhancements_doc/Enhancement-366.md) | [pzklu](examples/pzklu_examples/) |
| 367 | fix: `sweep` plots were named `unknown<N>` and the summary quoted a literal `'sweep'` no plot answered to; eight plot types registered and the real name printed | ngspice | [doc](enhancements_doc/Enhancement-367.md) | [sweepname](examples/sweepname_examples/) |
| 368 | fix: the periodic small-signal analyses named their plots wrong — `pxf` was `unknown<N>`, and `pac`/`psp`/`pnoise`/`qpnoise`/`phasenoise`/`qpss` each collided with an unrelated analysis | ngspice | [doc](enhancements_doc/Enhancement-368.md) | [periodicnames](examples/periodicnames_examples/) |
| 369 | fix: closes the E-365/366 stale-binding class — a KLU pole-zero binding was cleared only when re-established, so a later analysis dereferenced freed memory | ngspice | [doc](enhancements_doc/Enhancement-369.md) | [klubind](examples/klubind_examples/) |
| 370 | fix: every `.pz` re-expanded a URC subcircuit, creating nodes past the allocated RHS — a heap-buffer-overflow hiding under a passing crash fixture | ngspice | [doc](enhancements_doc/Enhancement-370.md) | [urcpz](examples/urcpz_examples/) |
| 371 | plot naming and dates: per-type numbering, so the first sweep is `sweep1` not `sweep500`; every plot now carries a date (command-created plots printed `(null)`) | ngspice | [doc](enhancements_doc/Enhancement-371.md) | [plotname](examples/plotname_examples/) |
| 372 | fix: `unset plots` printed a spurious `Internal Error: var 112` — a `%d` fed a dereferenced `char *`, on a branch valid input always reaches | ngspice | [doc](enhancements_doc/Enhancement-372.md) | [unsetvar](examples/unsetvar_examples/) |
| 373 | fix: a rawfile write/load round trip dropped the x-axis column from `print` (`pl_ndims` never restored) and renamed the `.dc` sweep axis to `v(v-sweep)` | ngspice | [doc](enhancements_doc/Enhancement-373.md) | [rawtrip](examples/rawtrip_examples/) |
| 374 | fix: `setseed` did not seed transient noise — the Wallace generator's pools were filled at startup from `getpid()` and never rebuilt | ngspice | [doc](enhancements_doc/Enhancement-374.md) | [setseed](examples/setseed_examples/) |
| 375 | fix: a loop that provably cannot finish is now a compile error — it used to emit a model that hung the simulator with no diagnostic; also closes 3 codegen crashes on `disable` | openvaf-r | [doc](enhancements_doc/Enhancement-375.md) | [vafloop](examples/vafloop_examples/) |
| 376 | fix: `$dist_*` returned `real`; the LRM makes it integer (`$rdist_*` is the real family) — needed a `ficast` in the lowering too, or the value read as 0 | openvaf-r | [doc](enhancements_doc/Enhancement-376.md) | [distint](examples/distint_examples/) |
| 377 | fix: OSDI diagnostics — name glued to its argument, no newline, no `free`, and `LOG_LVL_MASK` 8 made every severity report as `OSDI(debug)` on stdout | both | [doc](enhancements_doc/Enhancement-377.md) | [simparamdiag](examples/simparamdiag_examples/) |
| 378 | fix: a Verilog-A `$fatal` during the operating point was read as non-convergence, so the gmin/source ladder retried it 373x and blamed `timestep too small` | ngspice | [doc](enhancements_doc/Enhancement-378.md) | [opfatal](examples/opfatal_examples/) |
| 379 | fix: `cargo test --workspace` now builds and no longer overwrites checked-in source — verilogae drift, and three sourcegen generators that had fallen behind the files they generate | openvaf-r | [doc](enhancements_doc/Enhancement-379.md) | n/a |
| 380 | fix: a `.dc` sweep inherited stale integration coefficients from a preceding `pss`/`tran`/`envelope`, adding a spurious `ag[0]*cap` to every charge-storing device — 45% silent error | ngspice | [doc](enhancements_doc/Enhancement-380.md) | [dcstate](examples/dcstate_examples/) |
| 381 | fix: `stb` handed its probe sources back with `ac = 0` instead of their original values, so a following `.ac` returned all zeros | ngspice | [doc](enhancements_doc/Enhancement-381.md) | [stbrestore](examples/stbrestore_examples/) |
| 382 | fix: `loadpull` left the user's tuner R/L/C at the last swept grid point instead of restoring them, so a following analysis ran against the wrong network | ngspice | [doc](enhancements_doc/Enhancement-382.md) | [lprestore](examples/lprestore_examples/) |
| 383 | fix: four unreachable `plotabs[]` entries named plots after a different analysis — `envelope` as `op1`, `qpac` as `pac1`, `qpxf` as `pxf1`, `spectrum` as `sp1` | ngspice | [doc](enhancements_doc/Enhancement-383.md) | [plotorder](examples/plotorder_examples/) |
| 384 | fix: a transient after `sens` returned every node zero — plus `sens`/`sp` aborting the process, a silent partial S-matrix at `z0<=0`, an OSDI `DT` alias, and two device-table flags | ngspice | [doc](enhancements_doc/Enhancement-384.md) | [sensstate](examples/sensstate_examples/) |
| 385 | fix: `sens ac` zeroed VCCS/CCCS sources and `sweep` never restored an `alter`/`altermod` knob — found by a state-restoration audit that ships with it | ngspice | [doc](enhancements_doc/Enhancement-385.md) | [staterestore](examples/staterestore_examples/) |
| 386 | fix: the six sensitivity queries returned the previous query's value on every device — first seen as denormal garbage from a reused static | ngspice | [doc](enhancements_doc/Enhancement-386.md) | [senscplx](examples/senscplx_examples/) |
| 387 | fix: an empty `()` expression crashed openvaf-r with an internal compiler error; `-DNAME=VALUE` defined a macro called `NAME=VALUE`; a bad `TMPDIR` aborted via an uncaught C++ exception | openvaf-r | [doc](enhancements_doc/Enhancement-387.md) | [vafice](examples/vafice_examples/) |
| 388 | fix: `-D` macro values are now substituted (`-DK=5.5` → 5.5, bare `-DK` → 1 as documented); the expression-depth guard says "nests too deeply" instead of a bogus token error | openvaf-r | [doc](enhancements_doc/Enhancement-388.md) | [vafdefine](examples/vafdefine_examples/) |
| 389 | fix: a loop whose control variable is written but never changes (`k = k + 0`) compiled and then hung the simulator; ANSI and combined analog-function argument declarations are accepted; `$table_model` takes runtime array data; both quarantined code generators repaired and re-enabled | openvaf-r | [doc](enhancements_doc/Enhancement-389.md) | [vafopenitems](examples/vafopenitems_examples/) |
| 390 | fix: a `case` inside a `do-while` compiled into an infinite loop that hung the simulator (and crashed the compiler when nested in a loop); ANSI function args without a direction returned 0; `analog` blocks inside `generate` were silently dropped; `disable` with an unknown label was a silent no-op; `$table_model` runtime arrays now sort, de-duplicate and honour the cubic code, and an unusable data file is reported | openvaf-r | [doc](enhancements_doc/Enhancement-390.md) | [vafcaseloop](examples/vafcaseloop_examples/) |
| 391 | fix: a repeated abscissa in a runtime `$table_model` gave a different cubic spline than the identical compile-time table; repeats are now compacted out, with the natural boundary and the end tangent following the live knots | openvaf-r | [doc](enhancements_doc/Enhancement-391.md) | [vaftabledup](examples/vaftabledup_examples/) |
| 392 | fix: module instantiation was unvalidated -- a wrong port count, a port name the target lacks, and a `#(.param())` override naming no parameter all compiled clean, silently mis-wiring or leaving the default in place; a `$mfactor` override was zipped onto the first parameter instead; `generate` did not rename analog-block labels or function names, and rewrote the name inside a named connection; the runtime `$table_model` sort silently gave up above 64 knots (now a stable Batcher network to 256, a compile error beyond); a `localparam` is accepted as a generate bound; and `-2147483648` folded as a real, so integer division rounded and arithmetic saturated instead of wrapping | openvaf-r | [doc](enhancements_doc/Enhancement-392.md) | [vafinstcheck](examples/vafinstcheck_examples/) |
| 393 | fix: a `localparam` could size a bus but not index one -- `n[K]` was rejected as non-constant, as was a plain literal expression like `n[2+1]`; all three places that resolve a bit-select now fold it (an index in the analog body, a branch endpoint, and a port connection), while a plain `parameter` is still refused because it binds at simulation time | openvaf-r | [doc](enhancements_doc/Enhancement-393.md) | [vafconstidx](examples/vafconstidx_examples/) |
| 394 | fix: six ngspice/OSDI plumbing defects -- the subcircuit multiplier `X ... m=` never reached an OSDI device (1x instead of Nx in every analysis) and nested multipliers did not compound even for built-in devices; instance `temp=` was used as Kelvin without converting from Celsius (a VA diode off by 22 orders of magnitude, and `temp=0` divided by zero); `.option scale` and `.options savecurrents` never reached OSDI devices; and `$simparam$str("analysis_name")` contradicted `analysis()` | both | [doc](enhancements_doc/Enhancement-394.md) | [osdiplumb](examples/osdiplumb_examples/) |
| 395 | fix: nine openvaf-r defects -- a seeded `$random`/`$dist_*` returns a CONSTANT inside a loop, which is a deliberate [E-10](enhancements_doc/Enhancement-10.md) trade (advancing the seed in place breaks DC/transient convergence, measured) and is now reported by a new `rng_in_loop` lint instead of being silent; `laplace_np`/`zp`/`zd` built products of (s - r) instead of (1 - s/r), so DC gain was off by the root product; a runtime `$table_model` clamped instead of extrapolating past repeated end knots; five of the LRM's table control codes were silently ignored; `$discontinuity;` with no argument crashed; a foreign discipline's access function silently aliased the native one; and genvar name collisions, duplicate named ports and parameters, mixed positional/named connection lists, and a parameter set alongside its `aliasparam` were all accepted in silence | both | [doc](enhancements_doc/Enhancement-395.md) | [langguard](examples/langguard_examples/) |
| 396 | fix: ten openvaf-r defects -- `$limit` with any unresolvable name or arity (including `fetlim` spelled as the LRM documents it) left a NULL function pointer that the model then CALLED, **segfaulting ngspice with zero output**; [E-335](enhancements_doc/Enhancement-335.md)'s parameter-collision warning compared keywords only, so it fired on almost every industry model that declares the conventional `dtemp` -- 69 spurious warnings across the corpus, now 5 by comparing parameter ids; `$table_model` data files accepted `nan`/`inf`/`1e400` and poisoned the whole table; `@(timer)` with a zero or negative period fired on every evaluation; `$bound_step`, `noise_table` shape, `@(cross)` direction, `transition`/`slew`/`idtmod`/`absdelay` arguments and a bus port's two ranges were all unvalidated | both | [doc](enhancements_doc/Enhancement-396.md) | [limguard](examples/limguard_examples/) |
| 397 | fix: `temp`, `dtemp` and `dt` are readable on an OSDI device -- they were registered `IF_SET` without `IF_ASK`, so a value could be written and never read: `print @n1[temp]` answered "no such parameter" where every built-in reports one, `show` listed none of them, and a `sweep` over them ended with a spurious error AFTER completing correctly. Adding the flag alone was not possible because the synthesized ids COLLIDED with [E-394](enhancements_doc/Enhancement-394.md)'s terminal currents -- `dt`'s id WAS terminal 0's -- so they now sit above that range. Read-back matches the built-in convention exactly (`temp` in degrees Celsius following the ambient, `dtemp`/`dt` the offset), and `temp=` overriding `dtemp=` now clears it as `restemp.c` does, so what is reported is what is used | ngspice | [doc](enhancements_doc/Enhancement-397.md) | [instknobs](examples/instknobs_examples/) |
| 398 | fix: four silent `paramset` defects -- **it was the ONLY supply path that bypassed parameter range validation** (a model card, instance line, `alter`, `altermod`, `.param` and subcircuit parameter all reject an out-of-range value and abort; a paramset put it straight into the model), because binding an override turns the target parameter into a localparam whose constraints were discarded, leaving the value in the gap between compile-time and runtime checking; an override naming a parameter the target does not declare was dropped in silence; the same parameter assigned twice was accepted with the FIRST winning; and `$param_given` reported false for a paramset-supplied value, so every CMC "did the user set this?" derivation took the default branch | openvaf-r | [doc](enhancements_doc/Enhancement-398.md) | [paramsetguard](examples/paramsetguard_examples/) |
| 399 | fix: thirteen silent round-13 defects -- a concatenation `{..}` where the LRM requires an array literal `'{..}` made **`$table_model` return 0.0 and `noise_table` contribute no noise at all**, because every check read `if let Expr::Array` and a concatenation is a different variant; **no analysis-name string was validated anywhere**, so `analysis("tarn")` is false in every analysis and `@(initial_step("tarn"))` fires never; an event `or` list was truncated at its first `)`, silently discarding a good `final_step`; `@(cross/above/timer)` surplus arguments were dropped by an unconsumed iterator and their tolerances were absent from the HIR; `@(cross())` degraded the whole event control to an unconditional body; an integer parameter took **different values from the netlist (-2.5 -> -2) and in-model (-3)**; a plain convergence failure fell through into [E-378](enhancements_doc/Enhancement-378.md)'s abort path and was reported as a `$fatal` the model never raised; three more standard `$simparam` names; two natures that both omitted `units` compared compatible because `None == None`; `U+0060` was a unicode-lookalike of itself; and `from [3:1]` left a parameter silently unsettable | both | [doc](enhancements_doc/Enhancement-399.md) | [VA_TEST corpus](VA_TEST/) |
| 400 | fix: a contribution discarded by statement order (V and I on one branch) is reported | openvaf&#8209;r | [doc](enhancements_doc/Enhancement-400.md) | [VA_TEST corpus](VA_TEST/) |
| 401 | fix: `V(a,b) <+ 0` between two terminals was an open circuit, not a short | both | [doc](enhancements_doc/Enhancement-401.md) | [VA_TEST corpus](VA_TEST/) |
| 402 | fix: an OSDI instance line with too few nodes was accepted silently | ngspice | [doc](enhancements_doc/Enhancement-402.md) | n/a |
| 403 | fix: an instance `temp=` inflated thermal noise by the nominal temperature | both | [doc](enhancements_doc/Enhancement-403.md) | n/a |
| 404 | perf: a wide bus elaborated in time quadratic in its width — 31.5 s for `[65535:0]`, now 0.62 s | openvaf&#8209;r | [doc](enhancements_doc/Enhancement-404.md) | n/a |
| 405 | fix: z-domain filters reciprocated every pole and zero; empty denominator hung the compiler | openvaf&#8209;r | [doc](enhancements_doc/Enhancement-405.md) | [filterforms](examples/filterforms_examples/) |
| 406 | fix: a flow probe on a declared branch silently shorted the branch that was driven — new `probe_only_branch_short` lint | openvaf&#8209;r | [doc](enhancements_doc/Enhancement-406.md) | [probeshort](examples/probeshort_examples/) |
| 407 | feat: a `genvar` for-loop inside an `analog` block is unrolled at elaboration — three LRM examples now compile | openvaf&#8209;r | [doc](enhancements_doc/Enhancement-407.md) | [genvarloop](examples/genvarloop_examples/) |
| 408 | fix: bracketed names missed their target -- a leading-zero node index, a parameter name containing brackets, a bus range on an output or IC card | ngspice | [doc](enhancements_doc/Enhancement-408.md) | [busname](examples/busname_examples/) |
| 409 | fix: a wildcard `sweep` knob was never put back, and printed a parser error that looked like a bad parameter name | ngspice | [doc](enhancements_doc/Enhancement-409.md) | [wildrestore](examples/wildrestore_examples/) |

</details>

---

## VA_TEST — real-world compile corpus

`VA_TEST/` holds the public **VA-Models** collection as a compile-regression corpus: the industry-standard compact models (BSIM4/6/BULK/CMG/IMG/SOI, PSP 102/103/104, PSP-HV, HiCUM L0/L2, MEXTRAM 504/505, VBIC, EKV 2.6/3, ASM-HEMT, EPFL-HEMT, Angelov, MVSG, diode_cmc, r2/r3_cmc, L-UTSOI, MOSVAR, IGBT, …) — 124 `.va` files in total. `python3 VA_TEST/compile_all.py` compiles every file with the committed `openvaf-r` and regenerates [VA_TEST/compile_report.md](VA_TEST/compile_report.md); **all 92 standalone models compile** (the remaining 32 files are `` `include `` fragments — macro bodies and module-body pieces — reported separately since they aren't standalone modules).

---

## OSDI correctness campaign

`examples/osdicampaign_examples/` is an **oracle-based** campaign over the OSDI device path — 83 checks across analyses (both solvers), sweeps, all seven optimizers, Monte Carlo, RF, and deliberate abuse. Every check computes its expected value independently, so a pass means the number is *right*, not that a run finished: `.noise` is checked against √(4kTR), `.pz` against −1/RC, `.sp` against exact S-parameter algebra, the optimizers against an analytic optimum, and Monte Carlo against both a hand-rolled `reset`-loop and the exact Gaussian probability. OSDI devices come out **bit-identical** to ngspice's built-in `R`/`C`/`L`/`G` through `op`/`ac`/`tran`/`tf`/`pz`/`sens`.

It is **deliberately outside the regression suite** — `run_regression.py` discovers `verify_*.py`, and this driver is named `run_campaign.py`, so the routine sweep never picks it up. The suite answers "did anything change?" on every fold; this answers "is the OSDI path correct?" and is worth running when the OSDI or analysis machinery is touched:

```bash
cd examples/osdicampaign_examples && python3 run_campaign.py     # or: run_campaign.py A C
```

Last run: **83/83, no ngspice or OSDI defect.** Two differences are documented rather than tolerated — a 0.24 ppm thermal-voltage *constant* difference between OpenVAF's `$vt` (exactly the `constants.vams` value) and ngspice's built-in diode, and PSS discretisation error that the check verifies **converges** under grid refinement instead of pinning to a fixed tolerance. See [the README there](examples/osdicampaign_examples/README.md), which also collects the usage gotchas that each looked like a bug at first.

---

## Sparse vs KLU differential campaign

`examples/solverdiff_examples/` compares the two linear solvers on circuits where the solve is actually hard — ill-conditioned networks and stiff nonlinear ones. **A solver-vs-solver diff says they differ; it cannot say which is wrong**, so phase 1 has `numpy` solve the same MNA system independently as a third opinion, reports each deck's **condition number**, and asserts against `eps·cond`; decks beyond what float64 can deliver are reported, never asserted. Phase 2 covers the nonlinear regime — where Sparse actually re-pivots — using solver-vs-solver at tight tolerance plus a tightened-`reltol` run that separates a linear-solve difference from convergence slack.

Like the OSDI campaign it is **deliberately outside the regression suite**: the driver is named `run_solverdiff.py`, so `run_regression.py` (which discovers `verify_*.py`) never picks it up.

```bash
cd examples/solverdiff_examples && python3 run_solverdiff.py     # or: run_solverdiff.py 1
```

Last run: **37/37, no solver defect.** Worst Sparse-vs-KLU disagreement anywhere was 7.06e-06, on cond 2.4e12 where `eps·cond` is 5e-4. Both solvers track the exact solution in step with conditioning and **trade places** (Sparse better on `ladder_ratio`, KLU on `star(9)`), so neither shows systematic bias — Sparse is numerically sound where float64 allows; its weakness is cost, not accuracy. [The README there](examples/solverdiff_examples/README.md) also records the harness traps, each of which produced a false green or false red before being caught — including a first version that reported 25/25 and meant nothing.

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

For time-domain noise, [Transient noise in
ngspice](docs/internals/ngspice_internals/ngspice_transient_noise_analysis.md)
([PDF](docs/internals/ngspice_internals/ngspice_transient_noise_analysis.pdf))
covers both paths — the built-in `trnoise` sources and the OSDI (Verilog-A)
devices made noisy in `.tran` by Enhancement-364 — deriving the amplitude law
from the generator's structure and checking it against closed forms: the
parameter-free `kT/C` identity across a 10x resistance sweep, shot noise tracking
a 45x current sweep on a nonlinear diode, a 1/f spectrum matched to `.noise`, and
a variance cross-check between the transient, `.noise`, and thermodynamics. It
also records which elements are *not* noise sources in `.tran`, and a measurement
trap that made a correct result look 38% wrong.

[Temperature and the multiplier in
ngspice](docs/internals/ngspice_internals/ngspice_temperature.md)
([PDF](docs/internals/ngspice_internals/ngspice_temperature.pdf)) documents the
four instance knobs a compact model sits under — `m`, `temp`, `dtemp`, `dt` —
and how each reaches an OSDI (Verilog-A) device: that ngspice supplies all four
by *default* and declaring one in Verilog-A is what makes it step back; that `m`
and `$mfactor` are distinct parameters that **multiply** rather than alias; the
Celsius→Kelvin convention on `temp`; and why `$vt` must be checked by ratio
rather than against a textbook `kT/q`. Every figure is generated from a
simulation, each verified against a built-in device in the same deck — including
a resistor used as a thermometer.

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

---

## License

This repository is a **combined work**, and most of the code in it is not
original to this project.

The combination is distributed under **GPL-3.0** ([LICENSE](LICENSE)) — a
consequence rather than a choice: the bundled OpenVAF compiler is GPL-3.0, this
project modifies and redistributes it, and GPL-3.0 is the strongest copyleft
among the components. Every other component's license is compatible with it.

**Each bundled component keeps its own license.** GPL-3.0 governs the
combination; it relicenses nothing. In particular:

| Component | License |
|---|---|
| ngspice (`ngspice-46/`) | Modified BSD, © Regents of the University of California and others — with its own exception list in [`ngspice-46/COPYING`](ngspice-46/COPYING) |
| OpenVAF (`OpenVAF-master-20260610/`) | GPL-3.0 (two utility crates are MIT OR Apache-2.0) |
| the OSDI interface *in ngspice* (`ngspice-46/src/osdi/`) | MPL-2.0, © 2022 SemiMod GmbH — OpenVAF's side of the same ABI is GPL-3.0 |
| KLU | LGPL-2.1-or-later |
| parts of XSPICE, and `ndev` | public domain |

The BSD, MIT and MPL-2.0 components carry attribution notices that survive
redistribution. [**THIRD-PARTY-LICENSES.md**](THIRD-PARTY-LICENSES.md) is the
component-by-component manifest that records them, and is the file to read
before redistributing this work in any form.

The [prebuilt binaries](#prebuilt-binaries) under `bin/` are built from the
sources in this repository and are covered by GPL-3.0; the corresponding source
required by GPL-3.0 §6 is this repository itself, so source and binary always
travel together.

**No separate copyright is asserted over this project's modifications to ngspice
and OpenVAF.** Those changes are contributed under the terms of the works they
modify, and claim nothing beyond them. The files original to this project — the
documentation, examples, verification harnesses and change reports — are
© 2026 javaNoviceProgrammer under GPL-3.0.
