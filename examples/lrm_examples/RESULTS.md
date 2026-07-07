# Results — LRM 2023 example sweep vs openvaf-r

**Summary: 231 code blocks extracted from the 442-page LRM PDF. Of the
complete-module examples, 40 compile cleanly, 19 hit documented
openvaf-r limitations (each pinned to its exact diagnostic), 21 use the
mixed-signal subset a Verilog-A compiler correctly rejects. The sweep
exposed eight compiler defects — all eight are now fixed (six in
Enhancement-84, the final two in Enhancement-85). Two errors were found
in the LRM's own examples.**

## Defect findings

All repros live in `findings/` and are pinned by `verify_lrm.py`: fixed
defects must compile, open gaps must keep their exact diagnostic.

| # | Finding | Status | Repro |
|---|---------|--------|-------|
| F1 | **Named port branch crashed the compiler.** `branch (<p>) probe_p;` is plain Verilog-A (LRM 3.7.2) — openvaf-r panicked (`BranchWrite::nodes` unreachable). Now lowers to the same defining equation as a direct `I(<p>)` (E-29); runtime-verified in ngspice (probe reads +5 mA where the source branch reads −5 mA). Contributing to a port branch now gets a proper diagnostic instead of a panic. | **fixed (E-84)** | `micro_portbranch.va`, `va/lrm_p062_2.va` |
| F2 | **Garbage input crashed the parser.** Non-Verilog text (the LRM's attribute pseudo-code, its Annex B keyword table) tripped `bump_ts` assertions in port/function-argument direction parsing. Both sites now emit a diagnostic with forced progress; all 146 extracted LRM fragments compile-attempt cleanly as a fuzz corpus. | **fixed (E-84)** | any non-Verilog text |
| F3 | **Instantiating an undefined module was silently accepted.** The E-5 flattener dropped instantiations whose target didn't exist — a typo'd module name became an invisible open circuit. Now a hard error; discipline-named mis-parses (`electrical out[0:2];`) and dropped paramsets get their own tailored messages. Unmasked 13 suite files that had never really compiled. | **fixed (E-84)** | `micro_unknownmod.va` |
| F4 | **`` `__FILE__ `` / `` `__LINE__ `` were not implemented** (LRM-mandated predefined macros). Now expanded as a textual pre-pass: `` `__FILE__ `` becomes the source basename (machine-portable provenance), `` `__LINE__ `` the exact 1-based line; a use inside a `` `define `` body expands at the definition site (documented). Runtime-verified via `$strobe` in ngspice. | **fixed (E-85)** | `micro_file_line.va`, `filemacro` suite |
| F5 | **`$port_connected` failed on the port it exists for.** Flattening renamed an unconnected port to a local net, which then failed the port-reference check. Now resolved at elaboration time: the call becomes a literal `(1)`/`(0)` per instance. The page-265 clock example compiles. | **fixed (E-84)** | `micro_portconnected.va`, `va/lrm_p265_1.va` |
| F6 | **Part-selects in instance connections didn't parse.** `adc2 hi (out[3:2], in);` (pages 163–164). Now parsed (the colon in the bit-select bracket) and sliced onto bus ports during flattening — positional, named, and width-1 forms, runtime-verified per bit in ngspice; behavioral misuse gets a dedicated diagnostic. | **fixed (E-85)** | `micro_partselect.va`, `partselect` suite |
| F7 | **Dead analog operators aborted codegen.** An operator like `transition()` inside a constant-false branch survived const-folding as a detached op whose state setup read optimized-away values (`split_tainted` panic, then an undefined-value abort in LLVM codegen). Literal `if` conditions now lower only the taken branch, and `split_tainted` tolerates detached branches. Found while fixing F5 (whose `(0)` literals are exactly this shape). | **fixed (E-84)** | `micro_deadop.va` |
| F8 | **openvaf-r exited 0 on hard errors.** The driver's error arm printed the failure but fell through to a success exit — elaboration failures looked like successful compiles to shell scripts (a quirk first noticed in E-58). Now exits 65. Unmasked six more suite files whose "compiles" were error exits. | **fixed (E-84)** | `openvaf-r missing.va; echo $?` |

## Errata in the LRM itself

1. **Page 265, module `twoclk`**: declares `electrical vout_q1, vout_q1b;`
   but the port is named `vout_q2` — `vout_q1b` is a typo. (Patched in
   `va/lrm_p265_1.va`, annotated.)
2. **Port directions omitted throughout**: at least 5 examples (pages 62,
   343, 416) declare ports with no direction. openvaf-r treats this as a
   deny-level lint (L016); the affected files compile with
   `-W port_without_direction`.

## In-scope examples that compile (40)

| File | LRM page | Notes |
|---|---|---|
| `lrm_p018_1.va` | 18 | signal-flow disciplines (voltage/current); syntax-summary junk trimmed off the tail |
| `lrm_p044_1.va` | 44 | verbatim |
| `lrm_p048_2.va` | 48 | derived/alias natures (nature X : parent) with a context module added |
| `lrm_p062_2.va` | 62 | named port branch 'branch (<p>) probe_p;' (LRM 3.7.2); used to crash the compiler - fixed by E-84 (F1) |
| `lrm_p080_1.va` | 80 | verbatim |
| `lrm_p080_3.va` | 80 | verbatim |
| `lrm_p083_1.va` | 83 | verbatim |
| `lrm_p083_2.va` | 83 | verbatim |
| `lrm_p084_1.va` | 84 | verbatim |
| `lrm_p090_1.va` | 90 | verbatim |
| `lrm_p092_1.va` | 92 | verbatim |
| `lrm_p114_1.va` | 114 | verbatim |
| `lrm_p114_2.va` | 114 | verbatim |
| `lrm_p116_1.va` | 116 | verbatim |
| `lrm_p116_2.va` | 116 | verbatim |
| `lrm_p118_1.va` | 118 | verbatim |
| `lrm_p119_1.va` | 119 | hierarchical net + named-branch probes from sibling modules (V(top.drv.a), V(top.a1.b)); parse/elaboration added by E-86; trailing branch()-fragment section trimmed |
| `lrm_p138_1.va` | 138 | verbatim |
| `lrm_p140_1.va` | 140 | verbatim |
| `lrm_p142_1.va` | 142 | verbatim |
| `lrm_p143_1.va` | 143 | verbatim |
| `lrm_p150_1.va` | 150 | sigma-delta ADC loop (cross/transition/idt, implicit nets aa0-aa2); d2a context stub added |
| `lrm_p153_1.va` | 153 | verbatim |
| `lrm_p153_3.va` | 153 | hierarchy example (named parameter overrides); vco context stub added |
| `lrm_p155_1.va` | 155 | verbatim |
| `lrm_p155_2.va` | 155 | verbatim |
| `lrm_p156_1.va` | 156 | matched-resistor layout example: .$xposition/.$yposition instance overrides on each polyres (E-44 hidden state parameters); context stub added |
| `lrm_p163_1.va` | 163 | binary ADC tree wired with part-selects (out[3:2]); used to be a parse error - fixed by E-85 (F6) |
| `lrm_p164_1.va` | 164 | named part-select connections (.out(out[3:2])); parse fixed by E-85 (F6), adc context stub added |
| `lrm_p173_1.va` | 173 | verbatim |
| `lrm_p205_2.va` | 205 | verbatim |
| `lrm_p208_2.va` | 208 | verbatim |
| `lrm_p261_1.va` | 261 | verbatim |
| `lrm_p263_1.va` | 263 | hierarchical path illustration; module_a context stub added |
| `lrm_p263_2.va` | 263 | verbatim |
| `lrm_p263_3.va` | 263 | verbatim |
| `lrm_p265_1.va` | 265 | timer/transition/$port_connected clock source; $port_connected on unconnected flattened ports used to fail - fixed by E-84 (F5). Also fixes a genuine typo in the LRM's own example |
| `lrm_p274_1.va` | 274 | verbatim |
| `lrm_p416_1.va` | 416 | differential pair; LRM omits port directions (lint demoted) + vertNPN context stub |
| `lrm_p416_3.va` | 416 | ECP oscillator pair of examples merged; Annex E primitive stubs added |

## Documented limitations (19)

Each file is verified to be *rejected with this exact diagnostic and no
crash* — if a future enhancement implements one of these, verify fails and
the file graduates to `va/`.

| File | LRM page | Pinned diagnostic | What it needs |
|---|---|---|---|
| `lrm_p045_4.va` | 45 | `name-then-range bus declarations` | name-then-range array ports (input in[0:2]) not supported |
| `lrm_p091_1.va` | 91 | `not a constant expression` | parameter-dependent bus width (electrical [0:bits-1]) |
| `lrm_p112_1.va` | 112 | `unexpected token` | block-scoped parameters; the LRM example itself also demos an illegal override |
| `lrm_p117_1.va` | 117 | `not a constant expression` | parameter-dependent bus width |
| `lrm_p134_1.va` | 134 | `not a constant expression` | parameter-dependent bus width |
| `lrm_p152_2.va` | 152 | `refers to module` | instantiates the Annex E SPICE primitives spice_pmos/spice_nmos (SPICE-compatibility layer not supported) |
| `lrm_p153_2.va` | 153 | `refers to module 'mosp'` | uses the SPICE-compat mosp of the page-152 example, which itself cannot elaborate (Annex E) |
| `lrm_p155_3.va` | 155 | `'processinfo' was not found` | hierarchical refs to an uninstantiated process-info module |
| `lrm_p158_1.va` | 158 | `instantiates paramset 'nch'` | paramset targeting a SPICE primitive (nmos3) rather than a VA module |
| `lrm_p168_1.va` | 168 | `compile-time-constant integer` | generate-for with parameter loop bounds (structure cannot depend on runtime-bindable parameters; E-67 scope decision) |
| `lrm_p169_1.va` | 169 | `not a constant expression` | parameter-dependent bus width (electrical [0:N]) |
| `lrm_p169_2.va` | 169 | `not a constant expression` | parameter-dependent bus width |
| `lrm_p170_1.va` | 170 | `elaboration-time constant` | generate-if on $param_given (parameter-driven structure; E-67 scope decision) |
| `lrm_p171_2.va` | 171 | `elaboration-time constant` | generate-if on a parameter (parameter-driven structure; E-67 scope decision) |
| `lrm_p172_1.va` | 172 | `unexpected token 'if'` | generate-if with parameter condition + implicit genblk naming (E-67 scope decision) |
| `lrm_p267_1.va` | 267 | `refers to module 'resistor'` | $analog_node_alias/$analog_port_alias example; elaboration rejects the unconnected instance nets |
| `lrm_p274_3.va` | 274 | `requires a bit-select` | $table_model with runtime array data arguments |
| `lrm_p343_1.va` | 343 | `'$resistor' was not found` | Annex E SPICE-compatibility system function $resistor() |
| `lrm_p438_1.va` | 438 | `unexpected token 'generate'` | legacy Verilog-A 1.0 'generate i (msb,lsb)' statement (obsolete Annex C form) |

## Mixed-signal examples, correctly out of scope (21)

openvaf-r compiles the Verilog-A analog subset (LRM Annex C); these use the
digital/mixed-signal language.

| File | LRM page | Why out of scope |
|---|---|---|
| `lrm_p140_2.va` | 140 | cross() with digital enable expression (===) and empty optional args |
| `lrm_p144_1.va` | 144 | wreal/assign/always sampler (mixed-signal) |
| `lrm_p162_3.va` | 162 | digital testbench (reg/initial/always) |
| `lrm_p180_2.va` | 180 | wire net driving analog |
| `lrm_p181_1.va` | 181 | ddiscrete net with ===/x/z comparisons |
| `lrm_p182_1.va` | 182 | reg/initial digital converter |
| `lrm_p182_2.va` | 182 | reg/always sampler |
| `lrm_p184_1.va` | 184 | posedge on wire mixed with cross() |
| `lrm_p184_2.va` | 184 | always @(cross) driving a reg |
| `lrm_p191_1.va` | 191 | connectmodule skeletons (mixed-signal auto-insertion) |
| `lrm_p205_1.va` | 205 | digital inverter (reg/always/#delay) |
| `lrm_p206_1.va` | 206 | mixed digital/analog ring with connect rules |
| `lrm_p206_2.va` | 206 | digital inverter + analog inverter pair (reg/always) |
| `lrm_p208_1.va` | 208 | connectmodule + connectrules |
| `lrm_p209_1.va` | 209 | mixed-net example: analog inverter wired to ddiscrete_1v2 nets via connect rules |
| `lrm_p210_1.va` | 210 | connectmodule (elect_to_logic) |
| `lrm_p218_1.va` | 218 | wire nets |
| `lrm_p219_1.va` | 219 | wire [15:0] bus + posedge in analog |
| `lrm_p220_1.va` | 220 | connectmodule pair |
| `lrm_p256_1.va` | 256 | task/$display (digital context) |
| `lrm_p278_1.va` | 278 | connectmodule with drive strength |

## Excluded as non-code (5)

| Block | Page | What it is |
|---|---|---|
| `block_032_1` | 32 | attribute-section pseudo-code (<rest_of_case_statement>); crashes the compiler - finding F2 |
| `block_171_1` | 171 | contains a literal '...' placeholder; also generate-if on a parameter (see E-67) |
| `block_281_1` | 281 | compiler-directive name table; separately, `__FILE__/`__LINE__ are unsupported - finding F4 |
| `block_416_2` | 416 | SPICE netlist from Annex E, not Verilog-A |
| `block_416_4` | 416 | merged into block_416_3 |
