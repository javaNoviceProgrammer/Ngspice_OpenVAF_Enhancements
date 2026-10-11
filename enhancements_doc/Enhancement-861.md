# Enhancement-861: sensitivities by a central difference — every sensitivity to a resistance was low by exactly 1e-6

**Scope:** F6 of the
[third robustness and correctness campaign of 2026-10-10](../docs/bug_hunts/2026-10-10_ngspice-openvaf-r-third-robustness-campaign.md).

ngspice: `spicelib/analysis/cktsens.c`, `sens_sens`: a central difference where the parameter is
not zero.

`examples/senscentral_examples/` (new). **ngspice only.**

**Suites:**
- [`senscentral_examples`](../examples/senscentral_examples/): 5 of 5 per solver. On the
  E-859 binaries 3 fail; [4] and [5] are controls.
- The campaign's Family C, 12 282 dc sensitivities over 300 networks: 3 140 flags at 1e-6
  under Sparse and 3 127 under KLU, now 46 and 33. Every one of those left is a value that is
  zero at the circuit's scale (|value| below 1e-14, most near 1e-18), apart from one gain at
  2.6e-9.
- The full sweep: 566 of 566.

## What was wrong

`cktsens.c` loaded each device at the nominal parameter and at p + δ, with δ = `Sens_Delta` =
1e-6 of the value. It divided the difference of the stamps by δ: a one-sided difference.
- A parameter that enters the stamp linearly (a gain, a source) came out exact.
- A resistance enters as 1/R, and (1/(R+δ) − 1/R)/δ = −1/(R(R+δ)) is low by the factor
  1/(1 + 1e-6).

So every sensitivity to a resistance was low by exactly that factor: dV(4)/dR1 was −7.40740e-4,
where −7.4074074e-4 is right. The same held in ac, and for a diode's `rs`.

## The change

Where the parameter is not zero, the step is central: the stamps at p + δ and p − δ, with the
difference divided by 2δ. The error is of order δ², where it was δ. The load at p − δ takes the
nominal load's place, so a parameter costs the same number of loads.

Everything else the step does, the p − δ side does as well:
- [Enhancement-417](Enhancement-417.md)'s check for a moved Verilog-A node collapse;
- [Enhancement-825](Enhancement-825.md)'s count of `$fatal`, `$finish` and `$stop`;
- the model and instance snapshot that undoes the setter's side effects.

A parameter at zero keeps the one-sided step, `Sens_Abs_Delta`. Zero is how several models
switch an effect off, and −δ is no value for it.

A diode's `isr` shows what a model's *given* flags do here. The setter marks a parameter given,
and the recombination current is only on when `isr` is given. The one-sided step measured that
switch, the jump from off to on divided by 1e-20, and reported −1.8e15. Both sides of the
central step have it on, so it reports the slope, −1.8e9. Neither is a derivative of the model
the netlist describes, which has no recombination current.

## The checks

`senscentral_examples`:
- **[1]** dV(4)/dR1..dR4 of a resistive network with a VCVS, to 1e-9 of the analytic values.
  They come out 1.6e-11; on E-859, 1e-6.
- **[2]** An ac sensitivity, dH/dR of an RC low-pass at three frequencies, to 1e-9.
- **[3]** A diode's `rs`, against a central difference of two tight operating points, to 1e-7.
  It comes out 2.6e-8; on E-859, 1.0e-6.
- **[4]** (control) The VCVS's gain, exact before and after.
- **[5]** (control) A diode's `is`, against the same reference.
