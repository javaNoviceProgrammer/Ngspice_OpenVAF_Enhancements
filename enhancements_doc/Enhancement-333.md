# Enhancement-333 — integer division by a literal zero SIGTRAPped the simulator

```verilog
if ((5 / 0) > 0 && ione > 0)   // ione is a parameter
    V(o) <+ 1.0;
else
    V(o) <+ 2.0;
```

openvaf reported success — exit 0, no diagnostic. ngspice then died:

```
ngspice returncode = -5   (SIGTRAP)
output: (empty -- no error message at all)
```

## Root cause

LLVM treats `sdiv x, 0` as **immediate undefined behaviour**: it folds the result to
poison, poison reaching a branch becomes `unreachable`, and `unreachable` lowers to a
`brk`. So the whole enclosing function became a trap instruction, and the first call
into the compiled `.osdi` killed the host process.

The short-circuit `&&` is what made it reachable. With a runtime right operand the
division lands in a conditionally-executed block, where constant folding never
collapses it, so it survives into code generation. The same expression written
without the `&&` folded away instead — which is why this looked harmless.

Every spelling was in fact undefined; only some manifested as a trap. Before the fix
`V(o) <+ (5/0) > 0 ? 1.0 : 2.0;` printed `0`, which is not the value that expression
has — it was poison propagating.

## Why Enhancement-286 left it this way

E-286 fixed a *compiler* crash here: folding `5/0` evaluated the division inside
openvaf and killed it with an internal error. Its fix was to decline to fold, on the
stated reasoning that

> A *runtime* zero divisor has always been accepted, so a literal one must be too.

Both halves of that turn out to be wrong:

- **The literal case is not the runtime case.** Only the literal one leaves a
  constant-zero divisor in the IR, which is the exact thing the optimiser exploits.
  Verified: a `parameter`, a `localparam` and a derived constant (`3 - 3`) are all
  lowered as runtime values, and **none of them traps**. The literal is the whole
  undefined-behaviour surface.
- **Runtime acceptance is target-specific.** AArch64 returns a value for integer
  division by zero; **x86 raises SIGFPE**. This project ships x86 builds for macOS,
  Linux and Windows (and lists riscv64 among its targets), so there is no portable
  value to fold to.

So E-286 turned a compiler crash into a simulator crash, and the premise that would
have justified a value-based fix does not hold.

## The fix — reject it

There is no defensible value, so openvaf now refuses the program instead of emitting
something that cannot be given a meaning:

```
error: integer division by zero
  |
4 |   if ((5 / 0) > 0 && ione > 0)
  |         ----^
  |         |   |
  |         |   divisor is zero
  |         in this integer division
  |
  = help: an integer division or remainder by a literal zero has no value; the
          generated code would trap and take the simulator with it
  = help: a zero divisor that is a parameter or localparam is a runtime value and
          is still accepted
```

The check is **literal-only**, and deliberately so: that is precisely the set of
programs that reach LLVM with a constant-zero divisor. Widening it to any
constant-folded zero would reject working models for no safety benefit.

## Verified

- Every previously trapping or undefined spelling — inside `&&`, inside `||`, `%`
  instead of `/`, and the plain and direct forms — is now a clean exit 65.
- Zero divisors via `parameter`, `localparam` and a derived constant still compile
  **and simulate**, with no signal (`I = V/1k` exactly).
- Ordinary integer division and remainder are unchanged, and IEEE float division by
  zero (`1.0/0.0` → inf) is untouched — the check is integer-only.

## Corpus impact

Across 478 models, **exactly one** changes accept/reject:
`examples/vafcodegen_examples/constfold_divzero.va` — the negative test added by this
change to assert the rejection. No real model divides by a literal zero.

## Enhancement-286's example was updated, not deleted

`constfold.va` asserted that `5/0` and `5%0` compile. That assertion is now wrong, so
those two lines moved to `constfold_divzero.va`, which asserts the diagnostic instead.
E-286's actual invariant — the folder must not die with an internal error — is still
covered there and by the remaining cases (`i32::MIN / -1`, `1 << 40`, wrapping add),
plus a zero divisor reaching the fold path through a localparam.

## Files

- `OpenVAF-master-20260610/openvaf/hir_ty/src/inference.rs` — the literal-zero check
  and `InferenceDiagnostic::DivisionByZero`.
- `OpenVAF-master-20260610/openvaf/hir_ty/src/diagnostics.rs` — the rendered
  diagnostic.
- `examples/vafdivzero_examples/` — the trapping shape is a clean error, `%` likewise,
  non-literal zeros still compile and simulate (`verify_vafdivzero.py`, 5 checks).
- `examples/vafcodegen_examples/` — E-286's example split as described above.
