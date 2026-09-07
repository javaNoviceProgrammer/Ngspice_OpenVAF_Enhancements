# Enhancement-579: a branchless `select` in MIR, table-driven OSDI parameter access, and negative zero through the constant folder

**Scope:** two compiler findings of the 2026-09-07 hunt
([`docs/bug_hunts/2026-09-07_openvaf-r-language-semantics.md`](../docs/bug_hunts/2026-09-07_openvaf-r-language-semantics.md),
F3 and F4). New MIR instruction `select` (`openvaf/mir/src/instructions.rs`,
`instructions/generated.rs`, `builder/generated.rs`, `write.rs`; `openvaf/mir_reader`),
handled by the optimiser (`mir_opt/src/{simplify,const_prop}.rs`), automatic
differentiation (`mir_autodiff/src/{builder,live_derivatives}.rs`), the interpreter, the
LLVM backend (`mir_llvm/src/builder.rs`, also the store-placement fix there) and the
simulator back-end's topology passes (`sim_back/src/topology/{lineralize,builder,small_signal_network}.rs`);
used by the lowering for dynamic array reads and writes, retained-variable
initialisation and plain parameter defaults (`hir_lower/src/{expr,stmt,state,parameters}.rs`).
Table-driven OSDI access and given-query functions (`osdi/src/{access,given}.rs`, with
the per-parameter bit helpers they replaced removed from `bitfield.rs`, `inst_data.rs`,
`model_data.rs`), and `-O0` setup modules above 1024 parameters (`osdi/src/lib.rs`).
The constant table no longer aliases −0.0 (`mir/src/dfg/values.rs`). Each parallel
codegen closure owns its LLVM target-data object (`osdi/src/lib.rs`). A stale
`sim_back` parameter-info snapshot regenerated. `examples/run_regression.py` keeps a
failing suite's output under `examples/_failures/` (ignored by git). **OpenVAF-r only.**

**Suites:** new [`arrayscale_examples`](../examples/arrayscale_examples/) (29 checks);
full sweep 478 of 478 (476 of the earlier 477 plus this suite, all unchanged). Compiler
crate tests 104 of 104 (`mir`, `mir_opt`, `mir_autodiff`, `mir_interpret`, `mir_reader`,
`sim_back`, `hir_lower`, `hir`, `openvaf` with `llvm18`); the debug build's LLVM IR
verifier passes on the new functions.

| 10,000-entry array, compile time | before | after |
|---|---|---|
| model array parameter, static reads | 71 s | 4.2 s |
| model array parameter, dynamic read | 68 s | 4.3 s |
| instance array parameter | 375–410 s | 5.9 s |
| local array written in a loop each evaluation | 68 s | 26 s |

## F3 — the constant table normalised −0.0 to +0.0

`DfgValues::new` inserted `-0.0` into the real-constant map as an alias of `F_ZERO`
("normalize to plus zero for consts"), so every fold that produced a negative zero —
`-0.0`, `0.0 * -1.0`, `fneg` of a zero constant — came back as +0.0: `1.0/(-0.0)` folded
to +inf and `atan2(0.0, -0.0)` to 0, while the run-time path gave −inf and π. `Ieee64`
keys the map on the bit pattern, so removing the alias makes the two zeros two
constants; the simplifier's `== F_ZERO` tests (`x * 0 → 0`, `0 / x → 0`, `x - 0 → x`)
then match only the positive zero, which is exactly the one they are valid for. The
MIR crate tests and the full sweep are unchanged.

## F4 — compile time quadratic in an array's length

Profiling a 10,000-entry array (`sample` on the compiler, then `--dump-mir` block
counts and `--dump-unopt-ir` function sizes) found not one cause but a chain of them,
every link the same shape: **one or more CFG blocks per array element**, on which the
SSA construction, the MIR CFG simplifier and LLVM's dominator, scheduling and
register-allocation work are superlinear.

1. **A dynamic array read or write** (`tab[k]`, `tab[k] = v`) lowered to one
   `make_select` per element — a three-block `if` diamond and a phi — so a 2,000-entry
   read was a 4,000-block function and the SSA builder resolved each element variable
   through every diamond before it.
2. **Retained variables** (`hidden state`) were initialised with the same diamond,
   one per variable; an array of N elements is N variables.
3. **Parameter initialisation** in the setup function was a diamond per parameter
   (`given ? checked value : default`), and an array parameter is one OSDI parameter
   per element.
4. **The OSDI access function** was a `switch` with a case per parameter, each case
   carrying its own `if (write) set given bit` diamond: three blocks per parameter,
   32,000 IR lines for 2,000; **the given-query function** (Enhancement-555) nested a
   three-way `switch` in each case: four blocks and 18 lines per parameter, 66,000
   lines.
5. With all of that removed, a 10,000-parameter setup function is one straight-line
   block of 100,000 instructions, on which LLVM's instruction selection and register
   allocation are still superlinear.

