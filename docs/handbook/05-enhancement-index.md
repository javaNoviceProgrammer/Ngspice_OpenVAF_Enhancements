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
| 79 | Benchmark round 2 — BSIM4 ring-oscillator twin (1.1% freq match), `.ac`/`.noise` throughput, KLU-vs-SPARSE + solver-independence pin | [doc](../../enhancements_doc/Enhancement-79.md) | [benchmark](../../examples/benchmark_examples/) |
| 80 | Temperature physics — `$vt`≡kT/q, `dtemp` alias fix, noise ∝ T, MEXTRAM E_g = 1.25 eV, PSP103 ZTC flip | [doc](../../enhancements_doc/Enhancement-80.md) | [tempphys](../../examples/tempphys_examples/) |
| 81 | Session-lifecycle audit — reset loops leak-free, `destroy all` verified; once-per-excursion memory warning + `no_mem_check`, `pre_osdi` restart hint | [doc](../../enhancements_doc/Enhancement-81.md) | [lifecycle](../../examples/lifecycle_examples/) |
| 82 | Provenance + compliance docs — full change reports for both tools (`docs/change_log/`) and the Verilog-A LRM compliance document (`docs/compliance/`) | [doc](../../enhancements_doc/Enhancement-82.md) | — |
| 83 | Transistor-level µA741 demo — a Verilog-A BJT powering the textbook 20-transistor 741; datasheet figures emerge (104 dB, 0.75 MHz, 0.54 V/µs) | [doc](../../enhancements_doc/Enhancement-83.md) | [opamp741](../../examples/opamp741_examples/) |
| 84 | LRM example sweep — all 231 code examples of the Verilog-AMS LRM 2023 compiled + 6 defect fixes (port-branch/garbage-input panics, silent undefined modules, $port_connected on open ports, dead-op codegen aborts, exit-0-on-error) | [doc](../../enhancements_doc/Enhancement-84.md) | [lrm](../../examples/lrm_examples/) |
| 85 | `` `__FILE__``/`` `__LINE__`` predefined macros + part-selects in instance connections (`inst (out[3:2], in)`) — the last two LRM-sweep findings; all 8 sweep defects now fixed | [doc](../../enhancements_doc/Enhancement-85.md) | [filemacro](../../examples/filemacro_examples/), [partselect](../../examples/partselect_examples/) |
| 86 | Hierarchical branch probes — `V(top.a1.b)`, `V(inst.branch(a,b))`, `I(inst.branch(<p>))` via synthesized 0V ammeters; + 2 DAE fixes (V-source-to-internal-node open circuit, collapse-of-probed-branch) | [doc](../../enhancements_doc/Enhancement-86.md) | [hierbranch](../../examples/hierbranch_examples/) |
| 87 | Block-scoped parameters (`parameter`/`localparam` inside `begin: label`, read `label.name`) — feature validated end-to-end + clean diagnostic for the LRM's illegal `#(.blk.p(4))` override | [doc](../../enhancements_doc/Enhancement-87.md) | [blockparam](../../examples/blockparam_examples/) |
| 88 | Legacy `generate <id> (start, end)` statement (obsolete Verilog-A 1.0 analog-block loop-unroll, LRM Annex C.4) with constant bounds | [doc](../../enhancements_doc/Enhancement-88.md) | [legacygen](../../examples/legacygen_examples/) |
| 89 | Name-then-range net/port declarations (`input in[0:2]`, `electrical out[0:2]`) + an Annex E SPICE-primitives library (resistor/capacitor/inductor/sources/square-law MOS) | [doc](../../enhancements_doc/Enhancement-89.md) | [arrayport](../../examples/arrayport_examples/), [annexe](../../examples/annexe_examples/) |
| 90 | Multi-bit input bus port bit reads: fix scrambled terminal order when a vectored port (`input [0:2] in`) is not the last port in a non-ANSI header, so `V(in[k])` maps to the correct terminal | [doc](../../enhancements_doc/Enhancement-90.md) | [busport](../../examples/busport_examples/) |
| 91 | Multi-name name-then-range declarations (`input a[0:1], b[0:3], c;`) + parameter-dependent declaration widths (`electrical [0:N-1] out;`, `real w[0:N-1];`, folded from the parameter default) | [doc](../../enhancements_doc/Enhancement-91.md) | [paramwidth](../../examples/paramwidth_examples/) |
| 92 | Freeze structural (width) parameters to `localparam` so a netlist override cannot desync the frozen width from behavioural code (fixes a silent out-of-bounds in E-91) | [doc](../../enhancements_doc/Enhancement-92.md) | [paramfreeze](../../examples/paramfreeze_examples/) |
| 93 | Warn when a netlist sets a fixed (`localparam`) parameter: openvaf flags it non-settable (`PARA_FLAG_FIXED`), ngspice warns instead of silently ignoring the value | [doc](../../enhancements_doc/Enhancement-93.md) | [paramnonset](../../examples/paramnonset_examples/) |
| 94 | New ngspice `pyplot` command — plot simulated vectors with **matplotlib** (a Python counterpart to `gnuplot`); `pyplot_terminal=png` renders headless to a PNG | [doc](../../enhancements_doc/Enhancement-94.md) | [pyplot](../../examples/pyplot_examples/) |
| 95 | Make the `pyplot` output file name optional — `pyplot v(out)` (or bare node names) defaults the base name to `pyplot`; an explicit name still works | [doc](../../enhancements_doc/Enhancement-95.md) | [pyplot](../../examples/pyplot_examples/) |
| 96 | Parse a module-level `generate for`/`if`/`case` written **without** the optional `generate`/`endgenerate` keywords (was `unexpected token 'for'`, or silently dropped the loop) | [doc](../../enhancements_doc/Enhancement-96.md) | [baregenerate](../../examples/baregenerate_examples/) |
| 97 | Clean diagnostic instead of a compiler panic when a contribution's branch is entirely `ground` (`V(gnd) <+ ...`) | [doc](../../enhancements_doc/Enhancement-97.md) | [groundcontrib](../../examples/groundcontrib_examples/) |
| 98 | `pyplot` multi-panel subplots (`set pyplot_subplots=N`, N traces per stacked panel) + matplotlib style sheets (`set pyplot_style=dark`) | [doc](../../enhancements_doc/Enhancement-98.md) | [pyplotpanel](../../examples/pyplotpanel_examples/) |
| 99 | `pyplot` vector export formats (`set pyplot_terminal=svg`/`pdf`) + figure size (`set pyplot_figsize="W,H"`) | [doc](../../enhancements_doc/Enhancement-99.md) | [pyplotexport](../../examples/pyplotexport_examples/) |
| 100 | Milestone audit & retrospective — full-tree re-verification (90/90 suites + 28/28 integration), provenance/link audit, and a look back at the first hundred | [doc](../../enhancements_doc/Enhancement-100.md) | — |
| 101 | `$clog2` correctness — accept one argument (was a bad 2-arg signature) and return `ceil(log2 n)` (was off by one on exact powers of two) | [doc](../../enhancements_doc/Enhancement-101.md) | [clog2](../../examples/clog2_examples/) |
| 102 | Name-then-range array parameters — `parameter real c[0:2]` (dims after the name), completing the name-then-range line (vars/nets/ports already had it) | [doc](../../enhancements_doc/Enhancement-102.md) | [paramarray](../../examples/paramarray_examples/) |
| 103 | `ceil()` of a runtime argument no longer crashes the compiler (the `llvm.ceil.f64` intrinsic was unregistered; `floor` worked) | [doc](../../enhancements_doc/Enhancement-103.md) | [ceil](../../examples/ceil_examples/) |
| 104 | `$rtoi` / `$itor` real↔integer conversion functions (`$rtoi` truncates toward zero, distinct from the rounding implicit cast) | [doc](../../enhancements_doc/Enhancement-104.md) | [convert](../../examples/convert_examples/) |
| 105 | `$sscanf` / `$fscanf` honour the format base (`%h`/`%x` hex, `%o` octal, `%b` binary) instead of ignoring it | [doc](../../enhancements_doc/Enhancement-105.md) | [sscanf](../../examples/sscanf_examples/) |
| 106 | String relational comparison (`<`, `<=`, `>`, `>=`) via lexicographic `strcmp` (completes the string comparison surface; `==`/`!=` already worked) | [doc](../../enhancements_doc/Enhancement-106.md) | [stringcmp](../../examples/stringcmp_examples/) |
| 107 | `$fgetc(fd)` single-character file read (completes the file I/O family: `$fgets`/`$fscanf`/`$ftell`/… already existed) | [doc](../../enhancements_doc/Enhancement-107.md) | [fgetc](../../examples/fgetc_examples/) |
| 108 | `$ungetc(c, fd)` one-character pushback (the peek/look-ahead companion to `$fgetc`) | [doc](../../enhancements_doc/Enhancement-108.md) | [ungetc](../../examples/ungetc_examples/) |
| 109 | `noise_table`/`noise_table_log` interpolation corrected to the LRM (linear-in-`f` / log-log; both take Hz input) | [doc](../../enhancements_doc/Enhancement-109.md) | [noisetable](../../examples/noisetable_examples/) |
| 110 | ngspice `.option errpreset=conservative\|moderate\|liberal` — one knob for a coordinated tolerance/robustness set (Spectre-style); explicit options override regardless of order, `moderate` = historical defaults | [doc](../../enhancements_doc/Enhancement-110.md) | [errpreset](../../examples/errpreset_examples/) |
| 111 | ngspice `.option linesearch` — globalized (damped) Newton via Armijo backtracking on a new KCL-residual merit `‖F‖=‖G·x−b‖` (the merit ngspice lacked); result-neutral, off by default | [doc](../../enhancements_doc/Enhancement-111.md) | [linesearch](../../examples/linesearch_examples/) |
| 112 | ngspice KLU support for `.option linesearch` — `SMPmultiply`'s KLU path passed NULL ordering maps that `klu_matrix_vector_multiply` dereferenced (SIGSEGV); NULL now means identity ordering, so the line search runs under **both** KLU and Sparse 1.3 | [doc](../../enhancements_doc/Enhancement-112.md) | [linesearch](../../examples/linesearch_examples/) |
| 113 | ngspice KLU support for **noise** + single-ended **pole-zero** — `SMPcaSolve`'s adjoint KLU branch used a non-transposed solve (silently wrong noise on asymmetric matrices); now `klu_z_tsolve`, matching Sparse exactly. Balanced-output pz stays Sparse-only | [doc](../../enhancements_doc/Enhancement-113.md) | [analyses](../../examples/analyses_examples/) |
| 114 | ngspice KLU support for **sensitivity** (`.sens`, DC & AC) — the auxiliary perturbation matrix `delta_Y` is Sparse, but two KLU setup blocks gated on the *main* matrix's flag dereferenced its NULL `SMPkluMatrix` (segfault on every DC/AC `.sens`); now gated on `delta_Y`'s own flag, matching Sparse exactly | [doc](../../enhancements_doc/Enhancement-114.md) | [analyses](../../examples/analyses_examples/) |
| 115 | ngspice KLU support for **distortion** (`.disto`) — the complex distortion solve ran against a KLU matrix left in real mode (`distoan.c` had no KLU code), so every harmonic came back zero; now converts the matrix real↔complex around the solve loop like `acan.c`, matching Sparse bit-for-bit. Leaves balanced-output pole-zero as the only Sparse-only analysis under KLU | [doc](../../enhancements_doc/Enhancement-115.md) | [analyses](../../examples/analyses_examples/) |
