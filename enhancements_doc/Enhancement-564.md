# Enhancement-564: hierarchical names into generate blocks — `blk.x`, `g1[0].z`, the implicit `genblk<n>`, and single-item generate branches

**Scope:** §3.4's generate items (chapter 18) of the
[coverage audit of *A Practical Guide to Verilog-A*](../docs/audits/2026-09-05_practical-guide-verilog-a-coverage.md).
The parser (`openvaf/parser/src/grammar/items/module.rs`) and the generate elaboration
pass (`openvaf/hir/src/elaborate.rs`). **Compiler only; ngspice is unchanged.**

**Suites:** new [`genhier_examples`](../examples/genhier_examples/) (5 checks per solver,
both solvers); `generate`, `baregenerate`, `genvarloop`, `lrm`, `lrmhier`, `hiername`,
`hiernode`, `hierdev`, `hierbranch`, `langguard`, `defparam`, `instarray`, `lrmkernel`,
`paramsetlrm` pass; full sweep 463 of 463; the compiler's front-end crate tests pass; the
92-model corpus compiles as before (91 of 92 standalone, the EPFL-HEMT baseline). Handbook
[§2.1](../docs/handbook/02-verilog-a-language.md), the
[compliance matrix](../docs/compliance/OpenVAF_Verilog-A_LRM_Compliance.md) §6, the suite
README.

## What was wrong

Generate constructs elaborated (Enhancement-5, 67, 96, 390, 392), but a generate block
was not a *scope* anyone could name. The elaborator renders a `for` iteration's
declarations as `z_0`, `z_1` and an `if`/`case` block's flat, then drops the block; so
`V(blk.x)` for `if (sw) begin : blk electrical x; … end` was *'blk' was not found*
(`w01`, `u34b`), `V(g1[0].z)` a parse error (`u36`), `V(one.q)` for a case arm *'one'
was not found* (`u33`), and LRM 6.6.3's implicit `genblk<n>` names did not exist
(`u34`). The book's chapter 18 is about exactly these names, and the LRM's own 6.6.3
example — `if (genblk2) electrical a; else electrical b; // top.genblk1.b` — could not
even be parsed: a generate branch without `begin`/`end` was read as a block missing its
`begin`, swallowing every item up to the next `end`, which is why a `case` written after
one failed at its `default` (`t32d`).

## What changed

* **A generate block is a scope with a name.** Every generate construct of a scope is
  numbered in textual order; a block without a label is `genblk<n>`, with leading
  zeroes added while that name is a declared one (LRM 6.6.3, its example's `genblk02`).
  As the elaborator renders a block it records the flat name of everything the block
  declares under its LRM 6.7 hierarchical path relative to the module — `blk.x`,
  `genblk02.y`, `g1[0].z`, `g1[0].genblk1.w`, `two.q`, `g1[0].r1` — nested constructs
  numbering per block. When the module is rendered, every reference whose first segment
  is one of its generate labels is rewritten to the recorded flat name: the longest
  matching prefix, the rest kept, so `g1[0].r1.mid` becomes `r1_0.mid` for the
  instantiation pass to resolve. A path that starts with a label and reaches nothing —
  `blk.nosuch`, `g1[5].z` — is an error naming the block and what it declares.
* **Flat names no longer collide across blocks.** A declaration whose flat name the
  module already holds — its own declaration, an earlier `if` block's, another loop's
  iteration 0 — moves aside under the block's label (`b_genblk02`, `a_0_genblk1`), so the
  LRM's example, two unlabelled `if`s each declaring `b`, compiles. Bare references to a
  generate block's declarations, which the LRM does not allow and this project accepted,
  keep working for the first declaration of a name.
* **Single-item generate branches.** A conditional's branch, a case arm, or a loop body
  may be one item with no `begin`/`end` (LRM 6.6.2, 1364-2005 A.4.2); the parser wraps
  it in the same block node, so elaboration and naming see one shape.

The documented E-67 boundary is unchanged: a generate condition or case selector on a
module *parameter* stays an error, since parameters bind at simulation time under OSDI.

## Verification

| check | result |
|---|---|
| `V(blk.x)` (named `if`), `V(genblk02.y)` (unlabelled, `genblk2` declared), `V(g1[0].z)`, `V(g1[1].z)`, `V(g1[0].genblk1.w)`, `V(two.q)` (case arm), `V(g1[0].r1.mid)` (instance in a loop) summed into a current | −36.5 mA at 1 V, −40.5 mA at 2 V, exact |
| the LRM 6.6.3 example (`genblk1.b`, `genblk02.b`, `g1[0].genblk1.a`, `genblk4[0].genblk1.a`) | compiles; reads 1 + 2 + 3 + 4 V |
| `if (c) electrical y; else electrical y;` followed by a `case` | parses and elaborates |
| the audit's `w01`, `u34`, `u34b`, `u36`, `u33`; `t32d` with its selector a `localparam` | compile (`t32d` as written keeps the E-67 refusal of a `parameter` selector) |
| `blk.nosuch`; `g1[5].z` | *'blk.nosuch' names nothing declared in generate block 'blk' -- the block declares: blk.x*; likewise for `g1` |
| `genhier_examples`; fourteen generate, hierarchy and paramset suites; full sweep | 5 / 5 both solvers; all pass; 463 of 463 |
| front-end crate tests; model corpus | pass; 91 of 92 standalone (baseline) |