**The `select` instruction.** MIR had no branchless conditional value; every choice
was a branch and a phi. `InstructionData::Select { args: [cond, then, else] }`
(opcode `select`, 3 operands, 1 result, 16 bytes like every other instruction) is
handled everywhere an instruction kind is dispatched on: operand access, hashing and
equality, printing and parsing; the simplifier (a constant condition or equal operands
fold); sparse conditional constant propagation (a known condition copies one operand's
lattice value, an unknown one is overdefined unless both operands agree on a
constant); dead-code and value numbering (kept as-is); the interpreter; the LLVM
backend (`LLVMBuildSelect`); automatic differentiation (`d select(c, a, b) =
select(c, da, db)`, the condition carries no derivative, and the reachability walk
traverses it like any pure instruction); and the simulator back-end's three topology
passes, where a select is treated as a phi whose control dependence is its condition —
linear when the condition is fixed at the operating point, an equation when it moves.
The lowering uses it for dynamic array reads and writes (1), retained-variable
initialisation (2) and parameter defaults that are plain — a literal, a parameter or
`+ - *` of those, with no `from`/`exclude` — so both candidates can be computed up
front (3); a default with a call, a division or a conditional, or a bounded parameter,
keeps the diamond and is evaluated only when not given.

**What the first attempt got wrong.** The parameter store site is an `optbarrier`
whose value the setup wrapper writes back into the parameter slot, positioned "before
the terminator" of the value's block. The branchless init put the value in the setup
function's exit block, which has no terminator yet, so `select_bb_before_terminator`
placed the store *before* the value: the verifier reported "Instruction does not
dominate all uses" (the release build crashed in LLVM's scheduler instead), and with an
earlier value it stored the default over a given value — every given parameter was
silently lost. The builder now positions at the block's end when its last instruction
is not a terminator. The parameter probes (`pt.va`, `pg.va`, `rng.va`, `sp.va`, `nc.va`
from the hunt) and the `osdiplumb`, `paramgiven` and `paramarray` suites pin all of it.

**Table-driven access.** The parameter storage is a struct field per parameter at a
fixed byte offset, so `access(id)` is now `base + OFFSETS[id]` with the offsets in a
constant table computed from LLVM's data layout, and the given bit (word `id/32`,
mask `1 << id%32`, the layout `bitfield` uses) is set with a branchless masked OR;
the given-query function addresses the bitfield word arithmetically and is ten
blocks for any parameter count. Both functions are 72 and 59 IR lines whether the
module has two parameters or ten thousand. The opvar half of the access function
keeps its switch: opvars are few and heterogeneous. The per-parameter bit helpers
this replaced were deleted.

**Setup modules at −O0.** The two setup functions run once per model and once per
instance, so their code quality is irrelevant while their size is proportional to the
parameter count. Above 1024 parameters they are generated at `-O0` (FastISel, no
middle-end passes), which is linear; the evaluation, access and given functions keep
the requested level, and every ordinary compact model (the largest CMC models have a
few hundred parameters) is compiled exactly as before. The threshold is load-bearing:
with the table-driven access function but a fully optimised setup, the 10,000-entry
instance array ran for 53 minutes before it was killed — LLVM's full pipeline on a
100,000-instruction block is worse than the diamonds were. Measured on either side of
the threshold, an instance array of 500 entries compiles in 1.2 s and one of 1,000 in
2.9 s at the requested level, one of 1,100 in 0.3 s and one of 2,000 in 0.6 s at −O0.
The threshold stays at 1024 rather than lower so that BSIM4-class models (about 800
parameters) keep byte-identical setup code.

**A race the rewrite exposed.** The first sweeps after the table-driven access function
failed two or three suites each, a different set every time, always on one solver of the
two: the compiler itself died with SIGSEGV on a compile that passed standalone and passed
seventy times under an eight-way process load. The cause was inside one compile: LLVM's
`DataLayout` memoises struct layouts in a cache that is not thread-safe, every
`LLVMABISizeOfType` and `LLVMOffsetOfElement` on a struct type goes through it, and the
four codegen closures of a module run in parallel on the one target-data object the
driver created — a latent race that the access function's one query per parameter,
issued from a worker thread while the main thread sized the descriptor, widened enough
to hit. Each closure now creates its own target data from the layout string and drops
it when done. So that the next such failure leaves something to read, the sweep runner
now writes a failing suite's full output to `examples/_failures/<suite>.log` and says
so under the totals.

**What remains.** A local array of 10,000 elements rewritten in a loop on every
evaluation still costs 26 s: LLVM optimising a 10,000-phi loop in the evaluation
function, which cannot be compiled at a lower level. The dynamic-write chain is one
`select` per element per statement, which is the minimum for a value-only IR.

## Verification

`arrayscale_examples` pins the F3 values (−inf, −inf, −inf, π against the run-time
path), the shapes (one-block setup and evaluation functions for a 2,000-entry dynamic
read, only the loop's blocks for a 2,000-element loop write with one `select` per
element, access and given-query functions under 200 and 120 IR lines and identical for a
two-parameter module), generous wall-clock bounds for 10,000-entry model and instance
arrays, and the semantics: per-element overrides on the model card and the instance
line, `$param_given` per element, a dependent default, a bounded instance parameter, a
dynamic write landing on the indexed element only, an out-of-range read yielding
element 0, `alter`/`altermod` of array elements, and a `select` feeding a contribution
whose AC conductance is the selected element.
