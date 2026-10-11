# Enhancement-867: the dc and transient solve refines its answer — a high-gain loop through a 0 V source, and a dc sweep's reused pivot order, lost digits under Sparse

**Scope:** F1 and F2 of the
[Sparse and KLU correctness campaign of 2026-10-11](../docs/bug_hunts/2026-10-11_sparse-klu-correctness-campaign.md).

ngspice:
- `maths/ni/niiter.c`: `ni_refine` after the solve in `NIiter`, with `ni_residual` and
  `ni_scratch`.
- `maths/KLU/klusmp.c` and `maths/sparse/spsmp.c`:
  - `SMPluFac` and `SMPreorder` copy Sparse's loaded values into the matrix's `SMPloadCopy`,
    between the diagonal gmin and the factorization (`smp_copy_sparse_real`).
  - `SMPresidual` computes the residual from that copy, or from the matrix KLU keeps.
- `include/ngspice/smpdefs.h`: the `SMPloadCopy` field and `SMPresidual`.

`examples/realrefine_examples/` (new). **ngspice only.**

**Suites:**
- [`realrefine_examples`](../examples/realrefine_examples/): 9 of 9 per solver. On the E-866
  binaries [1] to [7] fail under Sparse, and none under KLU; [8] and [9] are controls.
- The campaign's families, run again:
  - **C, high gains, 300 networks.** Sparse was wrong by more than 1e-6 in 25 networks; it is
    in 5 now. Those 5 have condition numbers from 7e16 to 9e27, and KLU is wrong on 3 of them
    too, so no solve can promise more there. Networks that needed gmin stepping under Sparse:
    17, now 3.
  - **A, sweeps, 300 networks.** A sweep point and a fresh `op` at the same value disagreed under
    Sparse in 3 networks beyond rounding, worst 8 %. Now in none: seed 239's ammeter, 8 % off,
    is within 1.4e-9. Fresh operating points that Sparse got wrong and KLU right: 2 networks,
    now none.
  - **B, scale.** Seed 30 at a scale of 1e9 was 5.5e-4 off under Sparse; it is within 7.5e-13.
    No network is flagged at any scale.
- Warmstart, failacct, linesearch, solvercore, acrefine and oprobust pass under both solvers.
- The full sweep: 571 of 572. The one is `teardown` [8] under KLU, a timing ratio bounded at
  3×, which read 3.65× under the sweep's eight parallel jobs. Alone it reads 1.01× to 1.08×, on
  this build and on E-866's alike, and the suite passes under both solvers.

## What was wrong

**F1.** A unity follower built from a VCVS of gain A, with a 0 V source in its feedback path:

```
vin in 0 dc 1.234567 sin(1.234567 0.5 1k)
e1 out 0 in neg 1e12
vfb out neg 0
rl out 0 1k
```

Under Sparse it lost about A times the rounding of a double:

| gain | op | transient |
|---|---|---|
| 1e9 | 1.1e-7 | 2.2e-7 |
| 1e12 | 1.8e-5, after 126 iterations of gmin stepping | 2.4e-4 |
| 1e15 | −1.2e-2 | 25 % |

KLU was exact to 3e-16, in 3 iterations. The gain sits in the VCVS's branch row beside entries
of 1. Sparse never scales a row, so the pivot order it chose at a high gain was poor; KLU divides
each row by its largest entry before it pivots. In 300 random high-gain networks, Sparse was
wrong in 20 where KLU was right.

**F2.** A dc sweep orders the matrix at its first point and refactors with that order at every
later one. Sparse's `spFactor` stops only on a pivot of exactly zero. An ammeter beside a load
swept from 0.1 Ω to 40 MΩ read up to 0.5 % wrong; from 10 kΩ, or at any of those values as an
`op`, it read to 1e-9.

## The change

The real solve refines its answer the way the ac solve does since
[Enhancement-860](Enhancement-860.md):
1. **The copy.** Sparse factors in place and adds the diagonal gmin just before. `SMPluFac` and
   `SMPreorder` therefore copy the loaded values between the two, into the copy `NIiter` hangs
   on the matrix (`SMPloadCopy`). The gmin and the trust region's shunt are part of what was
   factored, so they are part of the residual. The element list is rebuilt after an ordering,
   when fill-ins move the element count, and for another matrix. KLU factors into its own
   object and keeps the loaded matrix, gmin included, so nothing is copied.
2. **The measure.** After the solve, `SMPresidual` gives, row by row:
   - r = b − Ax;
   - |A||x| + |b|;
   - |A|s, where sⱼ is the largest unknown of j's kind, in volts or in amperes.

   The backward error is max |rᵢ| / max((|A||x| + |b|)ᵢ, (|A|s)ᵢ). The first denominator is the
   componentwise one. The second keeps a row whose unknowns are all at rounding from counting:
   two nodes a 0 V source or an inductor ties to ground would otherwise read 1, and stop every
   refinement.
3. **The step.** Where the measure is above 64 ε, A d = r is solved with the same factors. The
   corrected x + d is kept while the measure falls, at most twice.

Every solve of `NIiter` is checked except the junction guess's. A converged `NIiter` reports the
iterate its last load used, so any other solve can become the reported point. A solve that was
good costs one pass over the matrix and keeps its bits: same factors, same pivots, same answer.

With it, F1's follower is exact under Sparse at every gain up to 1e15, op and transient, in 3
iterations. F2's sweep reads 0.6217/R to 1.7e-9 from either end. The campaign's F3 deck, teraohm
dead ends beside a VCVS, is exact too, and so is seed 365's 1.4e-11 A ammeter beside 70 A. Seed
187's 6e-8 A beside 4e5 A is not: its row's floor is set by that 4e5 A. N1 is unchanged: KLU's
inverter at a gain of 1e12 still goes through gmin stepping, since its solve was already good
and the E-256 guard declines it.

**The cost** is one pass over the matrix per Newton iteration, plus the Sparse copy at each
factorization. Best of three runs:

| circuit | Sparse | KLU |
|---|---|---|
| RC ladder, 20 000 nodes, transient | +22 % | +16 % |
| ring oscillator, 101 CMOS stages | +7 % | +4 % |
| 60 × 60 resistor mesh, dc sweep | +3 % | +4 % |

The ladder is the worst case: its loads cost nothing, and its factorization and solve are as
cheap as the pass. None of the three needed a refinement step, and their iteration counts are
unchanged.

## The checks

`realrefine_examples`:
- **[1]** F1: the follower's operating point at gains 1e6, 1e9, 1e12 and 1e15, to 1e-14.
- **[2]** F1: a transient at gains 1e9, 1e12 and 1e15, to 1e-14.
- **[3]** F1 at a gain of 1e12 converges in plain Newton, in at most 5 iterations (126 on E-866).
- **[4]** F2: the ammeter, its load swept from 0.1 Ω to 40 MΩ, reads 0.6217/R to 1e-8.
- **[5]** F2 started at 100 Ω: to 1e-8.
- **[6]** A dc sweep of the VCVS gain from 1e9 down to 1: to 1e-14 (1.1e-7 on E-866).
- **[7]** F3's deck: teraohm dead ends beside a VCVS read v(1) to 1e-12 (3.6e-4 on E-866).
- **[8]** (control) The diagonal shunt stays in the refined solve. Two current sources in a
  cutset need gmin stepping, and its last solve carries `gshunt=1e-6` on both nodes; v(1) is
  −1e-6 / (g + g/(1 + gR)) to 1e-12, the E-866 value to the bit.
- **[9]** (control) The follower wired straight back, and an inverting amplifier, at a gain of
  1e12: exact, as before.
