# Enhancement-510 — an LRM function that crashed the compiler, and four smaller misreports

Round 66 fuzzed 2089 constant-folded expressions through the compiler. Exactly two
crashed — and they crashed for *every* argument.

## `ln1p` and `expm1` crashed the compiler, always

```
internal error: entered unreachable code: intrinsic log1p not found
```

`Opcode::Ln1p` and `Opcode::Expm1` lower to the libm routines `log1p`/`expm1` —
the LRM lists these apart from `ln`/`exp` precisely for their precision near
zero, and the builder's own comment says so. The intrinsic **registry never
declared either name**, so `cx.intrinsic("log1p")` returned `None` and codegen hit
its own `unreachable!`. Both spellings, in every context tried — plain assignment,
noise power, `initial_step`, an operating-point variable, inside `ddt`.

The static diff is exact. Three libm names are requested by the builder:

| requested in `builder.rs` | declared in `intrinsics.rs`? |
|---|---|
| `hypot` | yes — through a special-case branch ([Enhancement-288](Enhancement-288.md)) |
| `log1p` | **no** |
| `expm1` | **no** |

`hypot` compiles in every form, which is what confirmed the diff rather than a
guess.

### Why it survived

[Enhancement-458](Enhancement-458.md) added these functions and tests them as
`$ln1p(0.5)` — a **literal**, which is constant-folded before codegen, so the
intrinsic is never emitted. A `parameter` or a probe reaches codegen; a literal
does not. That single distinction is why a completely broken builtin passed its
own suite. Checks [3]–[8] use both kinds deliberately.

Through [Enhancement-500](Enhancement-500.md)'s `pre_osdi -va` path the user saw
`openvaf-r failed (exit 25856)` followed by a misleading
`Unable to find definition of model mm`.

## Four smaller misreports, fixed alongside

**A deep `localparam` chain was refused as "not a compile-time constant".** The
fold recursion bound counts *parameter hops* and stopped at 32, so a 32-link chain
inside a compile-time table was refused — while the same chain used as an ordinary
value worked at any depth, and nested arithmetic was unaffected at any depth. The
bound exists to stop runaway recursion, not to decide what counts as a constant;
it is 512 now, in both folders, which must accept the same set
([Enhancement-508](Enhancement-508.md)).

**A folded `atanh` disagreed with the same call at run time.** For a *negative*
argument approaching −1, Rust's `f64::atanh` loses accuracy where the run-time
(libm) path is exact:

| x | folded rel. error (before) |
|---|---|
| −0.9999 | 2.1e−14 |
| −0.99999 | 1.1e−12 |
| −0.999999 | 4.6e−12 |
| −0.9999999 | **1.3e−10** |

Positive arguments were already exact. `atanh` is odd, so the negative side folds
through the accurate positive side.

**`pre_osdi -va` printed a wait status as an exit code.** `system()` returns a
wait status, so the compiler's 101 was reported as **25856** (101 << 8). The
comment at that site quotes *"exit 512"* as if it were an exit code — the same
encoding, gone unnoticed. Decoded now, and a signal death is named as such.

**Every resistor `.model` card reported a bogus parameter error:**

```
Error on .model mm : parameter (r) is not a number this parser accepts ...
```

The first token of a `.model` card is the model **type**, and ngspice's resistor
model has a parameter named `r`, so `.model mm r` and `.model mm res` matched the
type token as a parameter and the value check fired on what followed. The
simulation was right and the message was not — on every resistor model card in
every deck, and on the shipped binary.

`first_tok` already existed for exactly this collision — it gates the
duplicate-parameter warning a few lines above — and the value checks added by
[Enhancement-507](Enhancement-507.md) and
[Enhancement-509](Enhancement-509.md) simply never consulted it. A genuinely
unparsable value on a model card is still refused; check [21] holds E-507's
contract.

## Recorded, not fixed

**Constant folding loses the sign of zero.** `1.0/ceil(-0.5)` is `+inf` folded and
`-inf` at run time; the same for unary minus applied to a zero. The constant
interner is bit-exact (`Ieee64` keys on raw bits) and `eval_unary` folds `ceil`
correctly, so the loss is further down the constant emission path and I could not
place it.

Rewriting `Fneg` as `0 - x` — which *is* unsound for `+0.0`, since IEEE gives
`-(+0.0) = -0.0` but `0.0 - 0.0 = +0.0` — was tried and **reverted**: a constant
operand never reaches that arm (`eval_unary` folds it first), so the change fixed
nothing and only removed an optimisation. Shipping it would have looked like a fix
without being one. Recorded as open, the way
[Enhancement-505](Enhancement-505.md) recorded the unconditional `$strobe`.

**An operating-point variable co-printed with a swept vector** is rendered against
row 0 while holding the *last* point's value, with the remaining rows blank. The
scalar itself is [Enhancement-412](Enhancement-412.md)'s deliberate snapshot; only
the rendering misleads, and the fix belongs in the print path rather than here.

## Withdrawn at fix time

Round 66 also reported that a run-time out-of-range array index silently returns
element 0. The lowering site documents that decision in full: element 0 is
*"DELIBERATE and load-bearing"*, the select chain exists precisely so that an
out-of-range index can never read out of bounds, and both returning NaN and
splitting the parameter case from the variable case were considered and rejected —

> Splitting the two would leave the same operation judged by two different rules,
> which is the drift this project keeps having to undo.

That pre-rejects exactly the fix this enhancement would otherwise have written.

## Files

| file | change |
|---|---|
| `openvaf/mir_llvm/src/intrinsics.rs` | declare `log1p` and `expm1` |
| `openvaf/mir_opt/src/const_eval.rs` | fold `atanh` of a negative argument through its odd symmetry |
| `openvaf/hir_ty/src/validation/body.rs` | fold recursion bound 32 → 512 (two sites) |
| `openvaf/hir_lower/src/expr.rs` | the same bound, kept in step |
| `ngspice-46/src/frontend/com_dl.c` | decode the compiler's wait status |
| `ngspice-46/src/spicelib/parser/inpgmod.c` | the model TYPE token is not a parameter |
| `examples/lrmintrin_examples/` | new suite |

## Verification

`lrmintrin_examples` — **21 checks, both linear solvers**. On the shipped binaries
only **13 of them can run at all** (the compiler crash prevents the rest) and
**4 pass**. Full regression **424/424**.
