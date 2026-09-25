# Enhancement-714: a large OSDI descriptor module runs LLVM's -O1 middle end before the fast instruction selector — E-712 had built it at -O0 outright, and a 2 mm transmission line's transient (511 Jacobian entries) ran 2 % slower on the unoptimised helpers than on the -O3 descriptor; now within 0.4 %, the compile time unchanged, because the -O3 pipeline's SLP vectoriser is superlinear in the helpers (17 s at 6 200 entries)

**Scope:** a follow-up to [E-712](Enhancement-712.md), found while checking a
user's photonic transmission-line model (`fp_amf_tline_m2_gsg_1310`, 511 Jacobian
entries) against circuit theory. **Compiler only.** `osdi/src/lib.rs`
(`MAIN_FAST_PIPELINE`, the descriptor module's creation and emission, the
`OPENVAF_MAIN_PIPELINE` hook), `mir_llvm/src/lib.rs` (`ModuleLlvm::run_passes`).
[`examples/filterforms_examples/`](../examples/filterforms_examples/) (5 checks, 100 in
all).

**Suites:** `filterforms` 100 of 100 (97 of 100 on the E-713 binaries), `arrayscale`
38 of 38, `cubic_table`, `tablearray`, `evtedge`, `langguard` 132 of 132, `vafcrash2`,
`complexpole`, `lrmfilters` and `noise` unchanged; the compiler workspace tests green
apart from the three pre-existing sourcegen drift failures, no build warnings; full
sweep, run alone.

## What was wrong

E-712 moved the descriptor module — the `load_jacobian_*`, `load_residual_*`,
`load_spice_rhs_*` and `write_jacobian_array_*` helpers, one memory operation per
Jacobian entry in straight-line code — to -O0 above 256 entries, because two LLVM
backend passes were quadratic in such a block, on the reasoning that the helpers are
memory-bound copies whose code quality does not change with the level. That was
right about the backend and wrong about the middle end: at -O0 no middle-end pass
runs either, and the helpers as the code generator emits them carry a chain of
`getelementptr` per entry that the -O3 pipeline had been folding. For the 511-entry
line, `load_spice_rhs_tran` was 6 016 instructions with 2 645 address computations
against 4 567 and 1 071 after a middle end; `load_jacobian_resist` 3 207 against
2 521. The simulator calls these helpers on every Newton iteration.

Measured on the same ngspice with the model compiled by the E-711 compiler (the -O3
descriptor) and by the E-713 one (the -O0 descriptor), the difference is small and
consistent, CPU time over interleaved repetitions:

| transient | E-711 descriptor | E-713 descriptor |
|---|---|---|
| RC charge, 130 000 points | 5.16 s | 5.28 s, +2.3 % |
| 1 V step, 60 000 points | 2.45 s | 2.50 s, +2.1 % |
| RC charge, 260 000 points, 7 repetitions | 7.83 s | 8.00 s, +2.1 % |

The line's eval is a linear network, so the helpers are an unusually large share of
its work; a compact model with real physics in its eval sees less, and a file below
256 entries — every compact model in the integration set — was never on this path.
E-712's own run-time benchmark had reported no measurable difference, but its four
runs were within 1.5 % of each other.

