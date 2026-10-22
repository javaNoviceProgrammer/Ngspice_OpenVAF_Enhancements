# tnomoption_examples — `.option tnom` reaches compiled models (Enhancement-914)

```
python3 verify_tnomoption.py
```

14 checks, both solvers (12 fail on E-913).

## The need

F1 of the 2026-09-26 options-and-convergence hunt. A built-in model whose card gives no `tnom`
measures its parameters at the circuit's nominal temperature, which `.option tnom` sets. The OSDI
layer served it only as `$simparam("tnom")`, which the industry models do not read. So:
- `.option tnom=50` moved every built-in and no compiled model;
- the VA-Models BSIM4, which falls back to 25 °C when its `tnom` is not given, ran 1.5 % off its
  built-in twin by default.

## What changed

Before each `setup_model`, a compiled model's ungiven `tnom` gets the circuit's nominal
temperature, in the parameter's unit, in two cases:
- `.option tnom` is given;
- the model's own default is the SPICE 27 °C (300.15 K), or a "not given" sentinel.

A model with another default (DIODE_CMC's 21 °C) keeps it until the option is written. A value
outside the declared range is not written, and a warning says so. A model without `tnom` gets a
note naming its reference-temperature parameter.

## The checks

Each small module copies one family's pattern, with R(T) = r·(1 + tc·(T − tnom)) at 27 °C. A
built-in resistor with `tc1` is the twin.

- **[1]** The BSIM4 pattern (`$param_given` fallback to 25 °C) runs at 27 °C, as the twin does.
- **[2]** `.option tnom=50` reaches it.
- **[3]** A `tnom` on the card wins.
- **[4]** The DIODE_CMC pattern keeps 21 °C by default and takes the option.
- **[5]** A `tnom` in Kelvin, 300 K by default, takes the option as 323.15 K.
- **[6]** `TNOM = 27.0` declared with units "K" (HiSIM-HV) is read as Celsius.
- **[7]** The EKV pattern's sentinel default takes 27 °C.
- **[8]** A value outside [22:32] is not written, and a warning names the range.
- **[9]** A model without `tnom`: a note names its `TR`, only with the option.
- **[10]** The option changed between runs, then `altermod`, then `reset`.
- **[11]** The VA-Models BSIM4 against the built-in BSIM4 4.8.
