# Enhancement-712: a hundred twenty-pole Laplace filters compile in 1.6 s and half a gigabyte — the root expansion's zero-root choice was four branch diamonds per root and coefficient (54 000 blocks for twenty filters), and the OSDI descriptor module, whose helper functions are straight-line code over every Jacobian entry, is built at -O0 above 256 entries, where two LLVM backend passes are quadratic; 100 filters took 113 s and 48 GB, and a module of 1 000 idt states 139 s

**Scope:** F9 of the
[robustness campaign of 2026-09-23](../docs/bug_hunts/2026-09-23_openvaf-r-robustness-campaign.md).
**Compiler only.** `hir_lower/src/expr.rs` (`laplace_roots_to_poly`,
`const_real_value`), `osdi/src/lib.rs` (`MAIN_FAST_CODEGEN_ENTRIES`, the
`OPENVAF_LLVM_ARGS` hook, phase timings), `mir_llvm/src/lib.rs` (`parse_llvm_args`),
`sim_back/src/lib.rs` (phase timings).
[`examples/filterforms_examples/`](../examples/filterforms_examples/) (10 checks, 95 in
all). The hunt page.

**Suites:** `filterforms` 95 of 95 (93 of 95 on the E-711 binaries: the 100-filter
compile took 119 s and 47.9 GB there), `filterslice`, `lrmfilters`, `vaflaplace`,
`complexpole`, `nullarg` and `opargs` unchanged; the optimised MIR of 19 of the 22
filter-suite modules is identical to the E-711 compiler's modulo numbering, the two
with parameter roots differ only in a `select` where a diamond was, and the third is
the expected compile error; the compiler workspace tests green apart from the three
pre-existing sourcegen drift failures (221 passed), no build warnings; full sweep 532 of
532, run alone.

## What was wrong

One module with `n` contributions `I(p,n) <+ laplace_zp(V(p,n), '{}, '{-1,0, -2,0,
…, -20,0});`, twenty poles each, and the campaign's other shapes:

| module | states | Jacobian entries | before | now |
|---|---|---|---|---|
| 5 filters of 20 poles | 100 | 310 | 1.0 s, 255 MB | 0.1 s, 77 MB |
| 10 | 200 | 620 | 2.6 s, 577 MB | 0.2 s, 95 MB |
| 20 | 400 | 1 240 | 7.0 s, 2.6 GB | 0.3 s, 134 MB |
| 40 | 800 | 2 480 | 22 s, 7.9 GB | 0.6 s, 219 MB |
| 100 | 2 000 | 6 200 | 113 s, 48 GB | 1.6 s, 550 MB |
| 1 filter of 400 poles | 400 | | 6.1 s, 5.8 GB | 0.7 s, 366 MB |
| 4 filters of 100 poles | 400 | | 12.4 s, 7.6 GB | 0.3 s, 199 MB |
| 100 filters of 4 poles | 400 | | 6.5 s, 0.9 GB | 0.3 s, 185 MB |
| 400 `idt` states, no filter | 400 | 2 000 | 25 s, 369 MB | 0.5 s, 142 MB |
| 1 000 `idt` states | 1 000 | 5 000 | 139 s, 1.1 GB | 1.8 s, 339 MB |
| a ladder of 400 nodes, no state | | 1 204 | 5.8 s, 251 MB | 0.5 s, 116 MB |
| a ladder of 1 000 nodes | | 3 004 | 17.9 s, 600 MB | 1.2 s, 197 MB |

The hunt page attributed the memory to the autodiff differentiating every state
equation against every unknown. That was wrong: the whole MIR side of the compile —
the DAE build, the derivatives, the optimiser — took 110 ms of the 20-filter module's
7 s, and the eval function's LLVM module 400 ms. Two other things were quadratic, one
in each half of the compiler, and the `idt` and ladder rows show that the second has
nothing to do with filters.

**The memory was blocks.** `laplace_zp`, `laplace_np` and `laplace_zd` expand their
roots into polynomial coefficients at lowering time, one complex multiply-add per
(root, coefficient) pair. The LRM's exception — a root at zero contributes a bare `s`
rather than `(1 - s/r)` — was selected at run time with `make_select`, which is a
branch, two arms and a merge block, and it was selected FOUR times per pair (the real
and imaginary parts at two degrees). A 20-pole filter opened 4 × 20 × 21 / 2 = 840
diamonds, 2 520 blocks; twenty of them 54 183 blocks, a hundred 270 000 — every one of
which the optimiser folded away a moment later, because the roots are literals. The
SSA construction over that many blocks (`use_var_nonlocal`'s predecessor walks and
their per-variable block sets) was the 2.6 GB and the 48 GB, and most of the time.
Two more diamonds per root guarded the reciprocal's division. The "filter states"
cost was a block count.

