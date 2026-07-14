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

One hundred and eighty-nine enhancements so far — language features, correctness fixes, systematic audits, and simulator-side workflow tooling, each verified end-to-end by a committed example suite and released with a detailed write-up.

**🗂️ Browse them all in the [live feature catalog](https://javanoviceprogrammer.github.io/Ngspice_OpenVAF_Enhancements/)** — every enhancement grouped into 19 feature areas across the compiler and the simulator, searchable, with each entry linking to its write-up.

**📖 Start with the [User Handbook](docs/handbook/README.md)**, which organizes everything by topic: [getting started](docs/handbook/01-getting-started.md), the [Verilog-A feature matrix](docs/handbook/02-verilog-a-language.md), [ngspice workflows](docs/handbook/03-ngspice-workflows.md), and the [limitations & gotchas](docs/handbook/04-limitations-and-gotchas.md). The whole handbook plus the complete text of every enhancement write-up is also one linked PDF: [docs/Ngspice-OpenVAF-Handbook.pdf](docs/Ngspice-OpenVAF-Handbook.pdf).

**🔧 Want to understand the compiler itself?** [OpenVAF Compiler Internals](docs/internals/openvaf_internals/OpenVAF_compiler_internals.md) ([PDF](docs/internals/openvaf_internals/OpenVAF_compiler_internals.pdf)) is a ground-up, no-prior-knowledge walkthrough of how `openvaf-r` turns a Verilog-A model into a `.osdi` library — every stage of the pipeline (lexing → HIR → MIR → automatic differentiation → LLVM → OSDI), with real dumped IR traced end-to-end on a worked example.

**⚙️ Want to understand the simulator itself?** [ngspice Simulator Internals](docs/internals/ngspice_internals/ngspice_simulator_internals.md) ([PDF](docs/internals/ngspice_internals/ngspice_simulator_internals.pdf)) is the companion guide — a ground-up walkthrough of how `ngspice-46` turns a netlist into a running circuit: the shell/engine split, the netlist parser, the `CKTcircuit`, the `SPICEdev` device interface, the sparse-matrix Newton loop, the analyses, and — crucially — how OpenVAF `.osdi` models plug in as first-class devices, traced end-to-end on a worked RC example.

**🛡️ How robust is the compiler?** [OpenVAF Robustness Campaign](docs/internals/openvaf_internals/OpenVAF_robustness_report.md) ([PDF](docs/internals/openvaf_internals/OpenVAF_robustness_report.pdf)) reports a deep robustness audit of `openvaf-r` — the full production-model corpus, ~50 adversarial inputs, and 4,000 mutation-fuzzing iterations — and the four crash/hang paths it found and fixed (Enhancement-147/-148).

**⏱️ How fast does it compile?** [OpenVAF Compile-Time Analysis](docs/internals/openvaf_internals/OpenVAF_compile_time_analysis.md) ([PDF](docs/internals/openvaf_internals/OpenVAF_compile_time_analysis.pdf)) profiles where `openvaf-r`'s compilation time goes (≈70 % LLVM optimizing one `eval` function), why it's bound to a single core despite already parallelizing, and the compile-vs-simulation-speed trade-off of the `-O` level.

The index: **Doc** links each enhancement's detailed write-up, **Examples** links the folder whose verify script pins the behavior.

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
| 12 | `$simprobe`/aliases/plusargs as LRM fallbacks (last unsupported builtins) | openvaf&#8209;r | [doc](enhancements_doc/Enhancement-12.md) | [alias](examples/alias_examples/) |
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
| 74 | Performance benchmark — OSDI-vs-built-in twins at parity (RC ladder 0.99×), flagship compile times | both | [doc](enhancements_doc/Enhancement-74.md) | [benchmark](examples/benchmark_examples/) |
| 75 | Dynamic physics validation — reactive paths cross-checked (Cgg AC ≡ transient, charge conservation, tran-sine ≡ .ac) | openvaf&#8209;r | [doc](enhancements_doc/Enhancement-75.md) | [dynphys](examples/dynphys_examples/) |
| 76 | Multi-module `.osdi` libraries — audit + registration fixes (duplicate warning, double-load skip, stock `.model` segfault) | ngspice | [doc](enhancements_doc/Enhancement-76.md) | [multimod](examples/multimod_examples/) |
| 77 | ngspice zero-warning build (33 → 0) — SDK macro clashes, `%Id`→`%zu` (readable plot-memory errors), codemodel `dynamic_lookup` | ngspice | [doc](enhancements_doc/Enhancement-77.md) | — |
| 78 | `casex`/`casez` — don't-care digits in item literals as comparison masks (priority-encoder idiom) | openvaf&#8209;r | [doc](enhancements_doc/Enhancement-78.md) | [casexz](examples/casexz_examples/) |
| 79 | Benchmark round 2 — BSIM4 ring-oscillator twin (1.1% freq match), `.ac`/`.noise` throughput, KLU-vs-SPARSE + solver-independence pin | both | [doc](enhancements_doc/Enhancement-79.md) | [benchmark](examples/benchmark_examples/) |
| 80 | Temperature physics — `$vt`≡kT/q, `dtemp` alias fix, noise ∝ T, MEXTRAM E_g = 1.25 eV, PSP103 ZTC flip | openvaf&#8209;r | [doc](enhancements_doc/Enhancement-80.md) | [tempphys](examples/tempphys_examples/) |
| 81 | Session-lifecycle audit — reset loops leak-free, `destroy all` verified; once-per-excursion memory warning + `no_mem_check`, `pre_osdi` restart hint | ngspice | [doc](enhancements_doc/Enhancement-81.md) | [lifecycle](examples/lifecycle_examples/) |
| 82 | Provenance + compliance docs — full change reports for both tools (`docs/change_log/`) and the Verilog-A LRM compliance document (`docs/compliance/`) | both | [doc](enhancements_doc/Enhancement-82.md) | — |
| 83 | Transistor-level µA741 demo — a Verilog-A BJT powering the textbook 20-transistor 741; datasheet figures emerge (104 dB, 0.75 MHz, 0.54 V/µs) | openvaf&#8209;r | [doc](enhancements_doc/Enhancement-83.md) | [opamp741](examples/opamp741_examples/) |
| 84 | LRM example sweep — all 231 Verilog-AMS LRM-2023 code examples compile, plus 6 compiler defect fixes (port-branch panics, silent undefined modules, dead-op codegen, exit-0-on-error) | openvaf&#8209;r | [doc](enhancements_doc/Enhancement-84.md) | [lrm](examples/lrm_examples/) |
| 85 | `` `__FILE__``/`` `__LINE__`` predefined macros + part-selects in instance connections (`inst (out[3:2], in)`) — the last two LRM-sweep findings; all 8 sweep defects now fixed | openvaf&#8209;r | [doc](enhancements_doc/Enhancement-85.md) | [filemacro](examples/filemacro_examples/), [partselect](examples/partselect_examples/) |
| 86 | Hierarchical branch probes — `V(top.a1.b)`, `V(inst.branch(a,b))`, `I(inst.branch(<p>))` via synthesized 0V ammeters; + 2 DAE fixes (V-source-to-internal-node open circuit, collapse-of-probed-branch) | openvaf&#8209;r | [doc](enhancements_doc/Enhancement-86.md) | [hierbranch](examples/hierbranch_examples/) |
| 87 | Block-scoped parameters (`parameter`/`localparam` inside `begin: label`, read `label.name`) — feature validated end-to-end + clean diagnostic for the LRM's illegal `#(.blk.p(4))` override | openvaf&#8209;r | [doc](enhancements_doc/Enhancement-87.md) | [blockparam](examples/blockparam_examples/) |
| 88 | Legacy `generate <id> (start, end)` statement (obsolete Verilog-A 1.0 analog-block loop-unroll, LRM Annex C.4) with constant bounds | openvaf&#8209;r | [doc](enhancements_doc/Enhancement-88.md) | [legacygen](examples/legacygen_examples/) |
| 89 | Name-then-range net/port declarations (`input in[0:2]`, `electrical out[0:2]`) + an Annex E SPICE-primitives library (resistor/capacitor/inductor/sources/square-law MOS) | openvaf&#8209;r | [doc](enhancements_doc/Enhancement-89.md) | [arrayport](examples/arrayport_examples/), [annexe](examples/annexe_examples/) |
| 90 | Multi-bit input bus port bit reads: fix scrambled terminal order when a vectored port (`input [0:2] in`) is not the last port in a non-ANSI header, so `V(in[k])` maps to the correct terminal | openvaf&#8209;r | [doc](enhancements_doc/Enhancement-90.md) | [busport](examples/busport_examples/) |
| 91 | Multi-name name-then-range declarations (`input a[0:1], b[0:3], c;`) + parameter-dependent declaration widths (`electrical [0:N-1] out;`, `real w[0:N-1];`, folded from the parameter default) | openvaf&#8209;r | [doc](enhancements_doc/Enhancement-91.md) | [paramwidth](examples/paramwidth_examples/) |
| 92 | Freeze structural (width) parameters to `localparam` so a netlist override cannot desync the frozen width from behavioural code (fixes a silent out-of-bounds in E-91) | openvaf&#8209;r | [doc](enhancements_doc/Enhancement-92.md) | [paramfreeze](examples/paramfreeze_examples/) |
| 93 | Warn when a netlist sets a fixed (`localparam`) parameter: openvaf flags it non-settable (`PARA_FLAG_FIXED`), ngspice warns instead of silently ignoring the value | both | [doc](enhancements_doc/Enhancement-93.md) | [paramnonset](examples/paramnonset_examples/) |
| 94 | New ngspice `pyplot` command — plot simulated vectors with **matplotlib** (a Python counterpart to `gnuplot`); `pyplot_terminal=png` renders headless to a PNG | ngspice | [doc](enhancements_doc/Enhancement-94.md) | [pyplot](examples/pyplot_examples/) |
| 95 | Make the `pyplot` output file name optional — `pyplot v(out)` (or bare node names) defaults the base name to `pyplot`; an explicit name still works | ngspice | [doc](enhancements_doc/Enhancement-95.md) | [pyplot](examples/pyplot_examples/) |
| 96 | Parse a module-level `generate for`/`if`/`case` written **without** the optional `generate`/`endgenerate` keywords (was `unexpected token 'for'`, or silently dropped the loop) | openvaf&#8209;r | [doc](enhancements_doc/Enhancement-96.md) | [baregenerate](examples/baregenerate_examples/) |
| 97 | Clean diagnostic instead of a compiler panic when a contribution's branch is entirely `ground` (`V(gnd) <+ ...`) | openvaf&#8209;r | [doc](enhancements_doc/Enhancement-97.md) | [groundcontrib](examples/groundcontrib_examples/) |
| 98 | `pyplot` multi-panel subplots (`set pyplot_subplots=N`, N traces per stacked panel) + matplotlib style sheets (`set pyplot_style=dark`) | ngspice | [doc](enhancements_doc/Enhancement-98.md) | [pyplotpanel](examples/pyplotpanel_examples/) |
| 99 | `pyplot` vector export formats (`set pyplot_terminal=svg`/`pdf`) + figure size (`set pyplot_figsize="W,H"`) | ngspice | [doc](enhancements_doc/Enhancement-99.md) | [pyplotexport](examples/pyplotexport_examples/) |
| 100 | Milestone audit & retrospective — full-tree re-verification (90/90 suites + 28/28 integration), provenance/link audit, and a look back at the first hundred | both | [doc](enhancements_doc/Enhancement-100.md) | — |
| 101 | `$clog2` correctness — accept one argument (was a bad 2-arg signature) and return `ceil(log2 n)` (was off by one on exact powers of two) | openvaf&#8209;r | [doc](enhancements_doc/Enhancement-101.md) | [clog2](examples/clog2_examples/) |
| 102 | Name-then-range array parameters — `parameter real c[0:2]` (dims after the name), completing the name-then-range line (vars/nets/ports already had it) | openvaf&#8209;r | [doc](enhancements_doc/Enhancement-102.md) | [paramarray](examples/paramarray_examples/) |
| 103 | `ceil()` of a runtime argument no longer crashes the compiler (the `llvm.ceil.f64` intrinsic was unregistered; `floor` worked) | openvaf&#8209;r | [doc](enhancements_doc/Enhancement-103.md) | [ceil](examples/ceil_examples/) |
| 104 | `$rtoi` / `$itor` real↔integer conversion functions (`$rtoi` truncates toward zero, distinct from the rounding implicit cast) | openvaf&#8209;r | [doc](enhancements_doc/Enhancement-104.md) | [convert](examples/convert_examples/) |
| 105 | `$sscanf` / `$fscanf` honour the format base (`%h`/`%x` hex, `%o` octal, `%b` binary) instead of ignoring it | openvaf&#8209;r | [doc](enhancements_doc/Enhancement-105.md) | [sscanf](examples/sscanf_examples/) |
| 106 | String relational comparison (`<`, `<=`, `>`, `>=`) via lexicographic `strcmp` (completes the string comparison surface; `==`/`!=` already worked) | openvaf&#8209;r | [doc](enhancements_doc/Enhancement-106.md) | [stringcmp](examples/stringcmp_examples/) |
| 107 | `$fgetc(fd)` single-character file read (completes the file I/O family: `$fgets`/`$fscanf`/`$ftell`/… already existed) | openvaf&#8209;r | [doc](enhancements_doc/Enhancement-107.md) | [fgetc](examples/fgetc_examples/) |
| 108 | `$ungetc(c, fd)` one-character pushback (the peek/look-ahead companion to `$fgetc`) | openvaf&#8209;r | [doc](enhancements_doc/Enhancement-108.md) | [ungetc](examples/ungetc_examples/) |
| 109 | `noise_table`/`noise_table_log` interpolation corrected to the LRM (linear-in-`f` / log-log; both took Hz input) | openvaf&#8209;r | [doc](enhancements_doc/Enhancement-109.md) | [noisetable](examples/noisetable_examples/) |
| 110 | ngspice `.option errpreset=conservative\|moderate\|liberal` — one knob for a coordinated tolerance/robustness set (Spectre-style); explicit options override regardless of order, `moderate` = historical defaults | ngspice | [doc](enhancements_doc/Enhancement-110.md) | [errpreset](examples/errpreset_examples/) |
| 111 | ngspice `.option linesearch` — globalized (damped) Newton via Armijo backtracking on a new KCL-residual merit `‖F‖=‖G·x−b‖` (the merit ngspice lacked); result-neutral, off by default | ngspice | [doc](enhancements_doc/Enhancement-111.md) | [linesearch](examples/linesearch_examples/) |
| 112 | ngspice KLU support for `.option linesearch` — the KLU matrix-vector product passed NULL ordering maps and segfaulted; the line search now runs under **both** KLU and Sparse 1.3 (merit numerically identical) | ngspice | [doc](enhancements_doc/Enhancement-112.md) | [linesearch](examples/linesearch_examples/) |
| 113 | ngspice **KLU for noise + single-ended pole-zero** — fixed the KLU adjoint solve (was non-transposed, silently wrong on asymmetric circuits) so KLU noise matches Sparse exactly | ngspice | [doc](enhancements_doc/Enhancement-113.md) | [analyses](examples/analyses_examples/), [noisejw](examples/noisejw_examples/) |
| 114 | ngspice **KLU for sensitivity** (`.sens`, DC & AC) — fixed a segfault where KLU setup gated on the main matrix's flag dereferenced the auxiliary `delta_Y`'s NULL matrix; now matches Sparse | ngspice | [doc](enhancements_doc/Enhancement-114.md) | [analyses](examples/analyses_examples/) |
| 115 | ngspice **KLU for distortion** (`.disto`) — the complex solve ran on a real-mode matrix so every harmonic came back zero; now converts real↔complex around the solve like `acan.c` | ngspice | [doc](enhancements_doc/Enhancement-115.md) | [analyses](examples/analyses_examples/) |
| 116 | ngspice **KLU wrong-DC fix for decoupled OSDI nodes** — a `ground`-referenced internal node got an all-zero, structurally-singular solver row; now tied to ground at setup (fixes 2 of 3 KLU_XFAILs) | ngspice | [doc](enhancements_doc/Enhancement-116.md) | [groundcontrib](examples/groundcontrib_examples/), [hierbranch](examples/hierbranch_examples/) |
| 117 | ngspice **PSS productionized** — `.pss` was experimental (~230 trace lines/run); now built by default with the shooting trace gated behind `set ngdebug`. Foundation for the RF small-signal suite | ngspice | [doc](enhancements_doc/Enhancement-117.md) | [rfpss](examples/rfpss_examples/) |
| 118 | ngspice **PSS under KLU** — `.pss` hung because reused KLU pivots exploded the timestep; a full re-factor each step makes KLU match Sparse. Now runs under both solvers | ngspice | [doc](enhancements_doc/Enhancement-118.md) | [rfpss](examples/rfpss_examples/) |
| 119 | ngspice **retain the PSS operating point** — capture node voltages **and** device states per sample (with frequency + dims) as the substrate the periodic small-signal suite linearizes around | ngspice | [doc](enhancements_doc/Enhancement-119.md) | [rfpss](examples/rfpss_examples/) |
| 120 | ngspice **periodic small-signal Jacobian harmonics** — walk the retained op-point, re-linearize and stamp `G+jC` per sample, DFT to harmonics — the blocks the PAC conversion matrix is built from | ngspice | [doc](enhancements_doc/Enhancement-120.md) | [rfpss](examples/rfpss_examples/) |
| 121 | ngspice **PAC conversion-matrix engine** — assemble the `(2M+1)N` harmonic conversion matrix `H_{nm}=G_{n−m}+jω_m C_{n−m}` and solve it (dense complex LU) — the numerical heart of PAC/pnoise/PXF | ngspice | [doc](enhancements_doc/Enhancement-121.md) | [rfpss](examples/rfpss_examples/) |
| 122 | ngspice **`.pac` command** — user-facing periodic AC: `.pac <pss> <dec\|oct\|lin> N f0 f1` sweeps a small-signal input frequency, solving the conversion matrix per point → complex plot | ngspice | [doc](enhancements_doc/Enhancement-122.md) | [rfpss](examples/rfpss_examples/) |
| 123 | ngspice **finish `.pac`** — adds a source-referenced stimulus (true transfer / conversion gain) and multi-sideband output (`maxsideband K` → `<node>_usb<k>`/`_lsb<k>`). PAC complete | ngspice | [doc](enhancements_doc/Enhancement-123.md) | [rfpss](examples/rfpss_examples/) |
| 124 | ngspice **`.pnoise` command** — fold each device's noise through the conversion-matrix adjoint `Hᵀ Ψ = e_{out,0}` per sideband; reduces exactly to `.noise` in the linear limit. RF small-signal #2 | ngspice | [doc](enhancements_doc/Enhancement-124.md) | [rfpss](examples/rfpss_examples/) |
| 125 | ngspice **`.pxf` command** — periodic transfer function, the adjoint of PAC; sideband-0 is bit-identical to the PAC response. **Completes the RF periodic small-signal suite** (PSS→PAC→Pnoise→PXF) | ngspice | [doc](enhancements_doc/Enhancement-125.md) | [rfpss](examples/rfpss_examples/) |
| 126 | ngspice **cyclostationary noise** (`.pnoise … cyclo`) — evaluate each device's PSD `S(t)` at every PSS sample's bias and fold in the time domain; captures pumped devices' bias-dependent shot/flicker noise | ngspice | [doc](enhancements_doc/Enhancement-126.md) | [rfpss](examples/rfpss_examples/) |
| 127 | ngspice **pseudo-transient continuation** (`.option ptcont`) — a `Ẋ`-embedded DC homotopy that follows a stable trajectory to the correct root on stiff circuits where plain Newton overshoots. Off by default | ngspice | [doc](enhancements_doc/Enhancement-127.md) | [ptcont](examples/ptcont_examples/) |
| 128 | ngspice **LTE-based dynamic integration order** (`.option dynorder`) — pick the Gear order per step from the truncation-error limit (unlocking the unused orders 3–6); up to 8.9× fewer steps at matched accuracy. Off by default | ngspice | [doc](enhancements_doc/Enhancement-128.md) | [dynorder](examples/dynorder_examples/) |
| 129 | ngspice **sweep progress bar** — the throttled `Reference value` status line gains a live progress bar + percentage during tran/AC/DC/noise sweeps (stdout only, never in the rawfile). 22/22 | ngspice | [doc](enhancements_doc/Enhancement-129.md) | [progressbar](examples/progressbar_examples/) |
| 130 | ngspice **built-in optimizer** — new `optimize` command: a derivative-free Nelder-Mead search that varies `alter` parameters, re-runs an analysis, and minimizes an objective in normalized [0,1] space. 9/9 vs analytic optima | ngspice | [doc](enhancements_doc/Enhancement-130.md) | [optimize](examples/optimize_examples/) |
| 131 | ngspice **transient checkpoint / restart** — `savestate`/`loadstate` serialize the full transient integration state to disk and resume it, even in a fresh process (stock could only `resume` in memory). Sparse-only; 19/19 bit-identical | ngspice | [doc](enhancements_doc/Enhancement-131.md) | [checkpoint](examples/checkpoint_examples/) |
| 181 | **core-numerics audit + `.options ordfix`** — Gear/BDF corrector certified exact at orders 1–6 (residual ≤1.3e-13) via a fixed-order verification mode; 0 defects | ngspice | [doc](enhancements_doc/Enhancement-181.md) | [corenum](examples/corenum_examples/) |
| 182 | **pyplot autoscale by default** — the matplotlib bridge no longer pins axes from ngspice's grid-rounded ranges; it autoscales + `tight_layout` unless `xlimit`/`ylimit` is given | ngspice | [doc](enhancements_doc/Enhancement-182.md) | [pyplot](examples/pyplot_examples/) |
| 183 | **pyplot usability** — distinct default names for successive plots (fixes a background-viewer race), output written next to the deck, plus `pyplot_linewidth` and `pyplot_backend` | ngspice | [doc](enhancements_doc/Enhancement-183.md) | [pyplot](examples/pyplot_examples/) |
| 184 | **sweep progress bar reaches 100%** — the throttled `Reference value` line skipped the final point, freezing the bar below 100%; a one-shot end print forces it full | ngspice | [doc](enhancements_doc/Enhancement-184.md) | [progressbar](examples/progressbar_examples/) |
| 185 | **autodiff audit: `hypot` & `atan2` derivative fixes** — both had a correct DC value but a wrong Jacobian (`hypot` used the sqrt rule; `atan2` had a reciprocal + sign bug); first compiler-side accidental-correctness bug | openvaf-r | [doc](enhancements_doc/Enhancement-185.md) | [vafautodiff](examples/vafautodiff_examples/) |
| 186 | **autodiff audit: real-modulo (`%`) derivative fix** — `%` was grouped with floor/ceil and given a zero derivative (right value, zero AC/Jacobian); fixed to `x' − floor(x/c)·c'` | openvaf-r | [doc](enhancements_doc/Enhancement-186.md) | [vafautodiff](examples/vafautodiff_examples/) |
| 187 | **math-identity simplifier: invalid inverse-function cancellations** — `asin(sin x)`, `acos(cos x)`, `atan(tan x)`, `acosh(cosh x)`, `sqrt(x²)` were collapsed to the raw inner `x`, wrong for finite inputs outside the principal range (corrupts the DC value itself, not just the derivative); kept only the whole-real-line-valid identities | openvaf-r | [doc](enhancements_doc/Enhancement-187.md) | [mathident](examples/mathident_examples/) |
| 188 | ngspice **Monte Carlo warm-start** (`montecarlo … -warm`) — each MC sample cold-solved its DC bias point, re-running the full gmin/source-stepping homotopy (~52 Newton iterations) even though consecutive samples barely move the operating point. `-warm` reuses the previous converged solution as the initial guess (direct Newton, ~4 iters; auto-fallback to cold homotopy on a bad guess), so the yield is unchanged (exact at tight `reltol`) while the per-sample iteration count drops ~13×. Solver-side (Sparse+KLU); composes with `-lhs`; 5 checks | ngspice | [doc](enhancements_doc/Enhancement-188.md) | [warmstart](examples/warmstart_examples/) |
| 189 | ngspice **sweep waveform overlay** (`sweep … -overlay`) — the `sweep` command (E-146) recorded only each run's *last* value into its summary transfer curve; comparing the full per-point waveforms meant `setplot`-ing each run by hand. `-overlay` captures every point's whole waveform, resamples them onto a common grid (runs land on different adaptive time/freq grids), and builds one `sweepwave` plot with a `<out>_<val>` vector per point — the HSPICE `.step` overlay in one step. Front-end only; gracefully ignored for scalar `op`; curves match `1−exp(−t/RC)` to <1e-4; 5 checks | ngspice | [doc](enhancements_doc/Enhancement-189.md) | [sweepwave](examples/sweepwave_examples/) |
| 132 | ngspice **periodic S-parameters** (`.psp`) — small-signal S-parameters around a PSS op-point including input↔sideband conversion (mixers/switched circuits); sideband-0 reduces exactly to `.sp`. Both solvers; 8/8 | ngspice | [doc](enhancements_doc/Enhancement-132.md) | [psp](examples/psp_examples/) |
| 133 | ngspice **quasi-periodic two-tone steady state** (`qpss`) — two-tone spectrum incl. IM3 via transient + direct DFT at each exact intermod frequency (commensurate tones). Solver-independent; 11/11 incl. the 3:1 IP3 law | ngspice | [doc](enhancements_doc/Enhancement-133.md) | [qpss](examples/qpss_examples/) |
| 134 | ngspice **Harmonic Balance** (`hb`) — frequency-domain periodic steady state by Newton, using the E-121 conversion matrix as the exact Jacobian; nonlinear reactive via `C(v)v'` (no charge extraction). Both solvers, built-in + OSDI; 8/8 | ngspice | [doc](enhancements_doc/Enhancement-134.md) | [hb](examples/hb_examples/) |
| 135 | ngspice **HB source-stepping continuation** — an adaptive `λ:0→1` source homotopy that makes E-134 HB converge on strongly-driven circuits where a cold Newton diverges; bit-identical to the plain solve when it isn't needed. 9/9 | ngspice | [doc](enhancements_doc/Enhancement-135.md) | [hb](examples/hb_examples/) |
| 136 | ngspice **two-tone Harmonic Balance** (`qpss … hb`) — a frequency-domain 2-D HB engine = true incommensurate QPSS; devices sampled on a 2-D phase grid, sources via oversampled least-squares APFT. Both solvers; 7/7 | ngspice | [doc](enhancements_doc/Enhancement-136.md) | [qpss](examples/qpss_examples/) |
| 137 | ngspice **two-tone QPAC** (`qpac <f_in>`) — small-signal quasi-periodic AC around the QPSS-HB op-point, reporting the response at every sideband `f_in+k1·f1+k2·f2`. One dense solve, solver-independent by construction. 7/7 | ngspice | [doc](enhancements_doc/Enhancement-137.md) | [qpac](examples/qpss_examples/) |
| 138 | ngspice **two-tone QPnoise** (`qpnoise <out> <f_in>`) — quasi-periodic noise folding every device's noise over all sidebands via one adjoint solve `Hᵀ Ψ = e_{out,(0,0)}`; reduces exactly to `.noise` with no pump. 6/6 | ngspice | [doc](enhancements_doc/Enhancement-138.md) | [qpnoise](examples/qpss_examples/) |
| 139 | ngspice **cyclostationary QPnoise** (`qpnoise … cyclo`) — time-varying device PSD `S(t)` folded in the time domain (per-sample junction settling); a hard-pumped diode shows ~8× switching-mixer noise enhancement. 10/10 | ngspice | [doc](enhancements_doc/Enhancement-139.md) | [qpnoise](examples/qpss_examples/) |
| 140 | ngspice **oscillator phase noise** (`hbosc` + `phasenoise`) — autonomous HB (bordered Newton for V + ω0) plus a carrier-sideband adjoint giving `L(df)` in dBc/Hz; −20 dB/dec skirt and thermal L∝T validated. 8/8 | ngspice | [doc](enhancements_doc/Enhancement-140.md) | [phasenoise](examples/phasenoise_examples/) |
| 141 | ngspice **two-tone QPXF** (`qpxf <out> <f_in>`) — quasi-periodic transfer function, the adjoint of QPAC; `(0,0)` transfer bit-identical to QPAC by reciprocity. **Completes the two-tone small-signal suite.** 6/6 | ngspice | [doc](enhancements_doc/Enhancement-141.md) | [qpxf](examples/qpss_examples/) |
| 142 | ngspice **QP small-signal frequency sweep** — `qpac`/`qpnoise`/`qpxf` gain a `<dec\|oct\|lin> N f0 f1` sweep of `f_in`, emitting a plottable ngspice plot (conversion gain / NF / image-rejection curves). 5/5 | ngspice | [doc](enhancements_doc/Enhancement-142.md) | [sweep](examples/qpss_examples/) |
| 143 | ngspice **least-squares curve fitting for `optimize`** — a gradient-based `-target` least-squares mode (Levenberg-Marquardt) over one or more `-analysis` stages; ~27 vs 67 evals vs the simplex; OSDI diode extraction. 23/23 | ngspice | [doc](enhancements_doc/Enhancement-143.md) | [fit](examples/optimize_examples/) |
| 144 | ngspice **`optimize` tunes symbolic `.param` values** — new knob kind `-dparam` varies netlist `.param` symbols (via `alterparam` + a quiet `reset` re-source), mixing freely with `-param` device knobs. Closes the last E-143 follow-up. 31/31 | ngspice | [doc](enhancements_doc/Enhancement-144.md) | [fit](examples/optimize_examples/) |
| 145 | **`optimize` tunes `.model`-card parameters** — `-mparam` varies OSDI/built-in model-card values (via `altermod` + a quiet reset), composable with `-param`/`-dparam` | ngspice | [doc](enhancements_doc/Enhancement-145.md) | [fit](examples/optimize_examples/) |
| 146 | **universal `sweep` command + `.sweep` card** — step *any* knob (param, model card, temperature, source) in one nested-loop driver; generalizes `.dc` | ngspice | [doc](enhancements_doc/Enhancement-146.md) | [sweep](examples/sweep_examples/) |
| 147 | **nested `?:` no longer compiles in exponential time** — the ternary lowering was O(2^N) in nesting depth, now O(N); also allows `return;` inside a `?:` arm | openvaf&#8209;r | [doc](enhancements_doc/Enhancement-147.md) | [nested](examples/nested_cond_examples/) |
| 148 | **compiler hardening** — parser expression-depth cap (1000), `` `include `` nesting cap (64) and array-size cap (~1M); closes four crash/hang paths from the robustness campaign | openvaf&#8209;r | [doc](enhancements_doc/Enhancement-148.md) | [robustness](examples/robustness_examples/) |
| 149 | **Latin-Hypercube Monte Carlo** (`mcsample lhs <N>`) — stratified sampling (splitmix64 + probit) with ~130× lower variance of the mean than plain MC | ngspice | [doc](enhancements_doc/Enhancement-149.md) | [lhs](examples/lhs_examples/) |
| 150 | **high-sigma rare-event estimation** (`highsigma <N> -metric -max/-min`) — scaled-sigma importance sampling for far-tail failure probabilities | ngspice | [doc](enhancements_doc/Enhancement-150.md) | [highsigma](examples/highsigma_examples/) |
| 151 | **process/mismatch correlations + yield** (`mccorr`/`mvnorm`, `montecarlo`) — Cholesky-correlated parameter draws plus a packaged yield / confidence-interval report | ngspice | [doc](enhancements_doc/Enhancement-151.md) | [yield](examples/yield_examples/) |
| 152 | **KLU reordering + scaling controls** — `.option klu_ordering` / `klu_scale` / `klu_btf` and a growable memory pool for the KLU factorization | ngspice | [doc](enhancements_doc/Enhancement-152.md) | [klu](examples/klu_tuning_examples/) |
| 153 | **Levenberg-Marquardt trust-region Newton** (`.option trustregion`) — a globalized Newton that damps steps by a trust radius for hard-to-converge DC/transient | ngspice | [doc](enhancements_doc/Enhancement-153.md) | [trustregion](examples/trustregion_examples/) |
| 154 | **Envelope Following** (`envelope <node> <fc> <tstop>`) — tracks the slow envelope of a fast carrier by integrating over whole carrier periods | ngspice | [doc](enhancements_doc/Enhancement-154.md) | [envelope](examples/envelope_examples/) |
| 155 | **RC network reduction** (`reduce <fmax>`) — TICER-style post-layout model-order reduction that eliminates fast RC nodes while preserving the response below `fmax` | ngspice | [doc](enhancements_doc/Enhancement-155.md) | [reduce](examples/reduce_examples/) |
| 156 | **scalable sparse RC reduction** — the E-155 `reduce` made fill-in-aware so it scales to large extracted post-layout networks | ngspice | [doc](enhancements_doc/Enhancement-156.md) | [reduce](examples/reduce_examples/) |
| 157 | **device aging** (`aging <t_target> [dynamic]`) — HCI / NBTI / TDDB stress → degrade model parameters → re-stamp, for lifetime and drift analysis | ngspice | [doc](enhancements_doc/Enhancement-157.md) | [aging](examples/aging_examples/) |
| 158 | **power-grid EMIR** (`emir`) — electromigration + IR-drop on a power grid: current density J=I/(w·thick), Black's-law MTTF, and per-node IR drop | ngspice | [doc](enhancements_doc/Enhancement-158.md) | [emir](examples/emir_examples/) |
| 159 | **production compact-model bring-up** (BSIM4 + EKV) — real CMC models compiled to OSDI and validated against reference DC characteristics | ngspice + openvaf-r | [doc](enhancements_doc/Enhancement-159.md) | [compactmodels](examples/compactmodels_examples/) |
| 160 | **CMC compact-model coverage sweep** — a batch of production CMC models compiled and exercised across DC/AC/noise to confirm broad OSDI coverage | ngspice + openvaf-r | [doc](enhancements_doc/Enhancement-160.md) | [cmcsweep](examples/cmcsweep_examples/) |
| 161 | **dynamic (AC/RF) compact-model validation** — compiled-model AC conductances and capacitances cross-checked against transient and analytic laws | ngspice + openvaf-r | [doc](enhancements_doc/Enhancement-161.md) | [dynmodels](examples/dynmodels_examples/) |
| 164 | **large-signal RF of a real transistor** (P1dB / IP3) — compression and intercept points extracted from a compiled compact model via HB/PSS | ngspice + openvaf-r | [doc](enhancements_doc/Enhancement-164.md) | [rfpa](examples/rfpa_examples/) |
| 165 | **production compact-model noise validation** — a compiled CMC model's thermal / flicker / shot noise checked against analytic PSDs across bias | ngspice + openvaf-r | [doc](enhancements_doc/Enhancement-165.md) | [modelnoise](examples/modelnoise_examples/) |
| 166 | **electro-thermal / self-heating validation** — the thermal node of a self-heating compact model checked against the analytic ΔT = P·Rth law | ngspice + openvaf-r | [doc](enhancements_doc/Enhancement-166.md) | [electrothermal](examples/electrothermal_examples/) |
| 167 | **cross-model self-heating sweep** — self-heating consistency (thermal feedback on DC/AC) across several compact models at varying Rth | ngspice + openvaf-r | [doc](enhancements_doc/Enhancement-167.md) | [cmcselfheat](examples/cmcselfheat_examples/) |
| 168 | **RF noise figure of an LNA** — NF = 10·log10(inoise²/4kTRs); reproduces the classic U-shaped NF-vs-Rs curve from device noise | ngspice + openvaf-r | [doc](enhancements_doc/Enhancement-168.md) | [noisefigure](examples/noisefigure_examples/) |
| 169 | **interactive command-line syntax highlighting** — live green/red/neutral coloring of commands as you type in the ngspice REPL | ngspice | [doc](enhancements_doc/Enhancement-169.md) | [syntaxhl](examples/syntaxhl_examples/) |
| 170 | **semantic syntax highlighting** — extends E-169 to color invalid signals and expressions red, based on the loaded circuit | ngspice | [doc](enhancements_doc/Enhancement-170.md) | [syntaxhl](examples/syntaxhl_examples/) |
| 171 | **KLU pole-zero fixed** — `.pz` under KLU returned silent garbage for complex roots (mixed-up complex determinant); corrected with pivot-tolerance handling | ngspice | [doc](enhancements_doc/Enhancement-171.md) | [klupz](examples/klupz_examples/) |
| 172 | **KLU balanced pole-zero + full pivoting** — union-pattern column reservation and a full-pivot fallback, so nothing in `.pz` is Sparse-only | ngspice | [doc](enhancements_doc/Enhancement-172.md) | [klupz](examples/klupz_examples/) |
| 173 | **eigenvalue-based pole-zero** (`.options pzeig`) — shift-invert generalized-eigenvalue PZ via a new Francis-QR solver (no LAPACK); default stays Muller | ngspice | [doc](enhancements_doc/Enhancement-173.md) | [pzeig](examples/pzeig_examples/) |
| 174 | **`help all` crash fix** — command help strings were used as printf formats, so a stray `%` (montecarlo `95%% CI`) was fatal; escaped, with a static + runtime guard | ngspice | [doc](enhancements_doc/Enhancement-174.md) | [helpcmd](examples/helpcmd_examples/) |
| 175 | **RF-suite audit: dropped parametric term** — LPTV conversion matrices omitted the pumped-capacitance term Ċ·δv, shrinking mixer sidebands; fixed across pac/psp/pnoise/pxf/qp\* | ngspice | [doc](enhancements_doc/Enhancement-175.md) | [rfconv](examples/rfconv_examples/) |
| 176 | **driven-mode PSS shooting** — PSS hunted the frequency on driven circuits (breakpoint flood, non-convergence); driven mode pins the exact source period | ngspice | [doc](enhancements_doc/Enhancement-176.md) | [pssdriven](examples/pssdriven_examples/) |
| 177 | **pnoise folding referee + folded-flicker frequency fix** — folded sidebands were evaluated at the output frequency, not the true source frequency f+k·f0; frequency-dependent PSDs (flicker, `noise_table`) now correct | ngspice | [doc](enhancements_doc/Enhancement-177.md) | [pnoisefold](examples/pnoisefold_examples/) |
| 178 | **exact cyclostationary folding + HB DC-source fix** — separable-envelope folding (⟨m⟩² for flicker, ⟨m²⟩ for white); plus an HB bug that double-subtracted DC sources (every bias 2×) | ngspice | [doc](enhancements_doc/Enhancement-178.md) | [cyclofold](examples/cyclofold_examples/) |
| 179 | **standard-analyses audit + three fixes** — `.tf` output impedance stuck at 1e20 (SPICE3 clamp), KLU AC `.sens` truncated to one frequency, and `.meas DERIV` implemented | ngspice | [doc](enhancements_doc/Enhancement-179.md) | [stdaudit](examples/stdaudit_examples/) |
| 180 | **checkpoint/restart under KLU** — `loadstate` crashed because the solver option was applied after `CKTsetup`; fixed, plus cross-solver restore. Nothing is Sparse-only now | ngspice | [doc](enhancements_doc/Enhancement-180.md) | [checkpoint](examples/checkpoint_examples/) |
| 162 | **`.hb` dot-card for harmonic balance** — runs the E-134 `hb` engine straight from the deck (no `.control`) via the deck→control bridge | ngspice | [doc](enhancements_doc/Enhancement-162.md) | [hb](examples/hb_examples/) |
| 163 | **`.qpss` / `.hbosc` / `.phasenoise` dot-cards** — netlist dot-card parity for the two-tone QPSS, autonomous-oscillator HB, and phase-noise commands | ngspice | [doc](enhancements_doc/Enhancement-163.md) | [qpss](examples/qpss_examples/) · [phasenoise](examples/phasenoise_examples/) |

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
