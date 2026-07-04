# precedence_examples — operator-precedence audit + fixes (Enhancement-38)

A systematic audit of the **operator-precedence table** against the Verilog-AMS
LRM (Table 4-2), using **the committed** `openvaf-r` and `ngspice-46` — with
the defect it found, fixed.

## What was broken

- **`%` bound tighter than `*` and `/`** — the LRM puts all three on one
  left-associative level, so `6*7%4` parsed as `6*(7%4)` and evaluated to **18**
  instead of the LRM's `(6*7)%4 = 2`; silent wrong answers in any model mixing
  `*`/`/` with `%`.
- `~^`/`^~` were split from `^` (LRM: one level) — provably unobservable for
  xor/xnor chains, fixed for LRM exactness.

Everything else checked out: the full level ordering, left-associativity of all
binary operators (including `2**3**2 == (2**3)**2 == 64` per LRM 4.1.3), ternary
right-associativity (`a?b:c?d:e == a?b:(c?d:e)`), and unary binding **above**
`**` (`-2**2 == (-2)**2 == 4` — the classic Verilog difference from C/Python).

## The audit design

`precedence_audit.va`: 28 checks covering every adjacent level pair of the LRM
table plus associativity and unary corners. Each failing check adds a distinct
power of two to a score emitted on a signal-flow output — `v(out) == 0` ⇔ all
pass; any nonzero value is a bitmask naming the failing check.

## Run

```
python3 verify_precedence.py
```

Checks (ALL PASS): all 28 precedence/associativity checks read 0; the marquee
fix case asserted directly (`6*7%4 == 2`, was 18).
