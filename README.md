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

One hundred and thirty-nine enhancements so far — language features, correctness fixes, systematic audits, and simulator-side workflow tooling, each verified end-to-end by a committed example suite and released with a detailed write-up.

**📖 Start with the [User Handbook](docs/handbook/README.md)**, which organizes everything by topic: [getting started](docs/handbook/01-getting-started.md), the [Verilog-A feature matrix](docs/handbook/02-verilog-a-language.md), [ngspice workflows](docs/handbook/03-ngspice-workflows.md), and the [limitations & gotchas](docs/handbook/04-limitations-and-gotchas.md). The whole handbook plus the complete text of every enhancement write-up is also one linked PDF: [docs/Ngspice-OpenVAF-Handbook.pdf](docs/Ngspice-OpenVAF-Handbook.pdf).

**🔧 Want to understand the compiler itself?** [OpenVAF Compiler Internals](docs/internals/openvaf_internals/OpenVAF_compiler_internals.md) ([PDF](docs/internals/openvaf_internals/OpenVAF_compiler_internals.pdf)) is a ground-up, no-prior-knowledge walkthrough of how `openvaf-r` turns a Verilog-A model into a `.osdi` library — every stage of the pipeline (lexing → HIR → MIR → automatic differentiation → LLVM → OSDI), with real dumped IR traced end-to-end on a worked example.

