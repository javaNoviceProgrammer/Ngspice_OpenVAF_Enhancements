# Enhancement-455 — a guard, and the spelling next to it

Seven defects from a round-46 sweep of openvaf-r. They share one shape: a check
that exists, and a neighbouring spelling of the same mistake that walks straight
past it.

## Indexing a scalar crashed the compiler

```
$ openvaf-r m.va          //  real r;  ...  d = r[0];
OpenVAF encountered a problem and has crashed!
To help us fix the problem, please open an issue at https://github.com/...
```

Exit **101** for an ordinary typo. `infere_bit_select` resolves the base, finds
it is not a bus or array, and returns `None` — but on the path where the base
*does* resolve and simply is not indexable it pushed **no diagnostic at all**.
The expression's type became `Err` and `hir/src/body.rs:381` then hit
`panic!("invalid HIR: path .. was not resolved")`.

A targeted sweep bounds it exactly: every scalar kind (real, integer, string,
scalar parameter) × every index form (`[0]`, `[i]`, `[0][0]`) — fifteen
combinations in expression position and the same fifteen as assignment targets.
Array bases were always fine.

## The value guards were literal-only

`const_num` — which every value guard is built on — folded a literal and a unary
minus and nothing else. So each guard caught exactly one spelling:

```
white_noise(-1e-18)    ->  refused
white_noise(0-1e-18)   ->  ACCEPTED, and produced exactly the output noise
                           of the positive power, silently
```

The same gap let `$bound_step(1-1)`, `transition(x,0,0-1n,1n)`,
`slew(x,0-1e6,-1e6)`, `idtmod(x,0,2-2)` and `@(cross(e, 3+4))` through. It was
not even consistent within the compiler: the array-bounds and integer-division
checks fold first and **do** catch `arr[2+3]` and `1/(1-1)`.

`const_num` now folds constant `+ - * /` as well.

**A parameter is deliberately still not folded.** Its default may be overridden
on the instance or model card, so refusing a model for a default that will never
be used would be wrong — the same reasoning that keeps a parameter's default out
of its own range check. A control pins that.

## Reversed ranges spelled with `inf` were invisible

`from (5:1)` is refused. `from (inf:0)` — one transposition away from
`from (0:inf)` — was accepted, and the parameter then enforced **nothing**:
`p = -5`, `0` and `5` all pass a range that admits no value. The author asked
for a guard and silently got none.

`inf` is a **literal token** (`LiteralKind::Inf`), and the bound folder had no
case for it, so it gave up on any range mentioning `inf`. Folding it is strictly
better rather than riskier: `from (0:inf)` has lo < hi and stays accepted,
exactly as before. All six `inf` spellings of a reversed range are now caught,
and a range that is accepted still enforces its bound at run time.

## A constant outside a function's domain said nothing

```verilog
d = sqrt(-1.0);   // compiles with zero warnings
```

and the model then fails at simulation with *"Transient op failed, timestep too
small"* — a convergence message for a NaN written literally in the source.
Integer `1/0` and `5 % 0` have always been compile errors; the same mistake in a
real-valued call was silent. `sqrt`, `ln`, `log`, `asin`, `acos`, `acosh` and
`atanh` now report a constant argument outside their domain. A **run-time**
argument is left alone — that is the model's own business.

## Three declarations the LRM forbids

* **`$rdist_uniform` with reversed bounds** returned exactly what the correct
  ordering returns. LRM 9.13.2: *"The start value shall be smaller than the end
  value."*
* **An analog function with no arguments** compiled and returned its value. LRM
  4.7.1: a function *"shall have at least one formal argument declared"*.
* **A discipline naming one nature for both `potential` and `flow`** compiled,
  and the device it produced contributed **nothing** where its well-formed twin
  gave the right answer — and a node voltage of **−999** when a contribution was
  forced. The two `NatureRef`s carry different `kind`s, so they never compare
  equal as a whole; it is the *name* that has to match.

## The fix

| file | change |
|---|---|
| `hir_ty/src/inference.rs` | `NotIndexable` diagnostic on the resolve-but-not-an-array path |
| `hir_ty/src/diagnostics.rs` | its rendering |
| `hir_ty/src/validation/body.rs` | `const_num` folds constant arithmetic; math-domain and `$rdist_uniform` checks |
| `hir_def/src/item_tree/lower.rs` | `inf` folds as a range bound; zero-argument function; potential == flow |
| `hir_def/src/item_tree.rs`, `item_tree/diagnostics.rs` | the two new item-tree diagnostics |

## Verification

**`examples/valguard_examples` — 113/113** under both solvers, and **82/113 on
the previous compiler**, where the 31 failures are exactly the defect checks
while every control passes on both.

Because this enhancement adds new compile-time **rejections**, the decisive
check is that it rejects nothing real: the whole 124-model corpus compiled with
both drivers to the same output path gives **107 compiled by both, 17 rejected
by both, 0 rc differences, 0 byte differences**. `cargo test` passes with zero
failures across 47 test binaries. Full regression **369/369**, both solvers.

**One pinned expectation moved, deliberately.** Enhancement-421's
`rangeguard_examples` pinned `from [0:inf) exclude [0:inf)` as *clean*, and its
own label said why: *"`inf` does not fold, as E-399 leaves it"* — it recorded the
folding limitation, not a wanted behaviour. That range excludes every value it
allows, which is exactly what the check exists to report, so it is now pinned as
rejected, with two new checks either side proving a *partial* exclude over an
infinite range (`exclude [0:5]`) and a bare `from [0:inf)` still compile. That
suite is 74/74. The regression caught this on the first sweep — the fix was
verified against it rather than around it.

## Three findings withdrawn, and one left for a decision

Re-verifying each finding against full compiler output before writing any code
retired three of them:

* **unknown `analysis()` / `@(initial_step("..."))` names** are already reported
  — `warning[L021]`, from Enhancement-399. The round-46 probe counted event
  firings and never looked at the compile output.
* **an unrecognised `(* type="..." *)`** is already reported — *"unknown type
  ... expected "model" or "instance""*.
* **a real literal that underflows to zero** is a documented decision, stated in
  `syntax/src/validation.rs`: *"Underflow is left alone too: `1e-320` is a
  denormal and `1e-400` is 0.0, both of which IEEE 754 defines and neither of
  which destroys the rest of the computation."*

And one finding is **not fixed here**, deliberately. Two `white_noise()` calls
sharing a name label are combined as *perfectly correlated*, so renaming a
source from `"s2"` to `"s1"` inflates total output noise by exactly √2. The LRM
text points the other way — the name is *"a label ... used when the simulator
outputs the individual contribution"*, combined *"in the noise contribution
summary"*, and §4.6.4.6 says *"Each noise function generates noise which is
uncorrelated with the noise generated by other functions"*. But same-name
correlation is a **deliberate ngspice decision from Enhancement-42**,
implemented consistently in both `osdinoise.c` and `osditrnoise.c` and citing
LRM 4.6.4. Reversing it would change the physics of every model that relies on
it, so it is a design question rather than a defect to fix quietly.

Three further findings are also unfixed and are recorded for later: an
out-of-range array index from a variable or parameter is silently discarded on
write and returns element 0 on read (a real bounds check belongs at run time, in
codegen); an analog function's local read before assignment retains state across
evaluations, so its result depends on solver effort; and an integer literal above
`INT_MAX` silently clamps. Each needs a wider change than the evidence here
supports.
