# Enhancement-709: a Poisson draw takes Hörmann's transformed rejection above a mean of 10, and the chi-square, Student's t and Erlang draws take a Marsaglia–Tsang gamma variate above 256 degrees — the multiplicative Poisson method returned a seed-dependent count near 750 for every mean above 745 (768 for the campaign's seed, 745 ± 28 over 2 000 seeds), and the three sums cost one draw per degree at every evaluation, so a degree of 2³¹ − 1 never returned

**Scope:** F4 and F5 of the
[robustness campaign of 2026-09-23](../docs/bug_hunts/2026-09-23_openvaf-r-robustness-campaign.md).
**Compiler only** — the OSDI standard library that every compiled model carries:
`osdi/stdlib.c` (`osdi_loggam`, `osdi_rng_poisson_ptrs`, `OSDI_RNG_POISSON_PTRS_MIN`,
`osdi_rng_gamma`, `OSDI_RNG_DIRECT_SUM_MAX`; `osdi_rng_poisson`, `osdi_rng_chi_square`,
`osdi_rng_t` and `osdi_rng_erlang` route through them).
[`examples/rng_examples/`](../examples/rng_examples/) (`draw_samples` takes a timeout;
14 checks, 38 in all). The handbook's distributions row, the compliance document's
9.13 section, the hunt page.

**Suites:** `rng` 38 of 38 per solver, both solvers (30 of 38 on the E-704 binaries),
`distint` 22 of 22, `lrmkernel`, `lrmfuncs`, `langguard` 132 of 132, `constguard`,
`dropguard`, `osdidist`, `montecarlo`, `mcrecord`, `seedexpr`, `rndcast`,
`deckdomain` and `rtdomain` unchanged; the compiler workspace tests green apart from
the three pre-existing sourcegen drift failures (221 passed), no build warnings;
full sweep 532 of 532, run alone.

## What was wrong

**F4.** `I(p,n) <+ V(p,n) + $dist_poisson(s, mean)` at the operating point, the
current being 1 + the draw:

| mean | before | now |
|---|---|---|
| 100 | 113 | 94 |
| 500 | 508 | 485 |
| 700 | 722 | 682 |
| 740 | 763 | 722 |
| 750 | **768** | 732 |
| 800 | **768** | 781 |
| 1 000 | **768** | 979 |
| 10 000 | **768** | 9 931 |
| 10⁶ | **768** | 999 300 |
| 2³¹ − 1 | **768** | a count near 2³¹ (the integer cast is the caller's) |
| `$rdist_poisson` 760 / 10 000 | **768** / **768** | 741 / 9 931 |

No message at compile time or at run time. The generator was Knuth's multiplicative
method — draw uniforms until their product falls below `exp(−mean)` and return the
count. `exp(−745.13)` is the smallest positive double; above that mean the threshold
is exactly zero, the product of 53-bit uniforms reaches zero after about 768 factors,
and the loop count was the draw. Any model that counts photons or electrons per step
with a mean above 745 read 768.

**F5.** One operating point, one evaluation per Newton iterate:

| call | degree | before | now |
|---|---|---|---|
| `$dist_erlang(s, k, 1)` | 10⁶ / 10⁷ / 10⁸ | 0.2 / 0.5 / 3.4 s | 0.2 / 0.2 / 0.2 s |
| `$dist_chi_square(s, k)` | 10⁶ / 10⁷ / 10⁸ | 0.3 / 1.0 / 7.9 s | 0.2 / 0.2 / 0.2 s |
| `$dist_t(s, k)` | 10⁶ / 10⁷ / 10⁸ | 0.3 / 1.0 / 8.0 s | 0.2 / 0.2 / 0.2 s |
| all three | 2 147 483 647 | no result in 60 s | 0.2 s |
| `$rdist_erlang(s, 1e9, 1.0)` | 10⁹ | 31.6 s | 0.2 s |

The Erlang variate was the sum of `k` exponentials, the chi-square the sum of `k`
squared normals, and the t variate a normal over a chi-square of `k` degrees — each a
loop of `k` draws, run at every evaluation of the model. The compile-time check
refuses a degree of 0 and accepts any positive one; the degree may come from a
parameter and so from the card, where nothing sees it. A model could stall the
simulator with one integer.

## What changed

1. **Poisson above a mean of 10: PTRS.** Hörmann's transformed rejection with squeeze
   (1993) draws two uniforms per attempt and accepts almost every attempt at a large
   mean, so the cost is O(1) at any mean and the distribution is exact. The rejection
   test needs log Γ(k + 1); `osdi_loggam` computes it by Stirling's series after
   shifting the argument up to 7, so the standard library declares nothing new from
   libm. Below a mean of 10 Knuth's method stays, and every draw a model made with a
   small mean is bit for bit what it was. A mean that is not finite is returned as it
   is (an infinite mean is an infinite count; the compiler refuses the literal since
   E-706, and the deck route's `$dist_` cast is the caller's).
2. **Chi-square, t and Erlang above 256 degrees: a gamma variate.** Marsaglia and
   Tsang's method (2000) draws a normal and a uniform per attempt and accepts nearly
   every attempt at a large shape, so a Gamma(shape) variate costs O(1) at any shape.
   Chi-square(k) is 2·Gamma(k/2), Erlang(k, mean) is Gamma(k)·mean/k, and t(k) is
   z / √(chi-square(k)/k) with the chi-square from the same route; a shape below 1
   (chi-square with one degree) is lifted by one and scaled by U^(1/shape). Up to 256
   degrees the sums stay term by term, exact and cheap, and every draw is bit for bit
   what it was. A t degree that is not finite gives the normal limit, z.
3. **The degree is a double throughout the closed-form route** — the sums cast it to
   `long`, which a degree of 10¹⁰ would overflow where `long` is 32 bits.

## Verification

`rng_examples` (Enhancement-10's moment suite, N instances with seeds 1..N and one
`.op`) gains: Poisson(1 000) and Poisson(10⁶) moments (2 000 and 1 000 instances;
the old binaries return 745 ± 28 for both, so both fail there); chi-square(10⁵),
Erlang(k = 10⁵, mean 6) and t(10⁵) moments (1 000 instances — the old binaries pass
these in a few seconds each, summing 10⁸ terms); and the wall: chi-square, t and
Erlang at 2 147 483 647 degrees and Poisson at a mean of 10⁹, four instances each,
under a 30 s timeout, every draw within the distribution's spread of its centre —
the old binaries time out on the three degrees and draw 789 for the mean. By hand:
the two tables above, the campaign's `pJ.py` re-run to the number.

## What this does not do

- The thresholds are constants: 10 for the Poisson route (Knuth's method is exact and
  cheap below it, and PTRS is specified for a mean of 10 or more) and 256 degrees for
  the gamma route (a sum of 256 terms is microseconds). Below them nothing changed.
- `$dist_poisson(s, 2147483647)`, `$dist_chi_square(s, 2147483647)` and their kin
  return an `integer` through the compiler's real-to-integer cast, which does not
  saturate; a count above 2³¹ − 1 is the model's own business, exactly as before.
- Nothing is bounded at compile time: with an O(1) generator there is no degree or
  mean a model can use to stall the simulator, so no check was added.
