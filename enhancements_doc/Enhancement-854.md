# Enhancement-854: an OSDI device's non-finite load is named — `ln(V(x))` at Newton's zero start ended the operating point "cause unrecorded", naming neither the device nor the value

**Scope:** F10 of the
[second robustness and correctness campaign of 2026-10-10](../docs/bug_hunts/2026-10-10_ngspice-openvaf-r-second-robustness-campaign.md).

ngspice:
- `osdi/osdiload.c`: `nonfinite_count` and `nonfinite_report`, around each instance's load.
- `osdi/osdidefs.h`: `nonfinite_told`, once per instance.
- `include/ngspice/cktdefs.h`: `CKTtroubleNonfinite`, cleared with `CKTtroubleElt` in
  `cktdojob.c` and `cktinit.c`.
- `spicelib/analysis/ckttroub.c`: names that instance first.

`examples/osdinonfinite_examples/` (new). **ngspice only.**

**Suites:**
- [`osdinonfinite_examples`](../examples/osdinonfinite_examples/): 5 of 5 per solver. On the
  E-852 binaries checks [1] to [4] fail; [5] is a control.
- The full sweep: 560 of 560.

## What was wrong

```verilog
`include "disciplines.vams"
module q(x, o); inout x, o; electrical x, o;
analog V(o) <+ ln(V(x));
endmodule
```

With `vx x 0 1.056`, Newton's zero start evaluates ln(0) = −∞, with an infinite derivative.
Every homotopy restarts from the same point. The operating point ended `Timestep too small;
cause unrecorded`, naming neither the device nor the value that is not finite. Under KLU it named
"trouble with node o", the singular row that the NaN made.

A B-source `v=ln(v(x))` converges, since ngspice's own `ln()` is guarded. The model is at fault,
but the user was not told which one.

## The change

As each OSDI instance loads, `nonfinite_count` counts the entries that are not finite:
- in the right-hand side at its nodes;
- in its Jacobian entries.

It counts once before the load and once after, so a value another device left there is not
charged to this one. When the count rises:
- the instance becomes `CKTtroubleElt`, and also `CKTtroubleNonfinite`. `CKTtrouble` names the
  latter before a singular node, since the singular row is the consequence.
- A warning, once per instance, says which value it is and at what terminal voltages.

The result:

```
Warning: n1 (Verilog-A module q) loaded a value that is not finite: the residual of flow(o) is
NaN, at x = 0 V, o = 0 V. Newton cannot continue from it; if the analysis fails, the model needs
a guard at these voltages.
doAnalyses: OP:  Timestep too small; trouble with qm-instance n1, which loaded a value that is not finite
```

The warning does not say the analysis failed. A model can overflow on one wild Newton step and
recover when the step is cut.

The SPICE right-hand side carries J·v, so a Jacobian entry that is not finite usually shows in
the residual too. A current 1/(1 + 1/V) is 0 at 0 V and is still caught.

## The checks

`osdinonfinite_examples`, with three models:
- **[1]** `ln(V(x))` at the zero start: the op fails "trouble with lm-instance n1", not "cause
  unrecorded".
- **[2]** The warning names `n1`, module `lnout`, the residual of `flow(o)`, NaN and x = 0 V,
  once.
- **[3]** The same in a transient: the initial timepoint names `n1`.
- **[4]** A current 1/(1 + 1/V), whose derivative at 0 V is not finite: named.
- **[5]** (control) The same `ln()` with a guard converges, with no warning.
