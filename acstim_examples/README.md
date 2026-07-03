# acstim_examples — `ac_stim(...)` (Enhancement-26, baseline)

Demonstrates **`ac_stim([name][, mag][, phase])`**, the Verilog-AMS small-signal
AC stimulus source, using **version11's own** `openvaf-r` and `ngspice-46`.

## What this enhancement fixes

Previously `ac_stim` type-checked but any **contributing** use (`I(a,b) <+
ac_stim(...)`) fell through to an `unreachable!()` in the lowering and **crashed
the compiler**. Enhancement-26 (baseline) fixes that: `ac_stim` now lowers to its
correct **large-signal value of 0** (per the LRM, `ac_stim` is 0 in DC/transient
and injects `mag∠phase` only during small-signal AC analysis). So a model using
`ac_stim` compiles and simulates.

## Scope (baseline vs. follow-up)

- **Done here:** no more crash; `ac_stim` evaluates to 0 in the large-signal
  (DC/transient) domain — its correct value there. All four signature forms
  (`ac_stim()`, `ac_stim(name)`, `ac_stim(name, mag)`, `ac_stim(name, mag,
  phase)`) compile and run.
- **Not yet:** the small-signal **AC injection** (`ac_stim` contributing
  `mag∠phase` to the AC right-hand side). That needs a new OSDI AC-RHS mechanism
  plus ngspice support (a subsystem parallel to noise) and is a dedicated
  follow-up — see `Enhancement-26.md`.

## Run

```
python3 verify_acstim.py
```

Expected (`ALL PASS`):

- the model **compiles** (it used to crash `openvaf-r`);
- DC and transient currents equal `g*V(a,b)` and are **identical** with the
  `ac_stim` terms on vs off — i.e. `ac_stim` correctly contributes 0 in the
  large-signal domain.
