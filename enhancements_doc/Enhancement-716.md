# Enhancement-716: an integer division by a card-supplied zero is the run-time fatal the modulus by the same zero has been since E-518, naming the operator — it read 0 in silence, E-518's LLVM-level guard for a genuinely run-time zero answering for the card value too; a real quotient by a card zero stays the infinity IEEE gives it

**Scope:** F2 of the
[correctness campaign of 2026-09-25](../docs/bug_hunts/2026-09-25_openvaf-r-correctness-campaign.md).
**Compiler only.** `hir_lower/src/expr.rs` (`guard_div_divisor`, the integer arm of
`BinaryOp::Division`).
[`examples/fmtdiag_examples/`](../examples/fmtdiag_examples/) (section [5], 6 checks,
46 in all); [`examples/vafdivzero_examples/`](../examples/vafdivzero_examples/) (6 checks)
and [`examples/lrmexpr_examples/`](../examples/lrmexpr_examples/) (25 checks) re-pinned,
[`examples/vafintub_examples/`](../examples/vafintub_examples/) (7 checks) simulated with a card
value. The hunt page.

**Suites:** `fmtdiag` 46 of 46 (44 of 46 on the E-714 binaries); `vafdivzero` 6 of 6
(5 of 6) and `lrmexpr` 25 of 25 (24 of 25), whose E-333 and E-518 checks had pinned the
silent 0 of a parameter-zero quotient and now pin the fatal (their modules divide by a
genuinely run-time zero where they mean the defined 0); `vafintub` 7 of 7 (its
module, which must keep *compiling* with a parameter-zero divisor, now simulates with
`pzero=1` on the card); `langguard` 132 of 132,
`vafcrash2` 22 of 22, `arrayscale` 38 of 38, `filterforms` 100 of 100 and `array` 11 of
11 unchanged; the compiler workspace tests
green apart from the three pre-existing sourcegen drift failures (221 passed), no build
warnings; full sweep, run alone.

## What was wrong

`parameter integer pi = 7; parameter integer pz = 1;` and `pz=0` on the card:

| expression | E-714 |
|---|---|
| `pi % pz` | `OSDI(fatal) n1: %: the second operand (the modulus divisor) is zero, which LRM 4.2.4 makes an error`, the analysis aborted |
| `pi / pz` | `0`, no message |
| `pi / (pz - 1)` with `pz=1` | `0`, no message |
| `parameter integer pq = pi / pz;` | `pq = 0`, no message |
| `7.5 / rz` (real) with `rz=0` | `+inf` |
| `7 / 0` | `error: integer division by zero` at compile time (E-333) |

The three-route policy of E-509 and E-518 — a zero the compiler can see is a compile
error, a zero from the card is a run-time fatal naming the operator and the clause, a
genuinely run-time zero (one computed from a solution variable) is left defined — was
applied to the modulus and not to the division. E-518 had closed the *undefined
behaviour* of `sdiv` and `srem` by a zero at the LLVM layer, `x / 0 ⇒ 0`, so that a
run-time zero would not trap; the same guard answered for the card value, and a model
that divides an integer count by an integer parameter set to 0 on its card went on
computing with a quotient of 0 and nothing said. (On x86 without E-518's guard the same
division trapped; the 0 is the portable answer E-518 chose for the run-time case.)

## What changed

**The integer division has the modulus' guard** (`hir_lower/src/expr.rs`,
`guard_div_divisor`, called from the integer arm of `BinaryOp::Division`): when the
divisor is parameter-derived (`is_param_derived`, the same test the modulus and the
E-509 domain guards use) its value is tested against zero at run time and a zero
raises

```
OSDI(fatal) n1: /: the second operand (the divisor) is zero, so the integer quotient has no value (LRM 4.2.4 makes the modulus by it an error)
```

with the instance named — `mm` when it is a parameter default evaluated at setup —
and the analysis aborts as for the modulus. A divisor that is not parameter-derived
(`7 / $rtoi(V(p,n))` at V = 0) keeps E-518's defined 0, as the modulus keeps its
defined remainder; the real quotient is untouched (a card zero gives ±∞, which is
what E-706 folds the literal form to); `INT_MIN / -1` still wraps.

## Verification

`fmtdiag` section [5]: `7 / pz` with `pz=0` on the card is the fatal naming `/` and
LRM 4.2.4, and with `pz=2` an ordinary run; a parameter default `pi / pz` with `pz=0`
raises it at setup; a real quotient by a card zero stays the infinity, no fatal; a
voltage-derived zero divisor keeps the defined 0, no fatal; the literal form keeps
E-333's compile error. The 40 checks of E-578 unchanged. `vafdivzero`'s module now
simulates with `pzero=1` on the card and its default zero is checked for the fatal;
`lrmexpr`'s `d3` divides by a run-time zero (the defined 0) and a new `divz` module
carries the parameter-zero fatal and its nonzero override; `vafintub`'s `intub_ok`
simulates with `pzero=1`.

By hand: the table above on the new compiler, `pi / (pz - 1)` with `pz=1` (a
computed card divisor) raising the fatal, `INT_MIN / -1` reading −2147483648; the
eight suites; the workspace tests; the sweep.

## What this does not do

- It does not touch the real division: `x / rz` with a card `rz=0` is ±∞ by IEEE and
  by E-706's folding of the literal form, and a model may rely on it.
- It does not guard a genuinely run-time zero divisor — E-518's policy, that the
  quotient is a defined 0 rather than a trap, stands for both operators.
- LRM 4.2.4 names the modulus; the division's message says so and calls the quotient
  undefined rather than claiming the clause for it.
- A `localparam` integer zero divisor (`localparam integer lz = 0; 7 / lz`, or one
  that folds to zero) still folds to the defined 0 in silence, for `/` and for `%`
  alike — E-333's suite pins that acceptance ("rejecting these would break working
  models") and E-578 made only the real modulus' constant zero a compile error. Whether
  the integer forms should follow is a separate decision.
