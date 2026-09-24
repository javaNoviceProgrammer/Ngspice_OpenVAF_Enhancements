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

`verify_multimod.py` (28 checks), the five multi-module `.va` fixtures,
and this README.

## Enhancement-707 — a library of hundreds of modules links (robustness campaign F8 of 2026-09-23)

Every module compiles to four object files and each path went onto the linker's
argument vector, so a file of 1 800 one-line modules exceeded macOS's 256 KB `ARG_MAX`
and failed as "linker not found: Argument list too long" (1 700 linked). Since
[Enhancement-707](../../enhancements_doc/Enhancement-707.md) the linker reads its
arguments from a response file (`<output>.rsp`, `@file`) above 16 KiB, an `exec`
failure names the program and the cause, and a failed link removes its object files.

Checks [14]–[15]: a generated file of 400 modules — 1 600 object files, about 130 KB of
paths, eight times the threshold — compiles, leaves no `.rsp` behind, and its last
module loads and conducts 0.5 mA through `r=2k`; with no linker on `PATH` the compile
fails with "linker not found: '…' is not installed or not on PATH". The second fails on
the E-704 binaries (27/28); the first passes there too, since 400 modules were always
under the wall.
