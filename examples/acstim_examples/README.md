# acstim_examples — `ac_stim(...)` (Enhancement-26, baseline)

Demonstrates **`ac_stim([name][, mag][, phase])`**, the Verilog-AMS small-signal
AC stimulus source, using **the committed** `openvaf-r` and `ngspice-46`.

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

## Enhancement-51: the AC injection itself

E-51 completed the deferred half. `ac_stim` now lowers to a dedicated
callback riding the **noise-source extraction pipeline** (same branch/factor
machinery, small-signal network exclusion from the large-signal residual),
is **partitioned** at the OSDI level into its own descriptor array
(`num_ac_stim_src` / `ac_stim_sources` / `load_ac_stim`, appended fields —
**OSDI version bumped to 0.6**, stale `.osdi` files rejected with a clear
message), and ngspice's AC load adds `factor·mag·e^{jφ}` (phase in radians)
into the complex AC RHS at the source's mapped nodes — analysis-name matched
per LRM 4.6.3, so `ac_stim("sp")` stays inactive in AC. `mfactor` scales the
stimulus linearly (deterministic signal), unlike noise's sqrt law.

New checks (ALL PASS, exact): voltage stimulus = 1∠0; `ac_stim("ac", 2, π/2)`
= j2; non-matching name = 0; current stimulus into 1k = −1000 (contribution
sign); and the classic embedded test bench — an internal `ac_stim` driving an
RC lowpass reads exactly 0.5−0.5j at the pole (0.7071∠−45°) and 0.01 at
100·fc, measuring the model's own transfer function in AC.
