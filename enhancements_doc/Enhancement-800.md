# Enhancement-800: `.temp 0 27 50` runs at the first temperature it lists and says how to run them all — it ran at 27 C, "Could not set temperature"

**Scope:** D5 of the
[ngspice + OSDI hunt of 2026-10-08](../docs/bug_hunts/2026-10-08_ngspice-osdi-hierarchy-sweeps-events-and-outputs.md).
ngspice:
- `frontend/inp.c`: the `.temp` reader in `inp_spsource` recognizes a list of numbers.

`examples/osdislips_examples/` (section [5], seven checks); `sweepguard_examples` (E-437's
neighbour check) updated. **ngspice only.**

**Suites:** [`osdislips_examples`](../examples/osdislips_examples/) 56 of 56 per solver (3 of the 7
in [5] fail on the E-795 binaries); `sweepguard` 43 of 43; the full sweep, 538 of 538.

## What was wrong

SPICE2 runs every analysis once per temperature listed on `.temp`, and so do HSPICE and LTspice.
ngspice reads one number. A list failed its trailing-text test:

```
.temp 0 27 50
Warning: Could not set temperature to 0 27 50
   Set to default 27 C instead.
```

and the run went on at 27 °C. For `.temp -40 125` that is a temperature the deck does not list at
all. The message read like a typo report, and gave no hint of how ngspice runs several
temperatures.

## The change

A `.temp` whose value is a list of numbers, separated by spaces or commas, runs at the first:

```
Warning: .temp lists 3 temperatures (0 27 50); ngspice runs a circuit at one temperature, so this run uses the first, 0 C.
   To run at each: a .control block with `foreach t 0 27 50`, `set temp = $t`, `run`, `end` -- or `.dc temp` for a dc sweep.
```

The `foreach` it suggests is checked to run each temperature. A value that is not a list of
numbers keeps the old message and 27 °C: `.temp abc`, or `.temp 0 27 x`. So does E-437's empty
`.temp`.

## The checks

osdislips [5]:

- `.temp 0 27 50` runs at 0 °C (the tc1 resistor's current) and says how to run all three;
- `.temp=-40, 125`: two temperatures, commas read as separators, -40 °C;
- `.temp abc` and `.temp 0 27 x` keep the old message and 27 °C;
- one temperature says nothing;
- the suggested `foreach` runs 0, 27 and 50 °C.

sweepguard's E-437 neighbour check now expects `.temp 75 125` to warn and run at 75 °C.

## Limits

- ngspice still runs one temperature per circuit. A batch run per listed temperature, as SPICE2
  does it, would change the shape of every output: each `.print` and `.meas`, and the raw file. It
  is left for a decision. The warning names both ways to run them all.
