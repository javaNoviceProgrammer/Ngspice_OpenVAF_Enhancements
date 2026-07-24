# Enhancement-317 — openvaf-r: `idt` initial-condition in a dead branch crashed codegen

Found by grammar-based analog-operator fuzzing (the E-307…E-314 campaign family). An `idt()`
with an initial condition — `idt(x, IC)` or `idtmod` — placed inside a statically-false branch
crashed the shipped compiler.

## The bug

```verilog
x = idt(V(a), 0);
if (ceil(0) > 1)          // always false, but ceil() is NOT const-folded
    w = idt(V(a), 0);     // dead branch: w's idt initial-condition state is never used
I(a,b) <+ x;
```

`ceil(0) > 1` is always false, but the front end does not const-fold `ceil()`, so the dead
branch survives into MIR. Because `w`'s `idt` initial-condition state is never used, codegen
prunes the branch **condition's computation** as dead — yet the `Branch` instruction itself
survives into the derived `osdi::setup::setup_instance` function. When `build_func` reaches that
branch and reads its condition, the condition's `BuilderVal` is still `Undef`, and
`BuilderVal::get` hit `unreachable!("attempted to read undefined value")` (`mir_llvm/builder.rs:143`)
— a **shipped crash** (release aborts with exit 101 and an `openvaf-crash-*.log`).

Only `idt`/`idtmod` (integrator accumulator *state* with an initial condition) triggered it;
`ddt`, `absdelay`, `transition`, `slew`, `laplace_*`, and a bare `idt(x)` with no IC are all
clean. This is the E-52/263/307 (analog-operator-state) neighbourhood but a distinct
control-flow/SSA defect. It is the same `Undef`-value class as Enhancement-308 (which handled the
*phi-input* case); this is the *branch-condition* case.

## The fix

When a `Branch`'s condition is `Undef`, lower it as a constant `false` instead of crashing. The
branch only guards dead code (the unused idt-IC state init), so the guarded path never executes
on either edge — feeding `false` is observationally equivalent and avoids emitting an undefined
`br`. Verified corpus-bit-identical.

## Verification

`examples/vafidtcfg_examples/verify_vafidtcfg.py` — the reproducer compiles (it crashed the
shipped compiler before) and reduces to a plain integrator that simulates correctly; the whole
419-model corpus produces byte-identical MIR before and after (the fix only changes an
otherwise-crashing dead-branch condition).

## Scope of change

`openvaf/mir_llvm/src/builder.rs`, the `Branch` case of `build_inst` only.

## Not fixed here (deferred, from the same hunt)

Two findings from this fuzz round are left for dedicated changes:

- **PHI type mismatch (openvaf-r, assertions-only).** Reading an uninitialized *integer*
  variable through a ternary materialises its default as `F_ZERO` (an `f64` `0.0`), so codegen
  emits a phi with an `i32` result and one `f64` operand — the LLVM verifier (a `debug_assert`,
  off in release) rejects it. The shipped release compiles it and folds both edges to `0`, so
  the numeric output is correct; the fix is a deep change to how integer hidden-state defaults
  are typed and is deferred to avoid regression risk on that path.
- **`.tran` convergence livelock (ngspice).** A specific fuzzer-generated OSDI device (a tiny
  `1e-15` capacitor plus a clamped `exp` diode, `tanh`, and noise) makes a `.tran` livelock —
  the timestep freezes and ngspice never aborts with "timestep too small". It is a real
  robustness gap in the timestep controller, but pinning and fixing it safely requires dedicated
  convergence-engine work and is deferred.
