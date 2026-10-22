# subcktmfactor_examples — a subcircuit's multiplier reaches a compiled model that owns `m` (Enhancement-916)

```
python3 verify_subcktmfactor.py
```

12 checks, both solvers (7 fail on E-913).

## The need

F7 and F8 of the 2026-09-26 options-and-convergence hunt. A subcircuit called with `m=` had
` m={m}` appended to every device line inside it, and on an N line that `m` landed on whatever the
compiled device calls `m`:
- **F7.** A diode whose grading coefficient is `m` refused the line as a model parameter.
- **F8.** A module with an instance parameter `m` had it overwritten and was not multiplied.

## What changed

The expansion appends the multiplier to an N line as `_subckt_m=`. The parser multiplies it into
the device's own multiplier (`_mfactor` on a compiled device), times whatever the line or the card
gives. An `m=` the user wrote keeps the meaning the model gives it.

## The checks

- **[1]** A compiled diode owning `m`, in m=2: runs, on the built-in diode's point.
- **[2]** … with `_mfactor=3` on its line: six diodes.
- **[3]** A module with its own instance `m`, in m=2: two devices.
- **[4]** … with `m=3` on its line: the parameter stays 3, still doubled.
- **[5]** A resistor module with m=3 inside m=2: 6×.
- **[6]** Nested subcircuits 2 × 3 × 5: 30×.
- **[7]** A card's `_mfactor=3` default inside m=2.
- **[8]** m=0 (one note) and m=-1 (one warning) on the X line.
- **[9]** The built-in resistor, and a subcircuit that declares `m` itself.
- **[10]** The small-signal current.
