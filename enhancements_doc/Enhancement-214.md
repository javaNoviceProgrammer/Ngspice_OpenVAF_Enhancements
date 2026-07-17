# Enhancement-214 — whole-array type coercion: a recurring crash class, fixed at its root

Some bugs are found once. This one was found **four times**, in four different corners
of the compiler, and fixed four times — because each fix landed on the symptom rather
than the cause. This enhancement fixes the last two instances, and then removes the
trap that kept producing them.

The symptom is always the same: an **integer** Value reaches a **float** MIR op
(`feq`/`fmul`/`fsub`/`fdiv`), and `mir_opt::const_eval::eval_binary` has no
`(Int, Float)` case for it, so the compiler panics —

```
invalid operation fdiv Int(1) Float(Ieee64(1.0))
OpenVAF encountered a problem and has crashed!
```

— exit 101, with the usual invitation to file a bug report. If constant propagation
happens *not* to fold the expression, the very same defect instead survives to codegen
and reaches LLVM as `i32 = fadd .., ConstantFP:f64`, aborting with **`LLVM ERROR:
Cannot select`**. One bug, two faces, depending on an optimization that has nothing to
do with it.

Like [E-213](Enhancement-213.md), none of this requires exotic input. The trigger is
writing `{1}` where a real is expected — which is simply how a unity coefficient or a
small selector is naturally written.

## The four instances

| # | Where | Fixed in |
|---|-------|----------|
| 1 | `case` over an **integer array** — the array element type was hardcoded real, so an `feq` landed on i32 | [E-33](Enhancement-33.md) |
| 2 | `laplace_*`/`zi_*` integer-**literal** coefficients: `laplace_nd(V(in), {1}, …)` | `b77266ec` |
| 3 | `laplace_*`/`zi_*` integer **array-variable** coefficients | `c55812d6` (here) |
| 4 | An integer `case` **item** against a **real** array discriminant | `8d0ab057` (here) |

Instance 3 is a good illustration of how a symptom-level fix propagates the problem.
The fix for instance 2 cast integer-literal coefficients to real but *explicitly
excluded* the array-variable path, with this reasoning recorded in a comment:

> a whole-array *variable* reference is already real by its declaration, so the var-ref
> path needs no cast

That is false for an **integer** array:

```verilog
integer c[0:0];
analog begin
    c[0] = 1;
    V(out) <+ laplace_nd(V(in), c, '{1.0, 1e-6});   // panicked
end
```

Its element reads are i32 and hit exactly the mixed-type MIR the earlier fix set out to
prevent. Coefficient vectors are real per LRM 9.19; the var-ref path is now coerced
from the variable's declared type, and the comment corrected.

Instance 4 comes from the opposite direction — a real discriminant with integer items:

```verilog
real r[0:0];
analog begin
    r[0] = 1.0;
    case (r)
        {1}: g = 7.0;      // panicked: invalid operation feq Int(1) Float(..)
        default: g = 1.0;
    endcase
end
```

The comparison opcode is chosen from the **discriminant**'s type — `Feq`, for a real
array — but the item's integer elements lower to i32.

## The root: a cast that was silently dead

Type inference is not at fault here. It *does* record the coercion: `expect()` inserts
a cast for the offending array, `casts.insert(item, Array{Real})`. The problem is
**where** that cast lands and **who** reads it.

The cast is recorded on the **array expression**. But every whole-array consumer goes
through `hir_lower`'s `lower_array_elems_impl`, and that function **decomposes the
array and lowers each element itself** — it never routes the array expression through
`lower_expr`, which is the only place that consults `needs_cast()`. So the cast was
never applied. It was **dead**, and nothing reported that.

That is why the bug kept coming back. Each new context that consumed a whole array
inherited a trap that was invisible at the call site, and each was patched locally as
it was discovered. The fix is at the chokepoint every consumer already passes through:

