# Enhancement-267 — ngspice: `sweep` records array/bus nodes under their natural names

Sweeping a circuit whose outputs are **array/bus nodes** — a node named `ph[0]`
(Enhancement-221) — stored the result vectors under mangled names: `ph[0]` became
**`ph_0_`**, `ph[1]` became `ph_1_`, and so on. The sweep plot listed `ph_0_`,
`ph_1_`, … instead of `ph[0]`, `ph[1]`, ….

## Cause

The `sweep` command (Enhancement-146/-189/-190) builds each result-vector name
from the output expression plus, for a `-vs` family or an overlay waveform, an
appended `_<knob>_<value>` segment. That segment carries a floating-point value
(`_rt_1.5k`) whose `.`/`-`/`e` are illegal in a nutmeg vector name, so the name
builders `sw_familyname` / `sw_pointname` mapped every non-alphanumeric character
(except `_`) to `_`. But the mapping was applied to the **whole** string —
including the user's base output name — so a bus node's brackets were destroyed:
`ph[0]` → `ph_0_`.

## Fix

`src/frontend/com_sweep.c`:

1. **Sanitize only the appended suffix, not the base name.** A small helper
   `sw_append_sanitized(base, suffix)` sanitizes just the `_<knob>_<value>`
   segment it appends, leaving the base output name byte-for-byte intact.
   `sw_familyname` / `sw_pointname` now use it, so `ph[0]` stays `ph[0]` (and for a
   `-vs` family, `ph[0]_rt_2k`). Ordinary names are unchanged — a plain node has no
   special characters to preserve, and an explicit `-output name=expr` still uses
   the given clean name.

2. **`-output` accepts a bus range.** A bare `-output` token that is a bus range
   `ph[0:3]` is expanded into one output per index — `ph[0] ph[1] ph[2] ph[3]` —
   matching the netlist bus expansion (Enhancement-221). So
   `sweep rt … -output ph[0:3]` records the four taps directly.

Values are unaffected — the fix only changes the *name* the result is stored
under and how a range token is expanded; each output is still evaluated exactly as
before. A four-tap bus divider swept over its top resistance now records `ph[0]`…
`ph[3]` with the correct divider ratios.

## Verification

`examples/sweepbus_examples/verify_sweepbus.py` (4 checks): `-output ph[0:3]`
records four vectors named `ph[0]`..`ph[3]` (range expanded, natural names); the
mangled `ph_0_`… names are gone; the recorded values are the correct divider
ratios; and a plain `-output vo=v(out)` is unaffected. The full dual-solver example
regression is unchanged (the existing sweep suites use the `-output name=expr`
form, whose clean names are not touched).

## Scope

One source file (`src/frontend/com_sweep.c`) plus the new example. No change to any
analysis result.