The results are not the concern: on that model the -O0 descriptor gave the dc and ac
outputs byte for byte, and eight samples of 160 000 in three transients differed
by one unit in the ninth printed digit, the helpers' sums reassociated differently
by the -O3 pipeline (they carry LLVM's `reassoc` flag).

## What changed

**The descriptor module is created at the requested level and, above
`MAIN_FAST_CODEGEN_ENTRIES`, runs the `default<O1>` pipeline before its target
machine is swapped for a -O0 one** (`LLVMBackend::set_codegen_level`, the E-713
mechanism for an eval with a giant block), so its object code still comes out of the
fast instruction selector, which is linear, while its middle end folds the address
arithmetic and the repeated loads. `ModuleLlvm::run_passes` takes a pass pipeline
string as `opt -passes=` does; `optimize` is the module's own level through it.

**Why -O1 and not the requested -O3.** The -O3 pipeline is superlinear in these
helpers: its SLP vectoriser took 3.5 of the 4.4 s of a 5 000-entry descriptor and
17 of 18 s at 6 200 entries — the 100-filter module of E-712's table went from 1.6 s
to 18 s — and the vector code it produces goes through the fast selector worse than
scalar code (+1.6 % on the line's transient). The -O1 pipeline has no vectoriser and
is linear here: 67 ms for 511 entries, 0.4 s for 3 004, 0.6 s for 5 000, 0.75 s for
6 200. E-710's SLP switch is process-wide and stays as it is.

**Measured** on the line, CPU time of a 260 000-point transient over seven
interleaved repetitions, against the E-711 -O3 descriptor at 7.83 s:

| descriptor middle end, then the fast selector | transient | 100-filter compile |
|---|---|---|
| none (E-713) | +2.1 % | 1.60 s |
| `default<O1>` (this enhancement) | +0.4 % | 1.58 s |
| `sroa`, `early-cse`, `instcombine` | +1.9 % | 1.59 s |
| `default<O3>` | +1.6 % | 18.2 s |

The descriptor module is built on the main thread while the eval modules compile on
the worker threads, so its 0.75 s at 6 200 entries is hidden: the 100-filter module
compiles in 1.58 s (1.60 s before), the 1 000-node ladder in 1.20 s (1.21 s), the
1 000-idt module in 0.98 s (0.70 s: its eval is the small one). The line compiles in
0.16 s (0.14 s), its `.osdi` is 159 KB (212 KB), and its dc, ac, step-tail and RC
outputs are byte-identical to the E-711 compiler's; the two transient files that
differed in the ninth digit still do.

**`OPENVAF_MAIN_PIPELINE`** names another pipeline for a large descriptor module
(`default<O0>` reproduces E-713, `default<O3>` the table's last row), a diagnostic in
the manner of E-712's `OPENVAF_LLVM_ARGS`; and `PHASE_PROF=1`'s line for the main
module says `(fast isel)` when the path was taken.

## Verification

`filterforms` section "Enhancement-714": the 300-node ladder (904 entries) reports
the fast instruction selector in its phase profile and its `load_jacobian_resist` has
907 address computations, one per entry (2 712 on the E-713 binaries, and 2 712 with
`OPENVAF_MAIN_PIPELINE=default<O0>`, which the third check uses to show the hook
selects the pipeline); a 60-node ladder (184 entries) reports no fast selector and
draws 0.61 V over 61 kΩ to eleven digits. The 95 checks of E-405 and E-712
unchanged, the 100-filter module at 1.6 s and 0.56 GB.

By hand: the tables above; the four pipelines through the hook on the line and the
three big descriptors of E-712's table, one compile at a time under a 12 GB
watchdog; `opt -O3 -time-passes` on the dumped 5 000-entry descriptor, which named the
SLP vectoriser; the line's six bench decks (dc sweep, current-source dc, ac 1 MHz to
1 THz, step, 30 GHz sine, RC charge) compiled through the E-711, E-713 and this
compiler and compared byte for byte; the helper functions' instruction counts from
`--dump-ir`; the ten suites; the workspace tests; the sweep.

## What this does not do

- It does not change `MAIN_FAST_CODEGEN_ENTRIES` (256) or the eval's
  `EVAL_FAST_CODEGEN_BLOCK` path, whose middle end already ran at the requested
  level.
- It does not make the -O0 and -O3 descriptors bit-identical: the helpers' sums carry
  `reassoc`, and the -O1 pipeline reassociates them as the -O3 one did, so the
  last-digit differences against E-713 move to the same two files that differ
  against E-711. Dropping the flags would be a separate change.
- It does not restructure the helpers into loops, which would let them keep -O3 end
  to end (E-712's note stands).
- The remaining 0.4 % is within the measurement's noise; the fast selector's
  register assignment is what it is.
