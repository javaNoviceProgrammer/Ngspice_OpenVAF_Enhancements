# Enhancement-561: `{…}` of scalar integers is the LRM 4.1.13 bit-level concatenation wherever a scalar is expected

**Scope:** F12 (the "bit-level concatenation and replication of integers" gap) of
the [coverage audit of *A Practical Guide to Verilog-A*](../docs/audits/2026-09-05_practical-guide-verilog-a-coverage.md)
§3.2. The literal accessor (`openvaf/syntax/src/ast/expr_ext.rs`), the HIR body
(`openvaf/hir_def/src/{body.rs,body/lower.rs}`), type inference and its diagnostics
(`openvaf/hir_ty/src/{inference,diagnostics}.rs`), the body accessor
(`openvaf/hir/src/body.rs`) and the lowering (`openvaf/hir_lower/src/expr.rs`).
**Compiler only; ngspice is unchanged.**

**Suites:** [`concat_examples`](../examples/concat_examples/) 5 → 14 (a new
`bitcat.va` pins every value through ngspice, both solvers); `vafconcatsize`,
`array`, `lrmdata` and `lrmlex` pass; full sweep 459 of 459; the compiler's
front-end crate tests pass; the 92-model corpus compiles as before (91 of 92
standalone, the EPFL-HEMT baseline). Handbook
[§2.5](../docs/handbook/02-verilog-a-language.md), the
[compliance matrix](../docs/compliance/OpenVAF_Verilog-A_LRM_Compliance.md) §4.1,
the suite README.

## What was wrong

`{1'b1, 3'b101}` was typed as `integer[0:2]`. E-34 made `{…}` the concatenation
operator over *arrays and strings* — the spelling LRM 2.2-era models use for
`laplace_nd(x, {1}, {1, 2})`, `noise_table({…})` and array initialisation — and it
had no bit-level reading at all, so the LRM 4.1.13 meaning (the 4-bit integer
4'b1101 = 13) was unreachable: an integer concatenation could neither be assigned
to an integer nor stand as an operand, failing with *type mismatch: expected
integer value but found integer[0:2] value*. The book's chapter 2 teaches exactly
this form, with `{4{w}}` as the replication example, and the audit's probes
`u39`, `u40` and `t02` all refused.

## What changed

* **The reading is decided by what is expected of the expression.** A numeric
  `{…}` whose operands are all scalar integers is remembered as a *bit-level
  candidate* when it is inferred. If an array is expected of it (array
  assignment, a filter or `noise_table` argument, an array function argument)
  nothing changes: it is E-34's flat array. If a **scalar** is expected — a
  scalar assignment, an operator operand, a scalar function argument — the
  candidate is retyped `integer` and lowered bit-level: each operand masked to
  its width and shifted in from the left, the operand list repeated the
  replication count. The three places a scalar expectation is checked (the
  assignment path, the expectation check, the signature resolver for operators
  and calls) all consult the candidate before reporting a mismatch.
* **Widths.** A sized based literal contributes its declared size (`4'hA` four
  bits — the size now survives body lowering in `Body::literal_sizes`); any other
  integer expression contributes the 32 bits of an `integer` (LRM 3.2); a nested
  `{…}` contributes its own total. An **unsized literal** is an error, as 4.1.13
  requires ("unsized constant numbers shall not be allowed in concatenations"):
  *an unsized literal cannot be an operand of a bit-level concatenation — give
  the literal a size, e.g. `8'd5`*. A result **wider than 32 bits** is warned —
  *bit-level concatenation is 38 bits wide; an `integer` keeps the low 32* — and
  the low 32 bits are kept, which is the LRM 3.3 truncation on assignment, so the
  book's `{4{w}}` is `w`.
* **Nesting.** `{4'h0, {2'b01, 2'b10}}` is 6: converting the outer converts the
  inner, whose width is the sum of its operands.

## Verification

| check | result |
|---|---|
| `c1 = {1'b1, 3'b101};` | 13 |
| `{4'hA, 4'h5}` as an integer, and as a real operand `* 0.5` | 165, 82.5 |
| `{2{4'b1010}}` | 170 |
| `{4'h0, {2'b01, 2'b10}}` (nested) | 6 |
| `{2'b11, 4'hF, w} & 32'h0000000F` with `w = 3` | 3, with *bit-level concatenation is 38 bits wide; an `integer` keeps the low 32* |
| `integer r; r = {1, 2};` | *an unsized literal cannot be an operand of a bit-level concatenation* |
| `real x[0:1]; x = {1.0, 2.0};`, `laplace_nd(x, {1}, {1, 2})`, `avg4({1, 3, 2.0, 2.0})` | E-34's arrays, unchanged |
| the audit's `u39`, `u40`, `t02` probes | compile (`{4{w}}` warned as 128 bits, worth `w`) |
| `concat_examples`; full sweep | 14 / 14 both solvers; 459 of 459 |
| front-end crate tests; model corpus | pass; 91 of 92 standalone (baseline) |
