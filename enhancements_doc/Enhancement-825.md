# Enhancement-825: a Verilog-A `$fatal` raised while `sens` perturbs a parameter aborts the analysis, and `$finish` and `$stop` end it

**Scope:** F9 of the
[ngspice + OSDI hunt of 2026-10-08](../docs/bug_hunts/2026-10-08_ngspice-osdi-hierarchy-sweeps-events-and-outputs.md).

ngspice:
- `spicelib/analysis/cktsens.c`:
  - names each perturbation for the OSDI layer;
  - reads what the perturbed setup pass and load raised;
  - aborts on a `$fatal`, or ends on a `$finish` or `$stop`, once the parameter is back;
  - its error exit now restores `CKTbypass`.
- `osdi/osdicallbacks.c`: `OSDIsensPerturbing` labels the messages raised during a
  perturbation, and `OSDIfatalsReported` counts the `$fatal` messages.
- `include/ngspice/osdiitf.h`: their declarations.

`examples/libsens_examples/` (section [3], six checks). **ngspice only.**

**Suites:** [`libsens_examples`](../examples/libsens_examples/) 18 of 18 per solver (4 of the 6
checks in [3] fail on the E-822 binaries; the other two are the op after the analysis and a
perturbation that trips nothing). The full sweep, 544 of 544.

## What was wrong

A model with `if (g > lim) $fatal(...)` and nominal `g` = `lim`: the first upward
perturbation trips it.

```
OSDI(fatal) n1: g 0.001 over limit (at the operating point)
n1:g = -2.50000e+02
... every other sensitivity ...
```

The analysis was not aborted and printed its results, while op, dc, tran, ac and noise all
abort on `$fatal`. The label said "at the operating point" for a perturbation. `$stop` and
`$finish` raised the same way were ignored without a word, where op, dc and tran act on each
and say so.

The perturbation loop discards what its device calls return:
- `(void) sens_temp(...)`, the setup and temperature pass at the perturbed value;
- a bare `sens_load(...)`, the evaluation, whose `E_PANIC` carried the `$fatal`.

It never looked at the `$finish`/`$stop` requests. And a `$fatal` in code that reads only
parameters runs in the setup pass. In an AC `sens` no evaluation follows to return a flag at
all.

## The change

- **The label.** Before it perturbs a parameter, `sens` names it for the OSDI layer
  (`n1:g to 0.001000001`). A message raised by the setup pass or the load is labelled "(while
  sens perturbed n1:g to 0.001000001)".
- **The detection.** After the perturbed load, the perturbation raised a `$fatal` if any of
  these holds:
  - the load returned `E_PANIC` with a Verilog-A fatal recorded;
  - a `$fatal` message was reported since the perturbation began (counted at the log callback,
    which catches a setup pass's);
  - a deferred fatal (Enhancement-703) is newly pending.

  A newly pending `$finish` or `$stop` request is that task.
- **The action.** The parameter is put back first, as the loop always does (the value, and the
  model and instance snapshots of Enhancements 440 and 685). Then:
  - **`$fatal`:** an error naming the perturbation, and the analysis aborts. The models are
    restored, as on every error exit. No results are printed.
  - **`$finish`, `$stop`:** a Note naming the perturbation, and `sens` ends at its last
    completed point, through its normal end: plot closed, models back, `@(final_step)` fired.
    The sensitivities of the point being computed are not reported. `$stop` cannot pause
    there, because the perturbation loop cannot resume, and the Note says so.
- **`CKTbypass`.** `sens` switches bypass off for its run. Its error exit now switches it back
  on. It used to stay off for the rest of the session after any failed `sens`.

## The checks

`libsens_examples` [3]:
- DC `sens`, `$fatal` on the first upward step: aborted. The error and the device's line both
  name `n1:g to 0.001000001`, and no sensitivity is printed.
- The `op` after it runs on the netlist's `g`: v(2) = 0.5.
- AC `sens`, the same `$fatal`, raised in the setup pass: aborted.
- `$finish`: a Note, no sensitivities.
- `$stop`: the same, and the Note says `sens` cannot pause there.
- A perturbation inside the limit (control): `sens` completes, n1:g = −250.
