# Enhancement-97 — clean diagnostic for a contribution to a ground branch (version11)

A crash fix: contributing to a branch that is **entirely the `ground`
reference** — `V(gnd) <+ …`, `V(gnd, gnd) <+ …`, `I(gnd) <+ …` — panicked the
compiler with an internal error ("please open an issue"). It is now a clean,
located diagnostic.

## The bug

`ground` is the fixed 0 reference and has no DAE unknown, so during lowering
its node resolves to `None`. A contribution whose branch is *only* ground
reduces both endpoints to `None`, and
`lower_contribute_unnamed_branch` (`hir_lower/src/stmt.rs`) hit its
`(None, None) => unreachable!()` arm — an ICE — instead of any error:

```verilog
module m(a);
   inout a; electrical a;
   ground gnd; electrical gnd;
   analog V(gnd) <+ 0.0;      // panic
endmodule
```

## The fix

The check belongs in type validation, before lowering. `hir_ty`'s
`ExprValidator` (`validation/body.rs`) already rejects a contribution to a
port branch (`ContributeToPortFlow`); a sibling `ContributeToGround` check now
fires for a *write* whose branch is all-ground — the single-node access
(`V(gnd)`, where the node's `is_gnd` flag is set) and the two-node access
(`V(gnd, gnd)`, both nodes ground). It reports a proper error, so lowering is
never reached and the `unreachable!()` stays unreachable:

```
error: contribution to a ground node
  |    V(gnd) <+ 0.0;
  |    ^^^^^^ this branch is entirely 'ground'
  = help: the potential of 'ground' is fixed at 0, so there is no unknown to
    contribute to; contribute to a real node instead
```

Probing `V(gnd)` (a read) is untouched, and a real node-to-ground branch
(`V(a, gnd) <+ …`, `V(a) <+ …`) is unaffected — only an all-ground *write* is
rejected.

## Verification

- New UI snapshot test `contribute_to_ground` pins the three ground-branch
  errors (`V(gnd)`, `V(gnd, gnd)`, `I(gnd)`) and confirms the node-to-ground
  contribution on the same module is accepted.
- `groundcontrib_examples` (5/5): a valid node-to-ground source drives its node
  (`v(p) = 1.5`); `V(gnd) <+ 0` is rejected with the ground diagnostic and
  **no** ICE banner; `V(a, gnd) <+ 1` is not a false positive.
- Full regression: 87 verify suites + 28 integration tests; `hir` snapshot
  tests green.

Found while confirming Enhancement-96 (a malformed test drove the ground node);
independent of the generate work.
