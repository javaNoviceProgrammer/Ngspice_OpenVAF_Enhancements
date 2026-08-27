# Enhancement-494 — two ways a B source expression disagreed with every other value path

```
python3 verify_bexprvalue.py
```

63 checks, a few seconds. **37/63** against the pre-fix binary — **26**
checks discriminate.

## What it is

The B source expression path was compared against the paths that read the *same
number on the same deck*. It answered differently twice.

## 1. `x/0` lost its sign

Enhancement-491 replaced a `gmin`-derived fudge factor with a fixed epsilon and
wrote the nudge as

```c
arg2 = (arg1 >= 0.0) ? PTDIV_EPS : -PTDIV_EPS;
```

meaning to keep the sign of the numerator. But a negative numerator was then
divided by a **negative** epsilon, so the quotient came out positive either way:

| expression | before | after |
|---|---|---|
| `v(p)/0`, v(p) = +3 | +3e+32 | +3e+32 |
| `v(p)/0`, v(p) = −3 | **+3e+32** | −3e+32 |
| `-1/0` | **+1e+32** | −1e+32 |
| `(0-2)/0` | **+2e+32** | −2e+32 |

Every case Enhancement-491 measured had a positive numerator, which is why its
own suite did not catch this. A divisor of exactly zero has no sign to recover,
so the epsilon is now unconditionally **positive** — zero approached from above
— and the quotient keeps the sign of the numerator, which is what
`lim(x/eps), eps→0+` gives. The magnitude, and the `gmin` independence
Enhancement-491 established, are unchanged and pinned here.

## 2. Numeric literals were rounded to 11 significant digits

Every B source line is rewritten by `inp_modify_exp()`, which re-emitted each
literal it found with `"%18.10e"`.

```
B0 b0 0 v=1.2345678901234567     →  reaches the parser as 1.2345678901e+00
```

a relative error of **1.9e-11**, while the *same literal* written on an `R`, `C`
or `V` card, in a `.param`, or as an OSDI `.model` parameter kept all seventeen
digits. The B source was the only path in the simulator that could not carry a
double.

This is not only a printout: it reached the arithmetic. `tan(1.5707963267948966)`
returned **−1.96e11** where libm gives **1.633123935319537e+16** — the argument
was wrong, not the tangent.

### Why the shortest text, and not simply more digits

`INPevaluate()` re-reads the text this function emits, and accumulates the
mantissa by hand as `mantis = 10 * mantis + digit`, which loses a bit once the
accumulator passes 2^53. Handing it the **eighteen** digits of `"%.17e"` put
`0.7853981633974483` back 1 ulp out, when the user's own sixteen-digit text
would have survived intact. So `inp_num_text()` emits the **shortest** text that
reads back as the same double, trying 15, 16 then 17 significant digits.

### What is deliberately not fixed

A few values still land 1–2 ulp out through `INPevaluate`'s own
`pow(10, expo)` scaling. That residue is **shared by every value path** — a `V`
source shows it too — so it is a different, wider question than the one measured
here, and this enhancement does not reach into it. The suite therefore pins
**parity and a 2 ulp bound**, not bit-exactness: what must never come back is
the 11-digit rounding, which put the same values 1.0e5–1.6e5 ulp out.

## What must not move

`mkb()` in `inpptree.c` folds a constant `/` with a raw division and no zero
guard, bypassing `PTdivide` entirely. It was probed from `B`, `E` and `G`
sources in constant, parenthesised and mixed forms and **never produced an
infinity**, so the branch appears unreachable from user input and was left
alone rather than fixed past the evidence.

Also pinned: the SPICE suffixes (`100p`, `5MEG`, `1k`), a leading-dot `.5`,
exponent forms, `pwl` B sources (which `inp_bsource_compat` excludes from the
rewrite), current B sources, node references mixed with literals, and the value
surviving a transient.
