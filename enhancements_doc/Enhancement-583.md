# Enhancement-583: `montecarlo -track` on a dc sweep — the scale records as `track_v_sweep`, and the fast path no longer runs the temperature pass on a circuit not yet set up

**Scope:** `src/frontend/com_sweep.c` (the record's vector names in `com_montecarlo`;
the `DEVtemperature` pass in `sw_fp_apply`), `examples/mctrack_examples/` (a dc-sweep
section, 20 checks per solver). **ngspice only.**

**Suites:** [`mctrack_examples`](../examples/mctrack_examples/) 20 of 20 per solver,
both solvers; full sweep 480 of 480.

## Where both came from

The first `montecarlo -track` example on a **dc sweep** — a CMOS inverter whose
switching point and gain-region width vary with the two threshold voltages — showed
two things E-582's transient examples could not:

```spice
.param vtn = agauss(0.7, 0.1, 3)
.param vtp = agauss(-0.7, 0.1, 3)
.model nm nmos level=1 vto={vtn} kp=120u lambda=0.02
.model pm pmos level=1 vto={vtp} kp=60u  lambda=0.02
Vdd vdd 0 3
Vin in  0 0
M1 out in 0   0   nm w=2u l=1u
M2 out in vdd vdd pm w=4u l=1u
.control
  montecarlo 1000 -seed 7 -analysis "dc vin 0 3 5m" -track "v(out) -spec 'v(out) == v(in)'" -track "v(out) -spec 'abs(deriv(v(out))) > 1'" -expr vtn=@nm[vto] -expr vtp=@pm[vto]
  plot track1_v_sweep vs vtn          ; the switching point against the drawn nmos threshold
  pyplot -hist track2_width           ; the gain region's width
.endc
```

1. **An unspellable vector.** A dc sweep's scale is `v-sweep`, so E-582 recorded the
   position as `track1_v-sweep` — and `print track1_v-sweep` is the subtraction
   `track1_v - sweep` ("vector track1_v is not available"). The record now maps every
   character that is not a letter, digit or underscore to `_`: **`track1_v_sweep`**,
   the rule `sweep` already uses for its own scale names. `time`, `frequency`, `value`,
   `x_out`, `width`, `index` are unchanged.
2. **A spurious fatal error.** Every run printed `Fatal error: pm: Phi is not positive.`
   once, though `@pm[phi]` was 0.6 throughout and the results were right. The Monte
   Carlo fast path (E-320, models since E-344) pushes each sample's values straight
   into the device slots and then refreshes every touched device type's derived state
   with one `DEVtemperature` pass. On the **first sample of a fresh circuit** that pass
   ran before `CKTsetup` had applied the model defaults — MOS1 gives `phi` its 0.6 in
   `MOS1setup` — so `MOS1temp` saw `phi == 0`, printed the error and returned at the
   first model it checked. It was harmless only because `CKTdoJob` then ran `CKTsetup`
   and `CKTtemp` for the analysis anyway. The pass now runs only when `CKTisSetup` is
   set; on a fresh circuit the analysis's own setup and temperature pass do the work.
   Every MOS level-1/2/3 model without an explicit `phi` under `montecarlo`, `sweep`
   or `optimize` on the fast path was affected.

## Verification

The suite's new section runs six seeded samples of the inverter on both solvers:

| check | result |
|---|---|
| the dc scale | `track1_v_sweep` present with the voltage type, no `track1_v-sweep`; the switching point per sample equals (vtn + VDD + vtp)/2 within 20 mV (a beta ratio of 1) and moves with the drawn thresholds |
| the gain region | entry below and exit above the switching point on every sample, `width == x_out − entry`, in volts |
| the fast path | no "Phi is not positive" and no "Fatal error" in the output; the fast path still armed with two random bindings |

The earlier sections (17 checks, transient) and the 22 suites that use `montecarlo`
pass unchanged; the sweep is 480 of 480.
