# Enhancement-76 — multi-module `.osdi` libraries: audit + three registration fixes

This document describes Enhancement-76: an audit of the **multi-module
packaging surface** — one `.va` file holding several modules, compiled into
one `.osdi`, loaded by one `pre_osdi`. The machinery is plural by design on
both sides (`openvaf-r` exports an `OSDI_DESCRIPTORS` array with a count;
ngspice's registry iterates it), and the audit confirmed the happy path
end-to-end — then found **three registration defects**, all fixed on the
ngspice side (`dev.c` + one stock parser fix in `inpgmod.c`). No compiler
changes.

## Working by construction (probed, exact values)

- **Any number of modules per library**: three device types from one
  `pre_osdi`, simulating side by side (currents sum exactly);
- **hierarchy inside a multi-module file**: a module that instantiates
  another — the flattened parent (`top`) and the standalone child (`leaf`)
  coexist as independent device types with independent parameters;
- **`paramset` blocks mixed with plain modules** (the E-21 twin-module
  machinery composes with real multi-module files);
- **case-insensitive model-card types** (`.model m RES_A` finds `res_a`);
- a duplicated module name *within one file* is a clean compiler error
  ("already declared in this scope").

## The three fixes

**(1) Silent cross-library shadowing.** `osdi_add_device()` appended every
descriptor to the device table unconditionally; the model-card lookup scans
front-to-back, so a module name duplicated across two loaded libraries
silently resolved to the **first** registration — loading an updated model
library gave the stale device with no hint. Now each registration checks
the existing table (case-insensitively, matching the lookup) and a
duplicate is skipped with a warning naming the device:
`Warning(osdi): device "dup" is already registered; keeping the existing
device and ignoring this one`. First-wins stays the semantics — but loud.

**(2) Silent double-load.** `load_osdi()` now keeps the list of loaded
paths; `pre_osdi` of an already-loaded file prints
`Note(osdi): "<path>" is already loaded; skipping` instead of
re-registering (which, after fix 1, would have produced one warning per
module).

**(3) A stock ngspice segfault, found through the OSDI door.** The
Enhancement-29 gotcha — "a module named like a built-in (`vcvs`, `cccs`)
segfaults create_model" — turned out to be a **stock defect reachable with
no OSDI at all**: `find_model_parameter()` dereferences
`*(device->numModelParms)`, which is NULL for every built-in that takes no
model cards (VCVS, CCCS, CCVS, …). Any referenced `.model m vcvs()` card
crashed — e.g. an ordinary MOS instance `m1 a b c d mm` with that card.
One NULL guard fixes the class; both the OSDI shape (now: duplicate
warning + the `inp2n` "Expected OSDI device" located error) and the pure
stock shape (located "model type mismatch" error) terminate cleanly. The
E-29 gotcha is retired.

A debugging note for the record: the crash was initially masked in the
probe pipeline by `ngspice … | grep | head` — `head`'s exit status hides
the SIGSEGV. Same family as E-74's `strings`-without-`-a` lesson: exit
codes must be read from the process itself.

## Examples (`multimod_examples/`, 13 checks, ALL PASS)

`verify_multimod.py` + five multi-module fixtures (`trio.va`, `hier.va`,
`psmix.va`, `dup1.va`/`dup2.va`, `vcvs.va`) covering the five
by-construction behaviors and all three fixes, including the two
crash-regression pins.

## Regression

All 69 example verify suites pass with the rebuilt ngspice; the
integration suite 28/28; the VA_TEST corpus compiles 92/92 (compiler
unchanged).
