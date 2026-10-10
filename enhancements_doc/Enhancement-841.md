# Enhancement-841: `sens` binds the devices it perturbed back to the circuit's matrix — a second `.sens`, or an `.sp` after one, loaded through freed memory

**Scope:** F4 of the
[robustness and correctness campaign of 2026-10-10](../docs/bug_hunts/2026-10-10_ngspice-openvaf-r-robustness-and-correctness-campaign.md).

ngspice: `spicelib/analysis/cktsens.c`:
- `sens_rebind` re-runs the setup once the perturbations are done, on both ways out.
- The error path puts the circuit's matrix and right-hand sides back.

`examples/jobreset_examples/` (section [6]). **ngspice only.**

**Suites:**
- [`jobreset_examples`](../examples/jobreset_examples/): 21 of 21 per solver, under macOS Guard
  Malloc. 4 of the 5 checks in [6] fail on the E-840 binaries, all with SIGSEGV; the other is a
  control.
- The full sweep: 549 of 549.

## What was wrong

```spice
v1 in 0 dc 1
r1 in mid 1k
r2 mid 0 3k
.sens v(mid)
.sens v(mid)
.control
run
.endc
```

The first `sens` reported `r1 = -1.875e-04`. The second failed its operating point on the same
divider: `singular matrix: check node in`, every homotopy failed, "SENS: Timestep too small",
exit status 1. Under macOS Guard Malloc it faulted in the device load:

```
RESload+64 <- CKTload <- NIiter <- CKTop <- sens_sens <- CKTdoJob
```

To perturb a parameter, `sens_sens` swaps in a matrix of its own (`delta_Y`) and re-runs that
model's `DEVsetup` into it. That binds the model's instances' matrix pointers, such as
`RESposPosPtr`, to `delta_Y`'s elements. The ac path re-ran the full setup at every frequency
but the last; the dc path never did. Then `sens` freed `delta_Y`, and the perturbed devices
were left pointing into freed memory. The next load that came without a new setup wrote through
those pointers and stamped nothing into the circuit's matrix.

Within one `run` the analyses go in a fixed order, and the circuit is set up once:
- Op, dc, ac and transient run before `sens` and never noticed.
- A second `.sens` and an `.sp` run after it, and both were hit: a `.sens` followed by an `.sp`
  faulted under Guard Malloc as well. A `.pss` or an `.hb` comes after `sens` in the same order,
  so they stood in the same place; neither was tested.
- An interactive command after `sens` starts a new task with a fresh setup and was safe.

The error path had a second slip: an error inside the perturbation loop left
`CKTmatrix`, `CKTrhs` and `CKTirhs` pointing at `sens`'s own arrays.

## The change

Once the last perturbation is done, `sens_rebind` re-runs `CKTunsetup`, `CKTsetup` and `CKTtemp`.
That is the re-setup the ac path already did per frequency, and it binds every device back to
the circuit's matrix under either solver. It runs only when a `DEVsetup` actually went into
`delta_Y`. Enhancement-683's restore then puts the base operating point into the fresh
`CKTrhsOld` and fires `@(final_step)` as before.

The error path puts the matrix and right-hand sides back first and then rebinds. A failed
re-setup is now returned rather than dropped.

## The checks

`jobreset_examples` [6]:
- Two dc `.sens` in one deck: both give `d v(mid)/d r1` = −1.875e-4, with no singular matrix.
- A dc `.sens` and an ac `.sens`: |d v(mid)/d r1| = 1.875e-4 in each.
- Two `.sens` over an OSDI resistor: `d v(mid)/d r2` = r1/(r1+r2)² = 6.25e-5 both times. That
  covers E-351's node-reuse path.
- A `.sens` then an `.sp`: both plots are produced.
- One `.sens` (control).
