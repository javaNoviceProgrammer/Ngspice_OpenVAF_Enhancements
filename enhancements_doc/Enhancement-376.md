# Enhancement-376 — `$dist_*` returns `integer`, not `real`

Found by a correctness campaign over all 94 `$`-prefixed system functions.

## The LRM split

The `$dist_*` family comes from Verilog-2001 §17.9.2, where every parameter and
return value is an integer. Verilog-AMS added `$rdist_*` **because** the originals
are integer-only and analog modelling needs real values. If `$dist_*` already
returned real, there would be no reason for a second family to exist.

openvaf-r returned `real` from both. Two records inside this repo already said
otherwise:

* [`Enhancement-10.md`](Enhancement-10.md) lists `$rdist_*` **(real-valued)** and
  `$dist_*` **(integer-valued)**.
* An Enhancement-49 audit comment sitting directly above the signatures calls them
  *"the integer-distribution `$dist_*` functions"* while correcting their
  **argument** types on LRM grounds — and left the return types alone.

So the argument types were fixed in an earlier pass and the return types were
missed in the same pass. `$random`/`$arandom` have always been `-> Integer`.

## What it cost

LRM-conformant code did not compile:

```
$display("%d", $dist_uniform(seed, 10, 20));
error: type mismatch: expected integer value but found real value
```

That is how the campaign hit it — writing the obvious `%d` for an
integer-valued draw.

## The fix is in two places, and either alone is worse than neither

**1. The signature table** — eight `DIST_*` entries `-> Real` become `-> Integer`.
The eight `RDIST_*` entries are untouched.

**2. The lowering** — each `$dist_*` arm now ends in `ficast`, matching
`$random`/`$arandom`.

Changing only the signature was tried first and is a **wrong-code bug**: the type
checker accepts `%d` while the lowering still emits a real MIR value, so every
downstream integer consumer reads it as 0. Measured, not theorised — with the
signature changed and the lowering not:

| expression | result |
| --- | --- |
| `$display("%d", $dist_uniform(s,10,20))` | `0` — outside its own range |
| `iv = $dist_normal(s,100,15)` (integer) | `0` |
| `rv = $dist_poisson(s,4)` (real) | `2` — still fine |

## The draw itself does not move

Where the runtime value is not already integral the draw is **rounded first**
(`rng_round_real` = `floor(x+0.5)`, which is correct for negatives too — `$dist_t`
and a zero-mean `$dist_normal` need that); `ficast` then truncates an
exactly-integral double, which is lossless. `UniformInt` and `Poisson` are already
integral and are only cast.

Means and variances over 20000 draws are identical before and after — only the
static type moved:

| | mean | expected | variance | expected |
| --- | --- | --- | --- | --- |
| `$dist_uniform(10,20)` | 15.0214 | 15 | 9.9241 | 10.08 |
| `$dist_normal(100,15)` | 99.8969 | 100 | 222.83 | 225 |
| `$dist_poisson(4)` | 4.0319 | 4 | 4.0785 | 4 |

The discrete/continuous split is visible in the variances and is itself a check
that the two families stayed distinct: `$dist_uniform` sits at (n²−1)/12 = 10.08
while `$rdist_uniform` sits at 100/12 = 8.33.

## The `$rdist_*` half is the trap

`$rdist_poisson` lowers through the **same** `RngFun::Poisson` call as
`$dist_poisson`, so a textual edit casts it too and silently converts the
real-valued family to integer. That happened during development and was caught by
an arm-by-arm audit asserting `ficast` present for all seven `$dist_*` and absent
for all seven `$rdist_*`. `examples/distint_examples` therefore asserts the
**negative** case — every `$rdist_*` draw must be non-integral — rather than only
the positive one.

## Verification

`examples/distint_examples` — 22 checks.

```
   fixed:     22/22
   pre-fix:   19/22   `%d` rejected; both value checks unreachable
```

A **differential run over all 726 `.va` files in the repo**, new binary against the
shipped one: 0 regressions. Compatibility in the other direction was checked
explicitly — `%g` applied to a `$dist_*` result still compiles on both binaries, so
existing models that format the draw as a real are unaffected, as are models
assigning it to a `real` variable (implicit integer→real widening).

Regression 300/300 → 301/301.
