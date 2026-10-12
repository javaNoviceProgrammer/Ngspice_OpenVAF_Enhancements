# Enhancement-873: dynorder's high orders no longer explode — the truncation estimate at order 3 and above was (k+1)!/3! too small, and an RLC network that peaks at 0.919 V reached 9e22 V

**Scope:** F1 of the
[transient stress campaign of 2026-10-12](../docs/bug_hunts/2026-10-12_transient-sparse-klu-stress-campaign.md).

ngspice: `spicelib/analysis/cktterr.c`, `terr`: at order k ≥ 3 the error constant is scaled by
(k+1)!/3!.

`examples/dynstable_examples/` (new). **ngspice only.**

**Suites:**
- [`dynstable_examples`](../examples/dynstable_examples/): 5 of 5 per solver. On the E-872
  binaries [1] to [3] fail; [4] and [5] are controls.
- `dynorder`, `corenum`, `integmethod`, `maxordnote` and `opamp741` pass under both solvers.
- The campaign's Family A, rerun on its 540 networks with the dynorder and Adams settings: no run
  blows up. The worst error relative to the same network's trap run was 7e192×. It is now 646×:
  a `dynorder` run 5.8e-4 off at `reltol=1e-4` where trap happens to be 9e-7 off, as on E-872.
- The full sweep: 579 of 579.

## What was wrong

```
* nine elements; every node has a dc path
v1 in 0 pwl(0 -0.6 0.697u 0.19 0.70u 0.92 1.08u -0.7)
r1 in a 13.8k
r2 a b 21.2k
l1 b c 2.32u
l2 d b 6.7u
l3 e c 0.125u
r3 f d 44.9
c1 f e 1.23p
i1 e f sin(-0.42m 0.56m 164k)
.option method=gear maxord=6 dynorder
.control
tran 9n 1.82u
.endc
.end
```

The node c peaks at 0.919 V. Under `method=gear maxord=4 dynorder` it reached 2.5e7 V, at `maxord=6`
9e22 V, and under `method=adams maxord=3 dynorder` 1.2e8 V. Every run ended with status 0 and
nothing said, under both solvers. Tightening the tolerance made it worse: at `reltol=1e-5`,
`maxord=6` reached 9e34.

`dynorder` ([Enhancement-128](Enhancement-128.md)) chooses the order whose truncation estimate
allows the largest step. That estimate was wrong above order 2. The constants in `CKTterr` (1/12
for trap, 2/9 to 20/343 for Gear 2 to 6) are error constants for the derivative q⁽ᵏ⁺¹⁾.
`CKTterr` multiplies them by the (k+1)-th divided difference of the charge history, which is
q⁽ᵏ⁺¹⁾/(k+1)!. SPICE's default `trtol` of 7 stands in for the missing 3! = 6 at order 2, the only
orders SPICE uses. At order k the estimate was still (k+1)!/3! too small: 4 at order 3, 20 at 4,
120 at 5, 840 at 6.

So `dynorder` took the high orders for 20 to 840 times cheaper than they were. It went to order 4
at steps of 9 ns, where the network has a pole pair at 47 MHz with a Q of 60. There BDF 4 to 6
amplify instead of damping. The amplified mode grows smoothly and its tolerance grows with it, so
the order-4 estimate kept allowing 13 ns while v(c) went from 1 V to 21 V.

## The change

At order k from 3 to 6 the constant is multiplied by (k+1)!/3!, so every order is measured on the
footing trtol was set for. Orders 1 and 2 are left as SPICE has them, so every run that does not
go above order 2 is unchanged to the bit. That is every run without `dynorder` except `sdirk`'s,
whose order is 3: its estimate is now 4 times larger, as it should be
([Enhancement-874](Enhancement-874.md) measures it). `ordfix` runs at any order are unchanged too,
since they set the step regardless of the estimate.

The reproducer now gives a peak of 0.919 V and an end value of −0.6996 V at every `maxord`, and
under Adams, the conservative preset and `reltol=1e-5`. `dynorder` keeps its gains on smooth
circuits:
- E-128's RC: 228 rows against stock's 670, at 0.015 % error against 0.041 %.
- E-128's LC: 534 rows against 3 535, at 0.090 % error against 0.343 %.

## The checks

`dynstable_examples`, on the network above against a `reltol=1e-7` trap run:
- **[1]** `gear maxord=4`, `5` and `6` with `dynorder` agree in peak and end value.
- **[2]** `adams maxord=3` and `4` with `dynorder` agree.
- **[3]** `errpreset=conservative` with `gear maxord=4 dynorder`, and `gear maxord=6 dynorder`
  at `reltol=1e-5`, agree.
- **[4]** (control) `dynorder` still climbs to order 4 on a smooth LC, in fewer steps than the
  stock controller.
- **[5]** (control) An RC discharge under `gear maxord=4 dynorder` lands within 0.1 % of
  exp(−8).
