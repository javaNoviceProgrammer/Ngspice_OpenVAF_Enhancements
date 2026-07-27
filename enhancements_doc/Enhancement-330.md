# Enhancement-330 — `ddx` in a runtime loop hung the compiler forever

The last of the seven shipped crashes from the diverse-strategy fuzz campaign, and
the only one that was an infinite loop rather than a panic:

```verilog
real x; integer i;
analog begin
    x = 0.0; i = 0;
    for (i = 0; i < 1; i = i + 1) x = ddx(V(a)*x, V(a));   // compiler never returns
    V(a,b) <+ x;
end
```

## Root cause — a fixpoint that grows its own lattice

`live_derivative_fixpoint` (`mir_autodiff/src/live_derivatives.rs`) asks, for every
derivative already live at a `ddx` call, for one of **order + 1** via
`raise_order_with`. That is fine on a DAG: the order chain is bounded by the number
of `ddx` sites on the longest path.

A loop back edge closes the circuit. The differentiated expression `V(a)*x` depends
on `x`, which is the loop-carried phi fed by the `ddx` result itself, so:

1. round *n* creates derivative order *n+1* and interns it;
2. `populate_reachable` marks it reachable at that instruction;
3. the live set changed, so the argument's defining instructions are re-queued;
4. the back edge carries the new order around the phi and back into the `ddx`'s own
   input — and round *n+1* begins.

A monotone fixpoint terminates because its lattice is *fixed*. Here **the fixpoint
grows the very lattice it iterates over**, so it has no fixed point.

Measured, not inferred: `sample` puts **99.8 %** of 3944 samples in that one call
chain (`raise_order_with` → `TiSet::ensure` → `IndexMap::insert_full`), resident
memory climbs monotonically and never plateaus, and the process was still running
after 15 minutes with no output. This is true non-termination, not slowness.

## The correct answer is a clean error, not a cap

`ddx` is **symbolic and memoryless** — openvaf computes it as a derivative callback
on the MIR, and its result is determined by the *shape* of its argument. Inside a
runtime loop, `x = ddx(V(a)*x, V(a))` asks for a different symbolic form on every
trip: iteration *k* needs `dᵏ/dV(a)ᵏ`, and the trip count is not a compile-time
constant. **There is no finite MIR that implements it** — which is exactly why the
fixpoint diverges instead of converging to something wrong. It is ill-formed, not
legal-but-unbounded.

That is also what the language already says, and what this compiler already does
for every *other* analog operator. `ddx` is classified as an analog operator by
openvaf itself (`hir_def/src/builtin.rs`, `is_analog_operator()`), and LRM 4.5.1
forbids analog operators in non-genvar loops:

```
for (...) x = ddt(V(a));        -> error: analog operator 'ddt' is not allowed in loops
for (...) x = idt(V(a)*x);      -> error: analog operator 'idt' is not allowed in loops
for (...) x = ddx(V(a)*x, V(a));-> hung forever
```

The divergence came from one explicit escape hatch in
`hir_ty/src/validation/body.rs` — `_ if call.is_analog_operator() && call != BuiltIn::ddx`.
That exemption is **correct for conditionals**: the industry CMC corpus has 192
`ddx` call sites inside `if` bodies across 19 models (BSIM-BULK, BSIM-SOI, HICUM,
ASM-HEMT, L-UTSOI, …). It is simply too broad — it also covers loops.

## The fix

Track runtime-loop nesting and reject `ddx` there, reusing the existing
`IllegalCtxAccess` diagnostic (so this is an ordinary compile error, exit 65 — no
new machinery):

```
error: analog operator 'ddx' is not allowed in loops
  = help: analog operators are not allowed inside looping statements (LRM 4.5.1)
  = help: hoist the operator out of the loop, or unroll the loop with `generate`
```

A separate `loop_depth` counter is required rather than reusing `ctx`:
`validate_condition_in` *replaces* the context instead of stacking it, so an `if`
nested in a `for` resets it to `Conditional`; and it only becomes `Loop` when the
controlling expression is non-constant, so `repeat(3)` would slip through.

Trigger surface (each verified): `for`, `while` and `repeat` all hung, as did a
`ddx` under an intervening `if` and one routed through a second variable. The
multiplication is *not* essential — `ddx(V(a)+x, V(a))` hangs too. The precise
condition is *the argument depends on the differentiation unknown **and** on the
`ddx` call's own result through a back edge*.

## Scope — stated plainly

`ddx` outside a loop is untouched, including inside `if`/`else`, and is still
numerically exact there (`d/dV(V²) = 2V` → −6 mA at V = 3). A corpus scan of 514
models finds **0 of 755** `ddx` call sites inside a loop body, and the MIR oracle
reports no corpus model changed.

This is nonetheless the one fix in this series that **slightly narrows the accepted
language**: a loop containing a `ddx` with *no* self-reference — e.g.
`for (...) g = g + ddx(V(a)*V(a), V(a));` — compiles today and now errors. It is
absent from the corpus, the rejection is LRM-conformant, and it is exactly the
treatment `ddt`/`idt`/`transition`/`laplace_*` already receive; but it is not
strictly output-preserving and is not claimed to be. Keeping it would require
front-end dataflow that can distinguish "self-referential" from "not", which the
validator does not have.

## Separately discovered, not fixed here

While bounding the derivative order, a **second shipped crash** surfaced: 65 nested
`ddx` calls panic in `lib/bitset/src/lib.rs` — *"index out of bounds: the len is 1
but the index is 1"* — via `HybridBitSet::contains`, reached from
`populate_reachable`. A row that has gone dense keeps the word count it had at that
moment, so once the derivative universe grows past 64 (one word) a query on the new
index panics. It is independent of loops and of this fix, and is left for a
dedicated change.

## Files

- `OpenVAF-master-20260610/openvaf/hir_ty/src/validation/body.rs` — the
  `loop_depth` counter and the `ddx`-in-loop arm.
- `examples/vafddxloop_examples/` — the hanging shape is now a prompt error citing
  the LRM, and `ddx` outside a loop still compiles *and* stays exact
  (`verify_vafddxloop.py`, 4 checks).
