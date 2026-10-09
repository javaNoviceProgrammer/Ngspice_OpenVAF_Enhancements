# Enhancement-821: a `.dc` sweep stopped by a `$fatal` puts the swept source or parameter back

**Scope:** F5 of the
[ngspice + OSDI hunt of 2026-10-08](../docs/bug_hunts/2026-10-08_ngspice-osdi-hierarchy-sweeps-events-and-outputs.md).

ngspice:
- `spicelib/analysis/dctrcurv.c`:
  - `DCTrestoreSwept` is the restore loop, taken out of the sweep's end.
  - A new exit, `dct_abort`, restores. Every abort in the sweep goes through it.

`examples/sweepstate_examples/` (section [2], three checks). **ngspice only.**

**Suites:** [`sweepstate_examples`](../examples/sweepstate_examples/) 18 of 18 per solver (2 of
the 3 checks in [2] fail on the E-819 binaries; the third is the `$stop` control). The full
sweep, 543 of 543.

## What was wrong

```spice
v1 1 0 1
n1 1 0 fm          ; $fatal when V > 1.5
dc v1 0 3 1        ; stops at 2 V
print @v1[dc]      ; 2 -- the netlist says 1
op                 ; runs at 2 V and raises the same $fatal again
```

The sweep restores what it swept at its end, after a `$finish`, and after a refused point
(Enhancement-427). Every other exit returned with the knob at the failing value:
- a `$fatal` raised in the solve (Enhancement-673's message);
- a fatal judged on the accepted point (Enhancement-703);
- a point that did not converge;
- a parameter refused when an inner level went back to its start;
- an error from the sensitivity pass or from the output setup.

Every later analysis ran on that value until `reset`. A parameter sweep, `dc @fpm[g] 1m 4m 1m`
stopped at 3m, did the same. A temperature sweep was not affected: the next job's setup
re-reads the temperature.

Only `E_PAUSE` leaves a run resumable (`if_run`). An aborted run sets `ci_inprogress` false.
So nothing could use the value it left behind.

## The change

Every abort sets the sweep's return code and jumps to `dct_abort`:
- **On an abort:** `dct_abort` puts every level back, as the sweep's end does, and returns the
  code. It fires no `@(final_step)` and ends no plot, as before.
- **On a pause:** `$stop` and an interactive pause still return with the values in place, for
  `resume`.

## The checks

`sweepstate_examples` [2]:
- `dc v1 0 3 1` stopped by `$fatal` at 2 V: `@v1[dc]` is back to 1 (was 2). The next `op` runs
  (i(v1) = −1 mA), and the `$fatal` prints once.
- `dc @fpm[g] 1m 4m 1m` stopped by `$fatal` at 3m: `@fpm[g]` is back to 1m (was 3m), and the
  next `op` runs.
- `$stop` at 2 V (control): `@v1[dc]` stays 2 for `resume`.

## Limits

- A sweep that fails to converge could not be provoked here. It takes the same exit as the
  `$fatal`.