**⚙️ Want to understand the simulator itself?** [ngspice Simulator Internals](docs/internals/ngspice_internals/ngspice_simulator_internals.md) ([PDF](docs/internals/ngspice_internals/ngspice_simulator_internals.pdf)) is the companion guide — a ground-up walkthrough of how `ngspice-46` turns a netlist into a running circuit: the shell/engine split, the netlist parser, the `CKTcircuit`, the `SPICEdev` device interface, the sparse-matrix Newton loop, the analyses, and — crucially — how OpenVAF `.osdi` models plug in as first-class devices, traced end-to-end on a worked RC example.

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
| 84 | LRM example sweep — all 231 code examples of the Verilog-AMS LRM 2023 compiled + 6 defect fixes (port-branch/garbage-input panics, silent undefined modules, $port_connected on open ports, dead-op codegen aborts, exit-0-on-error) | openvaf&#8209;r | [doc](enhancements_doc/Enhancement-84.md) | [lrm](examples/lrm_examples/) |
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
| 113 | ngspice KLU support for **noise** and single-ended **pole-zero** — the KLU adjoint solve (`SMPcaSolve`) did a non-transposed solve, silently wrong on asymmetric circuits; now `klu_z_tsolve`, so KLU noise matches Sparse exactly (balanced-output pz stays Sparse-only) | ngspice | [doc](enhancements_doc/Enhancement-113.md) | [analyses](examples/analyses_examples/), [noisejw](examples/noisejw_examples/) |
| 114 | ngspice KLU support for **sensitivity** (`.sens`, DC & AC) — the auxiliary perturbation matrix `delta_Y` is Sparse, but two KLU setup blocks gated on the *main* matrix's flag dereferenced its NULL `SMPkluMatrix` (segfault on every `.sens`); now gated on `delta_Y`'s own flag, matching Sparse exactly | ngspice | [doc](enhancements_doc/Enhancement-114.md) | [analyses](examples/analyses_examples/) |
| 115 | ngspice KLU support for **distortion** (`.disto`) — the complex distortion solve ran against a KLU matrix left in real mode (`distoan.c` had no KLU code), so every harmonic came back zero; now converts the matrix real↔complex around the solve loop like `acan.c`, matching Sparse bit-for-bit. Balanced-output pole-zero is now the only Sparse-only analysis under KLU | ngspice | [doc](enhancements_doc/Enhancement-115.md) | [analyses](examples/analyses_examples/) |
| 116 | ngspice KLU **wrong-DC fix** for decoupled OSDI nodes — an OSDI internal node in no Jacobian entry (a `ground` reference whose `V(p,gnd)<+…` drops its column) got an all-zero solver row that made the KLU matrix structurally singular; now tied to ground at setup. Fixes 2 of 3 numerical `KLU_XFAIL`s (`groundcontrib`, `hierbranch`); only the `opamp741` stiff transient remains | ngspice | [doc](enhancements_doc/Enhancement-116.md) | [groundcontrib](examples/groundcontrib_examples/), [hierbranch](examples/hierbranch_examples/) |
| 117 | ngspice **periodic steady state (PSS) productionized** — `.pss` was experimental (`--enable-pss`, unimplemented in shipped builds) and printed ~230 trace lines/run; now built by default with the shooting-loop trace gated behind `set ngdebug` (232 → 31 lines), verified against the analytic AC response. Foundation for the RF periodic small-signal suite (PAC/pnoise/PXF) | ngspice | [doc](enhancements_doc/Enhancement-117.md) | [rfpss](examples/rfpss_examples/) |
| 118 | ngspice **PSS runs under KLU** — `.pss` hung under KLU because `klu_refactor`'s reused pivots inflated the truncation error into a ~20M-step timestep explosion; forcing a full re-factor (`NISHOULDREORDER`) each PSS step makes KLU converge to the same result as Sparse. E-117's Sparse-only guard removed — PSS now runs under both linear solvers | ngspice | [doc](enhancements_doc/Enhancement-118.md) | [rfpss](examples/rfpss_examples/) |
| 119 | ngspice **retain the PSS periodic operating point** — PSS sampled the node voltages per period for its DFT then freed them, and never captured device states; now voltages **and** states are captured per sample and retained on the job (with frequency + dims) as the substrate the periodic small-signal suite (PAC/pnoise/PXF) linearizes around. First step toward PAC | ngspice | [doc](enhancements_doc/Enhancement-119.md) | [rfpss](examples/rfpss_examples/) |
| 120 | ngspice **periodic small-signal Jacobian harmonics** — walk the retained op-point; at each sample re-linearize and stamp `G+jC`, read the osc-node diagonal → `g(t)`, `c(t)`, DFT to harmonics — the blocks the PAC conversion matrix is assembled from. RC verifies `G=1/R1`, `C=C1` exactly with harmonics≈0 (time-invariant). Second step toward PAC | ngspice | [doc](enhancements_doc/Enhancement-120.md) | [rfpss](examples/rfpss_examples/) |
| 121 | ngspice **PAC conversion-matrix engine** — extend E-120 to every matrix nonzero, complex-DFT to harmonics `G_k`,`C_k`, assemble the `(2M+1)N` harmonic conversion matrix `H_{nm}=G_{n−m}+jω_m·C_{n−m}` and solve it (dense complex LU) with a unit current at the osc node in sideband 0, reporting the sideband conversion gains — the numerical heart of PAC/pnoise/PXF. RC verifies sideband-0 = AC driving-point `\|Z\|(f0/2)` = 303.3 Ω with the ±1 sidebands at floating-point zero (no conversion). Third step toward PAC | ngspice | [doc](enhancements_doc/Enhancement-121.md) | [rfpss](examples/rfpss_examples/) |
| 122 | ngspice **`.pac` command** — the user-facing periodic-AC analysis on the E-121 engine. `.pac <pss params> <dec\|oct\|lin> Npts Fstart Fstop` runs PSS then sweeps a small-signal input frequency, solving the conversion matrix at each point and emitting the sideband-0 node responses as a complex `PAC Analysis` plot (`print`/`plot`/`wrdata`). RC verifies the swept `\|b(f)\|` == analytic AC driving-point `\|Z(f)\|` to 1.6e−7 across 10 kHz–1 MHz. Fourth step toward PAC | ngspice | [doc](enhancements_doc/Enhancement-122.md) | [rfpss](examples/rfpss_examples/) |
| 123 | ngspice **finish `.pac`** — completes periodic AC with (1) a **source-referenced stimulus** (drive a netlist `AC`-flagged source → a true transfer/conversion gain instead of a driving-point impedance) and (2) **multi-sideband output** (optional trailing `maxsideband Ksb` emits every conversion sideband `f_in+k·f0` as a named vector `<node>_usb<k>`/`<node>_lsb<k>`). RC with `V1 AC 1` verifies sideband-0 = low-pass transfer `1/√(1+(2πfRC)²)` (0.998→0.157) with the ±1 conversion sidebands at floating-point zero (no mixing). PAC complete | ngspice | [doc](enhancements_doc/Enhancement-123.md) | [rfpss](examples/rfpss_examples/) |
| 124 | ngspice **`.pnoise` command** (periodic noise) — fold each device's noise through the conversion-matrix adjoint `Hᵀ Ψ = e_{out,0}`, loading the sideband-`k` transfer into `CKTrhs`/`CKTirhs` and calling the existing device noise routines (`NevalSrc`, OSDI `load_noise`) per sideband, accumulating `Σ_k S·\|ΔΨ_k\|²` — reuses every device noise model via a local `NOISEAN` context. `.pnoise <pss> OutNode InSrc <dec\|oct\|lin> Np Fstart Fstop`. RC verifies pnoise reduces exactly to `.noise` (`4kTR/(1+(2πfRC)²)`, matching `.noise` to every digit). Second RF small-signal analysis | ngspice | [doc](enhancements_doc/Enhancement-124.md) | [rfpss](examples/rfpss_examples/) |
| 125 | ngspice **`.pxf` command** (periodic transfer function) — the adjoint of PAC, completing the PSS→PAC→Pnoise→PXF suite. `pxf_sweep` solves `Hᵀ Ψ = e_{out,0}` per frequency and dots each sideband block with the AC-source pattern `B0` to get the input→output transfer `xf_k=Σ_j Ψ_k(j)·B0(j)`. `.pxf <pss> OutNode <dec\|oct\|lin> Np Fstart Fstop [maxsb]` → `xf` + `xf_usb<k>`/`xf_lsb<k>`. By `(H⁻¹B)_out=(H⁻ᵀe_out)ᵀB` the sideband-0 transfer is bit-identical to the PAC response (0.998→0.157 low-pass), conversion sidebands ~2e−16. **RF periodic small-signal suite complete** | ngspice | [doc](enhancements_doc/Enhancement-125.md) | [rfpss](examples/rfpss_examples/) |
| 126 | ngspice **cyclostationary noise** (`.pnoise … cyclo`) — evaluate each device's noise PSD `S(t)` at every PSS sample's bias and fold through the time-domain adjoint transfer, averaging over the period: `onoise=(1/P)Σ_s S(t_s)·\|ΔA_s\|²`. Captures pumped devices' bias-dependent noise (shot `2qI(t)`, flicker `∝\|I(t)\|²`) that the stationary first cut missed. Verified: reduces **exactly** to `.noise` on the linear RC (Parseval reduction); a flicker resistor carrying the RC current gives `onoise·f = R1²·KF·⟨I²⟩ = 4.88e−10` using the period-average `⟨I²⟩` (5-digit match) | ngspice | [doc](enhancements_doc/Enhancement-126.md) | [rfpss](examples/rfpss_examples/) |
| 127 | ngspice **pseudo-transient continuation** (`.option ptcont`) — a `Ẋ`-embedded DC homotopy: embed `f(x)=0` in `f(x)+Gps·(x−x_prev)=0` and march the pseudo-timestep small→large (`Gps→0`). The `Gps·x_prev` RHS coupling makes each step follow a stable trajectory (vs a static gmin step), so it converges — to the physically correct root — on stiff circuits where plain Newton overshoots. Off by default, result-neutral. Verified KLU+Sparse: stiff no-limiting exp reaches the correct DC `0.837922 V` vs plain Newton's spurious `70.5 V` | ngspice | [doc](enhancements_doc/Enhancement-127.md) | [ptcont](examples/ptcont_examples/) |
| 128 | ngspice **LTE-based dynamic integration-order control** (`.option dynorder`) — pick the Gear order per step from the local-truncation-error limit instead of the stock 1↔2 toggle, so orders 3–6 (coded in `NIcomCof`, never used) are actually exercised. Compares the **raw** LTE step at the current order and its `±1` neighbours; moves with hysteresis, a settling hold after each change, and an order-dependent growth cap, plus stiff-transient guards (post-breakpoint order hold + rejection-rate order drop). Off by default, bounded by `maxord`, inert at `maxord=2`. Verified KLU+Sparse: RC decay 3–5× fewer steps at matched accuracy; smooth RLC ringdown **8.9× fewer steps AND more accurate** (0.13 % vs 0.34 %); nonlinear rectifier matches stock to 5 sig figs; the transistor-level µA741 ±5 V slew matches fixed Gear-2 | ngspice | [doc](enhancements_doc/Enhancement-128.md) | [dynorder](examples/dynorder_examples/) |
| 129 | ngspice **sweep progress bar** — the throttled `Reference value` status line (redrawn in place every 0.25 s) gains a live progress bar + percentage during a sweep. Fraction per analysis (`outp_progress_frac`): transient `(CKTtime−TSTART)/(TSTOP−TSTART)`, AC/noise the frequency's log/linear position in the band, DC the accepted points over the nested step-count product; op/no-span analyses keep the plain line. Fixed-width, stdout status-line only (never in the rawfile/`wrdata`). Verified 22/22: printed % matches the analytic sweep fraction to 0.5 % across tran/AC/DC/noise | ngspice | [doc](enhancements_doc/Enhancement-129.md) | [progressbar](examples/progressbar_examples/) |
| 130 | ngspice **built-in optimizer** — `optimize -param <name> <init> <lo> <hi> [-param ...] -analysis <cmd> -minimize <expr> [-maxiter N] [-tol T] [-verbose]` is a derivative-free Nelder-Mead search that varies device/`alter` parameters, re-runs an analysis, and minimizes a scalar objective in normalized [0,1] space (scale-invariant across orders-of-magnitude params). Sub-commands run synchronously via `cp_coms` (not the deferring re-entrant `cp_evloop`); the hundreds of inner analyses are silenced by a new `ft_optimizing` flag (`-verbose` to show). Verified 9/9 vs analytic optima: DC divider R1→2333.3 Ω, AC low-pass R1→2756.6 Ω, 2-D compound objective R1=3k/R2=2k exactly | ngspice | [doc](enhancements_doc/Enhancement-130.md) | [optimize](examples/optimize_examples/) |
| 131 | ngspice **transient checkpoint / restart** — `savestate <file>` / `loadstate <file>` serialize the full transient integration state (solution vector, device state history `CKTstates[]`, time/step/order/mode, pending breakpoints) to disk and resume it, **including in a fresh process** (stock ngspice could only `resume` in memory) — so a long run survives a crash, splits across sessions, or moves between machines. `DCtran()` gains a `CKTcheckpoint`-gated branch that opens a **fresh** output plot (no live plot to `666`-relink across a reload), inits the XSPICE breakpoint markers, and fixes up the breakpoint list; rhs length keyed off `SMPmatSize+1`. A stored signature rejects a mismatched circuit; **Sparse-only** (KLU rejected clearly). Verified 19/19: resumed waveform **bit-identical** to an uninterrupted run for RC step/pulse/diode, ~2e−7 for a compiled OSDI diode, across a separate process | ngspice | [doc](enhancements_doc/Enhancement-131.md) | [checkpoint](examples/checkpoint_examples/) |
| 132 | ngspice **periodic S-parameters** (`.psp`) — small-signal scattering parameters around a PSS operating point, including conversion between the input frequency and its sidebands `f_in+k·f0` (mixers / switched circuits, where a static-DC `.sp` cannot see the conversion). Sits on the PSS→conversion-matrix suite (E-117–126): after PSS, `psp_sweep` excites each RF port (`portnum`/`z0`, the `.sp` framework) by driving its branch source (V=1, like `.sp`'s `VSRCspupdate`) through the shared `(2M+1)N` conversion matrix, reads per-sideband port waves in the same Kurosawa power-wave convention, and forms `S^(k)=B^(k)·A^-1` (dense-complex `cinverse`/`cmultiply`). `pac_solve_at`'s matrix assembly factored into a reusable `pac_build_matrix`; `dot_psp` card + `psp` PSS param. Because `S=B·A^-1` is excitation-basis-invariant, sideband 0 reduces **exactly** to `.sp` for a time-invariant network. Runs under **both** linear solvers (the conversion matrix is a standalone dense LU; PSS runs under both since E-118). Verified 8/8: sideband-0 matches `.sp` to ~1e−16 for 1/2/3-port resistive + reactive networks (magnitude and phase) incl. **OSDI Verilog-A** devices, conversion sidebands correctly ~0 | ngspice | [doc](enhancements_doc/Enhancement-132.md) | [psp](examples/psp_examples/) |
| 133 | ngspice **quasi-periodic (two-tone) steady state** (`qpss`) — `qpss <expr> <f1> <f2> [periods] [maxorder]` computes the two-tone steady-state spectrum: every mixing product `k1·f1+k2·f2` including third-order **intermodulation** (IM3 at 2f1-f2 / 2f2-f1) that single-tone AC/PSS cannot show. For **commensurate** tones (common beat `fb=gcd(f1,f2)`) it runs an ordinary transient over a few beat periods, then evaluates the Fourier coefficient **directly at each exact intermod frequency** (a direct DFT, exact — no FFT-bin rounding) and labels it by the 2-D index `(k1,k2)`. A front-end command driving a transient — **solver-independent**, works with built-in + OSDI devices. Verified 11/11: analytic cubic fundamentals/IM3/3f, no even-order products, the **3:1 IP3 slope law** (fund ×2, IM3 ×8 per 2× drive), beat-frequency derivation, OSDI = built-in | ngspice | [doc](enhancements_doc/Enhancement-133.md) | [qpss](examples/qpss_examples/) |
| 134 | ngspice **Harmonic Balance** (`hb <f0> <K> [points] [maxiter]`) — solves the periodic steady state in the **frequency domain** by Newton (each node voltage a truncated Fourier series), instead of integrating in time; the real analysis behind ngspice's unimplemented `WITH_HB` stub. Residual `F_k=I_R,k(V)+[dq/dt]_k-Is_k=0` with the E-121 `(2K+1)N` conversion matrix as the exact Jacobian. Per iteration it drives DC+AC device loads at the current iterate's voltages for the resistive current and G(t)/C(t), then a dense complex Newton step (`pss_csolve`). **Nonlinear reactive with NO charge extraction**: `dq/dt=C(v)*v'`, so the reactive current is the conversion matrix's jwC term on V — nonlinear charge Q(v) (varactors) falls out of the sampled C(t). **Solver-independent (KLU + Sparse):** HB does its own dense complex Newton, so the linear solver only reads G(t)/C(t) off the matrix (`hb_extract` carries the KLU complex-CSC binding, `hb` honours `.option klu`) — verified bit-identical. Built-in + OSDI. Verified 8/8 vs transient/`fourier` with quadratic convergence: nonlinear R (analytic 3rd harmonic), R+C, a real **diode rectifier** (junction limiting), an OSDI varactor whose Q(v) 2nd harmonic matches, and KLU==Sparse parity | ngspice | [doc](enhancements_doc/Enhancement-134.md) | [hb](examples/hb_examples/) |
| 135 | ngspice **HB source-stepping continuation** — makes E-134 Harmonic Balance robust on **strongly-driven** circuits (nonlinearity comparable to the linear term — a PA near compression, a sharp rectifier at large drive) where a cold full-strength Newton **diverges** (`|F|→1e69`). Every independent source is scaled by a homotopy factor `λ: 0→1`, solving a warm-started sequence of HB problems along the continuous steady-state path. **Adaptive with backtracking**: the first level is full strength (`dλ=1`), so an easy circuit converges at `λ=1` immediately — **bit-identical** to the plain solve; a level that fails halves `dλ` and retries from the last converged `V`, a level that converges grows `dλ` (×1.7); a collapse below `1e-5` is reported as no reachable steady state. Automatic, no new syntax; `set hb_verbose` shows the `λ` ramp, and the summary reports iterations + continuation steps. Verified 9/9: a strongly-driven diode rectifier that diverges cold converges in **3 continuation steps** and matches the transient `fourier` to <0.1% (DC/f0/2f0); the other 8 HB checks stay bit-identical | ngspice | [doc](enhancements_doc/Enhancement-135.md) | [hb](examples/hb_examples/) |
| 136 | ngspice **two-tone Harmonic Balance** (`qpss <expr> <f1> <f2> hb [K1] [K2]`) — the **true, incommensurate-capable** quasi-periodic steady state, a frequency-domain HB engine alongside the E-133 transient `qpss`. Each node is a 2-D Fourier series `v(t)=ΣΣ V_{k1,k2} e^{j(k1ω1+k2ω2)t}`; devices are sampled on a 2-D **phase** grid `(θ1,θ2)` (time never appears → **incommensurate** tones with no beat period just work) and 2-D DFT'd to the conversion matrix `H_{(n),(m)}=G_{n−m}+jω_m C_{n−m}`, Newton-solved by `pss_csolve` with E-135 source stepping. Sources captured by an **oversampled least-squares APFT** (`ΓᴴΓ Is=Γᴴb`; a square Vandermonde is unstable past a few harmonics). Nonlinear reactive needs NO charge extraction; retains the operating point for `qpac`. **Solver-independent (KLU + Sparse)**, built-in + OSDI. Verified 7/7: analytic cubic `|IM3|/|3rd|=3`, even products ~0, 3:1 IP3 slope, **incommensurate `√2` tones** (E-133 cannot), HB==transient, KLU==Sparse — and E-133's transient `qpss` stays 11/11 | ngspice | [doc](enhancements_doc/Enhancement-136.md) | [qpss](examples/qpss_examples/) |
| 137 | ngspice **two-tone QPAC** (`qpac <f_in>`) — the small-signal quasi-periodic AC that completes the QPSS/QPAC gap: run after `qpss … hb`, it injects a small signal at `f_in` around the retained two-tone operating point and reports the response at **every sideband** `f_in+k1·f1+k2·f2` (conversion a static `.ac` cannot see). Exactly `pac_solve_at` on the 2-D harmonic set — build `H_{(n),(m)}=G_{n−m}+jω_m C_{n−m}` at `f_in` (`qp_build_matrix`, the same matrix QPSS used as its Jacobian), place the stimulus (captured `AC`-source RHS `B0`, or unit current) in the `(0,0)` sideband, one dense `pss_csolve`. Adds no device evaluation → **solver-independent (KLU + Sparse)** by construction. Verified 7/7: **reduce-to-AC** (pump→0 ⇒ direct `(0,0)` = plain `.ac` = R, sidebands vanish), `v²`-pump conversion ratio `\|(1,1)\|/\|(2,0)\|=2`, tone symmetry, clean no-op-point error, KLU==Sparse; QPSS suites stay 7/7 + 11/11 | ngspice | [doc](enhancements_doc/Enhancement-137.md) | [qpac](examples/qpss_examples/) |
| 138 | ngspice **two-tone QPnoise** (`qpnoise <output_node> <f_in>`) — quasi-periodic noise, the two-tone analogue of pnoise, on the retained `qpss … hb` operating point. Reports output + input-referred noise density at `f_in`, **folding** every device's noise over all sidebands `f_in+k1·f1+k2·f2` (the mixer/PA noise conversion a static `.noise` can't see). One **adjoint** solve `Hᵀ Ψ = e_{out,(0,0)}` of the 2-D conversion matrix (`qp_solve_adjoint` transposes `qp_build_matrix`) gives the transimpedance from every (node, sideband) to the output; each device's `DEVnoise` computes `S·\|Ψ\|²` and the sum over Nh harmonics is the folded onoise. Reads only retained data → **solver-independent (KLU + Sparse)** by construction. Verified 6/6: **reduce-to-noise** (pump→0 ⇒ onoise == plain `.noise` == `4kTR`, exactly), conversion active under pump, `inoise=onoise/gain²`, clean no-op-point error, KLU==Sparse; QPSS/QPAC suites stay 11/11+7/7+7/7 | ngspice | [doc](enhancements_doc/Enhancement-138.md) | [qpnoise](examples/qpss_examples/) |
| 139 | ngspice **cyclostationary QPnoise** (`qpnoise <output_node> <f_in> cyclo`) — upgrades E-138 to a **time-varying** device PSD `S(t)`: under a two-tone pump a device's bias swings over the period (a diode's shot noise `2qI_D(t)` spikes when it conducts), so instead of the single-bias frequency-domain fold it uses the identity `onoise = (1/P)·Σ_s S(t_s)·\|A_s\|²`, where `A_s` is the **inverse 2-D DFT** of the adjoint transfers `Ψ` (the time-domain transimpedance at phase sample `s`). Each sample re-biases the devices at the retained op-point (`qp_synth`) with **per-sample junction settling** (the E-134 fix — else a limited diode reports a stale bias and the noise looks stationary). By Parseval reduces to the stationary sum (and `.noise`) when `S` is constant. Verified 10/10 (6 stationary + 4 cyclo): cyclo reduce-to-noise, **Parseval** (bias-indep thermal ⇒ cyclo==stationary even under pump), a hard-pumped **diode** where cyclo differs from stationary by ~8× (switching-mixer noise enhancement), cyclo KLU==Sparse; QPSS/QPAC stay 11/11+7/7+7/7 | ngspice | [doc](enhancements_doc/Enhancement-139.md) | [qpnoise](examples/qpss_examples/) |

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
