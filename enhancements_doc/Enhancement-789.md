# Enhancement-789: `@(initial_step)` fires once in a sensitivity analysis — the perturbation and frequency passes re-fired it up to eleven times against one `@(final_step)`

**Scope:** F6 of the
[openvaf-r hunt of 2026-10-04](../docs/bug_hunts/2026-10-04_openvaf-r-run-time-domains-filters-and-instances.md).
ngspice: `src/osdi/osdisetup.c` (`OSDIholdInitialStep`; the two resets of `has_evaluated`, in setup
and in the temperature pass, skipped while held), `src/include/ngspice/osdiitf.h` (the declaration),
`src/spicelib/analysis/cktsens.c` (held from the base operating point to the end, released on both
exits). `examples/finalstep_examples/` (a module `fsinit` and section [9], twelve checks).
**ngspice only.**

**Suites:** [`finalstep_examples`](../examples/finalstep_examples/) 47 of 47 per solver (3 per solver
fail on the E-788 binaries: the two sensitivity forms and the op after one); the full sweep, 536 of
536.

## What was wrong

E-7 fires `@(initial_step)` on an instance's first evaluation of an analysis: setup and the
temperature pass clear a per-instance `has_evaluated` mark, and the next evaluation carries
`EVAL_FLAG_IS_INITIAL_STEP`. E-683 made every analysis, `sens` included, fire `@(final_step)` once.
Sensitivity analysis, though, re-runs setup and the temperature pass inside itself:

- per perturbed parameter, `cktsens.c` calls the device's `DEVsetup` on the perturbation matrix and
  its `DEVtemperature` (`sens_temp`) before loading it;
- per frequency of an AC sensitivity, it calls `CKTunsetup`, `CKTsetup` and `CKTtemp`.

Each pass cleared the mark, and the next load fired `@(initial_step)` again:

| analysis | `initial_step` | `final_step` |
|---|---|---|
| `sens v(a)`, a module with two parameters | 11 | 1 |
| `sens v(a) ac lin 3 1k 10k` | 4 | 1 |
| op, dc, ac, tran, noise, tf, pz, disto, sp | 1 | 1 |

A model that opens a file in `@(initial_step)` and closes it in `@(final_step)` opened eleven and
closed one; one that resets a counter, a seed or a running maximum there reset it on every
perturbation.

## The change

`OSDIholdInitialStep(true)` after the base operating point of `sens_sens` (which fires
`@(initial_step)` once, as every analysis does), `OSDIholdInitialStep(false)` before E-683's final
step and on the error exit. While held, `OSDIsetup` and `OSDItemp` leave `has_evaluated` alone. The
model-restore pass at the end (E-440, which runs `CKTtemp`) is inside the hold as well; the next
analysis's own setup clears the mark as before.

## The checks

finalstep [9], with `fsinit`, a module that counts its `@(initial_step)` firings into a variable its
`@(final_step)` prints, and two parameters for the dc sensitivity to perturb:

- `sens v(a)`: one `initial_step`, one `final_step`, the counter 1 at the end;
- `sens v(a) ac lin 3 1k 10k`: the same;
- an `op` after a `sens` fires its own `initial_step` (the hold is released);
- op, dc, ac, tran, noise, tf, pz, disto and sp: one of each.

On the E-788 binaries the counter read 1 at the end too — each pass's setup also reset the hidden
state — so the firings, not the counter, show the fault.

## Limits

- The hold is specific to sensitivity analysis, the one analysis that re-runs setup inside itself.
  A `.control` loop that runs several analyses fires `@(initial_step)` once per analysis, as before.
