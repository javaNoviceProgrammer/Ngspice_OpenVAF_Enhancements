# `scanbody_examples` — Enhancement-540

A scan in the analog body must not crash the simulator.

```bash
python3 verify_scanbody.py
```

**5 checks**, both solvers. Against the pre-fix compiler the suite scores
**1/5**, catching the crash as `exit=-11`.

## What it guards

A descriptor opened in `@(initial_step)` and scanned in the analog body used to
**SEGFAULT** ngspice:

```
EXC_BAD_ACCESS (code=1, address=0x0)
frame #0: scanbody.osdi`osdi_scan_real + 40
```

`$sscanf`/`$fscanf` lower to `ScanBegin` → `Scan*` → `ScanCount`, a sequence
that communicates through the runtime's cursor globals rather than through MIR
values. Nothing in the dataflow tied the three together, so the init/eval
splitter — which copies every instruction that is not operating-point dependent
into the instance-setup function — hoisted the field scanner and the count
while leaving `ScanBegin` behind with the descriptor it depends on. Setup then
ran a scanner with the cursor never initialised. See
[Enhancement-540](../../enhancements_doc/Enhancement-540.md).

## Why it checks the value, not just survival

A build that hoisted the scanner and silently used the **fallback** value would
also stop crashing. So the fixture's data file starts with `2.0`, making the
device a 500 Ω conductance against the deck's 1 kΩ series resistor, and the
check asserts the divider lands on exactly `500/1500`.

| fixture | form |
|---|---|
| `scanbody.va` | `$fscanf` in the analog body, descriptor from `@(initial_step)` |
| `scanbody_manual.va` | the manual equivalent — `$fgets` into a string, then `$sscanf` on it |

Both are pinned because both crashed, which is what proved the defect was the
scan protocol being split rather than anything specific to `$fscanf`. The last
check requires the two spellings to agree to the last digit.
