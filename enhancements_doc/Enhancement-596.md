# Enhancement-596: global value numbering compared a call expression with itself

**Scope:** `openvaf/mir_opt/src/global_value_numbering.rs` (the `Opcode::Call` arm of
`GVNExpression::eq`, and the test module wired in), `global_value_numbering/test.rs`
(two regression tests), `examples/gvncall_examples/` (new, 7 checks per solver).
**Compiler only; ngspice is unchanged.** Finding F1 of the 2026-09-10 integration hunt
([`docs/bug_hunts/2026-09-10_ngspice-osdi-integration-second-hunt.md`](../docs/bug_hunts/2026-09-10_ngspice-osdi-integration-second-hunt.md)).

**Suites:** [`gvncall_examples`](../examples/gvncall_examples/) 7 of 7 per solver, both
solvers; `cargo test -p mir_opt` 10 of 10 (the two new tests fail on the old comparison);
full sweep 490 of 490 with the rebuilt compiler.

## What was wrong

A model that read `$simparam("gmin")` without a default and then nine `$simparam` names
with defaults got the **wrong value for the tenth**: `$simparam("vntol", -1)` returned
gmin, `$simparam("reltol", -1)` in the same slot returned gmin too, and the literal
`vntol` was absent from the compiled object. Bisection in the hunt showed it was the
tenth call, only with the no-default form first, and not tied to any name.

The cause is one word in the optimiser. Global value numbering keys every side-effect-free
expression in a hash table so that a repeated computation is replaced by the earlier
value. For a call, the equality test read **both** payloads from `self`:

```rust
let CallExprPayLoad { func_ref: func_ref_1, args: args1 } = self.payload.call();
let CallExprPayLoad { func_ref: func_ref_2, args: args2 } = self.payload.call();   // sic
```

so any two call expressions the table happened to compare were "equal" whatever the
callee and the arguments. The table (hashbrown) compares a candidate only when its
7-bit tag matches in the probed group — about one pair in 128 in a small table — which
is why the defect looked like a threshold: the reproducer's value numbers put the tenth
call's probe on the first call's slot with the same tag, and `v62 = call simparam_opt
("vntol", -1)` was replaced by `v17 = call simparam("gmin")` before codegen. Move the
no-default read, add an unrelated string literal, or take one read away, and the probe
sequence changes and nothing collides.

Every side-effect-free callback is exposed the same way, with the same odds: a `ddx`
derivative (`CallBackKind::Derivative`), a string compare, `$simparam$str`, `%m`,
`$port_connected`, `$param_given`. A compact model that reads a handful of simparams and
compares a string parameter carries a few percent chance, per compile, of one silently
wrong value.

## What changed

- `other.payload.call()` on the second line. The Phi arm already read `other`.
- The GVN test module existed on disk but was never compiled in (`mod test;` was
  missing); it is wired in now and gains two tests: `call_expr_eq_reads_other`, which
  builds two call expressions and checks the comparison directly (different callee,
  swapped arguments, one argument changed: not equal; identical: equal), and
  `distinct_calls_are_kept`, the reproducer's exact value numbering (the collision is
  deterministic under FxHash), which asserts all ten calls survive and every
  `optbarrier` still reads its own call. Both fail on the old line.

## Verification

| check | result |
|---|---|
| the reproducer, ten reads, `.option vntol=1e-5 gmin=3e-11 abstol=7e-13 reltol=2e-3` | the tenth reads 1e-5; the other nine their own values (iteration 3, sourceScaleFactor 1, abstol 7e-13, reltol 2e-3, tnom 27, the unknown name's default 42, the two unserved names −1) |
| `reltol` in the tenth slot | 2e-3 |
| `abstol` as the no-default read, `vntol` tenth | 1e-5, and the no-default read 7e-13 |
| twelve string compares against distinct literals, each `kind` in turn | each literal selects only its own value |
| eight `ddx()` of one expression against eight unknowns | each its own partial, 1 mS to 8 mS |
| the compiled object | carries every simparam name literal |
| `cargo test -p mir_opt` | 10 of 10; the two new tests fail with the old comparison |

Full sweep 490 of 490 on both solvers with the rebuilt compiler.
