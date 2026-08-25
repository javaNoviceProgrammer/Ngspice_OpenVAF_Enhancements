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

Four hundred and thirteen enhancements so far — language features, correctness fixes, systematic audits, and simulator-side workflow tooling, each verified end-to-end by a committed example suite and released with a detailed write-up.

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
| 353 | `.disto` now works for models using `$limit`, i.e. every production compact model | openvaf&#8209;r | [doc](enhancements_doc/Enhancement-353.md) | [limitdisto](examples/limitdisto_examples/) |
| 359 | `.disto` rebuilt: tensors differenced from the analytic Jacobian in ngspice, so compile time and object size return to baseline | ngspice | [doc](enhancements_doc/Enhancement-359.md) | [osdidisto](examples/osdidisto_examples/) |
| 360 | fix: a second Verilog-A model no longer silences the first in `.disto` (per-model tensor cache) | ngspice | [doc](enhancements_doc/Enhancement-360.md) | [osdidisto](examples/osdidisto_examples/) |
| 361 | fix: ASan/UBSan in `.disto` — out-of-bounds read of the solution vector, and `(int)NaN` point count on degenerate sweeps | ngspice | [doc](enhancements_doc/Enhancement-361.md) | [osdidisto](examples/osdidisto_examples/) |
| 362 | fuzzing analysis-card sweep parameters: 7 fixes — counts cast to int reaching allocators, and an unbounded `.dc` sweep | ngspice | [doc](enhancements_doc/Enhancement-362.md) | [sweepguard](examples/sweepguard_examples/) |
| 363 | fix: two compiler crashes from cross-feature fuzzing — a block merged into itself (`case` in a `do-while`), and array parameters never instance-renamed | openvaf&#8209;r | [doc](enhancements_doc/Enhancement-363.md) | [vafcfg](examples/vafcfg_examples/) |
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
| 375 | fix: a loop that provably cannot finish is now a compile error — it used to emit a model that hung the simulator with no diagnostic; also closes 3 codegen crashes on `disable` | openvaf&#8209;r | [doc](enhancements_doc/Enhancement-375.md) | [vafloop](examples/vafloop_examples/) |
| 376 | fix: `$dist_*` returned `real`; the LRM makes it integer (`$rdist_*` is the real family) — needed a `ficast` in the lowering too, or the value read as 0 | openvaf&#8209;r | [doc](enhancements_doc/Enhancement-376.md) | [distint](examples/distint_examples/) |
| 377 | fix: OSDI diagnostics — name glued to its argument, no newline, no `free`, and `LOG_LVL_MASK` 8 made every severity report as `OSDI(debug)` on stdout | both | [doc](enhancements_doc/Enhancement-377.md) | [simparamdiag](examples/simparamdiag_examples/) |
| 378 | fix: a Verilog-A `$fatal` during the operating point was read as non-convergence, so the gmin/source ladder retried it 373x and blamed `timestep too small` | ngspice | [doc](enhancements_doc/Enhancement-378.md) | [opfatal](examples/opfatal_examples/) |
| 379 | fix: `cargo test --workspace` now builds and no longer overwrites checked-in source — verilogae drift, and three sourcegen generators that had fallen behind the files they generate | openvaf&#8209;r | [doc](enhancements_doc/Enhancement-379.md) | n/a |
| 380 | fix: a `.dc` sweep inherited stale integration coefficients from a preceding `pss`/`tran`/`envelope`, adding a spurious `ag[0]*cap` to every charge-storing device — 45% silent error | ngspice | [doc](enhancements_doc/Enhancement-380.md) | [dcstate](examples/dcstate_examples/) |
| 381 | fix: `stb` handed its probe sources back with `ac = 0` instead of their original values, so a following `.ac` returned all zeros | ngspice | [doc](enhancements_doc/Enhancement-381.md) | [stbrestore](examples/stbrestore_examples/) |
| 382 | fix: `loadpull` left the user's tuner R/L/C at the last swept grid point instead of restoring them, so a following analysis ran against the wrong network | ngspice | [doc](enhancements_doc/Enhancement-382.md) | [lprestore](examples/lprestore_examples/) |
| 383 | fix: four unreachable `plotabs[]` entries named plots after a different analysis — `envelope` as `op1`, `qpac` as `pac1`, `qpxf` as `pxf1`, `spectrum` as `sp1` | ngspice | [doc](enhancements_doc/Enhancement-383.md) | [plotorder](examples/plotorder_examples/) |
| 384 | fix: a transient after `sens` returned every node zero — plus `sens`/`sp` aborting the process, a silent partial S-matrix at `z0<=0`, an OSDI `DT` alias, and two device-table flags | ngspice | [doc](enhancements_doc/Enhancement-384.md) | [sensstate](examples/sensstate_examples/) |
| 385 | fix: `sens ac` zeroed VCCS/CCCS sources and `sweep` never restored an `alter`/`altermod` knob — found by a state-restoration audit that ships with it | ngspice | [doc](enhancements_doc/Enhancement-385.md) | [staterestore](examples/staterestore_examples/) |
| 386 | fix: the six sensitivity queries returned the previous query's value on every device — first seen as denormal garbage from a reused static | ngspice | [doc](enhancements_doc/Enhancement-386.md) | [senscplx](examples/senscplx_examples/) |
| 387 | fix: an empty `()` expression crashed openvaf-r with an internal compiler error; `-DNAME=VALUE` defined a macro called `NAME=VALUE`; a bad `TMPDIR` aborted via an uncaught C++ exception | openvaf&#8209;r | [doc](enhancements_doc/Enhancement-387.md) | [vafice](examples/vafice_examples/) |
| 388 | fix: `-D` macro values are now substituted (`-DK=5.5` → 5.5, bare `-DK` → 1 as documented); the expression-depth guard says "nests too deeply" instead of a bogus token error | openvaf&#8209;r | [doc](enhancements_doc/Enhancement-388.md) | [vafdefine](examples/vafdefine_examples/) |
| 389 | fix: a loop whose control variable never changes (`k = k + 0`) compiled and then hung the simulator; ANSI and combined analog-function argument declarations accepted; `$table_model` takes runtime array data | openvaf&#8209;r | [doc](enhancements_doc/Enhancement-389.md) | [vafopenitems](examples/vafopenitems_examples/) |
| 390 | fix: a `case` inside a `do-while` compiled into an infinite loop that hung the simulator; `analog` blocks inside `generate` were silently dropped; `disable` with an unknown label was a no-op; runtime `$table_model` arrays now sort and de-duplicate | openvaf&#8209;r | [doc](enhancements_doc/Enhancement-390.md) | [vafcaseloop](examples/vafcaseloop_examples/) |
| 391 | fix: a repeated abscissa in a runtime `$table_model` gave a different cubic spline than the identical compile-time table; repeats are compacted out, boundary and end tangent following the live knots | openvaf&#8209;r | [doc](enhancements_doc/Enhancement-391.md) | [vaftabledup](examples/vaftabledup_examples/) |
| 392 | fix: module instantiation was unvalidated -- wrong port count, unknown port names and `#(.param())` overrides naming nothing all compiled clean; plus a misbound `$mfactor` and a 64-knot `$table_model` sort limit | openvaf&#8209;r | [doc](enhancements_doc/Enhancement-392.md) | [vafinstcheck](examples/vafinstcheck_examples/) |
| 393 | fix: a `localparam` could size a bus but not index one -- `n[K]` and `n[2+1]` were rejected as non-constant; all three places that resolve a bit-select now fold it, while a plain `parameter` is still refused (it binds at simulation time) | openvaf&#8209;r | [doc](enhancements_doc/Enhancement-393.md) | [vafconstidx](examples/vafconstidx_examples/) |
| 394 | fix: six ngspice/OSDI plumbing defects -- a subcircuit `m=` never reached an OSDI device and nested multipliers never compounded; instance `temp=` was read as Kelvin; `.option scale` and `savecurrents` never arrived | both | [doc](enhancements_doc/Enhancement-394.md) | [osdiplumb](examples/osdiplumb_examples/) |
| 395 | fix: nine openvaf-r defects -- a seeded RNG is constant in a loop (a deliberate trade, now the `rng_in_loop` lint); `laplace_np/zp/zd` had the wrong DC gain; `$table_model` clamped instead of extrapolating | both | [doc](enhancements_doc/Enhancement-395.md) | [langguard](examples/langguard_examples/) |
| 396 | fix: ten openvaf-r defects -- `$limit` with a bad name or arity left a NULL pointer the model then CALLED (segfault, zero output); a collision warning fired on almost every industry model; `@(timer)` with period <= 0 fired every evaluation | both | [doc](enhancements_doc/Enhancement-396.md) | [limguard](examples/limguard_examples/) |
| 397 | fix: `temp`, `dtemp` and `dt` are readable on an OSDI device -- registered `IF_SET` without `IF_ASK`, so `print @n1[temp]` failed where every built-in answers; their ids had to move, `dt`'s having collided with a terminal current | ngspice | [doc](enhancements_doc/Enhancement-397.md) | [instknobs](examples/instknobs_examples/) |
| 398 | fix: four silent `paramset` defects -- it was the ONLY supply path bypassing parameter range validation; an override naming an undeclared parameter was dropped; a duplicate assignment let the FIRST win | openvaf&#8209;r | [doc](enhancements_doc/Enhancement-398.md) | [paramsetguard](examples/paramsetguard_examples/) |
| 399 | fix: thirteen silent round-13 defects -- `{..}` where the LRM wants `'{..}` made `$table_model` return 0.0 and `noise_table` contribute nothing; no analysis-name string was validated anywhere | both | [doc](enhancements_doc/Enhancement-399.md) | [VA_TEST corpus](VA_TEST/) |
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
| 410 | feat: `@x1.r1[param]` names a subcircuit device without its flattening type letter, in every accessor and in `show` | ngspice | [doc](enhancements_doc/Enhancement-410.md) | [hierdev](examples/hierdev_examples/) |
| 411 | feat: a descending netlist bus range binds terminals in reverse and is now reported -- silent until now | ngspice | [doc](enhancements_doc/Enhancement-411.md) | [busdir](examples/busdir_examples/) |
| 412 | fix: an OSDI operating-point variable read after `.ac`/`.noise` returned the small-signal solution, and changed with frequency | ngspice | [doc](enhancements_doc/Enhancement-412.md) | [opvarac](examples/opvarac_examples/) |
| 413 | fix: `.options savecurrents` registered an empty vector for a multi-terminal OSDI device; now one waveform per terminal | ngspice | [doc](enhancements_doc/Enhancement-413.md) | [savecuroff](examples/savecuroff_examples/) |
| 414 | fix: a genvar loop body of any statement shape now unrolls, and a dangling `else` no longer re-binds to an enclosing `if`; a parameter named in another's `from` range stays settable | openvaf&#8209;r | [doc](enhancements_doc/Enhancement-414.md) | [elabguard](examples/elabguard_examples/) |
| 415 | fix: an OSDI `@(timer)` event is no longer stepped over and lost; the per-device noise summary total is the device's own, not the first source's input-referred figure | both | [doc](enhancements_doc/Enhancement-415.md) | [evtnoise](examples/evtnoise_examples/) |
| 425 | fix: a corrupt row in a `$table_model`/`noise_table` data file was silently dropped -- a tenfold wrong answer, and in the N-dimensional form the whole table contributed exactly zero | openvaf&#8209;r | [doc](enhancements_doc/Enhancement-425.md) | [tabledata](examples/tabledata_examples/) |
| 426 | fix: inputs that were never checked -- an invented analysis output node (an out-of-bounds read), sweeps running a different range than asked, `meas` on an unsaved `@dev[param]` answering 0.0, and `m=-1` | ngspice | [doc](enhancements_doc/Enhancement-426.md) | [inputguard](examples/inputguard_examples/) |
| 427 | fix: `.dc @inst[param]` applied values the model's `from` range forbids and published them at rc=0 while every other path refused; it also handed the device one value past `stop`, and a `@(timer)` event landing exactly on `tstop` never fired | both | [doc](enhancements_doc/Enhancement-427.md) | [sweepparam](examples/sweepparam_examples/) |
| 428 | fix: a Verilog-A device's INTERNAL node inside a subcircuit reads as `v(x1.n1#mid)` as well as `v(n.x1.n1#mid)` in every consumer; the type letter was a flattening artefact leaking into a node name, and `.save` failed destructively | ngspice | [doc](enhancements_doc/Enhancement-428.md) | [hiernode](examples/hiernode_examples/) |
| 429 | fix: a `.tf`/`.noise` CARD naming a nonexistent node answered `transfer_function = 0.0` with no diagnostic -- Enhancement-426's guard fires only on the `.control` path, since a card's invented node is created before the matrix is sized | ngspice | [doc](enhancements_doc/Enhancement-429.md) | [inputguard](examples/inputguard_examples/) |
| 430 | fix: `.probe`'s refusal now names what it accepts and points `@device[param]` at `.save` -- the refusal itself is correct, since `.probe` measures by inserting series sources; the warning also printed twice per token | ngspice | [doc](enhancements_doc/Enhancement-430.md) | [probeshort](examples/probeshort_examples/) |
| 431 | fix: a `sweep -output` naming a vector that never resolves was recorded as a full column of zeros -- a plottable, entirely fictional flat line -- and is now named in an error, while genuine zeros and sibling outputs are kept | ngspice | [doc](enhancements_doc/Enhancement-431.md) | [sweepguard](examples/sweepguard_examples/) |
| 432 | fix: `sweep -output` takes every expression up to the next flag, not just the first token; also fixes an Enhancement-431 regression that dropped auto-collected curves | ngspice | [doc](enhancements_doc/Enhancement-432.md) | [sweepguard](examples/sweepguard_examples/) |
| 433 | fix: a double-quoted `-analysis`/`-output` kept its quotes in five commands (none called `cp_unquote`), and a subcircuit `.model` is now reachable as `@x1.rmod[res]` | ngspice | [doc](enhancements_doc/Enhancement-433.md) | [sweepguard](examples/sweepguard_examples/), [hierdev](examples/hierdev_examples/) |
| 434 | fix: three silent wrong answers plus a truncation -- `$simparam("temp")` was never supplied, `$simparam("abstime")` returned the DC sweep voltage, `-analysis` was cut at 512 bytes, and `.tf` swallowed a model's `$finish` | ngspice | [doc](enhancements_doc/Enhancement-434.md) | [silentloss](examples/silentloss_examples/) |
| 435 | fix: `sweep` accepts a subcircuit-local model parameter as `@x1.rmod[res]` -- it classifies knobs on its own path and missed Enhancement-433's fix, running on with a knob that never moved and drawing a plottable FLAT curve | ngspice | [doc](enhancements_doc/Enhancement-435.md) | [hierdev](examples/hierdev_examples/) |
| 452 | fix: three `-o` destinations the driver never checked, each reaching the backend and failing there. `openvaf-r m.va -o m.va` wrote the compiled module straight over the SOURCE and reported success -- 111 bytes of Verilog-A became a 36 KB shared object, exit 0, source gone. An empty `-o` hit an `.expect()` in osdi::compile and an unwritable directory hit an `assert_eq!` on the object-emit result, so both PANICKED: exit 101, a crash banner and a request to file a GitHub issue, for a typo. The destination is now validated in the driver before any parsing, at the last point that knows both input and output; overwriting a previous OUTPUT is still allowed | openvaf-r | [doc](enhancements_doc/Enhancement-452.md) | [optpath](examples/optpath_examples/) |
| 453 | fix: five ways the compiler answered a request it could not satisfy. Batch mode keyed its cache on the source but not on the settings that decide the machine code, so `-O 0` then `-O 3` produced ONE entry and the second run handed back the debug build at exit 0; a `--target` request was answered from the HOST cache, so a Linux build came back an arm64 Mach-O. Cross-compiling then PANICKED (exit 101), since only the native LLVM target is registered -- fixing the key alone would have turned a wrong answer into a crash, so the target is now probed before any work is spawned and the error names what the binary can really emit. Separately the LRM null argument (two adjacent commas, the LRM's own spelling for a filter with no zeros) was rejected for all eight filters, and printing a comparison or an array literal crashed the compiler -- a Bool now prints 1/0 | openvaf-r | [doc](enhancements_doc/Enhancement-453.md) | [batchkey](examples/batchkey_examples/), [nullarg](examples/nullarg_examples/) |
| 454 | fix: `.option autobus` was decided in two places that disagreed, so the same card meant ON inside a subcircuit and off at the top level, or the reverse, depending only on the spelling. The subcircuit reader took `=` as a clean terminator and never read the VALUE, so `autobus=0`, `=false` and `=no` each switched the feature on silently; the top-level reader asked only for a BOOL, so `autobus=1` -- not reported as unknown -- left a bus port unbound. Both now answer by one shared list of off-words, shared with savecurrents. A bus can also be passed down through nested subcircuits, which previously failed with too few nodes | ngspice | [doc](enhancements_doc/Enhancement-454.md) | [autobusopt](examples/autobusopt_examples/) |
| 455 | fix: seven ways a bad value was accepted, or crashed the compiler -- each a check that exists with a neighbouring spelling walking past it. Indexing a scalar (`r[0]` on a real, `p[0]` on a parameter) hit a `panic!` and exited 101 with a crash banner, for a typo. The value guards folded only a literal, so `white_noise(-1e-18)` was refused while `white_noise(0-1e-18)` was accepted and gave the positive power's noise silently. Reversed ranges spelled with `inf` were invisible -- `from (inf:0)` was accepted and enforced nothing. A constant outside a domain (`sqrt(-1.0)`) folded to NaN with no warning. And `$rdist_uniform` with reversed bounds, a zero-argument analog function and a discipline naming one nature for both potential and flow all compiled, the last producing a device that contributed nothing | openvaf-r | [doc](enhancements_doc/Enhancement-455.md) | [valguard](examples/valguard_examples/) |
| 456 | fix: `analog initial` ran on every evaluation instead of once (LRM 5.2). Its statements were concatenated into the front of the eval function, so they overwrote whatever the model had accumulated between timesteps -- destroying the one thing the construct exists for. A peak detector initialised there did not hold its peak, it followed the input back down (1.0 at the peak, then 0.4 and 0.1), and a counter never left zero; the identical models without the initialisation worked. Gated now on the same initial-step flag `@(initial_step)` uses, which fires once per analysis per instance -- once for an entire dc sweep however many points it has | openvaf-r | [doc](enhancements_doc/Enhancement-456.md) | [analoginit](examples/analoginit_examples/) |
| 478 | fix: five defects of one shape from a bug hunt -- a check was performed and then something **else** was used. A count was validated with a float parser and consumed with `atoi`, which stops at the `e`: `sweep lin 2e2` ran **2** points, `montecarlo 2e2` drew 2 samples and printed a yield from them, and `sweep lin 1e6` ran **one** point while the identical number written `1000000` was correctly refused as too many -- the float the validator computed was thrown away. The same block silently rewrote a count below 1, which for `dec`/`oct` changes the **spacing** and on a `-vs` knob collapses a sweep dimension, while every sibling (`ac`, `dc`, `tran`, montecarlo, highsigma, wcd, `.for`) names it. `spec` checked its step against the span but never against zero, so a negative step made a negative point count, a negative allocation and a NULL dereference -- **a deterministic SIGSEGV** in the shipped binary. Indexing a `@dev[param]` waveform returned the device's **live** value rather than the element, because the literal-index probe asks `vec_get` for a name that begins with `@` and that is answered from the device, not the plot -- so every index gave the same number while `length`, `maximum` and `wrdata` were right all along. `fourier` guarded a fundamental below the time span but not one above the sample rate, printing `THD: nan %` with no diagnostic. And a loop command run as another's `-analysis` overwrote the shared progress state, so the outer bar vanished and the line read 100% with points still to run. Two lookalikes are deliberately left alone and pinned by checks. | ngspice | [doc](enhancements_doc/Enhancement-478.md) | [guardmatch](examples/guardmatch_examples/) |
| 479 | fix: every value guard only ever saw a **literal**. `const_num` had arms for literals, unary minus and the four binary operators -- and none for a path -- so naming a value made every check skip: `white_noise(-1e-12)` was rejected and `white_noise(-1e-12*1.0)` was too (folding *is* applied), but a `localparam` holding the same number was **accepted in silence**, though the LRM forbids overriding one so the compiler knows its value exactly. One missing arm, **eleven guard sites** -- `$bound_step`, `@(timer)`, `@(cross)`, `transition`, `absdelay`, `zi_nd`, `last_crossing`, `white_noise`, `flicker_noise`, the `analysis`/`$simparam` name checks and the parameter-range emptiness check. A negative `transition` time supplied that way drove a 0-to-1 signal to **-2.5 V and made it respond before the input edge**, rc=0, silent. The same assumption built the compile-time tables: a **named** entry became a **zero** entry, so one table written two ways gave `$table_model` **15 and 5** and cost `noise_table` its noise entirely. `abs(-0.0)` disagreed with the compiler's own folding (`1/abs` giving **-inf** generated against **+inf** folded). Adds the guards that never existed -- six `$rdist_*` shapes, `$vt(T<=0)`, `ddt`/`idt` `abstol`, and a `laplace_nd`/`laplace_zd` denominator whose zero leading coefficient made the filter produce no output at all -- and makes a build that defines **no module** an error instead of a green *Finished building* over an empty `.osdi`. Pinned as deliberately unchanged: `@(timer)` period <= 0 fires once (LRM 5.10.3.3), `noise_table_log`'s linear input, `0.0 * NaN` (E-337), literal underflow, and a `parameter` default. | openvaf-r | [doc](enhancements_doc/Enhancement-479.md) | [constguard](examples/constguard_examples/) |
| 480 | fix: a check that could not **fire** where it mattered. Most of a bug-hunt round is not a *missing* check but a written one made unreachable. The duplicate-parameter test on a `.model` card was gated on its tracking list not being **full**, so once every distinct parameter had been seen once a repeat was never looked up -- a device with one model parameter could never report one; and it counted the model **type token** as a parameter, so `.model rmod r(r=1k)` was told *parameter 'r' is set more than once ... remove one* on the most ordinary card there is. `.measure`'s edge count collided with the field's `-1`/`-2` sentinels, so `fall=-1` was read as *no fall given* and answered with a **rising** edge. `%` disagreed with itself: `.param` and a B-source call `fmod` while the control operator truncated **both** operands to integers and dropped the sign, so `(0.5) % 3` was **0**; E-273's range check is kept, so `1e30 % 5` still errors. An unterminated control block was checked per *line*, never at the end of the section, so an `if` with no `end` swallowed every command after it and exited 0. Adds the guards that were absent -- a transmission line's `nl/f` (`f=0` printed a table of `nan` as an ordinary AC result), a switch's `vh`/`ih`, the code-model PWL's breakpoint order, a duplicate subcircuit parameter, a `.dc` step larger than its span -- and makes the limiter's reversed-limits message fire once at INIT instead of never in `op`/`dc` and 214 times in a transient. Pinned as deliberately unchanged: `vector(-4)`, a negative `pulse` TR/PW, `.dc` start == stop, `ac lin 1`. One fix built, measured and **reverted**: protecting the constant plot by shadowing broke name resolution and hung `lhs_examples`, because `run` is itself a built-in constant. | ngspice | [doc](enhancements_doc/Enhancement-480.md) | [gatecheck](examples/gatecheck_examples/) |
| 481 | feature: `.option silentports` -- an opt-out for a netlist **nobody typed**. E-402 made an omitted OSDI terminal audible and that stays the default, for good reason: it looks exactly like a typo, and it *dangles* rather than grounding. What it did not account for is a netlist written by a **tool** -- a schematic front end emits the short form for every instance of a model with an optional thermal port, and the author cannot add the pin from the schematic, so a five-device sheet collects twenty-five lines about a choice nobody made (KiCad's exporter is the case that prompted it). The option suppresses that warning and nothing else; it is opt-in, and a front end that cannot edit netlists can ship `set silentports` in `.spiceinit`. **It silences a warning, it does not repair a circuit**: on the E-402 reproducer, omitting the thermal node still leaves all six `singular matrix` reports because BSIM-BULK pins that node with a potential tie-off -- the answer there is still to write `0` for the pin, and three checks pin the distinction. **No openvaf-r change**: the warning is raised in `INP2N` from the terminal count already in the `.osdi` descriptor, and the compiler prints nothing about an unused port. Registered in **both** the option name list and the type dispatch -- the first build worked while still printing *unknown option*. All nine on/off spellings tested. | ngspice | [doc](enhancements_doc/Enhancement-481.md) | [silentports](examples/silentports_examples/) |
| 477 | feat: a progress line for the commands that run N analyses in a loop -- `sweep`, `montecarlo`, `highsigma`, `wcd`. All four silence per-point chatter (E-130's `ft_optimizing`), so they printed a banner and then **nothing at all**: a forty-point sweep of a slow transient looked hung for minutes. Letting the inner analysis's own bar through is the obvious fix and the wrong one -- it runs 0 to 100% for **every** point, so it resets N times and never says how far the sweep is, and it redraws the same line with a carriage return, so the two would overwrite each other. One line now carries both: `sweep: point 7/40 [=====    ] 17% (tran 63%)`, with the inner fraction also advancing the outer bar within the point so it moves smoothly instead of stepping once per analysis. Two drivers are needed and neither suffices alone -- while a point runs the command is blocked inside the analysis so only the output path can refresh, but the **default** analysis is `op`, which produces no swept data points and never reaches it, so the command also draws at each point boundary. `wcd` iterates to convergence and gets a counter rather than a bar against `maxiter` that would jump to done. Auto-enabled only on a terminal, since the line is redrawn in place; `loopbar`/`noloopbar` force it, all eight spellings tested. A standalone analysis keeps its own bar and `optimize` stays silent. | ngspice | [doc](enhancements_doc/Enhancement-477.md) | [loopbar](examples/loopbar_examples/) |
| 476 | fix: four defects of one shape from a bug hunt -- the simulator's account of itself did not match what it does, and none of them raised an error. An OSDI operating-point variable answered with a **number** when nothing had computed one: the opvar storage is zeroed, so a read after an aborted analysis, or with none run at all, returned a clean 0.0 that is indistinguishable from a real current or conductance, while `i(v1)` in the same `print` said it had no value. ngspice already applied that rule to `show`, which is why it never displayed one; the direct `@dev[opvar]` read was the path without it. Every OSDI device's integrated noise total was named with a trailing **space** -- `display` padded it away and every read missed it, so per-device noise attribution was advertised and unreachable while its own per-source children and the grand total were fine. A model declaring `dtemp` or `temperature` at model scope had `alter @n1[dtemp]=` accepted, discarded and unreported, where every other model-scope parameter is refused honestly. And the compiler warned that `$simparam("temp")` is unserved and fatal, of a name ngspice has served since E-434 -- three copies of one list, two of them stale, now one that the diagnostic is built from. Three lookalikes are deliberately left alone and pinned by checks. | both | [doc](enhancements_doc/Enhancement-476.md) | [reportguard](examples/reportguard_examples/) |
| 475 | fix: seven defects of one shape from a bug hunt -- a value the deck **stated** was discarded and something else quietly put in its place, or a refusal named the wrong fault. `sin` with an explicit `freq=0` took its frequency from TSTOP, so lengthening the run changed the stimulus (a zero frequency is DC, unlike a zero rise time; omitting it still defaults to 1/TSTOP). An unknown parameter on a subcircuit call was silently dropped and the default used, while the same mistake on a `.model` warns and on a device instance is an error. A failed `.measure` left the previous answer under its name, undetectable since `sim_status` is not set by `meas`. `tran` TMAX had no validation and a negative one reported *singular matrix* against the circuit. Six options accepted nonsense in silence while their siblings refused it. And two E-474 refusals named the wrong fault -- every unevaluable `{{ }}` claimed to be outside a loop, and a shadowed loop index died with *device already exists*. Three lookalikes are deliberately left alone and pinned by checks. | ngspice | [doc](enhancements_doc/Enhancement-475.md) | [explicitvalue](examples/explicitvalue_examples/) |
| 474 | feat: `.for` / `.endfor` in the netlist. A run of near-identical instance lines differing only by an index -- a ladder, a stack of periodic sections -- is long to write by hand and wrong in ways that are hard to see, since one node name out of step still parses and still simulates. `.for i in range(1,4)` around `XP{{i}} P{{i}} P{{i+1}} hl_periodic n1={nL}` expands to exactly those four lines. `range(first,last)` **includes both bounds** (four iterations, not Python's three), with optional step, or an explicit list `[7,2,9]`; `{{i}}` and `{{expression}}` (integer arithmetic) are substituted as text, so they build node, instance and model names alike; loops nest, and an inner bound may be an expression over an outer index. Double braces because numparam owns single ones -- a body carries both. Expanded before every other stage, so nothing downstream knows it exists; the bounds therefore cannot be `.param`s and that is refused by name. 14 malformed forms refused, one message each. | ngspice | [doc](enhancements_doc/Enhancement-474.md) | [forloop](examples/forloop_examples/) |
| 473 | fix: the Monte Carlo fast path armed on a draw it could not push -- a silently wrong **and unstable** yield. E-346 pushes re-drawn random values into the live circuit instead of re-sourcing per sample, which is sound only if every use is pushed; but only a **braced** expression is captured and numparam decides the braces, so a quoted `rd='rv'` was captured while a bare `v=rv` in a B-source was walked past and the line called eligible. A B-source value is substituted textually at parse time, so every sample after the first saw the first draw: a 40-sample run reported 100% or 0%, **differing between runs of the same deck and seed**, where the correct sampled answer is ~45%. A random draw outside any braces is now ineligible, so such a deck disarms; the quoted and braced forms still arm, and the three spellings of the same B-source value now agree. This also unblocked giving `montecarlo` -- only under `-warm`, since keeping the circuit also carries the previous sample's solution and E-188 made that opt-in -- the setup reuse E-472 withheld (1.29x, yield unchanged). | ngspice | [doc](enhancements_doc/Enhancement-473.md) | [mcarming](examples/mcarming_examples/) |
| 472 | perf: E-471 gave the setup reuse to `sweep` and nothing else. `optimize` never re-sources the deck for `-param`/`-mparam` knobs -- nor for `-dparam` once E-322's fast path arms -- yet still rebuilt a circuit it had not touched on every evaluation, hundreds of times in a fit. It now asks on the same terms, with every guard E-471's unchanged. The work was proving that holds when a **search step** moves a node collapse rather than a sweep point: a new `cs_thresh` model collapses below a threshold, and a search crossing it reports 1 rebuild in 17 analyses while returning the identical residual, evaluation count and parameter. A well-posed fit is unchanged under `lm` and `nm`; only a degenerate one already at its noise floor takes a different number of evaluations to the same answer. `montecarlo` was built, measured and **taken back out** -- its fast path can arm while a random `.param` has a use it cannot push, which already yields a wrong and run-to-run unstable yield with no reuse involved. | ngspice | [doc](enhancements_doc/Enhancement-472.md) | [reuseloops](examples/reuseloops_examples/) |
| 471 | perf: a sweep now keeps the circuit standing between points instead of tearing it down and building it again for each one -- `.dc` has never done that. After E-470 removed the quadratic teardown the rest of that per-point rebuild was still most of the run: 1001 points over a 2448-unknown stack, **7.24 s -> 0.57 s (12.8x)** under SPARSE with byte-identical results, and 6.35 s -> 1.38 s (4.6x) under KLU, where reusing the matrix ordering moved one number of 5005 by 4.7e-09 relative. KLU was the faster solver on this deck before the change and is now the slower one. The obstacle is node collapse -- a device may merge two of its nodes at setup, so naive reuse freezes the topology and draws a flat line (a first version did exactly that and was reverted). A reused point still runs `CKTtemp`, which re-decides an OSDI device's collapse against the snapshot the matrix was built from, and any change forces a real rebuild; a built-in device, which decides its collapse only in `DEVsetup`, declines reuse for the whole circuit; a failed point never hands its state on. Default on, `.option reusesetup=0` off, `set ngdebug` reports the decision. | ngspice | [doc](enhancements_doc/Enhancement-471.md) | [reusesetup](examples/reusesetup_examples/) |
| 470 | perf: tearing an OSDI circuit down was **quadratic** in its node count. `CKTdltNNum()` scans the node list from the head and `OSDIunsetup()` calls it once per internal node, so every repeated analysis paid O(k*N) -- a profile of a 1001-point sweep over a 2448-unknown circuit found **77% of the entire run** in the teardown *between* points. The caller now marks every number it wants gone and one walk removes them all. Per sweep point 32.9 -> 7.6 ms at 25 stack periods, 4.0 -> 2.3 at 10, 1.7 -> 1.2 at 5 -- the speedup growing with size is the signature of removing a quadratic; the full deck 29.78 s -> 7.12 s, byte-identical. Scoped as "move sweep's loop into the analysis kernel" on the theory that the gap was per-point setup; the scope note put instrumentation first and the profile overturned it, so the large rewrite was not built. A second profile was needed because the first fix sized its mark array from `CKTmaxEqNum`, which shrinks as nodes are deleted, so later model types fell back to the slow path | ngspice | [doc](enhancements_doc/Enhancement-470.md) | [teardown](examples/teardown_examples/) |
| 469 | feat: `.option saveused` (or `set saveused`) keeps only the vectors the `.control` block actually reads. An analysis stores every node at every point unless a `save` says otherwise; on a 2448-unknown dielectric stack a 201-point parameter sweep costs 104.73 s that way and 7.22 s with a hand-written `save`, a factor of 14.5 from one line the author has to remember and keep in step with the `wrdata` beside it. With the option on and no `save` line the same deck runs in 7.08 s with byte-identical results. The scan is deliberately wider than the output command's arguments -- every `v(...)`, `i(...)` and `@dev[param]` anywhere in the block -- because `let r = v(out) - v(mid)` then `wrdata r` names only `r`, and dropping the two vectors that build it would turn a performance option into a wrong answer. Stands aside entirely for an explicit `save`/`.save`, for `all`, and for a block with no output command. Not called `autosave`: E-192 owns that name for `set autosave=<file>`, and a filename is a string that is not an off-word, so reading it as a boolean would have switched filtering on for every deck using E-192's checkpointing | ngspice | [doc](enhancements_doc/Enhancement-469.md) | [saveused](examples/saveused_examples/) |
| 468 | fix: seven numbers that were wrong, two in code with no test coverage. `psd` reported a total power set by the WINDOW, not the signal -- a constant 1 V (true power 1 V^2) read 1.4999 under the default hanning window and 3.0 once zero-padded, because the window is scaled for unit coherent gain while a PSD sums squared bins; the normalisation is now N*sum(w^2), which leaves the already-correct rectangular case bit-for-bit unchanged. numparam's `**` and `^` dropped the sign of a negative base, so `.param {(-2)**1}` returned +2 -- E-446 fixed exactly this in the OTHER evaluator, whose suite builds only B-source decks, so one simulator answered -8 for a B-source and +8 for a `.param`. Over a nested `.dc`, avg and integ integrated across the sweep restarts (0.25 and 0.5) while rms refused on the same plot; the integrating three now refuse and explain, and max/min still work. Undoes an E-467 regression that let `meas dc` measure a tran or ac plot. `sens` reported `nan` for a diode's `ikf` on every model leaving it at its default. Duplicate parameters were silent on built-in model cards and instance lines -- extending E-395's check needed the discovery that built-in parameter ids are enum tags, not dense indices. And the XSPICE `limit` block stopped limiting for a negative `limit_range`, which the `climit` sibling has always tested for. Two candidates withdrawn as my own measurement error | ngspice | [doc](enhancements_doc/Enhancement-468.md) | [mathguard](examples/mathguard_examples/) |
| 467 | fix: eleven silent acceptances. Root of a class four enhancements had patched one site at a time -- an option's spelling decides its published type (bare a BOOL, `=1` a NUMBER, `=true` a STRING) and `cp_getvar` had no CP_BOOL coercion, so all ~110 CP_BOOL readers saw only the bare word: `set sqrnoise=1`, `interp=1` and `autostop=1` each did nothing. Fixed once in `cp_getvar`; `=0` still means off. The fix found its own hazard, a cascade leading with CP_BOOL that swallowed `.option autoadapt=debug`, caught by two existing suites. Also: `.option defas=` assigned the DRAIN field so the source-area default was unreachable; an instance `temp`/`dtemp` below absolute zero answered -0.998 V from a +1 V source; KiCad-spelled subcircuit formals never matched under `autobus=kicad`, leaving the device floating at 1.0 against 0.5238095; `.func sqrt(x)` silently replaced the built-in; `.adapt` validated the adapter model but not its node list, so one typo switched the feature off; `meas` lost max/min/avg/rms/integ over a `.dc` of a device parameter while find-when worked on the same plot; and `alter @dm[is]` blamed the parameter when the cause was that `dm` is a model. Four candidates were withdrawn rather than shipped -- three on re-verifying the measurement, and a negative-geometry guard when E-438's own suite caught it suppressing the `warn_physics` report it duplicated | ngspice | [doc](enhancements_doc/Enhancement-467.md) | [silentaccept](examples/silentaccept_examples/) |
| 466 | fix: `.option autoadapt` is quiet by default -- E-463 printed a line per adapter and per non-qualifying node, which buried the run's output; `.option autoadapt=debug` asks for it back, while errors are never silenced. Also fixes the value never being looked at, so `autoadapt=0`, `=false`, `=no` and `=off` ALL turned the feature on and a deck silently gained an adapter its author had just switched off -- the fourth appearance of that defect after E-450, E-451 and E-454, now using the word list they share | ngspice | [doc](enhancements_doc/Enhancement-466.md) | [adaptquiet](examples/adaptquiet_examples/) |
| 465 | perf+fix: `sweep` no longer re-sources the deck once per point for subcircuit and derived `.param` knobs -- 1.58s -> 0.50s on a 3000-element deck at 201 points, 0.54s -> 0.07s on 800 subcircuit instances. Derived params and chains, X-line passing, nested calls, header defaults, derived params inside subcircuits and local shadows all stay on E-320's fast path: each captured expression is rewritten once at build time into global names by walking the instance's scope chain, since a subckt param is bound PER INSTANCE while the template is keyed by source line. Also fixes the reset path never restoring the knob into the live circuit -- E-385 closed that for the fast path only, so every analysis after a fallback sweep was quietly wrong | ngspice | [doc](enhancements_doc/Enhancement-465.md) | [sweepsubfast](examples/sweepsubfast_examples/) |
| 464 | fix: a bus FORMAL and a LOCAL bus on the same OSDI instance line gave a wrong answer -- inside `.subckt s a[0] a[1] a[2] a[3]`, E-449 expanded `a` into the caller's four actuals while `b` stayed one token, leaving five node tokens where autobus needs two or eight, so nothing expanded and the tokens bound positionally with the top three bits dangling (1.0 against 0.5238095 for the same circuit flattened by hand). Every remaining bus port on such a line is now expanded too, using widths reached through `INPtypelook` and INP2N's own exported port grouping. A second defect surfaced during the fix: the `autobus` variable is not published at flattening time, so the kicad bit spelling was silently lost -- the style now travels with the flag | ngspice | [doc](enhancements_doc/Enhancement-464.md) | [busmix](examples/busmix_examples/) |
| 463 | feat: `.option autoadapt adapter=<model>` -- inject a two-bus-port adapter between two OSDI devices sharing a bus node, so `N1 a b m1` / `N2 b c m2` becomes `N1 a b_f m1` / `N2 b_r c m2` plus the adapter instance, instead of renaming the node on both lines by hand. Runs between INPpas1 and INPpas2 -- the only seam where the model table exists (so port structure is knowable), subcircuits are flattened, and INP2N has not run (so the rewrite is at token level and autobus expands all three lines). The forward side is chosen by port INDEX, not deck order, so reordering the netlist cannot change the circuit; every non-qualifying case is refused and reported. Optional `.adapt n1, n2` restricts the node set by whole token | ngspice | [doc](enhancements_doc/Enhancement-463.md) | [autoadapt](examples/autoadapt_examples/) |
| 462 | feat: `.option autobus=kicad` -- the bit spelling a schematic can write. E-444 names an expanded bus port's terminals `a[0]`..`a[4]`, but KiCad's SPICE exporter rewrites every `[` and `]` in a net name to `_`, so a sheet labelling a wire `AA[0]` emits `/AA_0_` (multi-digit indices intact, `ZA[10]` -> `/ZA_10_`) while KiCad's internal name keeps the brackets -- so the bits of a bus port could not be labelled, wired to ordinary parts, or plotted, and the signal list offered `/AA`, which after expansion carries no device at all. The option changes only the generated spelling; indices still come from the model, so `[4:1]` still expands 1..4. An unknown style is reported rather than silently falling back to a deck that still solves with every bit dangling | ngspice | [doc](enhancements_doc/Enhancement-462.md) | [autobuskicad](examples/autobuskicad_examples/) |
| 461 | fix: a string parameter's `from '{"a","b"}` set selection did not work -- only the FIRST member was ever enforced, because the parser reads the whole list but the AST accessor returned just the first child, so `from` rejected its own members, reordering the list changed which value was legal, and `exclude` silently ACCEPTED every forbidden value after the first; a set now becomes one constraint per member (numeric sets had the same bug). ngspice also corrupted the value before the model saw it -- `ty="PMOS"` arrived as `pmos` and `ty="with space"` as `with` -- so a quoted value on a model card or instance line now survives verbatim | both | [doc](enhancements_doc/Enhancement-461.md) | [strparam](examples/strparam_examples/) |
| 460 | fix: five defects from a one-hour hunt -- `a.potential.access` crashed the compiler (LRM Syntax 5-4 forbids reading `access`/`ddt_nature`/`idt_nature` this way; the attribute type never resolved, nothing was reported, and the lowering panicked); a multi-dimensional `$table_model` file whose axis was not ascending was interpolated to garbage in silence while every 1-D form already sorted its breakpoints; event control statements were accepted -- and their guarded statement silently dropped -- in the two places the LRM forbids them, `analog initial` and analog functions; and `-D =1` names no macro. Two further LRM nature rules were implemented and withdrawn when the sweep failed E-39's and E-422's suites, which pin the opposite on purpose | openvaf-r | [doc](enhancements_doc/Enhancement-460.md) | [ctxguard](examples/ctxguard_examples/) |
| 459 | fix: a part select as an analog-filter coefficient vector -- `de[0:1]`, the second of the three argument forms LRM Syntax 4-3 defines -- was rejected as "wrong number of array indices", since a part select and a multi-dimensional `m[i][j]` both reach inference as a two-index bit-select. They are distinguishable one layer up, where the parser keeps the colon and body lowering records every part select, so no new syntax was needed. The slice is built in the order written -- a reversed slice is a different filter, pinned by value -- and consuming it is what makes it legal, so a part select anywhere else stays refused | openvaf-r | [doc](enhancements_doc/Enhancement-459.md) | [filterslice](examples/filterslice_examples/) |
| 458 | fix: every LRM function checked in every argument form the spec defines (117 builtins, 223 compiled-and-run checks) and seven defects fixed -- `ln1p`/`expm1` did not exist in either spelling and are now their own opcodes on libm `log1p`/`expm1`, since the naive `ln(1+x)` is wrong in the first significant digit near zero; `$abs`/`$min`/`$max` were the only math functions whose `$`-spelling was unregistered; an array PARAMETER, the form the LRM lists first for a filter coefficient vector, was rejected by every Laplace/Z filter; a trailing null filter argument was a syntax error while the interior one worked; `$simparam` demanded a literal where the LRM allows a parameter or variable; `$fatal` alone refused its bare form; and a string-parameter `noise_table` file name panicked the compiler | openvaf-r | [doc](enhancements_doc/Enhancement-458.md) | [lrmfuncs](examples/lrmfuncs_examples/) |
| 457 | fix: replication inside an assignment pattern did not compile -- `'{4{0}}` failed at parse time, and so did the LRM's own initializer examples (`real distort[0:2][0:2] = '{ 3{ '{3{0.0}}}};`). The replication that always worked, `{4{0}}`, is the concatenation operator; `'{4{0}}` is an assignment pattern, a different construct one apostrophe away. The parser now builds the same node shape, and expansion happens in one shared walker instead of three, so the leaf count and the elements cannot disagree; an unfoldable, negative or oversized count is left unexpanded and reported | openvaf-r | [doc](enhancements_doc/Enhancement-457.md) | [patternrep](examples/patternrep_examples/) |
| 451 | fix: two options were located by a bare substring search over the option line, so any option whose NAME MERELY ENDED in the watched text was taken as that option -- `myseed=7`, `noseed=7` and `xseed=7` all set the RNG seed, and the `cshunt` equivalents moved a node from 1.0 V to 6.92e-07, six orders of magnitude. Each also printed "unknown option", so the user was told the name was not recognised while it changed the answer. Now matched as whole tokens, `seedinfo` included. Separately, three options that demonstrably take effect were reported as unknown -- `scale` doubles `@m1[w]`, `rseries` moves a transient, and `autostop` truncates one from 567 rows to 2 -- the case E-447 fixed for three other names; `scalm` is flagged too and deliberately left out, having no demonstrable effect | ngspice | [doc](enhancements_doc/Enhancement-451.md) | [optname](examples/optname_examples/) |
| 450 | fix: `.options savecurrents` could be requested but never declined. Whether it was in force was decided by a bare `strstr` for the word over the option line, so EVERY line merely containing it switched it on whatever the line said -- `savecurrents=0`, `savecurrents=false` and `nosavecurrents` all turned it ON, the last being ngspice's own `no<option>` convention (noacct, noinit, nomod), and any identifier containing the word matched too. Silent, because a deck that quietly saves every terminal current still simulates correctly; it just carries vectors nobody asked for. The line is now read as tokens, a `no` prefix or a false value turns it off, and the later card wins. Which card is retained is unchanged, so the `savecurrents_bsim3`/`_bsim4`/`_mos1` MOS variants still pick their own current sets | ngspice | [doc](enhancements_doc/Enhancement-450.md) | [savecuroff](examples/savecuroff_examples/) |
| 449 | fix: `.option autobus` did not reach inside a `.subckt`, and failed silently. A definition declaring `a[0:4]` has the formals `a[0]`..`a[4]`, so a device line writing the bare `a` matched none of them, became the local node `x1.a`, and was then expanded into five FLOATING nodes with the device wired to those instead of the ports. Nothing was reported, because every terminal did receive a node -- so turning the option ON removed the under-connected warning the same deck gets with it OFF. Expansion now happens at subcircuit substitution, where the `.subckt` line alone is enough, ordered by ascending bit index because the model orders bus terminals that way whatever direction the Verilog-A declared. The other form, `.subckt mysub a b` with scalar formals passing the bus base through, already worked and is unchanged | ngspice | [doc](enhancements_doc/Enhancement-449.md) | [subbus](examples/subbus_examples/) |
| 448 | fix: a node named after one of the twelve built-in constants (`c`, `e`, `i`, `pi`, `kelvin`, `boltz`, `echarge`, `planck`, `TRUE`, `FALSE`, `yes`, `no`) was answered with the constant. `v(c)` on a renamed or mistyped node returned 2.9979e+08 instead of failing, which `sweep` drew as a flat curve and which walked through E-431's "-output never resolved" refusal; the other names are worse because they look like results, `v(no)` giving a flat 0.0. A bus bit `c[0]` -- what `.option autobus` builds for a bus called `c` -- was unreachable while `print all` printed it correctly, because E-224 preferred the literal name only when nothing called `c` existed. The same gate silently returned the wrong vector's element whenever the base was longer, so a circuit with both a node `q` and a bus bit `q[0]` read node `q`'s first sample for `print q[0]` in tran | ngspice | [doc](enhancements_doc/Enhancement-448.md) | [constname](examples/constname_examples/) |
| 447 | fix: eight degenerate inputs accepted in silence, each with a working guard a few lines away covering a different spelling — a negative `gmin` wrecked the operating point while every sibling tolerance was guarded; `scale=0` shorted a resistor though a written `0` warned and was clamped; `trrandom` with a type outside 1–4 was a dead source; diode `level=99` was accepted while `level=2` was refused; `cshunt` from `.control` was ignored; `show` claimed a source had all eight transient waveforms; `savecurrents`/`seed`/`numdgt` were called unknown while working. `m=0` and `@r[resistance]` were left alone — E-426 had settled both | ngspice | [doc](enhancements_doc/Enhancement-447.md) | [guardspell](examples/guardspell_examples/) |
| 446 | fix: six things the netlist wrote that were quietly discarded — an explicit `TD1=0` on an EXP source was read as "not supplied" and replaced by the timestep, so the waveform ran a step late and the answer depended on the step (~4% at 100µs); the same zero-as-sentinel test made PULSE `PW=0`/`PER=0` differ between voltage and current sources; a PWL list with an odd token count had a value invented for the dangling time; a third `.dc` source and surplus `.ac` arguments were dropped in silence; `(-2)**3` returned +8 while the same simulator's Verilog-A `pow(-2,3)` returns −8; `@c[capacitance]` folded in `m=` while `@r[resistance]` did not | ngspice | [doc](enhancements_doc/Enhancement-446.md) | [argdiscard](examples/argdiscard_examples/) |
| 445 | fix: nine silent failures — a bare `.four` card segfaulted; `.four 1e400` overflowed to `+INF` and reported a 202% THD; `R1 a b 1,5k` silently became 5k because a trailing unlabeled number overwrote the value; an array instance past 8192 collapsed to ONE device; `.option autobus` indexed ground into five floating nodes, leaving the device disconnected; a failed `sweep` point republished the previous solution; a legal 20-deep hierarchy was refused as infinite recursion; an iteration limit below the solver floor was discarded unannounced | ngspice | [doc](enhancements_doc/Enhancement-445.md) | [guardgaps](examples/guardgaps_examples/) |
| 444 | opt-in `.option autobus`: a Verilog-A bus port can be connected by one name — `N1 a b` expands to `a[0]`…`a[4]` from the model's own terminal table, so the indices come from the model (a `[4:1]` port gives `a[1]`…`a[4]`), and the `$port_connected` idiom is untouched | ngspice | [doc](enhancements_doc/Enhancement-444.md) | [autobus](examples/autobus_examples/) |
| 443 | index lists: `a[1,3,5]` and `R[1,3,5]` alongside the existing ranges, and the two written together as `a[0:1,7]` — for node fields, instance names and wrapped `.save v(a[1,3,5])` refs. Written order is kept; a lone `a[2]` is still a scalar bit, so existing decks are unaffected | ngspice | [doc](enhancements_doc/Enhancement-443.md) | [idxlist](examples/idxlist_examples/) |
| 442 | `listing tree` draws the subcircuit hierarchy — each `X` labelled with the subcircuit it instantiates and drawn where it is *used*, plus a count of instances, devices and depth — instead of `listing e`'s flat one-line-per-device wall. `listing t` works too | ngspice | [doc](enhancements_doc/Enhancement-442.md) | [listtree](examples/listtree_examples/) |
| 441 | array instances: `R[0:3] a b r=1k` is four resistors in parallel, and `N[0:3] a[0:3] a[1:4] model` indexes each node range **in step** with the instance. A range on the NAME selects this reading, so Enhancement-221's `X1 bus[0:3] sub` (one device, wide port) is untouched. Elements are addressable as `@r[2][resistance]` | ngspice | [doc](enhancements_doc/Enhancement-441.md) | [arrayinst](examples/arrayinst_examples/) |
| 440 | fix: `sens` left the circuit altered -- perturbing a parameter marks it *given* and nothing un-marks it, so a BJT fell into the `ibe`/`ibc` branch with both at 0, lost its junction saturation currents, and every later analysis was 12.8% wrong (101% for a diffpair), silently. Models are now snapshotted and restored. Also: `pss` argument checks (a negative `stabtime` ran forever), `.meas` window checks, `pow(0,-1)`, a heap abort on `set curplotname`, and an unbounded `sprintf` in the expression parser | ngspice | [doc](enhancements_doc/Enhancement-440.md) | [sensrestore](examples/sensrestore_examples/), [argguard](examples/argguard_examples/) |
| 439 | fix: KLU accepted a singular refactor -- `klu_refactor` reuses the previous pivot order without pivoting or a singularity test, so it returned success on a zero-pivot LU and the solve produced NaN; an operating point SPARSE solves (a node with no DC path) failed after 33,911 iterations. A `klu_rcond` check routes it into the reorder path SPARSE already uses | ngspice | [doc](enhancements_doc/Enhancement-439.md) | [klusingular](examples/klusingular_examples/) |
| 438 | fix: a failed simulation no longer becomes data -- `montecarlo` counted samples that never solved as PASSING (100% yield on 14-of-20 failures); `sweep` and `optimize` now report theirs. Adds opt-in `.option warn_physics` | ngspice | [doc](enhancements_doc/Enhancement-438.md) | [failacct](examples/failacct_examples/), [warnphysics](examples/warnphysics_examples/) |
| 437 | fix: a swept `@*:model[param]` is put back when the sweep ends -- Enhancement-436 gave the form a set path but not Enhancement-409's capture-and-replay -- and a valueless `.temp` card, which silently ran the circuit at 0 C, is refused | ngspice | [doc](enhancements_doc/Enhancement-437.md) | [modelwild](examples/modelwild_examples/), [sweepguard](examples/sweepguard_examples/) |
| 436 | feat: `@*:model[param]` -- one model name, every instance path including the top-level card; a bare `@rmod` still means that card alone, but now reports the copies it left untouched | ngspice | [doc](enhancements_doc/Enhancement-436.md) | [modelwild](examples/modelwild_examples/) |
| 424 | fix: a noise or `ac_stim` source inside a run-time loop registered no source at all and contributed nothing, silently -- while every other analog operator in that position was already an error | openvaf&#8209;r | [doc](enhancements_doc/Enhancement-424.md) | [noiseloop](examples/noiseloop_examples/) |
| 423 | fix: a parenthesised comma list `(a, b)` kept only its first element and never checked the rest, so a `,` written for a `+` silently dropped a term and undeclared names hid in the discards | openvaf&#8209;r | [doc](enhancements_doc/Enhancement-423.md) | [commaexpr](examples/commaexpr_examples/) |
| 422 | fix: one reference, three outcomes -- an unresolvable parent nature CRASHED the compiler even when unused, `ddt_nature`/`idt_nature` went silent, and a discipline's `potential`/`flow` blamed the model body | openvaf&#8209;r | [doc](enhancements_doc/Enhancement-422.md) | [natureref](examples/natureref_examples/) |
| 421 | fix: a check that existed for one spelling and not its sibling -- an `exclude` swallowing its `from` range or written backwards, and `$simparam` names, the only such name whose typo is FATAL at run time | openvaf&#8209;r | [doc](enhancements_doc/Enhancement-421.md) | [rangeguard](examples/rangeguard_examples/) |
| 420 | fix: six things accepted then silently degenerate -- integer `**` with a negative exponent, a zero laplace denominator or `zi_*` period, an illegal `last_crossing` direction, an unmatched `ac_stim` name | openvaf&#8209;r | [doc](enhancements_doc/Enhancement-420.md) | [vafdegen](examples/vafdegen_examples/) |
| 419 | feat: three integration methods — trbdf2 (L-stable composite, kills trapezoidal ringing), sdirk (order-3 L-stable Runge-Kutta), adams (variable-step Adams-Moulton); all opt-in, error constants derived not borrowed | ngspice | [doc](enhancements_doc/Enhancement-419.md) | [integmethod](examples/integmethod_examples/) |
| 418 | fix: four unchecked things — absdelay/last_crossing read 0 unless contributed, pz blamed the netlist for that same empty row, .save never validated a device name, meas when invented a time in the first interval | ngspice | [doc](enhancements_doc/Enhancement-418.md) | [saveguard](examples/saveguard_examples/) |
| 417 | fix: a node collapse re-decided after setup — sens printed roundoff, a .dc temp sweep ran one topology, savecurrents skipped two-terminal names | ngspice | [doc](enhancements_doc/Enhancement-417.md) | [collapsestate](examples/collapsestate_examples/) |
| 416 | fix: a terminal collapsed onto an internal node reported exactly zero current; the whole collapse group is now summed | ngspice | [doc](enhancements_doc/Enhancement-416.md) | [collapsecur](examples/collapsecur_examples/) |

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

On Ubuntu 22.04 / Debian 12, whose repos stop at older LLVM versions, get `openvaf-r`'s LLVM 18 runtime from [apt.llvm.org](https://apt.llvm.org/) — which is also the exact build these binaries were linked against:
```bash
wget https://apt.llvm.org/llvm.sh && chmod +x llvm.sh && sudo ./llvm.sh 18
```

**Fedora / RHEL:**
```bash
sudo dnf install readline libX11 libXaw libXft libXext   # ngspice
sudo dnf install llvm18-libs                             # openvaf-r
```

> **`openvaf-r` needs one exact library *filename*, not merely the right LLVM
> version.** It links LLVM dynamically, and the recorded dependency is the
> SONAME **`libLLVM-18.so.18.1`**. The dynamic linker matches that string
> literally — there is no prefix or version-range matching — so a perfectly good
> LLVM 18.1 installed under a *different name* does not satisfy it:
>
> ```
> openvaf-r: error while loading shared libraries: libLLVM-18.so.18.1:
>            cannot open shared object file: No such file or directory
> ```
>
> Debian and apt.llvm.org use that spelling; several other packagings ship the
> same library as `libLLVM.so.18.1`, without the `-18` infix. (The binaries carry
> no `RUNPATH`, so only `ld.so.cache`, the standard directories and
> `LD_LIBRARY_PATH` are searched.) Check what you have, and if only the name
> differs, supply the name the loader asks for:
>
> ```bash
> ldd bin/linux/intel/openvaf-r | grep -i llvm                             # what is missing
> ls /usr/lib/*/libLLVM*18* /usr/lib/llvm-18/lib/libLLVM*.so* 2>/dev/null   # what you have
>
> have=/usr/lib/$(uname -m)-linux-gnu/libLLVM.so.18.1      # ...whatever the line above found
> sudo ln -s "$have" "$(dirname "$have")/libLLVM-18.so.18.1" && sudo ldconfig
> ```
>
> Use a **symlink, not a copy**: libLLVM is ~120 MB, and a copy silently goes
> stale the next time LLVM is updated. Keep it pointing at an **18.1.x** library
> — LLVM's C++ ABI is not stable across releases, so aliasing a different version
> turns a clean load error into a crash.

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
