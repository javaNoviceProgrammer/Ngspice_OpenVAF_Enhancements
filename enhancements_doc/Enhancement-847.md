# Enhancement-847: an inductor's truncation-error floor is a voltage tolerance — `abstol`, a current, stood in for it, and a linear L–C network collapsed under KLU at reltol 1e-7 with a small `chgtol`

**Scope:** the rest of F3 of the
[second robustness and correctness campaign of 2026-10-10](../docs/bug_hunts/2026-10-10_ngspice-openvaf-r-second-robustness-campaign.md),
after [Enhancement-846](Enhancement-846.md).

ngspice:
- `spicelib/analysis/cktterr.c`: the estimate takes its absolute floor as a parameter.
  `CKTterr` keeps `abstol`, and the new `CKTterrFlux` uses `vntol`.
- `spicelib/devices/ind/indtrunc.c`: the inductor calls `CKTterrFlux`.
- `include/ngspice/cktdefs.h`: its prototype.

`examples/firststep_examples/` [3]. **ngspice only.**

**Suites:**
- [`firststep_examples`](../examples/firststep_examples/): with Enhancement-846 alone, its check at
  `reltol=1e-7, chgtol=1e-20` passes under Sparse and fails under KLU with "Timestep too small".
  With this enhancement it passes under both.
- The full sweep: 553 of 553.

## What was wrong

`CKTterr` estimates a state's local truncation error and bounds it by
`trtol·max(volttol, chargetol)`:
- `volttol` = `abstol` + `reltol`·|the state's derivative|;
- `chargetol` = `reltol`·max(|the state|, `chgtol`)/h.

For a capacitor the state is a charge and its derivative a current, so `abstol`, 1e-12 A, is
the right floor. An inductor calls the same function on its flux, whose derivative is the
voltage across it. Its floor was still `abstol`: 1e-12 used as volts.

For an inductor with no dc current, the flux and its derivative both start near zero, and
`chgtol` is the only other relief. With `chgtol` small that is gone, and the estimate asks for
steps that the solve's own rounding decides.

F3's reduced L–C network shows it. With Enhancement-846, at `reltol=1e-7, chgtol=1e-20`, it runs
under Sparse and still collapses under KLU, whose rounding differs. An earlier cut of
Enhancement-846, which accepted a first step at its floor, collapsed under both. Raising
`abstol` to 1e-6 cured that and 1e-9 did not, which is what a voltage floor of 1e-12 predicts.

## The change

The estimate's absolute floor is a parameter. `CKTterr` passes `abstol` as before, for every
charge state. The new `CKTterrFlux` passes `vntol`, the voltage tolerance, 1e-6 V by default,
and `INDtrunc` calls it. Mutual inductance couples inductor fluxes and is covered with them.

An inductor's step control is looser only where its voltage is below `vntol`; the relative part
is unchanged.

## The checks

`firststep_examples` [3]: the reduced network at `reltol=1e-7, chgtol=1e-20` runs to tstop under
both solvers. The 14 hardest of the campaign's Family D runs, under Sparse, come out the same
with this floor as without it.
