# Enhancement-505 — a check the pipeline discarded is not a check

```
python3 verify_dropguard.py
```

22 checks, both linear solvers. 11 of them fail without the fix.

## What was wrong

Round 62's findings share a shape that is not the usual missing-guard one. In each
case the check or the side effect **existed and was correct**; something else in
the pipeline removed it, or it recognised only one of two spellings.

### 1. `$stop` was hoisted out of eval

[Enhancement-55](../../enhancements_doc/Enhancement-55.md) marks a return-flag
callback op-dependent when an op-dependent branch controls it, so it stays in the
eval function. A callback under **no** condition is in no such block: its
arguments are constants and nothing else makes it vary, so it stayed
op-*in*dependent and was hoisted into the instance-init split — which runs once at
setup.

A bare `$stop;` was therefore inert. Instrumenting `point_eval_flags` showed
`eval_flags = 0` for the whole analysis, while the same `$stop` under a run-time
condition set flag 8 at the first point. `$finish` only *appeared* to work because
ngspice also tests `FATAL|FINISH` at setup (`osdisetup.c`) — exactly where the
hoisted call had gone.

| form | before | after |
|---|---|---|
| `$stop;` | ran to the end, silently | halts, with a message |
| `begin $stop; end` | ran to the end, silently | halts |
| `if (1) $stop;` | ran to the end, silently | halts |
| `if ($abstime > 3n) $stop;` | halted at 3 ns | unchanged |

**Only `SetRetFlag` is moved.** `Print` was tried and reverted: its arguments are
real values, and an unconditional print whose operands are computed in the init
split does not dominate its new position once the call moves to eval — codegen
then reads a `BuilderVal::Undef` and the compiler aborts. `examples/concat_examples`
crashed outright. An unconditional `$strobe` consequently still runs at init
rather than per evaluation; that needs its operands moved too, which is a larger
change, and it is recorded as an open finding rather than half-fixed here.

### 2. The `$rdist_*` domains were unguarded from the deck

`hir_ty` refuses an out-of-domain constant, but only a literal or a `localparam`;
a `parameter` overridden from the deck reached the RNG untouched. What came back
was not merely odd, it was impossible:

| call | before | after |
|---|---|---|
| `$rdist_normal(seed, 0, -1)` | exactly the **negation** of the `+1` deviate | behaves as `sd = 0` |
| `$rdist_exponential(seed, -1)` | a **negative** deviate | behaves as `mean = 0` |
| `$rdist_poisson(seed, -1)` | a value | behaves as `mean = 0` |
| `$rdist_uniform(seed, 0, -10)` | sampled an inverted range | degenerates to the low bound |

Zero is the projection onto the domain and is a distribution the RNG can actually
produce. The upper bound is raised to the lower one rather than swapping them,
which would be inventing the author's intent.

### 3. The Laplace zero-denominator guard read one spelling

[Enhancement-420](../../enhancements_doc/Enhancement-420.md) refuses a denominator
that is identically zero — by matching `Expr::Array`, the `'{...}` aggregate.
`laplace_*` accepts the `{...}` **concatenation** too and lowers it identically
([Enhancement-399](../../enhancements_doc/Enhancement-399.md) measured that
deliberately), so `{0}` compiled clean and returned a silent **zero** — the
opposite of the division by zero it is. One apostrophe apart, the same split
[Enhancement-457](../../enhancements_doc/Enhancement-457.md) found in `'{4{0}}`
vs `{4{0}}`. A genuine integrator `{0,1}` is still accepted.

### 4. An opvar's name lost to the simulator's

ngspice writes its own instance parameters — `m`, `temp`, `dtemp`, `dt` — into the
lookup table first, so a model declaring an operating-point variable with one of
those names computes it on every evaluation and can never read it back.
`@n1[temp]` returned the ambient temperature, `@n1[m]` the multiplier. Legal
Verilog-A, and nothing said a word.

Named at load time now rather than refused: the rest of the model works, and
refusing would break a model that runs today over a name it never reads.

**Operating-point variables only.** A model may legitimately declare `m` or
`dtemp` as its own instance *parameter* — that is what
[Enhancement-394](../../enhancements_doc/Enhancement-394.md)'s `has_m` exists for,
a CMC-style model scales by its own `m`, and the loader routes the deck's value
into it. Checks [21] and [22] hold that case silent and working; `limguard`
asserts the same thing from the other side.

## Withdrawn

The "branch contributed as both a potential and a flow" warning not firing for
`V(a,b) <+ 0` was reported in round 62 and withdrawn on reading the site: a
literal-zero contribution is a **node-collapse request**, delivered by a
`CollapseHint` callback rather than by the branch's residual, so *"discarding one
discards nothing"*. A decision, not a defect.
