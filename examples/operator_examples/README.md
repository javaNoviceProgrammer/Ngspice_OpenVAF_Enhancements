# operator_examples — operator-correctness audit + fixes (Enhancement-37)

A systematic audit of the **arithmetic, relational, logical, bitwise/shift,
ternary and concatenation** operator families, using **the committed**
`openvaf-r` and `ngspice-46` — with the three real defects it found, fixed.

## What was broken

- **`~x` (bitwise NOT)** was lowered as arithmetic negation: `~12` gave **−12**
  instead of −13 — silent wrong answers in bit-manipulating models;
- **constant folding of `>>`** sign-extended (the `>>>` semantics): `-16 >> 2`
  folded to **−4** instead of the zero-filled `1073741820`, and disagreed with
  the (correct) runtime LLVM path for the same expression;
- the **ternary operator rejected string operands** (`c ? "a" : "b"` was a type
  error).

Everything else — truncation/sign rules of `/` and `%`, `**` incl. negative
exponents, all relationals/logicals, `& | ^ ~^`, shift semantics, precedence,
nested ternaries, concat/replication — checked out exactly correct.

## The audit design

`operator_audit.va`: five self-checking modules, one per family. Each failing
check adds a distinct power of two to a score emitted on a signal-flow output —
`v(out) == 0` ⇔ all checks pass; any nonzero value is a **bitmask naming the
failing check**. 60+ checks total.

## Run

```
python3 verify_operators.py
```

Checks (ALL PASS): the audit compiles (string ternaries used to error); all five
family scores are exactly 0; the three formerly-broken cases asserted directly
(`~12 == -13`, `-16 >> 2 == 1073741820`, string ternary).
