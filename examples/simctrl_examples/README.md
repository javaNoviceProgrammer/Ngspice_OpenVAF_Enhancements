# simctrl_examples — simulation-control tasks + discontinuity rejection (Enhancement-55)

Demonstrates **Enhancement-55**: the simulation-control system tasks
(`$finish`, `$stop`, `$fatal`) actually honored by ngspice, and
`$discontinuity(n>=0)` upgraded from next-step clamping to true **timestep
rejection**, using the committed `openvaf-r` and `ngspice-46`.

## What was broken

- **`$finish` was ignored entirely** — the FINISH eval-return flag was never
  checked in the load path; the transient ran to its full stop time.
- **`$stop` broke timestep control** — its `E_PAUSE` returned
  mid-Newton-iteration was treated as a step failure: the integrator ground
  the timestep down in a rejection loop instead of pausing. Both are now
  **latched per timepoint attempt** and honored at the **accepted-point
  boundary**: `$finish` ends the analysis cleanly — firing `@(final_step)`
  first, per the LRM — and `$stop` pauses resumably. Works in transient and
  DC sweeps.
- **`$fatal` under an op-dependent condition was silently deleted** — its
  `SetRetFlag`/print calls take no op-dependent arguments, so the init/eval
  split hoisted them to instance-init, where the op-dependent branch is
  rewritten to its else edge: the calls sat in an unreachable block and
  vanished from *both* functions. (Root cause: the shared post-dominator
  tree roots at the `exit` sink, so taint propagation never control-tainted
  the fatal arm.) Side-effecting callbacks under op-dependent control now
  stay in eval, and the resulting `E_PANIC` aborts the transient instead of
  being retried as nonconvergence. Parameter-only `$fatal` still validates
  at **setup** (instance rejected before any analysis).
- **`$discontinuity(n>=0)` only clamped the *next* step** (E-24's sentinel);
  the step containing the event still extrapolated across it. It now also
  raises `EVAL_RET_FLAG_DISCONT` (an additive return-flag bit — not an ABI
  break): `OSDItrunc` requests `delta/8` while the flag is set (with a
  `20*CKTdelmin` floor guaranteeing termination), so the integrator
  **rejects the too-large step and bisects onto the event**.

## Run

```
python3 verify_simctrl.py
```

Checks (17, ALL PASS): `$finish` ends the transient exactly at the
requesting point with `@(final_step)` firing there; `$stop` pauses cleanly
at the event; `$fatal` prints its message and aborts (was silently
deleted); parameter-only `$fatal` rejects the instance at setup; a DC-sweep
`$finish` ends the sweep at the requesting sweep value; and the
`$discontinuity` A/B twins show the event step at least 4× smaller (one
rejection bisection) with a sharper, no-later jump.
