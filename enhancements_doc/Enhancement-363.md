# Enhancement-363 — two openvaf-r compiler crashes from cross-feature fuzzing

A fuzzing campaign against `openvaf-r` (~3400 compiles) found **three defects**,
two of which are fixed here. None involves malformed input: every reproducer is
legal Verilog-A that the shipped compiler answered with *"OpenVAF encountered a
problem and has crashed!"* or a false diagnostic.

---

## Why a new kind of fuzzer was needed

The previous rounds ([Enhancement-213](Enhancement-213.md),
[220](Enhancement-220.md), [230](Enhancement-230.md),
[263](Enhancement-263.md)) all **mutate** the corpus — byte, token, keyword and
bracket injection. Mutation is very good at parser bugs, but almost every mutant
dies at parse time, so HIR lowering, MIR construction, the optimizer and codegen
are barely reached.

This campaign generated **valid-by-construction** programs that *compose*
features which had each been developed and tested in isolation — the ~100
enhancements in this repo. About 40% of generated inputs reach the backend. Both
crashes below are feature *interactions*, invisible to any single-feature test.

A second generator built module **hierarchies** (instantiation, generate/genvar,
bus ports, paramset, defparam), because the first only ever emits standalone leaf
modules and so never touches the elaboration/flatten path at all. It found no
crash in 700 runs — but its *diagnostics* exposed defect 2.

## 1. A block was merged into itself — `mir_opt/src/simplify_cfg.rs`

`simplify_unconditional_jmp_term(src, dst)` merges `src` into `dst`: it retargets
every predecessor of `src` to `dst`, then removes `src` from the layout. It had
no guard for `src == dst`.

A block whose terminator jumps to **itself** (`block2: jmp block2`) is a
self-loop, which is what a `case` inside a `do-while` folds to. The retarget was
then a no-op — every predecessor was already pointing at `dst == src` — and the
block was deleted anyway, while live terminators still named it:

```
block5:
    jmp block2      <-- block2 is not in the layout at all
block1:
    ...
```

`mir_llvm::Builder::new` allocates LLVM blocks only for blocks that **are** in the
layout, so codegen then unwrapped `None`
(`builder.rs:655`/`:656`/`:690`).

The CFG layer already treated this as invalid input: `ControlFlowGraph::replace`
opens with `debug_assert_ne!(old, new)` — exactly the assertion that fires on a
debug-assertions build (`flowgraph.rs:262`). The fix declines the self-merge; a
self-loop is a legitimate CFG shape and must survive to codegen.

**Trigger.** `case`, `casex` or `casez` inside a `do-while`, empty or not.
`if`/`else`, `while`, `for`, `repeat` and a nested `do-while` in the same
position always compiled — pinned in the example so a future change cannot
quietly start rejecting them.

## 2. Array parameters were never instance-renamed — `hir/src/elaborate.rs`

A module has **three** array collections: `buses` (vectored nets/ports),
`var_arrays` (array variables, [E-4](Enhancement-4.md)) and `param_arrays`
(array-valued parameters, [E-14](Enhancement-14.md)). Flattening renamed the
first two per instance and not the third, so every instance re-declared `cf[0]`,
`cf[1]`, … under the same names:

```
error: 'cf[0]' was already declared in this scope
```

So a module with an array parameter **could not be instantiated twice**. The bug
is broader than that framing suggests: two *different* modules that merely shared
an array-parameter name collided as well, and renaming them apart made the error
disappear — which is what identified the cause. Scalar parameters were always
renamed (`x0__g`); array *variables* were fine because `var_arrays` was already
in the chain.

## 3. Non-terminating analog loops — diagnosed, deliberately NOT patched

A provably non-terminating loop — `while (1)`, or the far more ordinary case of
forgetting the increment — still fails to compile.

After fix 1 its MIR is well-formed: the loop is a self-loop, as it should be. But
the contributions *after* the loop are then unreachable, and OSDI codegen reads
values that no reachable block defines.

There is **no correct object code** for such a model — it can never finish a
single evaluation. Emitting the loop faithfully produces a model that hangs the
simulator; substituting zero for the unreachable contributions produces a model
that silently pretends to be a device. The right answer is a compile-time
diagnostic rejecting it, which needs a new check in
`hir_ty/src/validation/body.rs` (and conservative handling of output-argument
calls, which assign indirectly). That is follow-up work: this enhancement does
not trade a loud crash for a silently meaningless model.

The crash is loud, reproducible and only reachable from a model that is already
broken, so leaving it is the safer of the two available states.

## Verification

`examples/vafcfg_examples` is a **proven trigger** — against the shipped compiler
it reports 1/4:

```
FAIL  case inside a do-while compiles  [COMPILER PANIC (exit 101)]
FAIL  array param, module instantiated twice  ['cf[0]' was already declared ...]
FAIL  array param name shared by two modules  ['cf[0]' was already declared ...]
PASS  if/while/do-while inside a do-while still compile
```

and 4/4 with the fixes.

Corpus: **380/380 files produce an identical verdict**, and the optimized MIR is
byte-identical for every one of them. (The `.osdi` binaries are *not* comparable
— the same binary on the same input produces a different hash on each run, so a
`.osdi` diff proves nothing. The MIR dump is deterministic under
`RAYON_NUM_THREADS=1`, which is what makes the equivalence check meaningful.)

`cargo test -p mir_opt -p sim_back --lib`: 33 passed, 0 failed.

Regression 287/287.

## Note on reproducing compiler panics

Panic sites are **nondeterministic** under rayon: the same input reported
`builder.rs:143` or `:690` across runs, because codegen is parallel. Set
`RAYON_NUM_THREADS=1` before minimizing, or the reduction chases a moving target.
