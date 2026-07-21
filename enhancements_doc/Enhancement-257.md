# Enhancement-257 — the transient operating point is guarded too

A direct extension of Enhancement-256. E-256 fixed the **silent spurious DC
operating point** for behavioral sources with an infinite derivative at the v = 0
initial guess (`B I=sqrt(v(n))`, `1/v`, `ln(v)`), but gated the false-convergence
guard to `MODEDCOP` only — the pure DC operating point. The **transient operating
point** (`MODETRANOP`, the bias a `.tran` starts from when `uic` is not given) was
left uncovered, so it still false-converged.

## The bug

A `.tran` of a biased circuit computes its starting point with a `MODETRANOP`
operating-point solve. For `B I=sqrt(v(n))` that solve still pinned the node at
`v ≈ 0` and falsely "converged" there — so the transient **started from a spurious
bias** and showed a fake startup transient:

```
t = 0         v(n) = 9.3e-17     <- spurious (should be the 0.178 bias)
t = 1e-7      v(n) = 0.037       <- fake ramp
t = 20ms      v(n) = 0.178045    <- eventually reaches the true equilibrium
```

The circuit is biased and should sit at `0.178` from `t = 0`; the `0 → 0.178`
ramp is an artifact of the wrong operating point.

## The fix

E-256's guard was safe to gate at `MODEDCOP` because of the `CKTdcFirstTry`
isolation (it fires only on the initial plain-Newton attempt, never inside a
convergence-aid sub-solve). The pseudo-transient / `optran` aids run in transient
modes, which is exactly why E-256 conservatively excluded `MODETRANOP`. But since
the guard already only fires when `CKTdcFirstTry` is set — and `optran` runs as a
*fallback* with `CKTdcFirstTry = 0` — it is safe to extend the mode condition to
`MODEDCOP || MODETRANOP`. One-line change in `maths/ni/niiter.c` (the residual
computation and the rejection check both broaden to the transient op).

Now the `.tran` operating point starts at the true bias `0.178045`, and every
convergence aid (`convhelp`, `ptcont`, `optran`, gmin/source stepping) still runs
untouched.

## Verification

`examples/bsrcconv_examples/verify_bsrcconv.py` gains check **[4]**: a `.tran` of
the biased `sqrt(v)` source has `v(n)` at `t = 0` equal to the true bias
`0.178045` (pre-fix `~9e-17`, a fake startup transient) — both solvers. Checks
[1]–[3] (the DC op fix and result-neutrality) are unchanged.

The full regression — including the convergence-aid suites `convhelp`, `ptcont`,
`corenum`, `tempphys` — passes on both solvers.

## Scope

One-line broadening of the E-256 false-convergence guard in `maths/ni/niiter.c`
from `MODEDCOP` to `MODEDCOP || MODETRANOP`; the ngspice binary is rebuilt. Still
confined to the first operating-point attempt via `CKTdcFirstTry`; result-neutral
for every circuit that already converged.
