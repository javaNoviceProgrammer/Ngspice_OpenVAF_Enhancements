# Device aging (reliability degradation flow) — Enhancement-157

`aging <t_target>` ages every aging-capable device in the loaded circuit to a
target operating lifetime and **re-stamps** the circuit, so any analysis run
afterwards sees the degraded devices. It is the industry "stress → degrade →
re-simulate (fresh vs aged)" reliability flow (HCI / NBTI / TDDB), built on top
of the Verilog-A / OSDI device layer.

```
aging <t_target> [rate <opvar>] [param <ageparam>] [dynamic <tstop> [tstep]] [verbose]
```

## How a model opts in

The command is **model-agnostic**: a device participates by exposing two things
in its Verilog-A source (see [`agemos.va`](agemos.va), a square-law NMOS with an
NBTI-style threshold shift):

* a **degradation-rate operating-point variable** — default name `agerate` —
  the instantaneous stress rate at the present bias, in *dose units per second*
  (here, gate overdrive above the fresh threshold):

  ```verilog
  (* desc="NBTI aging rate", units="V/s" *) real agerate;
  ...
  agerate = (V(g,s) > vth0) ? (V(g,s) - vth0) : 0.0;
  ```

* a **per-instance age parameter** — default name `age` — the accumulated stress
  dose, written back by the command; the model owns the physics mapping `age` to
  a parameter shift:

  ```verilog
  (* type="instance" *) parameter real age = 0.0 from [0:inf);
  ...
  dvth   = dvth_ref * pow(age/age_ref, nnbti);   // sublinear NBTI power law
  vtheff = vth0 + dvth;
  ```

The engine only integrates the rate into a dose and feeds it back; all the
degradation physics lives in the model. Devices without **both** names (ordinary
resistors, sources, …) are skipped, so probing never errors.

## Two modes

* **static** (default) — read the rate at the DC operating point and multiply by
  the lifetime: `age = agerate(op) · t_target`. For a device held at a fixed
  stress bias.

* **dynamic** (`dynamic <tstop> [tstep]`) — run a transient over one
  representative window, integrate the rate over time, and extrapolate:
  `age = (∫ agerate dt / tstop) · t_target`. This captures **duty cycle**: a gate
  biased on only part of the time ages by its time-averaged stress.

## Run it

```
openvaf-r agemos.va -o agemos.osdi
ngspice -b aging_demo.cir          # static: fresh vs aged operating point
```

[`aging_demo.cir`](aging_demo.cir) reads the fresh drain current, ages the
device to ~10 years at its stress bias, and reads the degraded current and
shifted threshold. The `aging` line prints a per-device report:

```
aging: 1 device aged to t = 3.15e+08 s (9.98 years), static stress [rate 'agerate' -> param 'age']
  device                       rate       age (dose)
  n1                            1.3        4.095e+08
```

## Verify + figure

```
python3 verify_aging.py     # 6 checks, under BOTH the Sparse and KLU solvers
python3 make_aging_fig.py   # -> aging_iv.png
```

![fresh vs aged](aging_iv.png)

* **A.** Transfer curves `Id(Vg)` fresh and after 10 / 20 / 40 years of NBTI
  stress at Vg = 1.8 V: the threshold shift pulls the curve down and right.
* **B.** The extracted threshold shift `ΔVth` vs stress time follows the
  sublinear `ΔVth ∝ t^0.25` power law the model implements.

## Why the results are physically correct

* **Dose ∝ stress × time.** The reported age is exactly `rate · t_target`
  (static) or `mean-rate · t_target` (dynamic); a device biased below threshold
  accrues zero dose and does not age.
* **Sublinear in time.** `ΔVth ∝ age^0.25` reproduces the classic NBTI/HCI
  power-law: ten times the stress time is only ~1.8× the shift.
* **Near-threshold sensitivity.** A device biased close to threshold loses a
  larger *fraction* of its current for the same `ΔVth` — the well-known reason
  analog/low-overdrive stages are the reliability bottleneck. In `st.cir` the
  hard-driven N1 (Vgs = 1.8) loses 8% while the near-threshold N2 (Vgs = 0.9)
  loses 22%, even though N1 accumulates the larger dose.
* **Duty cycle.** In dynamic mode a gate pulsed at 30% duty ages at 0.30× the
  rate of an identically-biased DC device — the time-weighted average of the
  stress waveform.

## Notes

* The command runs the fresh operating point / transient first, leaving it as
  the current plot — a convenient "fresh" baseline to compare against.
* `age` is a **per-instance** parameter (`(*type="instance"*)`), so devices at
  different bias in the same `.model` age independently.
* Aging is solver-independent (it drives `op`/`tran` and reads opvars); results
  are identical under Sparse 1.3 and KLU.

See [Enhancement-157](../../enhancements_doc/Enhancement-157.md) for the full
write-up.
