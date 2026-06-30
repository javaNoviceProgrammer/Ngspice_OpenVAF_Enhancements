# Enhancement-2 — Indirect Branch Assignment support in OpenVAF (version3)

This document describes every source-code change made to **OpenVAF** in the
`version3/` directory, on top of `version2/` (Enhancement-1, `absdelay`), to
implement Verilog-AMS **indirect branch assignment**. It was produced by
diffing `version2/OpenVAF-master` against `version3/OpenVAF-master`.

The goal of Enhancement-2 is to make the Verilog-AMS construct

```verilog
<lhs_access>(<branch>) : <rhs_access>(<branch>) == <expr> ;
```

compile and simulate correctly end-to-end (DC, AC, transient) through the
OSDI flow. The canonical motivating example, taken directly from the LRM
(Accellera Std VAMS-2023, p. 114), is an **ideal op-amp**:

```verilog
module opamp(out, pin, nin);
    inout out, pin, nin;
    electrical out, pin, nin;
    analog
        V(out):V(pin,nin) == 0;
endmodule
```

Before this change, OpenVAF's parser rejected the `:` token here:

```
error: unexpected token ':'; expected ';'
  --> opamp.va:9:15
  |
9 |         V(out):V(pin,nin) == 0;
  |               ^
```

Unlike Enhancement-1, this change is **entirely confined to OpenVAF**
(parser → AST → HIR → HIR lowering). No ngspice/OSDI changes were needed —
see [§6](#6-why-no-backendosdi-changes-were-needed).

---

## 1. The idea (how indirect branch assignment is modeled)

Indirect branch assignment introduces **one new free unknown** `u` per
statement, plus **one new implicit equation** that solves for it:

| Quantity | Meaning |
|---|---|
| `u` | a fresh DAE unknown, contributed into the LHS branch exactly like a normal `<+` contribution |
| residual | `constraint_lhs - constraint_rhs = 0`, where `constraint_lhs == constraint_rhs` is the RHS of the statement |

For `V(out):V(pin,nin) == 0;`:
- `u` is contributed into the `out` branch **as a voltage contribution**
  (`V(out) <+ u`), because the LHS access function is `V`. This reuses
  OpenVAF's existing voltage-source stamping path, which already augments the
  DAE with the auxiliary current unknown a voltage source needs (the same
  mechanism behind plain `V(br) <+ expr;`) — nothing new had to be built for
  that half.
- The residual equation enforces `V(pin,nin) - 0 = 0`, i.e. it solves `u`
  (the now-ideal output voltage) for whatever value makes the input pins
  equal — exactly the nullor behavior of an ideal op-amp.

This is conceptually the same "new unknown + new implicit equation" DAE
pattern Enhancement-1 used for `absdelay` (see
`version2/.../hir_lower/src/expr.rs`, `BuiltIn::absdelay`), except:
- Enhancement-1 needed **two** implicit equations per call (`AbsDelayInput`,
  `AbsDelayOutput`) plus a runtime/OSDI contract because the second equation
  was stamped by **ngspice** (it needs a time-domain delay history).
- Enhancement-2 needs only **one** implicit equation per statement, and it is
  stamped entirely by **OpenVAF** at compile time — both halves (the branch
  contribution and the residual) are ordinary algebraic MIR, so no new OSDI
  export or ngspice-side code was required.

---

## 2. OpenVAF changes

9 source files touched, all under `openvaf/{parser,syntax,hir_def,hir_ty,hir,hir_lower}`.

### 2.1 `openvaf/parser/src/grammar/stmts.rs` — accept `:`

`assign_or_expr()` previously only accepted `<+` (contribute) or `=`
(assign) after the LHS expression. Added `T![:]` to the accepted
`TokenSet`; the `:` token already existed in the lexer (used for ternary
`?:`, case labels, array ranges), so no lexer change was needed.

```rust
if p.eat_ts(TokenSet::new(&[T![<+], T![=], T![:]])) {
```

### 2.2 `openvaf/syntax/veriloga.ungram` + `src/ast/{node_ext,expr_ext}.rs` — new `AssignOp` variant

- `veriloga.ungram`: `Assign` rule's operator alternatives extended to
  `('<+' | '=' | ':')`.
- `node_ext.rs`: new `AssignOp::IndirectBranch` variant; `Assign::op()`
  recognizes `T![:]`.
- `expr_ext.rs`: the parallel (currently unused outside this enum)
  `AsssigmentOp` got a matching `IndirectBranch` arm in `op_details()`, for
  consistency.

The generated AST node `Assign { syntax }` carries no per-operator fields
(the operator is read directly off the raw syntax node), so no AST codegen
regeneration was required — only the two hand-written extension files above.

### 2.3 `openvaf/hir_def/src/body/lower.rs`, `src/expr.rs` — no change

`hir_def::Stmt::Assignment { dst, val, assignment_kind }` already carries
`assignment_kind: ast::AssignOp` opaquely, so it picks up the new variant for
free. For the indirect form, `dst` is the LHS access expression (`V(out)`)
and `val` is the **entire** RHS expression after `:` — i.e. the equality
expression `V(pin,nin) == 0`, parsed as one ordinary `==` `BinaryOp` (the
expression grammar already understood `==`; nothing new needed there).

### 2.4 `openvaf/hir_ty/src/inference.rs` — validate & decompose the constraint

This is where most of the new logic lives.

- New `InferenceResult::indirect_branch_constraints: AHashMap<StmtId, (ExprId, ExprId)>`
  — for an indirect-branch `StmtId`, the decomposed `(lhs, rhs)` operand
  `ExprId`s of its `==` constraint.
- `Ctx::infere_stmt`'s `Stmt::Assignment` arm now special-cases
  `assignment_kind == AssignOp::IndirectBranch`: it still calls
  `infere_assignment_dst` (unchanged dst-resolution logic — `V()`/`I()`
  branch access detection is identical to the `Contribute` path), but routes
  `val` through a **new** method instead of the generic `infere_assignment`:

  ```rust
  fn infere_indirect_branch_constraint(&mut self, stmt: StmtId, val: ExprId, dst_ty: Option<Type>)
  ```

  This requires `val` to be a top-level `Expr::BinaryOp { op: Some(BinaryOp::EqualityTest), lhs, rhs }`.
  If it isn't, a new diagnostic `InferenceDiagnostic::IndirectAssignRequiresEquality { e }`
  is emitted (e.g. `V(out):V(pin,nin) <+ 0;` or `V(out):1;` are rejected with
  a clear error instead of a generic type mismatch or a panic). If it is, both
  operands are type-checked against `dst_ty` (`Type::Real`, same rule as a
  normal contribution) and recorded in `indirect_branch_constraints`.

  Crucially, the constraint operands are inferred **individually** — `val`
  itself (the whole `==` expression, whose value type is boolean-like) is
  never type-checked against the branch-access `Real` type, which is what a
  naive reuse of `infere_assignment` would have done and incorrectly
  rejected.

- The `(dst, assignment_kind)` operator-compatibility match gained an arm so
  `(AssignDst::Var | AssignDst::FunVar, AssignOp::IndirectBranch)` is
  rejected with the existing `InvalidAssignDst` diagnostic (you can't use
  `:` on a plain variable), grouped with the existing `Contribute` rejection.

### 2.5 `openvaf/hir_ty/src/diagnostics.rs` — error reporting

- `InvalidAssignDst` report: added `AssignOp::IndirectBranch` arms to both
  the primary-message match and the `maybe_different_operand` hint match
  (e.g. "found a branch access, perhaps you meant an indirect branch
  assignment (:)").
- New report arm for `IndirectAssignRequiresEquality`: *"invalid indirect
  branch assignment ... help: indirect branch assignment requires a
  constraint of the form `<access> == <expr>`"*.

### 2.6 `openvaf/hir/src/body.rs` — new `Stmt::IndirectContribute`

- New HIR statement variant:

  ```rust
  Stmt::IndirectContribute {
      kind: ContributeKind,
      branch: BranchWrite,
      constraint_lhs: ExprId,
      constraint_rhs: ExprId,
  }
  ```

- `BodyRef::get_stmt`: when `infere.indirect_branch_constraints` has an
  entry for the statement, emits `Stmt::IndirectContribute` (mapping
  `AssignDst::Flow`/`Potential` to `ContributeKind::Flow`/`Potential`,
  exactly like the existing `Contribute` path); otherwise falls through to
  the unchanged `Stmt::Assignment`/`Stmt::Contribute` logic.

### 2.7 `openvaf/hir_lower/src/lib.rs` — new implicit equation kind

- New `ImplicitEquationKind::IndirectBranch(u32)` — one per indirect branch
  assignment slot; its residual row enforces `constraint_lhs == constraint_rhs`.
- New `HirInterner::indirect_branch_equations: Vec<ImplicitEquation>` — slot
  index → implicit equation, parallel to Enhancement-1's
  `absdelay_equations` but a 1-tuple per slot instead of a pair (only one
  equation is needed here).

### 2.8 `openvaf/hir_lower/src/stmt.rs` — lowering

- **Refactored** `contribute()` (used for plain `V/I(br) <+ expr;`) into a
  thin wrapper around a new value-based primitive:

  ```rust
  fn contribute_value(&mut self, voltage_src: bool, write: BranchWrite, rhs: Value, is_zero: bool)
  ```

  `contribute_value` contains the exact same branch-stamping logic
  `contribute()` had (unnamed-branch resolution, `IsVoltageSrc` place,
  collapse-hint call, accumulating the `Contribute` place) but takes an
  already-lowered MIR `Value` instead of an `ExprId`. `contribute()` now just
  lowers its `rhs` expression and calls `contribute_value` — behavior for
  ordinary `<+` statements is unchanged (verified by the unmodified
  `absdelay`/regression test suite, see [§7](#7-testing--verification)).

- New `indirect_contribute()`:

  ```rust
  fn indirect_contribute(&mut self, voltage_src: bool, branch: BranchWrite,
                          constraint_lhs: ExprId, constraint_rhs: ExprId)
  ```

  1. Allocates one implicit equation: `(eq, u) = self.ctx.implicit_equation(ImplicitEquationKind::IndirectBranch(idx))`.
  2. Contributes `u` into `branch` via `contribute_value(voltage_src, branch, u, false)`
     — i.e. literally `V(branch) <+ u` or `I(branch) <+ u`, reusing the exact
     same backend stamping path (and its automatic auxiliary-unknown
     augmentation for voltage contributions) as a normal contribution.
  3. Lowers `constraint_lhs` and `constraint_rhs`, builds
     `residual = lhs - rhs`, and calls `self.ctx.def_resist_residual(residual, eq)`
     — the same `ImplicitEquation`/residual primitives Enhancement-1 used for
     `eq_y` in `absdelay`.

- `lower_stmt` dispatches the new `Stmt::IndirectContribute` to
  `indirect_contribute`, alongside the existing `Stmt::Contribute` arm.

---

## 3. Diff summary (version2 → version3)

| File | Kind of change |
|---|---|
| `openvaf/parser/src/grammar/stmts.rs` | accept `:` as a 3rd assignment operator |
| `openvaf/syntax/veriloga.ungram` | grammar: `Assign` op alternatives |
| `openvaf/syntax/src/ast/node_ext.rs` | new `AssignOp::IndirectBranch` + `Assign::op()` |
| `openvaf/syntax/src/ast/expr_ext.rs` | matching `AsssigmentOp::IndirectBranch` |
| `openvaf/hir_ty/src/inference.rs` | new constraint map, new inference method, new diagnostic, operator-compat match |
| `openvaf/hir_ty/src/diagnostics.rs` | error report text for the two new/extended diagnostics |
| `openvaf/hir/src/body.rs` | new `Stmt::IndirectContribute` + dispatch in `get_stmt` |
| `openvaf/hir_lower/src/lib.rs` | new `ImplicitEquationKind::IndirectBranch`, new interner field |
| `openvaf/hir_lower/src/stmt.rs` | `contribute()` refactor + new `contribute_value`/`indirect_contribute` |

No changes to `openvaf/hir_def`, `openvaf/mir*`, `openvaf/sim_back`, or
`openvaf/osdi` — see next section for why.

---

## 4. New diagnostics

| Diagnostic | When |
|---|---|
| `InvalidAssignDst` (extended) | `:` used on a non-branch-access LHS (e.g. a plain variable) |
| `IndirectAssignRequiresEquality` (new) | RHS of `:` is not a top-level `==` expression (e.g. `V(out):1;` or `V(out):V(pin,nin) <+ 0;`) |

Both produce a normal compiler error with a source span and a help note,
not a panic.

---

## 5. Why no backend/OSDI changes were needed

Both halves of an indirect branch assignment lower to mechanisms the
backend (`sim_back`) and the OSDI exporter already handle generically:

1. The branch contribution (`contribute_value`) produces exactly the same
   `PlaceKind::Contribute` / `PlaceKind::IsVoltageSrc` outputs as a literal
   `V(br) <+ expr;` would — `sim_back::topology` doesn't know or care
   whether the contributed value came from a lowered expression or a fresh
   implicit unknown.
2. The constraint residual uses the exact same `ImplicitEquation` /
   `PlaceKind::ImplicitResidual` mechanism as `absdelay`'s `eq_y` — already
   wired all the way through `sim_back/src/topology/lineralize.rs` and the
   OSDI Jacobian/residual export.

This was confirmed empirically: the generated MIR for the op-amp example
(`openvaf/test_data/mir/indirect_branch.mir`) shows the implicit unknown
flowing straight into the `Contribute` place and the residual into the
`ImplicitResidual` place with no special-casing required, and the compiled
`.osdi` simulates correctly (§7) without touching a single line in
`sim_back` or `osdi`.

---

## 6. Build

```bash
cd version3/OpenVAF-master
cargo clean
LLVM_SYS_181_PREFIX=/opt/homebrew/opt/llvm@18 \
  cargo build --release --bin openvaf-r --features openvaf-driver/llvm18
cp target/release/openvaf-r ../bin/macos/apple-silicon/openvaf-r
```

(`--features openvaf-driver/llvm18` is required — `mir_llvm`/`openvaf-driver`
have no default LLVM version feature, see their `Cargo.toml`.)

---

## 7. Testing & verification

### 7.1 Compiler unit / snapshot tests
- `cargo test -p syntax -p hir_def -p hir_ty -p hir -p hir_lower` — all
  existing fast tests pass unchanged (no regression in plain `<+`/`=`
  contributions, `absdelay`, case statements, etc).
- New MIR snapshot test `openvaf/test_data/mir/indirect_branch.va` /
  `.mir`, exercising the op-amp example end-to-end through
  `hir_lower::MirBuilder`. The generated MIR confirms the unknown is
  contributed to the `out` branch and the residual is `V(pin,nin) - 0`.

### 7.2 End-to-end compile
`version3/opamp.va` (the LRM example, using
`` `include "disciplines.vams" `` — resolved by OpenVAF's built-in stdlib,
no `-I` needed) compiles to a working `.osdi` with zero errors/warnings.

### 7.3 ngspice simulation — new feature
`version3/indirect_assignment_examples/` — a unity-gain buffer built from the
op-amp (`nin` tied to `out`), simulated with `version3/bin/.../ngspice`:
- **DC** sweep −2V…2V: `V(out) == V(pin)` exactly.
- **AC** 1kHz…1GHz: flat 0 dB gain, 0° phase (ideal, infinite bandwidth).
- **Transient** 1MHz sine: `V(out)` tracks `V(pin)` with no lag.

PNG plots of all three are in that folder (`dc.png`, `ac.png`, `tran.png`).

### 7.4 Regression — Enhancement-1 (`absdelay`)
`version3/absdelay_examples/` recompiled (`absdelay.va` → `.osdi` with the
new `openvaf-r`) and re-run (DC/AC/transient, KLU vs SPARSE):
DC and transient bit-identical between solvers, AC differs only by ~2e-15
(floating-point roundoff) — matching the documented Enhancement-1 baseline.

This confirms indirect branch assignment support introduced no regressions
in the existing `absdelay`-based models or the broader OSDI/ngspice
pipeline.
