# Enhancement-815: no route hands a model a temperature at or below absolute zero — `alter n1 dtemp=-400` said "the offset is ignored" and evaluated the model at -99.85 K

**Scope:** F24 of the
[ngspice + OSDI hunt of 2026-10-08](../docs/bug_hunts/2026-10-08_ngspice-osdi-hierarchy-sweeps-events-and-outputs.md),
with four more routes found while fixing it. ngspice:
- `spicelib/parser/inpdpar.c`: `INPtempParamKind` and `INPtempBelowZero` judge an instance
  temperature knob by parameter id. Enhancement-467's line guard uses them.
- `frontend/spiceif.c`: `doset_user` refuses an `alter` that the line refuses, and counts its
  refusals (`if_user_write_refusals`, declared in `spiceif.h`).
- `spicelib/analysis/dctrcurv.c`: a `.dc` sweep of a temperature knob is refused when its
  first or last point reaches 0 K.
- `frontend/com_sweep.c`: a point whose knob value `alter` refused is recorded as NaN, and the
  sweep says so.
- `osdi/osdisetup.c`: `osdi_instance_temp`, one guarded composition for `OSDIsetup`,
  `OSDItemp` and the osdimc re-derivation.
- `osdi/osdiparam.c`: `OSDItempParamKind`.
- `osdi/osdidefs.h`: `temp_refused`.
- The declarations in `inpdefs.h` and `osdiitf.h`.

`examples/tempguard_examples/` (new, 18 checks per solver). **ngspice only.**

**Suites:** [`tempguard_examples`](../examples/tempguard_examples/) 18 of 18 per solver (13
fail on the E-813 binaries; the five that pass are the two line refusals that already worked
and the three checks of a physical value). `inputguard`, `silentaccept`, `argguard`,
`sweeptemp` and the `sweep` command's suites are unchanged within the full sweep, 541 of 541.

## What was wrong

A Verilog-A resistor whose resistance has a temperature coefficient, `r*(1 + 0.01*($temperature - 300.15))`,
at 1 V, with the circuit at 27 °C:

| how | said | the model saw | i(v1) |
|---|---|---|---|
| `n1 … dtemp=-400` on the line | refused (E-467) | 300.15 K | −1 mA |
| `n1 … dt=-400` on the line | "… the offset is ignored" | **−99.85 K** | **+0.33 mA** |
| `alter n1 dtemp=-400` (or `dt=`, `@n1[dtemp]=`) | "… the offset is ignored" | **−99.85 K** | **+0.33 mA** |
| `alter n1 temp=-300` | "… (temp=27 C, dtemp=0); the offset is ignored" | **−26.85 K** | **+0.44 mA** |
| `dc @n1[dtemp] -400 0 200`, `dc @n1[temp] -300 27 100` | nothing | −99.85 K, −26.85 K at the first point | |
| `sweep @n1[dtemp] -400 0 200` | nothing | −99.85 K at the first point | |
| `dtemp=-290`, then `set temp=-10` | "… the offset is ignored" | **−26.85 K** | |

Enhancement-426 guarded the composed instance temperature, but only in `OSDIsetup`.
`OSDItemp` composes it again for every analysis after the first and at every sweep point, with
no guard. So the setup said the value was ignored, and the next evaluation used it. The
`temp=-300` message also printed the circuit temperature and a zero `dtemp`, not the value
that caused it.

The instance line's guard (E-467) tested the keyword `dtemp`, so `dt`, the same knob's other
spelling on an OSDI instance (E-397), went through. A built-in device took the values through
`alter`, and through a `.dc` sweep, without a word.

## The change

- **One rule for a written value.** `INPtempParamKind` identifies the knob by parameter id
  (absolute `temp`, or the `dtemp` offset with every spelling of it). `INPtempBelowZero` says
  whether a value puts the device at or below absolute zero at the present ambient. Three
  places use the rule:
  - the instance line, which refuses as before, now `dt=` too, naming the keyword written;
  - `alter`, which refuses with "not applied, the instance keeps the value it had", for
    OSDI and built-in devices alike;
  - a `.dc` sweep of the knob, refused when its first or last point reaches 0 K, as
    `.dc temp` is (E-426). The last point is the last one swept, not a `stop` the steps never
    reach.
- **A `sweep` point that could not be set.** The `sweep` command sets each point with
  `alter`. A refused value would leave the knob where it was, and the point would be solved
  at the previous value and recorded under this one. Such a point is now recorded as NaN,
  the way E-445 records a point that did not converge, and the sweep prints how many could
  not be set. `doset_user` counts its refusals, so this holds for any refused value: a
  non-finite number and an integer out of range too.
- **One composition at run time.** `osdi_instance_temp` composes `temp`/`dtemp` with the
  ambient for `OSDIsetup`, `OSDItemp` and the osdimc re-derivation. A valid offset can still
  become unphysical later, when the ambient changes (`dtemp=-290`, then `set temp=-10`). The
  device then runs at the circuit temperature, and a warning names the offset, the circuit
  temperature and the device temperature. It is said once while the condition holds, not at
  every sweep point, and the offset is used again as soon as the ambient allows.

## The checks

`tempguard_examples`. The module `$strobe`s the temperature it is evaluated at, so each check
reads what the model saw, not only what was printed.
- **[1]** On the line, `dtemp=-400`, `dt=-400` and `temp=-300` are refused by name; the model
  is at 300.15 K and i(v1) = −1 mA.
- **[2]** `alter n1 dtemp=-400`, `dt=-400`, `temp=-300` and `alter @n1[dtemp]=-400` are not
  applied. `@n1[dtemp]` stays 0 and `@n1[temp]` stays 27, and the model is at 300.15 K.
- **[3]** A physical value still applies: `alter n1 dtemp=-200` gives 100.15 K, and
  `dc @n1[dtemp] -250 0 125` gives 50.15, 175.15 and 300.15 K.
- **[4]** A built-in resistor: `alter r1 dtemp=-400` and `temp=-300` are not applied, and
  i(v2) = −1 mA.
- **[5]** Sweeps:
  - `dc @n1[dtemp] -400 0 200`, `dc @n1[temp] -300 27 100` and `dc @r1[dtemp] -400 0 200`
    are refused, and nothing is evaluated below 0 K;
  - `dc @n1[dtemp] -60 -320 -120` runs, at 240.15, 120.15 and 0.15 K: its stop is below
    0 K, but its last point is not;
  - `sweep @n1[dtemp] -400 0 200` records the first point as NaN and says so; the other two
    are real.
- **[6]** The ambient makes a valid offset unphysical:
  - with `dtemp=-290` and `set temp=-10`, the model is at 263.15 K for two analyses, with one
    warning;
  - back at 27 °C it is at 10.15 K again;
  - under `dtemp=-280`, `dc temp 27 -13 -10` evaluates the model at 20.15, 10.15 and 0.15 K,
    then at the circuit's 270.15 and 260.15 K, with one warning.

## Limits

- A built-in device composes its own temperature in its own `DEVtemperature`. A valid offset
  that a later ambient makes unphysical still reaches a built-in model; only the OSDI
  composition has the run-time guard. The line, `alter` and `.dc` refuse for both.
- A model's own parameter named `temperature` keeps the model's meaning and is not judged.
