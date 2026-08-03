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
| 12 | `$simprobe` + alias/plusargs builtins | [doc](../../enhancements_doc/Enhancement-12.md) | [alias](../../examples/alias_examples/) |
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
| 73 | The user handbook, its PDF edition, and this README index | [doc](../../enhancements_doc/Enhancement-73.md) | [docs/handbook](docs/handbook/README.md) |
| 74 | OSDI-vs-built-in benchmark (twins at parity) | [doc](../../enhancements_doc/Enhancement-74.md) | [benchmark](../../examples/benchmark_examples/) |
| 75 | dynamic-physics cross-checks (Cgg AC≡tran) | [doc](../../enhancements_doc/Enhancement-75.md) | [dynphys](../../examples/dynphys_examples/) |
| 76 | multi-module `.osdi` libraries | [doc](../../enhancements_doc/Enhancement-76.md) | [multimod](../../examples/multimod_examples/) |
| 77 | ngspice build warnings → 0 (macOS/clang) | [doc](../../enhancements_doc/Enhancement-77.md) | — |
| 78 | `casex`/`casez` don't-care masks | [doc](../../enhancements_doc/Enhancement-78.md) | [casexz](../../examples/casexz_examples/) |
| 79 | 1M-element benchmark round 2 (BSIM4) | [doc](../../enhancements_doc/Enhancement-79.md) | [benchmark](../../examples/benchmark_examples/) |
| 80 | temperature physics (`dtemp` alias fix) | [doc](../../enhancements_doc/Enhancement-80.md) | [tempphys](../../examples/tempphys_examples/) |
| 81 | lifecycle: re-source/reset leak-free | [doc](../../enhancements_doc/Enhancement-81.md) | [lifecycle](../../examples/lifecycle_examples/) |
| 82 | provenance / compliance docs | [doc](../../enhancements_doc/Enhancement-82.md) | — |
| 83 | transistor-level `opamp741` demo | [doc](../../enhancements_doc/Enhancement-83.md) | [opamp741](../../examples/opamp741_examples/) |
| 84 | LRM-2023 example sweep (231 examples) | [doc](../../enhancements_doc/Enhancement-84.md) | [lrm](../../examples/lrm_examples/) |
| 85 | `__FILE__`/`__LINE__` directives | [doc](../../enhancements_doc/Enhancement-85.md) | [filemacro](../../examples/filemacro_examples/), [partselect](../../examples/partselect_examples/) |
| 86 | hierarchical branch probes | [doc](../../enhancements_doc/Enhancement-86.md) | [hierbranch](../../examples/hierbranch_examples/) |
| 87 | block-scoped parameters | [doc](../../enhancements_doc/Enhancement-87.md) | [blockparam](../../examples/blockparam_examples/) |
| 88 | legacy `generate` syntax | [doc](../../enhancements_doc/Enhancement-88.md) | [legacygen](../../examples/legacygen_examples/) |
| 89 | array ports + Annex E SPICE compat | [doc](../../enhancements_doc/Enhancement-89.md) | [arrayport](../../examples/arrayport_examples/), [annexe](../../examples/annexe_examples/) |
| 90 | multi-bit bus port ordering fix | [doc](../../enhancements_doc/Enhancement-90.md) | [busport](../../examples/busport_examples/) |
| 91 | param-dependent width + multi-name decls | [doc](../../enhancements_doc/Enhancement-91.md) | [paramwidth](../../examples/paramwidth_examples/) |
| 92 | parameter freeze | [doc](../../enhancements_doc/Enhancement-92.md) | [paramfreeze](../../examples/paramfreeze_examples/) |
| 93 | unset-parameter warning | [doc](../../enhancements_doc/Enhancement-93.md) | [paramnonset](../../examples/paramnonset_examples/) |
| 94 | `pyplot` (matplotlib backend) | [doc](../../enhancements_doc/Enhancement-94.md) | [pyplot](../../examples/pyplot_examples/) |
| 95 | `pyplot` default filename | [doc](../../enhancements_doc/Enhancement-95.md) | [pyplot](../../examples/pyplot_examples/) |
| 96 | bare `generate` blocks | [doc](../../enhancements_doc/Enhancement-96.md) | [baregenerate](../../examples/baregenerate_examples/) |
| 97 | contributing to all-`ground` branches | [doc](../../enhancements_doc/Enhancement-97.md) | [groundcontrib](../../examples/groundcontrib_examples/) |
| 98 | `pyplot` subplots | [doc](../../enhancements_doc/Enhancement-98.md) | [pyplotpanel](../../examples/pyplotpanel_examples/) |
| 99 | `pyplot` export formats (png/svg/pdf) | [doc](../../enhancements_doc/Enhancement-99.md) | [pyplotexport](../../examples/pyplotexport_examples/) |
| 100 | milestone audit | [doc](../../enhancements_doc/Enhancement-100.md) | — |
| 101 | `$clog2` | [doc](../../enhancements_doc/Enhancement-101.md) | [clog2](../../examples/clog2_examples/) |
| 102 | array parameters | [doc](../../enhancements_doc/Enhancement-102.md) | [paramarray](../../examples/paramarray_examples/) |
| 103 | `ceil()` non-const fix | [doc](../../enhancements_doc/Enhancement-103.md) | [ceil](../../examples/ceil_examples/) |
| 104 | `$rtoi`/`$itor` | [doc](../../enhancements_doc/Enhancement-104.md) | [convert](../../examples/convert_examples/) |
| 105 | `$sscanf` format bases | [doc](../../enhancements_doc/Enhancement-105.md) | [sscanf](../../examples/sscanf_examples/) |
| 106 | string relational operators | [doc](../../enhancements_doc/Enhancement-106.md) | [stringcmp](../../examples/stringcmp_examples/) |
| 107 | `$fgetc` | [doc](../../enhancements_doc/Enhancement-107.md) | [fgetc](../../examples/fgetc_examples/) |
| 108 | `$ungetc` one-char pushback | [doc](../../enhancements_doc/Enhancement-108.md) | [ungetc](../../examples/ungetc_examples/) |
| 109 | `noise_table` interpolation | [doc](../../enhancements_doc/Enhancement-109.md) | [noisetable](../../examples/noisetable_examples/) |
| 110 | `.option errpreset` (cons/mod/lib tolerance sets) | [doc](../../enhancements_doc/Enhancement-110.md) | [errpreset](../../examples/errpreset_examples/) |
| 111 | globalized-Newton line search | [doc](../../enhancements_doc/Enhancement-111.md) | [linesearch](../../examples/linesearch_examples/) |
| 112 | KLU line search | [doc](../../enhancements_doc/Enhancement-112.md) | [linesearch](../../examples/linesearch_examples/) |
| 113 | KLU noise + pole-zero | [doc](../../enhancements_doc/Enhancement-113.md) | [analyses](../../examples/analyses_examples/), [noisejw](../../examples/noisejw_examples/) |
| 114 | KLU sensitivity | [doc](../../enhancements_doc/Enhancement-114.md) | [analyses](../../examples/analyses_examples/) |
| 115 | KLU distortion | [doc](../../enhancements_doc/Enhancement-115.md) | [analyses](../../examples/analyses_examples/) |
| 116 | `KLU`: decoupled-OSDI noise & pole-zero | [doc](../../enhancements_doc/Enhancement-116.md) | [groundcontrib](../../examples/groundcontrib_examples/), [hierbranch](../../examples/hierbranch_examples/) |
| 117 | PSS (shooting) productionized | [doc](../../enhancements_doc/Enhancement-117.md) | [rfpss](../../examples/rfpss_examples/) |
| 118 | PSS under KLU | [doc](../../enhancements_doc/Enhancement-118.md) | [rfpss](../../examples/rfpss_examples/) |
| 119 | PAC: retain PSS op-point | [doc](../../enhancements_doc/Enhancement-119.md) | [rfpss](../../examples/rfpss_examples/) |
| 120 | PAC: Jacobian harmonics | [doc](../../enhancements_doc/Enhancement-120.md) | [rfpss](../../examples/rfpss_examples/) |
| 121 | PAC: conversion matrix | [doc](../../enhancements_doc/Enhancement-121.md) | [rfpss](../../examples/rfpss_examples/) |
| 122 | `.pac` command (periodic AC sweep) | [doc](../../enhancements_doc/Enhancement-122.md) | [rfpss](../../examples/rfpss_examples/) |
| 123 | `.pac` finish | [doc](../../enhancements_doc/Enhancement-123.md) | [rfpss](../../examples/rfpss_examples/) |
| 124 | `.pnoise` | [doc](../../enhancements_doc/Enhancement-124.md) | [rfpss](../../examples/rfpss_examples/) |
| 125 | `.pxf` | [doc](../../enhancements_doc/Enhancement-125.md) | [rfpss](../../examples/rfpss_examples/) |
| 126 | cyclostationary noise | [doc](../../enhancements_doc/Enhancement-126.md) | [rfpss](../../examples/rfpss_examples/) |
| 127 | `.option ptcont` DC homotopy | [doc](../../enhancements_doc/Enhancement-127.md) | [ptcont](../../examples/ptcont_examples/) |
| 128 | `.option dynorder` (LTE-based Gear order) | [doc](../../enhancements_doc/Enhancement-128.md) | [dynorder](../../examples/dynorder_examples/) |
| 129 | `sweep` progress bar | [doc](../../enhancements_doc/Enhancement-129.md) | [progressbar](../../examples/progressbar_examples/) |
| 130 | `optimize` (Nelder-Mead) | [doc](../../enhancements_doc/Enhancement-130.md) | [optimize](../../examples/optimize_examples/) |
| 131 | transient checkpoint/restart | [doc](../../enhancements_doc/Enhancement-131.md) | [checkpoint](../../examples/checkpoint_examples/) |
| 132 | `.psp` (PSS-based) | [doc](../../enhancements_doc/Enhancement-132.md) | [psp](../../examples/psp_examples/) |
| 133 | `qpss` two-tone (transient DFT) | [doc](../../enhancements_doc/Enhancement-133.md) | [qpss](../../examples/qpss_examples/) |
| 134 | Harmonic Balance (`hb`) | [doc](../../enhancements_doc/Enhancement-134.md) | [hb](../../examples/hb_examples/) |
| 135 | HB source-stepping continuation | [doc](../../enhancements_doc/Enhancement-135.md) | [hb](../../examples/hb_examples/) |
| 136 | two-tone QPSS via HB | [doc](../../enhancements_doc/Enhancement-136.md) | [qpss](../../examples/qpss_examples/) |
| 137 | `qpac` two-tone small-signal | [doc](../../enhancements_doc/Enhancement-137.md) | [qpac](../../examples/qpss_examples/) |
| 138 | `qpnoise` | [doc](../../enhancements_doc/Enhancement-138.md) | [qpnoise](../../examples/qpss_examples/) |
| 139 | cyclostationary `qpnoise` | [doc](../../enhancements_doc/Enhancement-139.md) | [qpnoise](../../examples/qpss_examples/) |
| 140 | oscillator phase noise | [doc](../../enhancements_doc/Enhancement-140.md) | [phasenoise](../../examples/phasenoise_examples/) |
| 141 | `qpxf` | [doc](../../enhancements_doc/Enhancement-141.md) | [qpxf](../../examples/qpss_examples/) |
| 142 | QP small-signal freq sweep (`qpac`/`qpnoise`/`qpxf`) | [doc](../../enhancements_doc/Enhancement-142.md) | [sweep](../../examples/qpss_examples/) |
| 143 | least-squares `optimize` (Levenberg-Marquardt) | [doc](../../enhancements_doc/Enhancement-143.md) | [fit](../../examples/optimize_examples/) |
| 144 | `optimize -dparam` (`.param` knobs) | [doc](../../enhancements_doc/Enhancement-144.md) | [fit](../../examples/optimize_examples/) |
| 145 | `optimize -mparam` (`.model` knobs) | [doc](../../enhancements_doc/Enhancement-145.md) | [fit](../../examples/optimize_examples/) |
| 146 | universal `sweep` command + `.sweep` card | [doc](../../enhancements_doc/Enhancement-146.md) | [sweep](../../examples/sweep_examples/) |
| 147 | nested `?:` compile time O(2^N)→O(N) | [doc](../../enhancements_doc/Enhancement-147.md) | [nested](../../examples/nested_cond_examples/) |
| 148 | compiler hardening (parser depth/include) | [doc](../../enhancements_doc/Enhancement-148.md) | [robustness](../../examples/robustness_examples/) |
| 149 | Latin-Hypercube sampling | [doc](../../enhancements_doc/Enhancement-149.md) | [lhs](../../examples/lhs_examples/) |
| 150 | high-sigma analysis | [doc](../../enhancements_doc/Enhancement-150.md) | [highsigma](../../examples/highsigma_examples/) |
| 151 | correlations + yield (Cholesky) | [doc](../../enhancements_doc/Enhancement-151.md) | [yield](../../examples/yield_examples/) |
| 152 | KLU tuning (ordering/scale/BTF) | [doc](../../enhancements_doc/Enhancement-152.md) | [klu](../../examples/klu_tuning_examples/) |
| 153 | trust-region optimizer | [doc](../../enhancements_doc/Enhancement-153.md) | [trustregion](../../examples/trustregion_examples/) |
| 154 | envelope following | [doc](../../enhancements_doc/Enhancement-154.md) | [envelope](../../examples/envelope_examples/) |
| 155 | RC reduction (`reduce`/TICER) | [doc](../../enhancements_doc/Enhancement-155.md) | [reduce](../../examples/reduce_examples/) |
| 156 | sparse RC reduction (scales to millions) | [doc](../../enhancements_doc/Enhancement-156.md) | [reduce](../../examples/reduce_examples/) |
| 157 | device aging (`aging`; static + dynamic) | [doc](../../enhancements_doc/Enhancement-157.md) | [aging](../../examples/aging_examples/) |
| 158 | power-grid EMIR (IR-drop + EM) | [doc](../../enhancements_doc/Enhancement-158.md) | [emir](../../examples/emir_examples/) |
| 159 | real compact models (BSIM4/EKV) | [doc](../../enhancements_doc/Enhancement-159.md) | [compactmodels](../../examples/compactmodels_examples/) |
| 160 | CMC coverage sweep (19 models) | [doc](../../enhancements_doc/Enhancement-160.md) | [cmcsweep](../../examples/cmcsweep_examples/) |
| 161 | dynamic C-V / fT vs built-in | [doc](../../enhancements_doc/Enhancement-161.md) | [dynmodels](../../examples/dynmodels_examples/) |
| 162 | `.hb` dot-card | [doc](../../enhancements_doc/Enhancement-162.md) | [hb](../../examples/hb_examples/) |
| 163 | `.qpss`/`.hbosc`/`.phasenoise` dot-cards | [doc](../../enhancements_doc/Enhancement-163.md) | [qpss](../../examples/qpss_examples/) · [phasenoise](../../examples/phasenoise_examples/) |
| 164 | large-signal RF (P1dB/IP3) | [doc](../../enhancements_doc/Enhancement-164.md) | [rfpa](../../examples/rfpa_examples/) |
| 165 | model noise (flicker/thermal/shot) | [doc](../../enhancements_doc/Enhancement-165.md) | [modelnoise](../../examples/modelnoise_examples/) |
| 166 | electro-thermal self-heating | [doc](../../enhancements_doc/Enhancement-166.md) | [electrothermal](../../examples/electrothermal_examples/) |
| 167 | cross-model self-heating (4 classes) | [doc](../../enhancements_doc/Enhancement-167.md) | [cmcselfheat](../../examples/cmcselfheat_examples/) |
| 168 | LNA noise figure (Friis / noise match) | [doc](../../enhancements_doc/Enhancement-168.md) | [noisefigure](../../examples/noisefigure_examples/) |
| 169 | interactive syntax highlighting | [doc](../../enhancements_doc/Enhancement-169.md) | [syntaxhl](../../examples/syntaxhl_examples/) |
| 170 | semantic highlighting (signals/exprs) | [doc](../../enhancements_doc/Enhancement-170.md) | [syntaxhl](../../examples/syntaxhl_examples/) |
| 171 | KLU pole-zero (complex determinant) | [doc](../../enhancements_doc/Enhancement-171.md) | [klupz](../../examples/klupz_examples/) |
| 172 | KLU balanced PZ + full pivoting | [doc](../../enhancements_doc/Enhancement-172.md) | [klupz](../../examples/klupz_examples/) |
| 173 | eigenvalue pole-zero (`pzeig`) | [doc](../../enhancements_doc/Enhancement-173.md) | [pzeig](../../examples/pzeig_examples/) |
| 174 | `help` command crash fix | [doc](../../enhancements_doc/Enhancement-174.md) | [helpcmd](../../examples/helpcmd_examples/) |
| 175 | conversion-matrix parametric-term fix | [doc](../../enhancements_doc/Enhancement-175.md) | [rfconv](../../examples/rfconv_examples/) |
| 176 | driven-mode PSS (~1000x) | [doc](../../enhancements_doc/Enhancement-176.md) | [pssdriven](../../examples/pssdriven_examples/) |
| 177 | pnoise folding referee + flicker fix | [doc](../../enhancements_doc/Enhancement-177.md) | [pnoisefold](../../examples/pnoisefold_examples/) |
| 178 | exact cyclostationary folding + HB DC fix | [doc](../../enhancements_doc/Enhancement-178.md) | [cyclofold](../../examples/cyclofold_examples/) |
| 179 | `.tf`/`.sens`/`.meas` audit + referees | [doc](../../enhancements_doc/Enhancement-179.md) | [stdaudit](../../examples/stdaudit_examples/) |
| 180 | checkpoint under KLU (cross-solver) | [doc](../../enhancements_doc/Enhancement-180.md) | [checkpoint](../../examples/checkpoint_examples/) |
| 181 | integrator certified + `ordfix` | [doc](../../enhancements_doc/Enhancement-181.md) | [corenum](../../examples/corenum_examples/) |
| 182 | `pyplot` autoscale by default | [doc](../../enhancements_doc/Enhancement-182.md) | [pyplot](../../examples/pyplot_examples/) |
| 183 | `pyplot`: distinct names, deck output, linewidth, backend | [doc](../../enhancements_doc/Enhancement-183.md) | [pyplot](../../examples/pyplot_examples/) |
| 184 | progress bar reaches 100% | [doc](../../enhancements_doc/Enhancement-184.md) | [progressbar](../../examples/progressbar_examples/) |
| 185 | autodiff `hypot`/`atan2` derivative fixes | [doc](../../enhancements_doc/Enhancement-185.md) | [vafautodiff](../../examples/vafautodiff_examples/) |
| 186 | autodiff real-modulo derivative fix | [doc](../../enhancements_doc/Enhancement-186.md) | [vafautodiff](../../examples/vafautodiff_examples/) |
| 187 | simplifier inverse-function cancellation fixes | [doc](../../enhancements_doc/Enhancement-187.md) | [mathident](../../examples/mathident_examples/) |
| 188 | warm-start Monte Carlo | [doc](../../enhancements_doc/Enhancement-188.md) | [warmstart](../../examples/warmstart_examples/) |
| 189 | `sweep -overlay` waveform families | [doc](../../enhancements_doc/Enhancement-189.md) | [sweepwave](../../examples/sweepwave_examples/) |
| 190 | `sweep -vs` nested multi-knob sweeps | [doc](../../enhancements_doc/Enhancement-190.md) | [nestedsweep](../../examples/nestedsweep_examples/) |
| 191 | `.ac`/`.sp lin 2` off-by-one fix | [doc](../../enhancements_doc/Enhancement-191.md) | [aclin2](../../examples/aclin2_examples/) |
| 192 | auto-checkpoint on interrupt (`Ctrl-C`) | [doc](../../enhancements_doc/Enhancement-192.md) | [autosave](../../examples/autosave_examples/) |
| 193 | `.pnoise` honors `sqrnoise` (V/√Hz) | [doc](../../enhancements_doc/Enhancement-193.md) | [pnoiseunits](../../examples/pnoiseunits_examples/) |
| 194 | `optimize -method pso` (global) | [doc](../../enhancements_doc/Enhancement-194.md) | [psoopt](../../examples/psoopt_examples/) |
| 195 | `optimize -method de` (global) | [doc](../../enhancements_doc/Enhancement-195.md) | [deopt](../../examples/deopt_examples/) |
| 196 | `optimize -method sa` (global) | [doc](../../enhancements_doc/Enhancement-196.md) | [saopt](../../examples/saopt_examples/) |
| 197 | 100-parameter curve-fit (raised caps) | [doc](../../enhancements_doc/Enhancement-197.md) | [opt100](../../examples/opt100_examples/) |
| 198 | `stb` loop-gain + phase/gain margin | [doc](../../enhancements_doc/Enhancement-198.md) | [stb](../../examples/stb_examples/) |
| 199 | N-port Touchstone device (S-param, AC+tran) | [doc](../../enhancements_doc/Enhancement-199.md) | [nport](../../examples/nport_examples/) |
| 200 | `pre_snp`: built-in Touchstone→OSDI command | [doc](../../enhancements_doc/Enhancement-200.md) | [presnp](../../examples/presnp_examples/) |
| 201 | `pre_snp` scalability: fast vector fit (N→100) | [doc](../../enhancements_doc/Enhancement-201.md) | [presnp](../../examples/presnp_examples/) |
| 202 | `.sp` S-param inverse O(N!)→O(N³) | [doc](../../enhancements_doc/Enhancement-202.md) | [spscale](../../examples/spscale_examples/) |
| 203 | `.meas ac` gain/phase margin + batch `vdb` fix | [doc](../../enhancements_doc/Enhancement-203.md) | [acmargin](../../examples/acmargin_examples/) |
| 204 | `.option convhelp` convergence ladder | [doc](../../enhancements_doc/Enhancement-204.md) | [convhelp](../../examples/convhelp_examples/) |
| 205 | `pre_snp` low-rank residue factorization | [doc](../../enhancements_doc/Enhancement-205.md) | [lowrank](../../examples/lowrank_examples/) |
| 206 | `optimize -center` design centering (yield/Cpk) | [doc](../../enhancements_doc/Enhancement-206.md) | [dcenter](../../examples/dcenter_examples/) |
| 207 | `eye` diagram / jitter (SerDes) | [doc](../../enhancements_doc/Enhancement-207.md) | [eye](../../examples/eye_examples/) |
| 208 | `pyplot -eye` eye diagrams | [doc](../../enhancements_doc/Enhancement-208.md) | [pyplot](../../examples/pyplot_examples/) |
| 209 | `hb` publishes spectrum as nutmeg vectors | [doc](../../enhancements_doc/Enhancement-209.md) | [hb](../../examples/hb_examples/) |
| 210 | `.pss` dot-card + complex node vectors | [doc](../../enhancements_doc/Enhancement-210.md) | [rfpss](../../examples/rfpss_examples/) |
| 211 | static-analysis DC-op/import bug fixes | [doc](../../enhancements_doc/Enhancement-211.md) | [codeanalysis](../../examples/codeanalysis_examples/) |
| 212 | crash hardening: 7 input-handling crashes | [doc](../../enhancements_doc/Enhancement-212.md) | [crashfix](../../examples/crashfix_examples/) |
| 213 | openvaf crash hardening: 4 compiler panics | [doc](../../enhancements_doc/Enhancement-213.md) | [vafcrash](../../examples/vafcrash_examples/) |
| 214 | openvaf whole-array coercion crash class (root fix) | [doc](../../enhancements_doc/Enhancement-214.md) | [arraycast](../../examples/arraycast_examples/) |
| 215 | `$test`/`$value$plusargs` | [doc](../../enhancements_doc/Enhancement-215.md) | [plusargs](../../examples/plusargs_examples/) |
| 216 | `optimize -method nsga2` Pareto front | [doc](../../enhancements_doc/Enhancement-216.md) | [pareto](../../examples/pareto_examples/) |
| 217 | `pyplot -hist` histograms | [doc](../../enhancements_doc/Enhancement-217.md) | [pyplothist](../../examples/pyplothist_examples/) |
| 218 | `pyplot -contour` 2-D maps | [doc](../../enhancements_doc/Enhancement-218.md) | [pyplotcontour](../../examples/pyplotcontour_examples/) |
| 219 | openvaf preprocessor macro-arg hang + diag cap | [doc](../../enhancements_doc/Enhancement-219.md) | [robustness](../../examples/robustness_examples/) |
| 220 | openvaf crash hardening r2 (10 panics) | [doc](../../enhancements_doc/Enhancement-220.md) | [vafcrash2](../../examples/vafcrash2_examples/) |
| 221 | array/bus node ranges (`a[0:1]`) | [doc](../../enhancements_doc/Enhancement-221.md) | [busnodes](../../examples/busnodes_examples/) |
| 222 | parser fuzz hardening (7 crashes/hangs) | [doc](../../enhancements_doc/Enhancement-222.md) | [parserfuzz](../../examples/parserfuzz_examples/) |
| 223 | XSPICE a-device model-type check (`MIFgetMod`) | [doc](../../enhancements_doc/Enhancement-223.md) | [xspicemodel](../../examples/xspicemodel_examples/) |
| 224 | array-node voltages in `print`/`plot` (`v(a[0])`) | [doc](../../enhancements_doc/Enhancement-224.md) | [arraynodeprint](../../examples/arraynodeprint_examples/) |
| 225 | harden `fft`/`deriv`/`fourier`/`meas`/`?:` evaluator against fuzz crashes | [doc](../../enhancements_doc/Enhancement-225.md) | [cmdfuzz](../../examples/cmdfuzz_examples/) |
| 226 | rawfile `load` crash hardening (fuzz: missing `Flags:` line → NULL deref) | [doc](../../enhancements_doc/Enhancement-226.md) | [rawfuzz](../../examples/rawfuzz_examples/) |
| 227 | Touchstone `pre_snp` crash hardening (fuzz: huge `.sNp` port count → heap corruption) | [doc](../../enhancements_doc/Enhancement-227.md) | [snpfuzz](../../examples/snpfuzz_examples/) |
| 228 | OSDI `.osdi` loader crash hardening (fuzz: reject implausible descriptor counts) | [doc](../../enhancements_doc/Enhancement-228.md) | [osdifuzz](../../examples/osdifuzz_examples/) |
| 229 | `pre_osdi -f` reloads a recompiled `.osdi` model in-session (no restart) | [doc](../../enhancements_doc/Enhancement-229.md) | [osdireload](../../examples/osdireload_examples/) |
| 230 | openvaf-r crash hardening round 3 (fuzz: 3 panics → clean errors) | [doc](../../enhancements_doc/Enhancement-230.md) | [vafcrash3](../../examples/vafcrash3_examples/) |
| 231 | wrdata CSV output: set wr_csv + wrdata -csv flag (any position) | [doc](../../enhancements_doc/Enhancement-231.md) | [csv](../../examples/csv_examples/) |
| 232 | harden KLU solver-glue (null-checks, collapse-map, bounds) | [doc](../../enhancements_doc/Enhancement-232.md) | [solverfix](../../examples/solverfix_examples/) |
| 233 | fix KLU glue null-check order and collapse-map gaps | [doc](../../enhancements_doc/Enhancement-233.md) | [solverfix](../../examples/solverfix_examples/) |
| 234 | `loadpull` PA load/source-pull contours on Smith chart | [doc](../../enhancements_doc/Enhancement-234.md) | [loadpull](../../examples/loadpull_examples/) |
| 235 | fix `stb` probe-lookup use-after-free; case-insensitive probes | [doc](../../enhancements_doc/Enhancement-235.md) | [stbfix](../../examples/stbfix_examples/) |
| 236 | fix `.meas` stack overflow on long measurement names | [doc](../../enhancements_doc/Enhancement-236.md) | [measovf](../../examples/measovf_examples/) |
| 237 | fix `.print`/`.plot`/`.four` overflow on long node names | [doc](../../enhancements_doc/Enhancement-237.md) | [nameovf](../../examples/nameovf_examples/) |
| 238 | fix NULL-deref on malformed `v(1,` differential token | [doc](../../enhancements_doc/Enhancement-238.md) | [malftoken](../../examples/malftoken_examples/) |
| 239 | fix NULL-deref on 1-arg `min`/`max`/`pow`/`pwr` | [doc](../../enhancements_doc/Enhancement-239.md) | [funcarity](../../examples/funcarity_examples/) |
| 240 | fix XSPICE `s_xfer` OOB on static-gain transfer function | [doc](../../enhancements_doc/Enhancement-240.md) | [sxfer](../../examples/sxfer_examples/) |
| 241 | fix `fft` amplitude norm for non-power-of-2 records | [doc](../../enhancements_doc/Enhancement-241.md) | [fftnorm](../../examples/fftnorm_examples/) |
| 242 | native N-port device via `pre_snp -native` (direct Y stamp, no OSDI) | [doc](../../enhancements_doc/Enhancement-242.md) | [nport_native](../../examples/nport_native_examples/) |
| 243 | `pre_snp -osdi` emits ref terminal for identical instance line | [doc](../../enhancements_doc/Enhancement-243.md) | [presnp](../../examples/presnp_examples/) |
| 244 | fix `nport` unbound-node abort and `pyplot -hist`/`-contour` UAF | [doc](../../enhancements_doc/Enhancement-244.md) | [crashfix2](../../examples/crashfix2_examples/) |
| 245 | fix `meas` stray-`=` and `altermod` NULL-param derefs | [doc](../../enhancements_doc/Enhancement-245.md) | [crashfix3](../../examples/crashfix3_examples/) |
| 246 | fix OOB read in `pwl`/`pwlts` code models on mismatched arrays | [doc](../../enhancements_doc/Enhancement-246.md) | [pwlfix](../../examples/pwlfix_examples/) |
| 247 | fix OOB/UB in `table2d`/`table3d` XSPICE models on degenerate tables | [doc](../../enhancements_doc/Enhancement-247.md) | [tablefix](../../examples/tablefix_examples/) |
| 248 | fix OOB in `CPL` coupled-line device on excess conductors | [doc](../../enhancements_doc/Enhancement-248.md) | [cplfix](../../examples/cplfix_examples/) |
| 249 | validate `URC` lump count and reject negative R/L/G/C in `LTRA` | [doc](../../enhancements_doc/Enhancement-249.md) | [tlinefix](../../examples/tlinefix_examples/) |
| 250 | fix UB `1<<n` shift in `d_lut`/`d_genlut` by capping input ports | [doc](../../enhancements_doc/Enhancement-250.md) | [dlutfix](../../examples/dlutfix_examples/) |
| 251 | prove HB converges to exact steady state; tighten tolerance | [doc](../../enhancements_doc/Enhancement-251.md) | [hb](../../examples/hb_examples/) |
| 252 | fix heap OOB writes in `xfer`/`file_source` file parsers | [doc](../../enhancements_doc/Enhancement-252.md) | [filefix](../../examples/filefix_examples/) |
| 253 | `rfstab` two-port stability report (K, Delta, mu, MSG/MAG) | [doc](../../enhancements_doc/Enhancement-253.md) | [rfstab](../../examples/rfstab_examples/) |
| 254 | `pyplot -smith` Smith-chart view for S-params | [doc](../../enhancements_doc/Enhancement-254.md) | [pyplotsmith](../../examples/pyplotsmith_examples/) |
| 255 | prove `.disto` exact vs HB; warn on B-source nonlinearities | [doc](../../enhancements_doc/Enhancement-255.md) | [distoexact](../../examples/distoexact_examples/) |
| 256 | fix DC false-convergence on singular-derivative B-sources | [doc](../../enhancements_doc/Enhancement-256.md) | [bsrcconv](../../examples/bsrcconv_examples/) |
| 257 | extend DC false-convergence guard to `.tran` op point | [doc](../../enhancements_doc/Enhancement-257.md) | [bsrcconv](../../examples/bsrcconv_examples/) |
| 258 | extend false-convergence guard to `.dc` sweep cold-start | [doc](../../enhancements_doc/Enhancement-258.md) | [bsrcconv](../../examples/bsrcconv_examples/) |
| 259 | verify TRAP/Gear2/BE integration order and energy behavior | [doc](../../enhancements_doc/Enhancement-259.md) | [integaccuracy](../../examples/integaccuracy_examples/) |
| 260 | verify LTE step-controller accuracy tracks `reltol` on stiff circuit | [doc](../../enhancements_doc/Enhancement-260.md) | [integaccuracy](../../examples/integaccuracy_examples/) |
| 261 | regularize `sqrt()` derivative singularity at V=0 in autodiff | [doc](../../enhancements_doc/Enhancement-261.md) | [vafsqrtguard](../../examples/vafsqrtguard_examples/) |
| 262 | regularize fractional `pow(V,Y)` derivative singularity at V=0 | [doc](../../enhancements_doc/Enhancement-262.md) | [vafsqrtguard](../../examples/vafsqrtguard_examples/) |
| 263 | harden 3 fuzz-found compiler panics (`ddt`/`ddx`/empty module) to clean errors | [doc](../../enhancements_doc/Enhancement-263.md) | [vafcrash4](../../examples/vafcrash4_examples/) |
| 264 | instance-array flatten O(N^2)->O(N) plus fix codegen stack overflow | [doc](../../enhancements_doc/Enhancement-264.md) | [vafhang](../../examples/vafhang_examples/) |
| 265 | fix `laplace_*`/`zi_*` bad-coefficient and empty-denominator crash | [doc](../../enhancements_doc/Enhancement-265.md) | [vaflaplace](../../examples/vaflaplace_examples/) |
| 266 | announce linear solver once per multi-point run, not every analysis | [doc](../../enhancements_doc/Enhancement-266.md) | [solverannounce](../../examples/solverannounce_examples/) |
| 267 | `sweep` keeps bus-node names as `ph[0]` not `ph_0_` | [doc](../../enhancements_doc/Enhancement-267.md) | [sweepbus](../../examples/sweepbus_examples/) |
| 268 | wildcard model-param knob `@*[param]` sets every model in place | [doc](../../enhancements_doc/Enhancement-268.md) | [sweepwild](../../examples/sweepwild_examples/) |
| 269 | `@#*[param]` instance-wildcard knob sets param on all instances | [doc](../../enhancements_doc/Enhancement-269.md) | [sweepwild](../../examples/sweepwild_examples/) |
| 270 | `sweep` validates numeric bounds (reject non-numeric/inf/overflow) | [doc](../../enhancements_doc/Enhancement-270.md) | [sweepbounds](../../examples/sweepbounds_examples/) |
| 271 | fix `let` out-of-bounds read on empty left-hand side | [doc](../../enhancements_doc/Enhancement-271.md) | [letoob](../../examples/letoob_examples/) |
| 272 | fix `alter`/`sweep` NULL-param SEGV on m-named device | [doc](../../enhancements_doc/Enhancement-272.md) | [alternull](../../examples/alternull_examples/) |
| 273 | fix cmaths `%`/`vector`/`unitvec` double-to-int cast UB | [doc](../../enhancements_doc/Enhancement-273.md) | [mathcast](../../examples/mathcast_examples/) |
| 274 | fix vector index `v[expr]` non-finite cast UB | [doc](../../enhancements_doc/Enhancement-274.md) | [idxcast](../../examples/idxcast_examples/) |
| 275 | fix `ifft()` heap over-read on real-input vector | [doc](../../enhancements_doc/Enhancement-275.md) | [ifftreal](../../examples/ifftreal_examples/) |
| 276 | fix `rnd()` non-finite operand cast UB | [doc](../../enhancements_doc/Enhancement-276.md) | [rndcast](../../examples/rndcast_examples/) |
| 277 | fix `deriv()` complex-vector over-read and wrong result | [doc](../../enhancements_doc/Enhancement-277.md) | [derivcx](../../examples/derivcx_examples/) |
| 278 | fix `integ`/`deriv`/`ifft` over-read when length != plot scale | [doc](../../enhancements_doc/Enhancement-278.md) | [scaleguard](../../examples/scaleguard_examples/) |
| 279 | guard remaining `(int)floor` user-value casts (`let`/`set`/`meas`) | [doc](../../enhancements_doc/Enhancement-279.md) | [castguard](../../examples/castguard_examples/) |
| 280 | fix OOB write on out-of-range single index in `let` assignment | [doc](../../enhancements_doc/Enhancement-280.md) | [letidxoob](../../examples/letidxoob_examples/) |
| 281 | fix `deriv()` heap over-read on a partial last block | [doc](../../enhancements_doc/Enhancement-281.md) | [derivgroup](../../examples/derivgroup_examples/) |
| 282 | fix `asciiplot` axis-label over-read on 3-digit exponent | [doc](../../enhancements_doc/Enhancement-282.md) | [plotlabel](../../examples/plotlabel_examples/) |
| 283 | fix plot-coordinate UB casting non-finite doubles to int | [doc](../../enhancements_doc/Enhancement-283.md) | [plotcoord](../../examples/plotcoord_examples/) |
| 284 | `@*[[p]]` wildcard names the working instance-vs-model form | [doc](../../enhancements_doc/Enhancement-284.md) | [wildparam](../../examples/wildparam_examples/) |
| 285 | fix plot/wrdata/`.meas` OOB and complex-vector NULL deref | [doc](../../enhancements_doc/Enhancement-285.md) | [veclenmix](../../examples/veclenmix_examples/) |
| 286 | fix const-fold int div-by-zero crash; wrapping arith matches codegen | [doc](../../enhancements_doc/Enhancement-286.md) | [vafcodegen](../../examples/vafcodegen_examples/) |
| 287 | fix const-fold branch leaving stale phi edge (broken SSA) | [doc](../../enhancements_doc/Enhancement-287.md) | [vafcodegen](../../examples/vafcodegen_examples/) |
| 288 | fix `hypot` declared unary but called binary (invalid IR) | [doc](../../enhancements_doc/Enhancement-288.md) | [vafcodegen](../../examples/vafcodegen_examples/) |
| 289 | fix `$clog2` invalid IR (`llvm.ctlz` missing type suffix) | [doc](../../enhancements_doc/Enhancement-289.md) | [vafcodegen](../../examples/vafcodegen_examples/) |
| 290 | fix `$temperature` operator-arg wrong struct offset (SIGSEGV) | [doc](../../enhancements_doc/Enhancement-290.md) | [vafcodegen](../../examples/vafcodegen_examples/) |
| 291 | fix `max`/`min`/`abs` in `case` default leaving block unsealed | [doc](../../enhancements_doc/Enhancement-291.md) | [vafcodegen](../../examples/vafcodegen_examples/) |
| 292 | fix small-signal pruning crash on missing linear-contrib key | [doc](../../enhancements_doc/Enhancement-292.md) | [vafcodegen](../../examples/vafcodegen_examples/) |
| 293 | fix `ddt(ddt(x))` directly-nested analog-operator crash | [doc](../../enhancements_doc/Enhancement-293.md) | [vafcodegen](../../examples/vafcodegen_examples/) |
| 294 | fix `Branch`-to-`Jump` rewrite leaving stale condition use | [doc](../../enhancements_doc/Enhancement-294.md) | [vafcodegen](../../examples/vafcodegen_examples/) |
| 295 | add regression guards for 4x4 matrices and param-slot readback | [doc](../../enhancements_doc/Enhancement-295.md) | [vafcodegen](../../examples/vafcodegen_examples/) |
| 296 | `pyplot` figure styling via 7 `set` vars (grid, legend, dpi) | [doc](../../enhancements_doc/Enhancement-296.md) | [pyplotmore](../../examples/pyplotmore_examples/) |
| 297 | `pyplot -fft` one-sided amplitude spectrum | [doc](../../enhancements_doc/Enhancement-297.md) | [pyplotmore](../../examples/pyplotmore_examples/) |
| 298 | `pyplot -bode`/`-nyquist`/`-polar` complex AC views | [doc](../../enhancements_doc/Enhancement-298.md) | [pyplotmore](../../examples/pyplotmore_examples/) |
| 299 | `pyplot` overlay sizes to longest run + `pyplot_cursor` crosshair | [doc](../../enhancements_doc/Enhancement-299.md) | [pyplotmore](../../examples/pyplotmore_examples/) |
| 300 | `pyplot_mplcursors` selects mplcursors hover-cursor backend | [doc](../../enhancements_doc/Enhancement-300.md) | [pyplotmore](../../examples/pyplotmore_examples/) |
| 301 | `pyplot_cursor` single master switch for interactive cursor | [doc](../../enhancements_doc/Enhancement-301.md) | [pyplotmore](../../examples/pyplotmore_examples/) |
| 302 | `.meas avg` clips window to [from,to] | [doc](../../enhancements_doc/Enhancement-302.md) | [measwindow](../../examples/measwindow_examples/) |
| 303 | `.meas dc avg` clips window to [from,to] | [doc](../../enhancements_doc/Enhancement-303.md) | [measwindow](../../examples/measwindow_examples/) |
| 304 | fix `.meas dc integ`/`rms` OOB on descending dc sweep | [doc](../../enhancements_doc/Enhancement-304.md) | [measwindow](../../examples/measwindow_examples/) |
| 305 | `wcd` worst-case-distance / MPFP high-sigma analysis | [doc](../../enhancements_doc/Enhancement-305.md) | [wcd](../../examples/wcd_examples/) |
| 306 | fix `fft()` vector-expr amplitude scaled by padded size | [doc](../../enhancements_doc/Enhancement-306.md) | [fftexpr](../../examples/fftexpr_examples/) |
| 307 | fix compiler crash on `ddt` reaching no contribution | [doc](../../enhancements_doc/Enhancement-307.md) | [vafdeadop](../../examples/vafdeadop_examples/) |
| 308 | fix codegen crash on var read before its only-writer loop | [doc](../../enhancements_doc/Enhancement-308.md) | [vafuninitloop](../../examples/vafuninitloop_examples/) |
| 309 | fix GVN crash re-queuing users in unreachable block | [doc](../../enhancements_doc/Enhancement-309.md) | [vafgvnunreach](../../examples/vafgvnunreach_examples/) |
| 310 | fix `simplify_cfg` const-fold leaving SSA-invalid phi | [doc](../../enhancements_doc/Enhancement-310.md) | [vafcfgphi](../../examples/vafcfgphi_examples/) |
| 311 | `.control meas` supports `param`/`expr` measurements | [doc](../../enhancements_doc/Enhancement-311.md) | [measparam](../../examples/measparam_examples/) |
| 312 | fix XSPICE integrating code models to true O(h^2) transient | [doc](../../enhancements_doc/Enhancement-312.md) | [sxferorder](../../examples/sxferorder_examples/) |
| 313 | type-check `$fwrite`/`$sformat` format args, fix `ddx(int)` crash | [doc](../../enhancements_doc/Enhancement-313.md) | [vafargcoerce](../../examples/vafargcoerce_examples/) |
| 314 | fix const-fold int overflow abort and cap `{N{...}}` replication | [doc](../../enhancements_doc/Enhancement-314.md) | [vafconstlit](../../examples/vafconstlit_examples/) |
| 315 | clean-error `.tf`/`.pz`/`.disto` crashes on degenerate circuits | [doc](../../enhancements_doc/Enhancement-315.md) | [ngcrashanalysis](../../examples/ngcrashanalysis_examples/) |
| 316 | fix `.meas avg` dropping final timestep before `to` | [doc](../../enhancements_doc/Enhancement-316.md) | [measavgwin](../../examples/measavgwin_examples/) |
| 317 | fix `idt`-IC codegen crash in statically-false branch | [doc](../../enhancements_doc/Enhancement-317.md) | [vafidtcfg](../../examples/vafidtcfg_examples/) |
| 318 | fix SFFM/AM voltage sources dropping DC offset before TD | [doc](../../enhancements_doc/Enhancement-318.md) | [sffmoffset](../../examples/sffmoffset_examples/) |
| 319 | fix `qpss` transient-form spectral leakage into mixing bins | [doc](../../enhancements_doc/Enhancement-319.md) | [qpssleak](../../examples/qpssleak_examples/) |
| 320 | `sweep` of a `.param` updates values in place, no full reset | [doc](../../enhancements_doc/Enhancement-320.md) | [paramfastsweep](../../examples/paramfastsweep_examples/) |
| 321 | extend `.param` fast-sweep to subcircuit-internal device values | [doc](../../enhancements_doc/Enhancement-321.md) | [paramfastsweep](../../examples/paramfastsweep_examples/) |
| 322 | `optimize` reuses `.param` fast-path, no per-eval reset | [doc](../../enhancements_doc/Enhancement-322.md) | [optimize](../../examples/optimize_examples/) |
| 323 | arm `optimize` fast-path for small OSDI fits (weight OSDI 30x) | [doc](../../enhancements_doc/Enhancement-323.md) | [optimize](../../examples/optimize_examples/) |
| 324 | fix `$fatal` stranding code in an unreachable block (2 shipped crashes) | [doc](../../enhancements_doc/Enhancement-324.md) | [vaffatalcfg](../../examples/vaffatalcfg_examples/) |
| 325 | bound materialized size of `{n{...}}` (string arity hang, 2^40 u32 wrap) | [doc](../../enhancements_doc/Enhancement-325.md) | [vafconcatsize](../../examples/vafconcatsize_examples/) |
| 326 | fix shipped SIGSEGV: cross-namespace `Value` compare mis-typed init cache slots | [doc](../../enhancements_doc/Enhancement-326.md) | [vafinitcache](../../examples/vafinitcache_examples/) |
| 327 | fix `ddx` crash on reverse-oriented or ground unknowns (now compile) | [doc](../../enhancements_doc/Enhancement-327.md) | [vafddxunknown](../../examples/vafddxunknown_examples/) |
| 328 | fix crash: dynamic array index used directly as a contribution RHS | [doc](../../enhancements_doc/Enhancement-328.md) | [vafdynidx](../../examples/vafdynidx_examples/) |
| 329 | fix crash: GRAVESTONE phi operand in the small-signal network builder | [doc](../../enhancements_doc/Enhancement-329.md) | [vafssngravestone](../../examples/vafssngravestone_examples/) |
| 330 | fix compiler hang: `ddx` in a runtime loop now a clean LRM 4.5.1 error | [doc](../../enhancements_doc/Enhancement-330.md) | [vafddxloop](../../examples/vafddxloop_examples/) |
| 331 | fix crash: `BitSet::contains` panicked outside its domain (dense rows) | [doc](../../enhancements_doc/Enhancement-331.md) | [vafbitsetdomain](../../examples/vafbitsetdomain_examples/) |
| 332 | fix wrong charge: summing 3+ `ddt()` terms dropped all but one | [doc](../../enhancements_doc/Enhancement-332.md) | [vafddtsum](../../examples/vafddtsum_examples/) |
| 333 | fix crash: integer division by a literal zero SIGTRAPped the simulator | [doc](../../enhancements_doc/Enhancement-333.md) | [vafdivzero](../../examples/vafdivzero_examples/) |
| 334 | fix crash: `INT_MIN/-1` and out-of-range shifts also SIGTRAPped (E-333 gap) | [doc](../../enhancements_doc/Enhancement-334.md) | [vafintub](../../examples/vafintub_examples/) |
| 335 | fix wrong answers: `!=` vs NaN, runtime shift masking, fast-math folds on doubles | [doc](../../enhancements_doc/Enhancement-335.md) | [vafieee](../../examples/vafieee_examples/) |
| 336 | fix OSDI binding: param `M` taken as multiplier, case collisions, stale Jacobian count | [doc](../../enhancements_doc/Enhancement-336.md) | [osdiparam](../../examples/osdiparam_examples/) |
| 337 | keep `x*0` fold: removing it shifted HiSIM2 drain current 10x (E-335 overreach) | [doc](../../enhancements_doc/Enhancement-337.md) | [vafmulzero](../../examples/vafmulzero_examples/) |
| 338 | fix hang: 64-bit bus range overflowed the width guard (7.6 GB in 9 s) | [doc](../../enhancements_doc/Enhancement-338.md) | [busoverflow](../../examples/busoverflow_examples/) |
| 339 | fix crash: `v()` with 3+ node names double-freed (print/let/pyplot) | [doc](../../enhancements_doc/Enhancement-339.md) | [vfuncarity](../../examples/vfuncarity_examples/) |
| 340 | fix nondeterminism: implicit-net declaration order came from HashMap walk | [doc](../../enhancements_doc/Enhancement-340.md) | [vafdeterminism](../../examples/vafdeterminism_examples/) |
| 341 | fix crash: `sweep -analysis reset/remcirc` freed the circuit mid-loop | [doc](../../enhancements_doc/Enhancement-341.md) | [sweepanalysis](../../examples/sweepanalysis_examples/) |
| 342 | fix crash: rawfile `Option: plots` use-after-free; `unset plots` double free | [doc](../../enhancements_doc/Enhancement-342.md) | [usrvarown](../../examples/usrvarown_examples/) |
| 343 | perf: sweep no longer O(N&#178;) -- 26.6x at 16k points; `cp_getvar` built all 5 usrvars per call | [doc](../../enhancements_doc/Enhancement-343.md) | [sweepscale](../../examples/sweepscale_examples/) |
| 344 | perf: `.model` params join the fast `.param` sweep's direct set -- now as cheap as instance params | [doc](../../enhancements_doc/Enhancement-344.md) | [modelparamset](../../examples/modelparamset_examples/) |
| 345 | perf: sweep is now LINEAR -- plot naming no longer walks the plot list; 87x at 64k points | [doc](../../enhancements_doc/Enhancement-345.md) | [plotname](../../examples/plotname_examples/) |
| 346 | fix: fast `.param` path froze random draws reset re-drew; adds the Monte Carlo tier | [doc](../../enhancements_doc/Enhancement-346.md) | [mcfastpath](../../examples/mcfastpath_examples/) |
| 347 | fix: SSA re-builder no longer mints an Invalid phi operand (assertions build clean) | [doc](../../enhancements_doc/Enhancement-347.md) | [ssavalid](../../examples/ssavalid_examples/) |
| 348 | fix crash: `.pss` segfaulted on a short argument list, and on `harmonics 0` at full arity | [doc](../../enhancements_doc/Enhancement-348.md) | [pssargs](../../examples/pssargs_examples/) |
| 349 | fix crash: a mistyped node name on `tf`/`pz`/`noise`/`sens`/`pss` killed the process | [doc](../../enhancements_doc/Enhancement-349.md) | [nodetypo](../../examples/nodetypo_examples/) |
| 350 | fix: a sweep now restores its `.param`; repeat sweeps no longer disarm the fast path | [doc](../../enhancements_doc/Enhancement-350.md) | [sweeprestore](../../examples/sweeprestore_examples/) |
| 351 | fix crash: `sens` killed ngspice on any OSDI model with an internal node | [doc](../../enhancements_doc/Enhancement-351.md) | [osdisens](../../examples/osdisens_examples/) |
| 352 | `.disto` for Verilog-A devices via OSDI 0.8 Taylor tensors; no variable-count limit | [doc](../../enhancements_doc/Enhancement-352.md) | [osdidisto](../../examples/osdidisto_examples/) |
| 353 | `.disto` now works for models using `$limit`, i.e. every production compact model | [doc](../../enhancements_doc/Enhancement-353.md) | [limitdisto](../../examples/limitdisto_examples/) |
| 359 | `.disto` rebuilt: tensors differenced from the analytic Jacobian in ngspice, so compile time and object size return to baseline | [doc](../../enhancements_doc/Enhancement-359.md) | [osdidisto](../../examples/osdidisto_examples/) |
| 360 | fix: a second Verilog-A model no longer silences the first in `.disto` (per-model tensor cache) | [doc](../../enhancements_doc/Enhancement-360.md) | [osdidisto](../../examples/osdidisto_examples/) |
| 361 | fix: ASan/UBSan in `.disto` — out-of-bounds read of the solution vector, and `(int)NaN` point count on degenerate sweeps | [doc](../../enhancements_doc/Enhancement-361.md) | [osdidisto](../../examples/osdidisto_examples/) |
| 362 | fuzzing analysis-card sweep parameters: 7 fixes — counts cast to int reaching allocators, and an unbounded `.dc` sweep | [doc](../../enhancements_doc/Enhancement-362.md) | [sweepguard](../../examples/sweepguard_examples/) |
| 363 | fix: two compiler crashes from cross-feature fuzzing — a block merged into itself (`case` in a `do-while`), and array parameters never instance-renamed | [doc](../../enhancements_doc/Enhancement-363.md) | [vafcfg](../../examples/vafcfg_examples/) |
| 364 | transient noise for OSDI devices — Verilog-A `white_noise`/`flicker_noise` injected into `.tran`, activating automatically when the deck has a `trnoise` source | [doc](../../enhancements_doc/Enhancement-364.md) | [trnoise](../../examples/trnoise_examples/) |
| 365 | fix: `pz` left device matrix bindings dangling, so a following `hb` returned a silently wrong result (and read freed memory) | [doc](../../enhancements_doc/Enhancement-365.md) | [pzhb](../../examples/pzhb_examples/) |
| 366 | fix: two more sites of the E-365 stale-binding class — `pz` then `qpss`, and a KLU NULL check that reported the NULL then dereferenced it | [doc](../../enhancements_doc/Enhancement-366.md) | [pzklu](../../examples/pzklu_examples/) |
| 367 | fix: `sweep` plots were named `unknown<N>` and the summary quoted a literal `'sweep'` no plot answered to; eight plot types registered and the real name printed | [doc](../../enhancements_doc/Enhancement-367.md) | [sweepname](../../examples/sweepname_examples/) |
| 368 | fix: the periodic small-signal analyses named their plots wrong — `pxf` was `unknown<N>`, and `pac`/`psp`/`pnoise`/`qpnoise`/`phasenoise`/`qpss` each collided with an unrelated analysis | [doc](../../enhancements_doc/Enhancement-368.md) | [periodicnames](../../examples/periodicnames_examples/) |
| 369 | fix: closes the E-365/366 stale-binding class — a KLU pole-zero binding was cleared only when re-established, so a later analysis dereferenced freed memory | [doc](../../enhancements_doc/Enhancement-369.md) | [klubind](../../examples/klubind_examples/) |
| 370 | fix: every `.pz` re-expanded a URC subcircuit, creating nodes past the allocated RHS — a heap-buffer-overflow hiding under a passing crash fixture | [doc](../../enhancements_doc/Enhancement-370.md) | [urcpz](../../examples/urcpz_examples/) |
| 371 | plot naming and dates: per-type numbering, so the first sweep is `sweep1` not `sweep500`; every plot now carries a date (command-created plots printed `(null)`) | [doc](../../enhancements_doc/Enhancement-371.md) | [plotname](../../examples/plotname_examples/) |
| 372 | fix: `unset plots` printed a spurious `Internal Error: var 112` — a `%d` fed a dereferenced `char *`, on a branch valid input always reaches | [doc](../../enhancements_doc/Enhancement-372.md) | [unsetvar](../../examples/unsetvar_examples/) |
| 373 | fix: a rawfile write/load round trip dropped the x-axis column from `print` (`pl_ndims` never restored) and renamed the `.dc` sweep axis to `v(v-sweep)` | [doc](../../enhancements_doc/Enhancement-373.md) | [rawtrip](../../examples/rawtrip_examples/) |
| 374 | fix: `setseed` did not seed transient noise — the Wallace generator's pools were filled at startup from `getpid()` and never rebuilt | [doc](../../enhancements_doc/Enhancement-374.md) | [setseed](../../examples/setseed_examples/) |
| 375 | fix: a loop that provably cannot finish is now a compile error — it used to emit a model that hung the simulator with no diagnostic; also closes 3 codegen crashes on `disable` | [doc](../../enhancements_doc/Enhancement-375.md) | [vafloop](../../examples/vafloop_examples/) |
| 376 | fix: `$dist_*` returned `real`; the LRM makes it integer (`$rdist_*` is the real family) — needed a `ficast` in the lowering too, or the value read as 0 | [doc](../../enhancements_doc/Enhancement-376.md) | [distint](../../examples/distint_examples/) |
| 377 | fix: OSDI diagnostics — name glued to its argument, no newline, no `free`, and `LOG_LVL_MASK` 8 made every severity report as `OSDI(debug)` on stdout | [doc](../../enhancements_doc/Enhancement-377.md) | [simparamdiag](../../examples/simparamdiag_examples/) |
| 378 | fix: a Verilog-A `$fatal` during the operating point was read as non-convergence, so the gmin/source ladder retried it 373x and blamed `timestep too small` | [doc](../../enhancements_doc/Enhancement-378.md) | [opfatal](../../examples/opfatal_examples/) |
| 379 | fix: `cargo test --workspace` now builds and no longer overwrites checked-in source — verilogae drift, and three sourcegen generators that had fallen behind the files they generate | [doc](../../enhancements_doc/Enhancement-379.md) | n/a |
| 400 | fix: a branch contributed as both a potential and a flow source silently kept only the last contribution -- new `discarded_contribution` lint (L022), with the switch-branch idiom deliberately untouched | [doc](../../enhancements_doc/Enhancement-400.md) | n/a |
| 401 | fix: `V(a,b) <+ 0` between two module terminals silently produced an open circuit instead of a short -- a two-sided fix, real 0 V source plus new OSDI terminal-short metadata so the simulator can drop it when redundant | [doc](../../enhancements_doc/Enhancement-401.md) | n/a |
| 402 | fix: an OSDI instance line with fewer nodes than the model has terminals was accepted in silence -- now warns, naming each absent terminal and stating that it is not grounded | [doc](../../enhancements_doc/Enhancement-402.md) | n/a |
| 403 | fix: five device noise routines added the nominal temperature in Celsius to a temperature difference, so an instance `temp=` inflated thermal noise power by 9%; plus a type error that listed the same expected type three times | [doc](../../enhancements_doc/Enhancement-403.md) | n/a |
| 404 | perf: a module declaring a wide bus elaborated in time quadratic in the bus width -- 31.5 s for `[65535:0]` -- from a linear node scan run once per declared bit and, behind it, a dense jacobian row rescanned per row; both made linear, emitted `.osdi` byte-identical | [doc](../../enhancements_doc/Enhancement-404.md) | n/a |
| 405 | fix: the `zi_np`/`zi_zp`/`zi_zd` z-domain filters reciprocated every pole and zero (a pole written 0.5 landed at z=2), an empty coefficient denominator hung the compiler at tens of GB, and `laplace_*` silently truncated a numerator of higher order than its denominator; plus parameter arrays now take a runtime index, array bounds accept constant expressions, and a declared `genvar` is no longer reported as undeclared | [doc](../../enhancements_doc/Enhancement-405.md) | [filterforms](../../examples/filterforms_examples/) |
| 406 | fix: probing the flow of a declared `branch (a,b) br` while the node pair `(a,b)` is the one actually contributed to gave `br` an ideal ammeter that SHORTED the driven branch -- two 1 kOhm sections in series drew 1.0 mA instead of 0.5 mA, rc=0, silently; new `probe_only_branch_short` lint (L023), with the deliberate sense-ammeter idiom deliberately untouched | [doc](../../enhancements_doc/Enhancement-406.md) | [probeshort](../../examples/probeshort_examples/) |
