# Enhancement-327 — `ddx` unknowns that are not a bare `Param` (shipped crash)

From the seven-strategy fuzz campaign. `ddx` lowering assumed its *unknown*
argument always lowers to a bare MIR `Param`, and unwrapped one unconditionally:

```rust
let call = if signature == DDX_POT {
    // TODO how to handle gnd nodes?              <-- the TODO was the bug
    let node = self.ctx.unwrap_node(unknown);
    CallBackKind::NodeDerivative(node)
} else {
    CallBackKind::Derivative(self.ctx.dfg().value_def(unknown).unwrap_param())
};
```

That assumption is false. `LoweringCtx::nodes` can yield three shapes:

| unknown | lowers to | old behaviour |
|---|---|---|
| `V(a,b)`, `V(a)` — forward-oriented | a `Param` | fine |
| `V(b,a)` — reverse-oriented, or a probe whose *high* side is ground | **`fneg(param)`**, an instruction | **panic** |
| `V(gnd)` — ground only | **`F_ZERO`**, a constant | **panic** |

Both panics (`Value is not a parameter`, `mir/src/dfg/values.rs`) crashed the
**shipped** compiler on legal input.

## Compile, don't reject

Both extra shapes have an unambiguous derivative, so the right fix is to compile
them:

- `V(b,a)` denotes the *same branch* with the opposite reference direction, i.e.
  `V(b,a) == -V(a,b)`, so `∂f/∂V(b,a) == -(∂f/∂V(a,b))`.
- Ground is not an unknown of the DAE system, so `∂f/∂V(gnd) == 0` — which is
  exactly what the backend already does for a derivative callback that never
  became an unknown.

Erroring instead would also be arbitrary: openvaf already accepts `V(a,b)` as a
ddx unknown (an extension beyond the LRM's single-net/branch-flow rule, announced
by its own `L011` lint), and having accepted `V(a,b)` it cannot coherently reject
`V(b,a)`.

## The fix

Peel an `fneg` off the unknown (recording that the result must be negated), then
ask — rather than assert — whether what remains is a parameter:

```rust
let mut negate = false;
let mut probe = unknown;
if let Some(inst) = self.ctx.dfg().value_def(probe).inst() {
    if let InstructionData::Unary { opcode: Opcode::Fneg, arg } = self.ctx.dfg().insts[inst] {
        negate = true;
        probe = arg;
    }
}
match self.ctx.dfg().value_def(probe).as_param() {
    None => F_ZERO,                       // not an unknown -> derivative is 0
    Some(param) => { /* … callback …; negate the result if we peeled an fneg */ }
}
```

with a non-panicking `ParamKind::pot_node()` replacing `unwrap_pot_node()` on the
`DDX_POT` path, and a `LoweringCtx::param_kind()` accessor so lowering can inspect
a user-supplied unknown instead of asserting its shape.

## Verified numerically, not just "it compiles"

Differentiating `V²` (exact derivative `2V`) at `V = 3`, scaled by 1 mS:

| unknown | expected | measured |
|---|---|---|
| `V(a,b)` | −6 mA | `-6.00000e-03` |
| `V(b,a)` | +6 mA (exact negative) | `+6.000000e-03` |
| `V(gnd)` | 0 (only the 1e-9 leak) | `-3.00000e-09` |

The reverse case is the exact negative of the forward case to machine precision,
and the ground case contributes precisely zero.

## Output preservation

The new code diverges from the old only when `value_def(unknown)` is **not** a
`Param` — which is precisely the case that previously reached `unwrap_param()` /
`unwrap_node()` and panicked, producing no output at all. When the unknown *is* a
`Param` (every model that compiles today) the `fneg` peel does not fire and the
callback construction is unchanged, so there is nothing to preserve in the
diverging case and nothing to change in the converging one. Confirmed against the
corpus with the deterministic `--dump-mir` oracle.

## Follow-up — the methods this replaced were left behind

Switching `ddx` lowering from asserting to asking left the old panicking pair with
no callers: `LoweringCtx::unwrap_node` (`ctx.rs`) and its only callee
`ParamKind::unwrap_pot_node` (`lib.rs`). They were removed afterwards.

Worth recording *how* that was missed. The tree is audited warnings-clean, and
`cargo` does not re-emit warnings for a crate it does not recompile — so every
incremental build after this change stayed silent, and the two `dead_code`
warnings only appeared on a **clean** build of `hir_lower`.

Behaviour is unaffected by construction: the methods had no callers, so nothing
could invoke them. Checked after the removal — 0 warnings, 0 errors, and the
`ddx` examples still hold to the closed form (forward `d/dV(V²) = 2V` → −6 mA,
the reverse orientation its exact negative, a ground unknown exactly 0, and the
higher-order chain `3V²`/`6V`/`6` at V = 2 → −12/−12/−6 mA). The corpus-wide
`--dump-mir` A/B was **not** run to completion for this removal and no such
claim is made here.

## Files

- `OpenVAF-master-20260610/openvaf/hir_lower/src/expr.rs` — the `ddx` arm.
- `OpenVAF-master-20260610/openvaf/hir_lower/src/ctx.rs` — `param_kind()`.
- `OpenVAF-master-20260610/openvaf/hir_lower/src/lib.rs` — `ParamKind::pot_node()`.
- `examples/vafddxunknown_examples/` — the two crashing shapes compile and their
  derivatives are checked against the closed form
  (`verify_vafddxunknown.py`, 4 checks).
