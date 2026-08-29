# Enhancement-505 — a check the pipeline discarded is not a check

Round 62's findings share a shape that is not the usual missing-guard one. In
each case the check or the side effect **existed and was correct**; something
else in the pipeline removed it, or it recognised only one of two spellings.

## 1. `$stop` was hoisted out of eval

Enhancement-55 marks a return-flag callback op-dependent when an op-dependent
branch controls it, so it stays in the eval function. A callback under **no**
condition is in no such block — its arguments are constants and nothing else
makes it vary — so it stayed op-*in*dependent and was hoisted into the
instance-init split, which runs once at setup.

A bare `$stop;` was therefore inert. Instrumenting `point_eval_flags` settled it:
`eval_flags = 0` for the whole analysis, against flag 8 at the first point for the
same `$stop` under a run-time condition. `$finish` only *appeared* to work because
ngspice also tests `FATAL|FINISH` at setup (`osdisetup.c`) — exactly where the
hoisted call had gone.

| form | before | after |
|---|---|---|
| `$stop;` | ran to the end, silently | halts, with a message |
| `begin $stop; end` | ran to the end, silently | halts |
| `if (1) $stop;` | ran to the end, silently | halts |
| `if ($abstime > 3n) $stop;` | halted at 3 ns | unchanged |

### Only `SetRetFlag` moves, and that is deliberate

`Print` was included in the first version and reverted. Its arguments are real
values, and an unconditional print whose operands are computed in the init split
does not dominate its new position once the call moves to eval; codegen then reads
a `BuilderVal::Undef` and the compiler aborts (`mir_llvm/builder.rs:143`).
`examples/concat_examples`, whose `$sformat` machinery this touches, crashed
outright — the regression caught it at suite 59.

A `SetRetFlag` takes no arguments, so relocating one cannot strand an operand.
An unconditional `$strobe` therefore still runs at init rather than per
evaluation — measured at 2 prints across a 146-point transient against 294 for
the conditional form. Moving it safely means moving its operands too, which is a
larger change than this one; it is recorded as an open finding rather than
half-fixed.

## 2. The `$rdist_*` domains were unguarded from the deck

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
produce: a zero standard deviation is the mean with certainty, a zero
exponential/poisson mean is zero with certainty. The uniform upper bound is raised
to the lower one rather than swapping the pair, which would be inventing intent.

## 3. The Laplace zero-denominator guard read one spelling

Enhancement-420 refuses a denominator that is identically zero — by matching
`Expr::Array`, the `'{...}` aggregate. But `laplace_*` accepts the `{...}`
**concatenation** too and lowers it identically, which Enhancement-399 measured
and allowed on purpose. So `'{0}` was refused and `{0}` was not: it compiled clean
and returned a silent **zero**, the opposite of the division by zero it actually
is.

One apostrophe apart — the same split Enhancement-457 found between `'{4{0}}` and
`{4{0}}`. Both the length check and the all-zero check now accept a plain
concatenation as a written-out list. A replication (`{4{0}}`) is left alone for
the length check, whose question it does not answer. A genuine integrator `{0,1}`
is still accepted, and `zi_nd` is covered by the same code.

## 4. An opvar's name lost to the simulator's

ngspice writes its own instance parameters — `m`, `temp`, `dtemp`, `dt` — into the
lookup table before anything the model declared, so a model with an
operating-point variable of one of those names computes it on every evaluation and
can never read it back. `@n1[temp]` returned the ambient temperature and `@n1[m]`
the multiplier. The name is legal Verilog-A and nothing said a word, in the
compiler or the loader.

It is named at load time rather than refused: the rest of the model works, and
refusing would break a model that runs today over a name it never reads.

**Operating-point variables only.** A model may legitimately declare `m` or
`dtemp` as its own instance *parameter* — that is what Enhancement-394's `has_m`
exists for, a CMC-style model scales by its own `m`, and the loader routes the
deck's value into it so nothing is shadowed. The first version warned for both and
`limguard` caught it, which is the check that states this decision from the other
side; the suite here pins it from this side.

## Withdrawn

The "branch contributed as both a potential and a flow" warning not firing for
`V(a,b) <+ 0` was reported in round 62 and withdrawn on reading the site. A
literal-zero contribution is a **node-collapse request**, delivered by a
`CollapseHint` callback rather than by the branch's residual — *"Discarding one
discards nothing"*, as `hir/src/body.rs` puts it. A decision, not a defect, and
the one spelling a model author would use for a short.

## Files

| file | change |
|---|---|
| `openvaf/sim_back/src/context.rs` | a `SetRetFlag` callback is op-dependent in every block, not only op-controlled ones |
| `openvaf/hir_lower/src/expr.rs` | `clamp_non_negative`/`clamp_upper_bound` for the `$rdist_*` arguments |
| `openvaf/hir_ty/src/validation/body.rs` | the filter length and all-zero checks accept a concatenation |
| `ngspice-46/src/osdi/osdiinit.c` | name a shadowed operating-point variable at load time |

## Verification

`examples/dropguard_examples/verify_dropguard.py` — 22 checks under both linear
solvers. 11 fail on the shipped binaries.
