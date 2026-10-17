# Enhancement-896: the built-in HICUM's Jacobian is its currents' — `ac` at 1 Hz was 2.1 % off the dc derivative at the default t0 = 0

**Scope:** F2 of the
[analyses correctness campaign of 2026-10-16](../docs/bug_hunts/2026-10-16_ngspice-openvaf-r-analyses-correctness-campaign.md),
and two KLU slips found while checking it. The rest of what the dig found is
[E-897](Enhancement-897.md) (values), [E-898](Enhancement-898.md) (pnp) and
[E-899](Enhancement-899.md) (self-heating robustness).

ngspice:
- `spicelib/devices/hicum2/hicumL2.cpp`: the low-injection `Q_0` derivative; `calc_rbi` and
  `calc_ibet` take their bias-dependent inputs as dual numbers.
- `spicelib/devices/hicum2/hicum2bindCSC.c` and `spicelib/devices/soi3/soi3bindCSC.c`: a
  matrix pointer bound twice for KLU, once each.

**ngspice only.**

**Suites:**
- [`hicum2_examples`](../examples/hicum2_examples/), new: checks [1] to [6] are this
  enhancement's, 16 of 16 per solver. On the E-895 binaries 15 of 16 fail; [6], a scan of
  the source tree, passes on any binary.
- The full sweep: 592 of 592.

## What was wrong

`ac` at 1 Hz is the derivative of the operating point. The campaign's Family A found the built-in
HICUM (`level=8`) 9.2e-4 off it, where every other model was within 3.4e-6. The compiled HICUM
L2, with the same card, was within 1e-8.

Four slips, each in a derivative the C++ port computes beside its current:
- **The low-injection hole charge.** With `t0` = 0, its default, the transfer current takes
  the branch that skips the inner Newton for `Q_pT`. The dual seed of that branch's ∂/∂Vbiei
  call read `Q_0*Vbiei`, the charge times the voltage, where every other call passes
  `Q_0_Vbiei`. With only `c10` and `qp0` given, `ac` was 2.07 % off.
- **The internal base resistance.** `calc_rbi` took `Qjei` and `Qf` as dual arguments but read
  `Qjci` and `ibei` from the enclosing scope as plain numbers. ∂rbi/∂Vbici left out the
  conductivity modulation through `Qjci`. ∂rbi/∂Vbiei and ∂rbi/∂T left out the emitter current
  crowding through `ibei`. With `rbi0` = 10: 1.04e-3.
- **The tunnelling current.** `calc_ibet` read `Cjep` and `Cjei` as plain numbers, so ibet's
  derivatives left out the capacitances' bias dependence. With the b-e junction reverse biased
  by 3 V, the base's `ac` gain was 71 % off.
- **KLU.** `hicum2bindCSC.c` bound `HICUMcollTempPtr` twice. The second lookup searched for a
  pointer the first had already moved into the CSC matrix, missed, and set the binding to
  NULL. So `ac` never switched that entry to the complex matrix, and its stamps landed in the
  real one. Self-heating with `rcx` and `zetarcx` gave 3.6e-3 under KLU, nothing under Sparse.
  `soi3bindCSC.c` did the same with `SOI3TOUT_toutPtr`, the thermal node's diagonal.
  An SOI3 stage with `rt` gave −5.29 under KLU against −1.31 under Sparse, with "matrix bindings
  are stale" on stderr.

The transient was unaffected: Newton converges on the currents, whatever the Jacobian. `noise`,
`pz` and `.sp` stamp the same matrix as `ac`.

## The change

- `Q_0+e1*Q_0_Vbiei` in the low-injection ∂/∂Vbiei call.
- `calc_rbi(T, Qjei, Qjci, Qf, ibei)`. Each call seeds the derivative of every argument that
  depends on its variable: `Qjci` for Vbici, `ibei` for Vbiei and T.
- `calc_ibet(Vbiei, Vbpei, T, Cjei, Cjep)`, seeded the same way.
- The second binding of `HICUMcollTempPtr`, and of `SOI3TOUT_toutPtr`, is gone, in each file's
  three binding functions.

## The checks

`hicum2_examples`:
- **[1]** `t0` = 0: `ac` within 1e-6 of the central difference of a three-point `dc` sweep.
  E-895: 2.1e-2.
- **[2]** `rbi0` = 10: within 1e-6. E-895: 1.0e-3.
- **[3]** Tunnelling, b-e at −2 V: the base within 1e-6. E-895: 0.43.
- **[4]** Self-heating with `rcx` and `zetarcx` under KLU: within 1e-6, and equal to Sparse's
  `ac`. E-895: ngspice exits at the `dc` sweep that follows the `ac` (E-899's thermal node); the
  `ac` alone is 3.6e-3 off under KLU.
- **[5]** SOI3 with `rt` under KLU: `ac` equal to Sparse's, no stale binding. E-895: −5.29
  against −1.31.
- **[6]** No device's KLU binding names a matrix pointer twice, unless an `else` separates the
  two. VSRC binds its port and non-port pointers that way.

200 random cards over the model's feature groups (GICCR, base currents, tunnelling, avalanche,
rbi, external resistances, the substrate transistor, every capacitance, transit time, critical
current, vcbar, NQS, lateral spreading, temperature, self-heating), `ac` against the dc
derivative for both the base drive and the supply, with this and E-897 to E-899 together:
- E-895: 74 cards more than 1e-5 off, 54 more than 1e-3, 5 more than 0.1.
- Now: 4 more than 1e-5. Two are finite-difference noise: gains of 0.002 V/V, and a smaller step
  agrees to 1e-6. Two keep 4e-5 and 1e-4 at every step; see Limits.

## Limits

Two of the 200 cards keep a steady 4e-5 and 1e-4 gap between `ac` and the dc derivative, at
every finite-difference step. Both combine GICCR weighting, `rbi0`, tunnelling and the
peripheral b-e current. The gap is 1/10 to 1/100 of a typical `reltol`, and its source was not
found.
