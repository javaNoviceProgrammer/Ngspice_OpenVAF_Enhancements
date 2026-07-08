# Enhancement-38 — operator-precedence audit + fixes

This document describes the changes made to **OpenVAF-r** in the `version11/`
directory after a systematic **operator-precedence audit** against the
Verilog-AMS precedence table (LRM Table 4-2). One observable defect and one
harmless deviation were found and fixed — both in the parser's Pratt
binding-power table (`parser/src/grammar/expressions.rs`); nothing else in the
pipeline changes.

## The audit

The parser's binding-power table was compared entry-by-entry against the LRM
table (highest → lowest):

```
unary + - ! ~   >   **   >   * / %   >   + -   >   << >> <<< >>>
  >   < <= > >=   >   == !=   >   &   >   ^ ~^ ^~   >   |   >   &&   >   ||   >   ?:
```

with associativity rules from LRM 4.1.3: *all operators associate left to
right except the conditional* (right to left). The structural review confirmed:

- **left associativity** for all binary operators — `expr_bp(p, op_bp + 1)`
  parses each right operand one level tighter, including
  `2**3**2 == (2**3)**2 == 64`;
- **right associativity** for `?:` — the else-branch reparses a full
  expression, so `a ? b : c ? d : e == a ? b : (c ? d : e)`;
- **unary above `**`** — prefix operators take an *atom* operand, so
  `-2**2 == (-2)**2 == 4` (the classic Verilog difference from C/Python).

`precedence_examples/precedence_audit.va` then verifies all of it empirically:
28 checks covering every adjacent level pair, each failing check adding a
distinct power of two to a score on a signal-flow output (`v(out) == 0` ⇔ all
pass; any nonzero value is a bitmask naming the failure).

## The defects found → fixed

### 1. `%` bound tighter than `*` and `/` (observable)

The LRM puts `*`, `/`, `%` on **one** left-associative level; the table gave `%`
a higher binding power. Consequence: `a * b % c` parsed as `a * (b % c)` —

```
6*7%4   ==>  6*(7%4) = 18      (LRM: (6*7)%4 = 2)
42/5%3  ==>  42/(5%3) = 21     (LRM: (42/5)%3 = 2)
```

Silent wrong answers in any model mixing multiplication/division with modulus.
Fixed: `%` now shares level 12 with `*` and `/`.

### 2. `~^`/`^~` bound tighter than `^` (harmless, fixed for exactness)

The LRM puts `^`, `~^`, `^~` on one level. The split was **provably
unobservable**: xor is associative/commutative and each xnor contributes exactly
one global inversion, so every grouping of an xor/xnor chain yields the same
value. Fixed anyway so the table is LRM-exact.

Everything else in the table was already correct.

## Verification — `precedence_examples/`

`verify_precedence.py` (ALL PASS):

1. all **28** precedence/associativity checks read exactly 0 — including the
   `* / %` level (4 groupings), `**` vs `*` and unary, `**` left-associativity,
   shifts below `+ -`, relational below shifts, `==` below relational, the
   `& ^ |` ladder, `&&`/`||` levels, ternary lowest + right-associative, and
   unary-tightest cases (`!0+1 == 2`, `~0+1 == 0`);
2. the marquee fix case asserted directly: `6*7%4 == 2` (was 18).

Regressions: no example in either tree contains a `*`/`/`-then-`%` grouping
(grep-audited, so the behaviour change affects no shipped model), and all **34**
version11 example verify suites ALL PASS — including the Enhancement-37 operator
audit, which now doubles as a semantics regression lock for this change.