**The time was the descriptor module.** OSDI's descriptor carries a family of helper
functions per module — `load_jacobian_resist`, `load_jacobian_tran`,
`load_jacobian_with_offset_*`, `load_residual_*`, `load_spice_rhs_dc`,
`load_spice_rhs_tran`, `write_jacobian_array_*` — each one straight-line block with a
few memory operations per Jacobian entry or unknown: `*jacobian_ptr[i] += value[i]` for
every entry, `rhs[node[i]] -= J[i,j] * x[j]` for every entry of every row. They are
built in one LLVM module after the eval, on the main thread, at the requested -O3, and
for 2 000 entries that module took 24 s of the 400-idt module's 25 s (the eval 0.2 s).
LLVM's own pass timings, reached through the new `OPENVAF_LLVM_ARGS=-time-passes`
hook, name the passes: the post-legalisation DAG combine (its post-indexed
load/store search visits every use of a base pointer for every load of it, so the
node-index array loaded once per entry is quadratic) and the machine scheduler (an
alias check between every pair of memory operations through the loaded pointers).
Neither has a switch that is not process-wide, and both are per basic block, which
straight-line code defeats. The same IR through `opt -O3` and `llc -O3` reproduced
the 8 s of `load_spice_rhs_tran` exactly, and at -O0 it was 0.05 s.

## What changed

**The zero-root choice is decided at lowering time**
(`hir_lower/src/expr.rs`, `laplace_roots_to_poly`). A root whose real and imaginary
parts are constants — a literal, or the `fneg` of one, which is what `-1.0` lowers
to — is known zero or known non-zero before any instruction is emitted, and the loop
emits the one form. A known-zero root shifts the polynomial up a degree and skips the
reciprocal entirely. A root that is not a constant (a parameter, or an expression)
keeps the run-time choice as a branchless `select` on the four values, and the
reciprocal's guard is a `select` too. The arithmetic is the same operations in the
same order, so the coefficients are the same numbers: the 20-filter module lowers to
183 blocks instead of 54 183, the 100-filter one to 903.

**The descriptor module is built at -O0 above 256 Jacobian entries**
(`osdi/src/lib.rs`, `MAIN_FAST_CODEGEN_ENTRIES`, the count summed over the file's
modules), on the model of E-579's setup modules. FastISel and no middle-end passes are
linear, and the helpers are memory-bound copies whose code quality does not change
with the level: a 2 ms transient of the 10-filter module (620 entries) ran in 12.9
and 13.2 s with the helpers at -O3 and 13.1 and 13.2 s at -O0, and both descriptor
variants give the same currents. Every compact model keeps the requested level — the
largest CMC models have about a hundred entries (BSIM-bulk 122, BSIM-SOI 118, BSIM4
107, HiSIM2 63) and their descriptor modules take 0.15 to 0.3 s. The eval, access and
setup modules are unaffected either way.

**Two diagnostics stay.** `OPENVAF_LLVM_ARGS` hands whitespace-separated LLVM
command-line options (`-time-passes`, `-print-after=codegenprepare
-print-module-scope`, `-enable-misched=false`) to LLVM's parser once, before the first
pass pipeline (`mir_llvm::parse_llvm_args`); and `PHASE_PROF=1` now also prints the
lowering, initial-optimisation and topology phases and, for each of the five LLVM
modules, its optimise and emit times, the descriptor module's with its Jacobian entry
and unknown counts. Both are opt-in and change nothing else.

## Verification

`filterforms` section "Enhancement-712": the 100-filter module compiles in under 60 s
and 4 GB (1.6 s and 541 MB; 119 s and 47.9 GB on the E-711 binaries), its dc current
is 100 × V (every filter has unit dc gain) and its step response settles to it at
50 µs; a zero root written as the literal 0 and as a parameter set to 0 give the
same differentiator, 0.532018 at 100 kHz against the analytic 0.532018, which is the
known-zero path and the `select` path; a 300-node ladder (904 entries, the -O0
descriptor) compiles in 0.4 s (4.3 s before) and its dc current is 3.01 V over
301 kΩ to eleven digits. The 85 checks of E-405 unchanged.

By hand: the table above; `PHASE_PROF=1` on the 100-filter module — lowering
170 ms (2.4 s before the guards became selects), DAE and derivatives 170 ms, the
descriptor module 0.5 s at -O0 (14 s at -O3 for the 40-filter one); the E-711
compiler's optimised MIR against this one's for the 22 modules of the ten filter
suites: 19 identical modulo value and block numbering, `complexpole_demo` and
`laplace_variants` (parameter roots) differ in 40 and 4 `select`s where diamonds
were, `bad_coeff_net` the same compile error; the run-time benchmark of the
descriptor level above; the ten filter suites; the workspace tests; the sweep.

## What this does not do

- It does not restructure the descriptor helpers into loops, which would let them keep
  -O3 at any size. The entries are heterogeneous (a cache slot, a constant, a resist
  and a react part, an offset form), so a loop needs a uniform layout that the eval
  would have to write; the -O0 path costs nothing measurable and is twenty lines.
- The reciprocal guard of the **runtime-table** interpolation (E-390's
  `fdiv_guarded`) is still a diamond; its tables are capped at 256 knots (E-392).
- The polynomial expansion still emits its instructions for constant roots and lets
  the optimiser fold them (296 000 for 100 twenty-pole filters, 170 ms); a compile-time
  f64 expansion would save that and nothing else.
- The autodiff is as it was; it was never the cost.
- `MAIN_FAST_CODEGEN_ENTRIES` is 256 by measurement (the -O3 descriptor module costs
  0.8 s at 310 entries and 2 s at 620); it is a constant, not an option.
