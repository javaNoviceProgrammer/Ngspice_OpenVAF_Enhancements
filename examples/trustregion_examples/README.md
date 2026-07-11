# trustregion_examples — Levenberg-Marquardt trust-region Newton (Enhancement-153)

`.option trustregion` adds a **Levenberg-Marquardt (trust-region) globalized
Newton** for the DC operating point, alongside the Enhancement-111 line search.
Where the line search only *shortens* a fixed Newton direction, the trust-region
also *re-aims* the step by damping the Jacobian diagonal.

## What it does

At each iteration the true KCL residual `‖F(x)‖ = ‖G·x − b‖` is monitored (the
E-111 merit). If the just-solved step would **increase** the residual, it is
**rejected**: the damping `lambda` is grown and the step is retried with

```
x_{k+1} = x_k − (J + mu·I)^-1 F(x_k),   mu = lambda·‖diag(J)‖
```

(the diagonal damping applied at factor time, plus the matching `mu·x_k` RHS
coupling — the same mechanism Enhancement-127's pseudo-transient uses). The
`‖diag(J)‖` scale makes `lambda` dimensionless (Marquardt scaling). As `mu`
grows, the step rotates from the Newton direction toward steepest descent,
**regularizing an ill-conditioned or near-singular Jacobian** — something a line
search cannot do. Because the fixed point is `F = 0` for **any** `mu`, and
`lambda` relaxes back to 0 once steps succeed, the method converges to the **same
operating point** as plain Newton.

## Honest scope

`.option trustregion` is **result-neutral** and off by default. In practice, on
ordinary circuits it is **inert**: ngspice already prevents the residual-increasing
overshoot a trust-region would catch, one layer lower — through **per-device
junction limiting** (`limexp` / `pnjlim` / `fetlim` across 30 device families),
which damps the controlling voltages before the residual is ever computed. So the
damping stays at `lambda = 0` and the step is never rejected on the circuits here.
The option provides a *solver-level* regularization for the (unusual) cases where
the device-level machinery and the gmin/source-stepping homotopy do not suffice,
and completes the damped/trust-region-Newton capability.

## Files

- **`trustregion_demo.cir`** — a diode circuit solved with plain Newton and again
  with `.option trustregion`; the same operating point to 12 digits.
  Run with `ngspice -b trustregion_demo.cir`.
- **`verify_trustregion.py`** — validation, under **both** the Sparse and KLU
  solvers (the method lives in the solver-independent Newton loop):
  1. **result-neutrality** — `.option trustregion` gives the **bit-identical** DC
     solution as plain Newton (diode, BJT, resistor divider);
  2. **correctness** — the solution matches the analytic value;
  3. **transient neutrality** — a diode-RC transient is unchanged (the trust-region
     touches only the DC/tran operating point, not the timesteps).

```
python3 verify_trustregion.py
```

## Notes

- Trust-region and the E-111 line search are mutually exclusive; `trustregion`
  takes precedence if both are set.
- Every SPICE deck's first line is the **title** (ignored by the parser).
