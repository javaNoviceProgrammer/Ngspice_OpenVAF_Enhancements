# Enhancement-76 — multi-module `.osdi` libraries

A single `.va` file may hold many modules: `openvaf-r` compiles every one
into the `.osdi` as its own OSDI descriptor, and ngspice's `pre_osdi`
registers each descriptor as a device type. This suite audits that whole
packaging surface — and pins the three defects the audit found and fixed
(all ngspice-side; the compiler needed nothing).

## What works by construction

- Any number of modules per file/library, all usable side by side
  (`trio.va`: three device types from one `pre_osdi`);
- a module that instantiates another: the flattened parent and the
  standalone child coexist as separate device types (`hier.va`);
- `paramset` blocks mixed with plain modules in one library (`psmix.va`);
- case-insensitive model-card type names (SPICE convention);
- a duplicated module name *within one file* is a clean compiler error.

## The three fixes

1. **Silent cross-library shadowing** — a module name duplicated across
   two loaded `.osdi` files silently kept the first registration: loading
   an updated model library gave you the stale device with no hint. Now a
   warning names the device and states that the existing registration is
   kept (deterministic first-wins).
2. **Silent double-load** — `pre_osdi` of an already-loaded path now notes
   it and skips instead of re-registering a page of duplicates.
3. **A stock ngspice segfault, found through the OSDI door** — a `.model`
   card naming a device type that takes no model cards (VCVS, CCCS, …),
   once referenced by any instance, crashed in `find_model_parameter`
   (NULL model-parameter table dereference). This was the root of the
   Enhancement-29 "module named like a built-in segfaults" gotcha — but
   it reproduces with **no OSDI at all** (an ordinary MOS instance and a
   `.model m vcvs()` card). One NULL guard: both shapes now produce
   clean, located errors, and the E-29 gotcha is retired.

## Files

`verify_multimod.py` (13 checks), the five multi-module `.va` fixtures,
and this README.