```rust
// openvaf/hir_lower/src/expr.rs
let coerce_real = coerce_real
    || matches!(self.body.needs_cast(expr), Some((_, dst)) if *dst.base_type() == Type::Real);
```

Inference's intent is now effective for **every** consumer, present and future, instead
of requiring each call site to remember to ask. Verified in isolation: with the
`case`-site flag disabled, this guard **alone** fixes every `case` repro.

The explicit `coerce_real` flag is kept, for a reason worth stating: it serves
consumers whose element type is fixed by *the language* rather than by an inferred
cast. A `laplace_*`/`zi_*` coefficient vector is real per LRM 9.19 and
`infere_laplace` records **no** cast for it, so there is nothing for the structural
guard to honour there. `lower_case` likewise keeps its own coercion tied to its opcode
(`discr_op == Opcode::Feq`) — choosing the opcode from the discriminant makes matching
the operand types *that function's own invariant*, independent of inference's
bookkeeping. The two mechanisms are complementary, not redundant.

## Verification — coercion that does not miscompile

A compiles-without-crashing test would pass even if the coercion silently changed a
coefficient, so the suite checks meaning, not just survival.

The same first-order filter is compiled twice — once with the integer spelling `{1}`,
once with `'{1.0}` — and swept over 13 AC points from 1 kHz to 10 MHz:

| | worst deviation |
|---|---|
| integer **literal** `{1}` vs real `'{1.0}` | **0 dB** (bit-identical) |
| integer **array variable** vs real `'{1.0}` | **0 dB** (bit-identical) |
| integer-coefficient filter vs analytic `1/(1+jωτ)` | 3.4e-08 dB |

The integer `case` item still **matches**: the arm is taken (`g = 7`, not the default
`1`), giving a current identical to the `'{1.0}` spelling. Valid code is unaffected —
real coefficients, real array variables, real/integer/string scalar cases, and E-33's
element-wise real array case all behave exactly as before.

**Mutation-tested.** A guard that cannot fail is worth nothing, so the fixes were
reverted in a scratch build and the repros re-run against it: all four crash again with
exit 101. The suite catches every instance of the class.

## Verification guards hardened

Two suites were sharpened during the same hunt, each with a blind spot that could hide
exactly the kind of defect it was meant to catch:

- **`vafautodiff_examples`** (8 → 16 checks). The suite held every builtin's second
  argument constant, so it never exercised that argument's chain rule — precisely where
  [E-185](Enhancement-185.md)'s `hypot` bug lived. Added a cross-derivative referee
  (both arguments live circuit unknowns, read off the off-diagonal AC Jacobian) at
  asymmetric bias points, since `hypot`'s wrong rule was accidentally *correct* at
  `x == y`; plus a 44-point battery, as the old suite used a single point per builtin.
  Re-injecting E-185's bug makes it fail at 50% on both partials.

- **`operator_examples`** (+14 checks). Every check used **literal** operands, so it
  exercised only the constant folder. But [E-37](Enhancement-37.md)'s `>>` bug was a
  *disagreement* between the folder and the runtime path — a literals-only test
  exercises just the side that happened to be broken. Each operator is now computed
  twice, once folded and once through `$rtoi(V(in))` so it cannot be folded, and the
  two are compared. Breaking only the runtime path leaves the old check passing while
  the new one fails with score 9.

## Scope

openvaf-r only, two files (`hir_lower/src/expr.rs`, `hir_lower/src/stmt.rs`). No
accepted program changes meaning: every fix is on a path that previously aborted the
compiler, and the generated OSDI for every existing model is identical — the full
example suite compiles and simulates unchanged. Toolchain tests pass. New
`examples/arraycast_examples` (23 checks, both solvers). Full regression: 174/174.

If a fifth instance ever appears, the question to ask first is whether the context
bypasses `lower_array_elems_impl` (reading variables directly, say), and whether
inference records a cast for it at all.
