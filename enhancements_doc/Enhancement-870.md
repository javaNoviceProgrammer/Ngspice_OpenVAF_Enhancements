# Enhancement-870: `sens … ac` moves a coupled inductor's mutual inductance with its inductance — the sensitivity to L1 held M fixed

**Scope:** F4 of the
[Sparse and KLU correctness campaign of 2026-10-11](../docs/bug_hunts/2026-10-11_sparse-klu-correctness-campaign.md).

ngspice:
- `spicelib/analysis/cktsens.c`: `sens_couples`. When the perturbed device is an inductor,
  the couplings are set up into `delta_Y` beside it, and `sens_temp` and `sens_load` take them
  in.
- `spicelib/devices/ind/muttemp.c`: `MUTfactors`, declared in `indext.h`.

`examples/senscouple_examples/` (new). **ngspice only.**

**Suites:**
- [`senscouple_examples`](../examples/senscouple_examples/): 5 of 5 per solver. On the E-869
  binaries [1], [2] and [3] fail under both solvers; [4] and [5] are controls.
- The campaign's family F, run again, against the exact derivative: all 288 flagged values per
  solver were inductors coupled by a `K`. Now none of them is flagged. Coupled inductors come
  within 3.2e-9 on the ordinary networks and 9.7e-7 on the inductor-heavy ones. The rest are
  unchanged, the one flag left being an output that is identically 0.
- `senscentral`, `sensstate`, `libsens`, `analyses` and `klubind` pass.
- The full sweep: see [Enhancement-872](Enhancement-872.md), folded with it.

## What was wrong

```
v1 1 0 dc 0 ac 1
r1 1 2 50
l1 2 0 10u
l2 3 0 40u
k1 l1 l2 0.9
r2 3 0 200
.control
sens v(3) ac lin 1 100k 100k
print l1
.endc
```

`sens` gave 2527.59 − 977.07j, and a central difference of two `alter l1` runs gave
5086.58 + 9447.94j. The exact derivative with M = k√(L1L2) following L1 is the second. With M
held at its nominal value it is the first: 4 times smaller, with the sign of the imaginary part
flipped.

`sens` measures a parameter by re-running only its own device's setup, temperature and load
into a scratch matrix, at p ± δ. A K element is a device of its own (MUT), whose M `MUTtemp`
computes from the two inductances, so the inductor's perturbation never reached it. The deck
names k, not M, and `alter` re-runs every device's temperature, M included, so `alter` moved M
and `sens` did not. Dc sensitivities are not affected, since an inductor is a short at dc.

## The change

When the perturbed device is an inductor and the circuit has couplings:
1. **Setup.** `MUTsetup` runs into `delta_Y` beside the inductor's setup.
2. **Temperature.** After the inductor's temperature, `MUTfactors` recomputes every coupling's
   M = k√(L1L2) from the inductances as they stand. That is the one line of `MUTtemp` it needs,
   without the system checks and their reports.
3. **Load.** `MUTacLoad` loads the couplings at both values. A coupling of other inductors
   loads the same M twice and cancels exactly.

The couplings' pointers go back to the circuit's matrix with the re-setup Enhancement-841 already
does after the perturbations. `MUTtemp` itself would have run the system check at every
perturbation and, before [Enhancement-872](Enhancement-872.md), written into freed memory.

`sens` now gives 5086.5764562 + 9447.9387789j under both solvers, the exact derivative to
1.3e-9.

## The checks

`senscouple_examples`: a transformer with an uncoupled third inductor, against the exact complex
MNA (numpy):
- **[1]** d v(3)/d l1, the coupled primary, to 1e-6 of the exact value.
- **[2]** d v(3)/d l2, the coupled secondary, to 1e-6.
- **[3]** `sens` d/dl1 agrees with a central difference of two `alter`ed ac runs, to 1e-5.
- **[4]** (control) d/dk1, right before, to 1e-6.
- **[5]** (control) An uncoupled l3 and a resistor r1, right before, to 1e-6.
