# Enhancement-494 — two ways a B source expression disagreed with every other value path

**Files:** `src/spicelib/parser/ptfuncs.c`, `src/frontend/inpcom.c`.

**Suite:** `examples/bexprvalue_examples/` — 63 checks.

## Why

Round 54 compared the B source expression path against the paths that read the
**same number on the same deck**. It answered differently twice: once about the
sign of a value, once about the value itself.

## 1. `x/0` lost its sign

Enhancement-491 removed a `gmin`-derived fudge factor from `PTdivide` and
replaced it with a fixed epsilon, writing the nudge as

```c
arg2 = (arg1 >= 0.0) ? PTDIV_EPS : -PTDIV_EPS;
```

The intent was to keep the sign of the numerator. The effect was the opposite: a
negative numerator was divided by a **negative** epsilon, so the quotient came
out positive either way.

| expression | before | after |
|---|---|---|
| `v(p)/0`, v(p) = +3 | +3e+32 | +3e+32 |
| `v(p)/0`, v(p) = −3 | **+3e+32** | −3e+32 |
| `-1/0` | **+1e+32** | −1e+32 |
| `(0-2)/0` | **+2e+32** | −2e+32 |
| `E0 b0 0 vol='-1/0'` | **+1e+32** | −1e+32 |

Every case Enhancement-491 measured had a positive numerator, which is why its
own suite did not see this.

A divisor of exactly zero carries no sign to recover, so the choice is which
side zero is approached from, and it must be made once rather than per operand.
The epsilon is now unconditionally **positive** — zero from above — and the
quotient therefore keeps the sign of the numerator, which is what
`lim(x/eps) as eps→0+` gives and what the surrounding comment already described.

Everything Enhancement-491 established is unchanged and is pinned by the suite:
the magnitude of `1/0` is still 1e32, an ordinary non-zero divisor is still used
exactly as written, and `1/1.38064852e-23` still does not move when `gmin` does.

## 2. Numeric literals were rounded to 11 significant digits

Every B source line is rewritten before parsing by `inp_modify_exp()`, which
re-emitted each numeric literal it found with `"%18.10e"` — eleven significant
digits.

```
B0 b0 0 v=1.2345678901234567     →  reaches the parser as 1.2345678901e+00
```

a relative error of **1.9e-11**. The *same literal* written on an `R`, `C` or `V`
card, in a `.param`, or as an OSDI `.model` parameter kept all seventeen digits.
The B source was the only path in the simulator that could not carry a double.

It was not merely a printout. The rounding reached the arithmetic:

```
B0 b0 0 v=tan(1.5707963267948966)   →  -1.96e11      (libm: 1.633123935319537e+16)
```

The tangent was right; its argument was not.

### Why the shortest text, and not simply more digits

`INPevaluate()` reads this text back on the way in, and accumulates the mantissa
by hand as `mantis = 10 * mantis + digit`, which loses a bit once the accumulator
passes 2^53. Emitting more digits than the value needs is therefore not free: a
fixed `"%.17e"` turns the sixteen digits of `0.7853981633974483` into eighteen
and brings it back **1 ulp out**, when the user's own text would have survived
intact.

`inp_num_text()` instead emits the **shortest** decimal text that reads back as
the same double, trying 15, 16 then 17 significant digits and keeping the first
that round-trips. That reproduces the literal the user wrote whenever it was
itself minimal, and never emits precision the value does not carry. Seventeen
digits always suffice for an IEEE754 double, so a finite value cannot fall out of
the loop unmatched.

## What is deliberately not fixed

**`INPevaluate`'s own scaling.** A few values still land 1–2 ulp from the double
they name, through that hand-rolled mantissa and the `pow(10, expo)` that scales
it. This is **shared by every value path** — a `V` source shows it on the same
literals — so it is a wider question than the one measured here, and this
enhancement does not reach into it. The suite pins **parity and a 2 ulp bound**
rather than bit-exactness; what must never come back is the 11-digit rounding,
which put the same values 1.0e5–1.6e5 ulp out.

**`mkb()`'s unguarded constant fold.** `mkb()` in `inpptree.c` folds a constant
`/` with a raw `left->constant / right->constant` and no zero guard, bypassing
`PTdivide` entirely; a sibling branch returns a bare `0` for `0/x`. Probed from
`B`, `E` and `G` sources in constant, parenthesised, nested and mixed forms, it
**never produced an infinity** — every constant division still arrives through
`PTdivide` with the corrected sign — so the branch appears unreachable from user
input and was left alone rather than fixed past the evidence.

## What must not move

* **The sign and magnitude of a positive `x/0`**, and `gmin` independence — all
  of Enhancement-491's contract.
* **Ordinary divisors**: `2/4`, `-2/4`, `2/-4`, `-2/-4`, `0/5`, `1/1e-30`.
* **SPICE suffixes** `100p`, `5MEG`, `1k`, a leading-dot `.5`, and exponent
  forms — all still parsed by the rewritten emitter.
* **`pwl` B sources**, which `inp_bsource_compat()` excludes from the rewrite.
* **Current B sources**, node references mixed with literals, and the value
  surviving a transient.
* **`E` and `G` expressions**, which never passed through `inp_modify_exp()` —
  only `b` lines do — and were already exact.

## Verification

```
python3 examples/bexprvalue_examples/verify_bexprvalue.py   # 63/63
python3 examples/run_regression.py                          # 408/408
```

**37/63** against the pre-fix binary, so **26 of 63 checks discriminate**. The
other thirty-seven are controls that must not move, and do not — most importantly
Enhancement-491's own contract, which this change is careful to preserve while
correcting the one line of it that was wrong.
