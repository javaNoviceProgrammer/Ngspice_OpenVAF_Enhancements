# Enhancement-37 — operator-correctness audit + fixes

This document describes the changes made to **OpenVAF-r** in the `version11/`
directory after a systematic **operator-correctness audit** covering the
arithmetic, relational, logical, bitwise/shift, ternary and concatenation
operator families. Three real defects were found and fixed; everything else
checked out exactly correct. Purely front-end/middle-end (`hir_lower`,
`mir_opt`, `hir_ty`); no OSDI/ngspice change.

## The audit

`operator_examples/operator_audit.va` holds five self-checking modules — one per
operator family. Every individual check that fails adds a distinct power of two
to a score emitted on a signal-flow output, so `v(out) == 0` means every check
in that family passes and any nonzero value is a **bitmask pinpointing exactly
which check failed**. 60+ checks cover:

- integer arithmetic: `+ - * / %` incl. truncation toward zero (`-7/3 == -2`)
  and modulus sign rules (`-7%3 == -1`, `7%-3 == 1`), `**`, unary minus,
  precedence;
- real arithmetic: `+ - * / %` (fmod semantics, sign of first operand), `**`
  incl. negative exponents and negative base with odd integer exponent;
- relational/logical: `< <= > >= == !=` on integers and reals, 0/1 result
  values, `&& || !`, mixed expressions;
- bitwise/shifts: `& | ^ ~^ ^~ ~`, `<< >> <<< >>>` incl. sign-extension vs
  zero-fill, shift-by-zero, involution (`~~x == x`), `& |` precedence;
- ternary: integer/real/string results, nested, comparisons inside conditions;
- concatenation/replication (regression-locking Enhancement-34).

## The three defects found → fixed

### 1. `~x` (bitwise NOT) was lowered as arithmetic negation

`hir_lower` mapped `UnaryOp::BitNegate` to `ineg` (`-x`), so `~12` evaluated to
**−12** instead of −13 (`~x = −x − 1`). Silent wrong answers in any model using
bit manipulation. Fixed to the `inot` opcode (whose const-fold, `!val`, was
already correct — only the lowering picked the wrong instruction).

### 2. constant folding of `>>` sign-extended

The MIR distinguishes `Ishr` (logical `>>`, zero-fill) from `Iashr`
(arithmetic `>>>`, sign-extending), and the LLVM runtime path emits the correct
`LShr`/`AShr` pair — but the **constant folder** in `mir_opt/src/const_eval.rs`
computed both with Rust's `>>` on a signed `i32`, which sign-extends. So
`-16 >> 2` folded to **−4** instead of the zero-filled `1073741820`
(`0x3FFFFFFC`), and — worse — a constant-foldable `>>` disagreed with the same
expression computed from runtime values. Fixed by folding through `u32`:
`((lhs as u32) >> rhs) as i32`.

### 3. the ternary operator rejected string operands

`cond ? "a" : "b"` was a type error (`SignatureData::SELECT` only allowed
bool/real/integer branch pairs). Per the LRM the conditional operator supports
string operands. Fixed by appending a `STR_BIN_OP` signature
(`(String, String) → String`) to the SELECT list — appended **last**, keeping
the existing signature indices stable. The lowering needed no change (the
existing `phi` handles string values).

## Verification — `operator_examples/`

`verify_operators.py` (ALL PASS):

1. the audit file **compiles** (string ternaries used to be a type error);
2. all five family scores read **exactly 0** (60+ individual operator checks,
   any failure would name itself in the bitmask);
3. the three formerly-broken cases asserted directly:
   `~12 == -13`, `-16 >> 2 == 1073741820`, `(1>0) ? "yes" : "no" == "yes"`.

Regressions: all **33** version11 example verify suites ALL PASS and all **75**
example models recompile after the fixes (the `~`/`>>`/ternary changes touch
shared lowering and const-eval paths, so the full sweep matters).
