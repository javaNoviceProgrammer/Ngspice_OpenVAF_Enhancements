# Enhancement-878: a transient step whose Newton iteration fails is retried from where the step started — one iteration that ran to 1e10 V ended a Van der Pol oscillator's run under every method and solver

**Scope:** F5 of the
[transient stress campaign of 2026-10-12](../docs/bug_hunts/2026-10-12_transient-sparse-klu-stress-campaign.md).

ngspice: `spicelib/analysis/dctran.c`: `acc_save` before each step's solve, `acc_restore` when the
solve does not converge. Stock ngspice-46 behaviour.

`examples/newtonretry_examples/` (new). **ngspice only.**

**Suites:**
- [`newtonretry_examples`](../examples/newtonretry_examples/): 4 of 4 per solver. On the E-875
  binaries [1] to [3] fail; [4] is a control.
- The campaign's Family C: the tight trap references (`reltol=1e-6`, KLU) of the 440 nonlinear
  decks fail in 40 cases instead of 59. All 17 Van der Pol failures are gone, and 2 of the 7 boost
  converters'. The 35 charge pumps' are N1's, switches without hysteresis.
- The full sweep: 583 of 583.

## What was wrong

```
* Van der Pol from a B-source: a bounded limit cycle, peak 2.0198 V (scipy Radau, rtol 1e-10)
l1 x 0 78.66u
c1 x 0 1.113p
b1 x 0 i=0.000595*(v(x)^3/3 - v(x))
r1 x 0 1e6
.ic v(x)=0.0458
.control
tran 1.41n 0.706u uic
.endc
.end
```

At about 38 ns, at the first fast swing, the run printed `b1: expression evaluated to infinity`
and then `Timestep too small; time = 3.80136e-08, timestep = 1.7625e-21: trouble with node "x"`.
The same happened under trap, Gear, `trbdf2` and `sdirk`, Sparse and KLU, at `reltol` 1e-3 to
1e-6. The output it left peaked at 5.9e102 V.

`PREDICTOR` is not compiled in, so a transient step starts at `CKTrhsOld`. When a step did not
converge, `DCtran` cut the step by 8 and solved again, from `CKTrhsOld`. That still held the
failed step's last iteration, which had run out to 1e10 V and beyond. From there a cubic needs some
60 Newton steps to come back, against `itl4`'s 10, at any step size. With the cubic's argument
clamped at ±1 kV, which the true path never reaches, the run went through; clamped at ±1e10 V it
failed as before. So it was not the overflow: once one iteration had gone far, no retry recovered.

## The change

The solution a step starts from is kept, and a step that does not converge is retried from it. A
fresh step starts there too, so a retry is a fresh step with a smaller delta. The first step keeps
[Enhancement-846](Enhancement-846.md)'s retry from t = 0. A step rejected for its truncation error
is retried as before.

The oscillator now runs to the end under every method and both solvers. At `reltol=1e-6` it peaks
at 2.019945 V against scipy's 2.0198.

## The checks

`newtonretry_examples`, on the oscillator above:
- **[1]** It runs to the end under trap, Gear, `trbdf2` and `sdirk`.
- **[2]** At `reltol=1e-6` its peak is within 0.1 % of 2.0198 V.
- **[3]** With the cubic's argument clamped at ±1e10 V it also runs.
- **[4]** (control) Clamped at ±1 kV it runs at `reltol=1e-6` and peaks within 0.1 % of
  2.0198 V.
