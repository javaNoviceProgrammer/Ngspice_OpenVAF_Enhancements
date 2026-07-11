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

One hundred and fifty-four enhancements so far — language features, correctness fixes, systematic audits, and simulator-side workflow tooling, each verified end-to-end by a committed example suite and released with a detailed write-up.

**🗂️ Browse them all in the [live feature catalog](https://javanoviceprogrammer.github.io/Ngspice_OpenVAF_Enhancements/)** — every enhancement grouped into 17 feature areas across the compiler and the simulator, searchable, with each entry linking to its write-up.

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
| 145 | ngspice **`optimize` tunes `.model`-card parameters** — a third knob kind `-mparam` varies model params named `@<model>[<param>]` (e.g. `@dmod[is]`), which are neither `alter`-reachable nor `.dc`-sweepable; applied in place with `altermod` (no re-source, like `-param`). All three kinds — `-param` (instance), `-mparam` (model), `-dparam` (`.param`) — mix in one run, so the optimizer now covers every circuit knob. In `com_optimize.c` only. Verified 39/39 (adds OSDI + built-in model-param fits, model+instance joint fit, in-place fast path) | ngspice | [doc](enhancements_doc/Enhancement-145.md) | [fit](examples/optimize_examples/) |
| 146 | ngspice **universal `sweep` command + `.sweep` card** — sweeps **any** knob, generalizing `.dc` (which only steps sources/resistors/instance params). Auto-detects the kind and applies it: device/instance/source via `alter`, `@model[param]` via `altermod`, `.param` via `alterparam`+`reset` — so model params and `.param`s, impossible with `.dc`, are now sweepable. `sweep <knob> (<start> <stop> <step> \| lin\|dec\|oct N a b \| list …) [-analysis <cmd>] [-output name=expr …]` runs a chosen inner analysis (default `op`) at each point and records outputs into a plot (knob as scale); `.sweep` card does the same from the netlist (with a re-entrancy guard so a `.param` re-source can't recurse). New `com_sweep.c` + `inp.c` hook. Verified 11/11: `sweep R1` == built-in `.dc R1` exactly, model-param + `.param` sweeps vs analytic, AC/tran inner analyses, `.sweep` card == command form, spec forms | ngspice | [doc](enhancements_doc/Enhancement-146.md) | [sweep](examples/sweep_examples/) |
| 147 | openvaf-r **nested `?:` no longer compiles in exponential time** — a robustness campaign (117 production models + ~50 adversarial inputs + 4000 fuzz iterations) found the body validator fell through the ternary (`Select`) arm to a generic `walk_child_exprs`, re-validating both branches, so a chain of N nested `?:` was validated **2ⁿ** times — depth ~30 (easily reached via macros) hung the compiler. Fix: `return` from the `Select` arm like the `Call`/`Path` arms. **O(2ⁿ)→O(N)**: depth 160 went from hopeless to 0.11 s. One line in `hir_ty/validation/body.rs`; behaviour-preserving (all 117 models identical verdict, 0 flips; unit tests pass). Campaign also confirmed 0 panics/segfaults on 4000 fuzz iterations. Verified 7/7 | openvaf&#8209;r | [doc](enhancements_doc/Enhancement-147.md) | [nested](examples/nested_cond_examples/) |
| 148 | openvaf-r **compiler hardening: parser depth / include cap / array cap** — closes the three lower-severity robustness findings from E-147, turning pathological input from crashes/hangs into clean diagnostics. (1) A shared `expr_depth` counter bounds expression-tree depth at 1000, so deeply nested/chained expressions (`----…x`, `x+1+1+…`, `((…))`, `sin(sin(…))`) no longer overflow the recursive-descent parser (or a later tree traversal). (2) An `include_depth` cap (64) + new `IncludeRecursionLimit` stops a self-`` `include ``ing file from overflowing the stack (mirrors the E-65 macro-recursion guard). (3) An `array_elem_count` cap (~1M) + new `ArrayTooLarge` refuses to materialize an absurd array/bus/instance range (`real x[0:100000000]`) element-by-element — applied to variable/parameter/net-bus/function-return arrays (item-tree) and instance arrays (item-tree **and** elaboration). Behaviour-preserving: all 117 production models identical verdict (0 flips); parser/preprocessor/hir_def/hir_ty/sim_back tests pass. Verified 17/17 | openvaf&#8209;r | [doc](enhancements_doc/Enhancement-148.md) | [robustness](examples/robustness_examples/) |
| 149 | ngspice **Latin-Hypercube Monte Carlo sampling (`mcsample`)** — low-discrepancy statistical sampling, closing a ❌ gap vs commercial tools. Plain MC draws each random `.param` independently, so `N` runs clump and the estimate converges only as `1/√N`. `mcsample lhs <N> [seed <s>]` puts the netlist stochastic functions (`agauss`/`gauss`/`aunif`/`unif`/`limit`) into a **stratified** sampler: each random dimension's range is split into `N` equal strata hit exactly once (independent permutation per dimension; Gaussians stratified in probability space via an inverse-normal-CDF probit). The existing `reset`-driven idiom is unchanged — one `reset` = one stratified sample (advanced on the `NUPADECKCOPY` pass edge). `mcsample random`/`off` reverts. New sampler + `com_mcsample` in `randnumb.c`, draw hook in `xpressn.c`, boundary hook in `spicenum.c`. Front-end only, so solver-independent. Verified 5/5 under both solvers: stratification (each of 48 strata once vs random's gaps), multi-dimension, **~130× lower Var(mean)** at same `N`, reproducibility, analytic correctness | ngspice | [doc](enhancements_doc/Enhancement-149.md) | [lhs](examples/lhs_examples/) |
| 150 | ngspice **high-sigma rare-event estimation (`highsigma`)** — the second half of the statistical story (after E-149), reaching the **rare tail** plain MC can't: 4–6σ failure probabilities (SRAM/standard-cell yield) that would need 10⁷–10⁹ runs. `highsigma <N> [-scale <λ>] -metric <expr> [-max <hi>] [-min <lo>]` uses **scaled-sigma importance sampling** — inflates every Gaussian `.param` σ by λ so the failure region is sampled often, then reweights each sample by the likelihood ratio `p_nom/p_inflated` for an **unbiased** estimate. Direction-free (no gradient/MPFP search). Reports P(fail), relative error, and equivalent sigma-to-fail; leaves them in `highsigma_*` vectors. Reuses com_sweep.c's synchronous-run + expr-eval; new `MC_MODE_SSS` in `randnumb.c`. Front-end/solver-independent. Verified vs analytic Φ(−β): β=4 → σ 4.000, P 3.16e-5; **β=5 (P=2.87e-7) from 6000 runs** where plain MC sees ~0; two-sided spec, reproducibility, multi-parameter combining. Sparse-only (heavy deck) | ngspice | [doc](enhancements_doc/Enhancement-150.md) | [highsigma](examples/highsigma_examples/) |
| 151 | ngspice **process/mismatch correlations + packaged yield (`mccorr`/`mvnorm`, `montecarlo`)** — closes the last two ⚠️ statistical rows vs a commercial simulator. Plain MC draws every `agauss` independently, so matched devices couldn't be modelled. `mccorr <k> <matrix>` registers a `k×k` correlation matrix (Cholesky-factored); a new `.param` function **`mvnorm(i)`** returns the i-th component of one correlated standard-normal draw per sample (`y=L·z`), so process/mismatch correlation is expressed natively — and it composes with LHS (E-149) and importance sampling (E-150) automatically. **`montecarlo <N> [-lhs] (-spec <metric> [-max <hi>] [-min <lo>])…`** packages the yield flow: passes a sample only if all specs hold, reports yield + a **Wilson 95% CI** + per-spec violations (corners via existing `.lib`). New sampler in `randnumb.c`, `mvnorm` in `xpressn.c`, `com_montecarlo` in `com_sweep.c`. Front-end/solver-independent. Verified: corr 0.711/−0.614 vs target, non-PD rejected, single/multi-spec yield vs analytic, `-lhs` ~800× lower yield variance, correlation raises joint yield (0.75→0.82); demo: matched divider **~100% correlated vs ~74% independent** | ngspice | [doc](enhancements_doc/Enhancement-151.md) | [yield](examples/yield_examples/) |
| 152 | ngspice **KLU matrix reordering + scaling controls** — the KLU direct solver ran on hard-coded defaults (AMD ordering, max scaling, BTF on); now they're `.option`s: `klu_ordering=amd\|colamd`, `klu_scale=none\|sum\|max`, `klu_btf=on\|off` (friendly names → KLU's integer codes), plus a fixed `klu_memgrow_factor` (was a no-op — `(rValue==1.2)` set a boolean). Follows the existing option-plumbing chain (optdefs → cktsopt handlers → TSK/CKT/SMP structs → cktdojob/niinit → `klusmp.c` sets `Common->ordering/scale/btf` after `klu_defaults`; defaults match, so unchanged unless set). KLU-only, changes only *how* the matrix factors, never the solution. Verified on a resistor grid: all settings **physically identical** (rel spread 2.8e-14); AMD≠COLAMD and scale=max≠none in the **last digits** (deterministic proof the knobs reach KLU); invalid values warn; default == amd/max/btf-on bit-for-bit; badly-scaled net correct under all scalings | ngspice | [doc](enhancements_doc/Enhancement-152.md) | [klu](examples/klu_tuning_examples/) |
| 153 | ngspice **Levenberg-Marquardt trust-region Newton (`.option trustregion`)** — completes the damped/trust-region-Newton row alongside the E-111 line search. Where the line search only *shortens* the Newton direction, this damps the **Jacobian** (`x_{k+1}=x_k−(J+μI)⁻¹F`, μ=λ·‖diag(J)‖ added at factor time + μ·x_k RHS coupling, Marquardt-scaled so λ is dimensionless), re-aiming the step toward steepest-descent to regularize an ill-conditioned Jacobian. A rejected (residual-increasing) step retries with grown λ; λ relaxes to 0 on success, and a convergence guard forbids converging while λ>0 — so it's **result-neutral** (verified **bit-identical** to plain Newton on diode/BJT/divider, both solvers). New `SMPdiagNorm` (both solvers); plumbing mirrors `linesearch`. **Honest finding**: measured **zero step-rejections** on every circuit — ngspice globalizes at the *device* level (junction limiting) *before* the residual, so a solver-level trust-region stays inert on typical circuits; the option is a solver-level regularization for the cases limiting+homotopy miss | ngspice | [doc](enhancements_doc/Enhancement-153.md) | [trustregion](examples/trustregion_examples/) |
| 154 | ngspice **Envelope Following (`envelope` command)** — the last remaining ❌ in the RF/periodic-steady-state suite. For a carrier-driven circuit whose amplitude/phase modulates slowly over many carrier periods (a ringing resonator, a settling PLL, a modulated PA), it samples the state once per carrier period `T=1/fc` and integrates the slow drift, jumping M periods at a time. The jump is **implicit** — `X_{n+M}=X_n+M(φ(X_{n+M})−X_{n+M})`, Newton `[(1+M)I−M·Φ]ΔY=−G` with `Φ=dφ/dY` the one-period **monodromy** (finite-differenced) — which is A-stable, so it tracks a resonator's envelope where the naive **explicit** jump blows up (the reason an earlier forward-Euler attempt was shelved). `M` is chosen by step-doubling LTE control; the one-period map is self-started trapezoidal (BE damps high Q). New `EFanalysis` engine + `envelope` command; emits an `envelope` plot (`<node>_amp/_dc/_re/_im` vs time). Verified vs full `.tran`: <3% across a Q~3160 ring-up, ~1.6% on Q~316, bounded over 3000 periods, both solvers — 26 samples reproduce ~3000 carrier periods (several× faster than the transient when the envelope is much slower than the carrier). Completes the RF suite | ngspice | [doc](enhancements_doc/Enhancement-154.md) | [envelope](examples/envelope_examples/) |

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
