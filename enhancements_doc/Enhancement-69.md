# Enhancement-69 — operating-point variables end-to-end: validation deliverable

This document records the Enhancement-69 audit of **operating-point
variable (opvar) access** — Verilog-A module variables carrying a
`(* desc="..." *)` attribute, exposed through the OSDI descriptor and
read back from ngspice as `@instance[variable]`. **No defects were
found — the surface is fully working** — so, like Enhancements 57, 60,
and 66, the deliverable is the validation itself. No compiler or ngspice
source changes.

## What was probed (all exact)

- **`.op` access** (`print @n1[ids]`): real and integer opvars exact
  (1 mA / 1 mS / region flag 2); a module variable *without* a desc
  attribute is correctly **not exposed** — `no such parameter`, a clean
  error rather than a silent zero or crash.
- **`.tran` per-point recording** (`.save @n1[ids] @n1[region]`):
  508-point vectors for the real *and the integer* opvar — the
  Enhancement-32 `outitf.c` IF_INTEGER fix finally gets a regression
  pin. `.meas MAX` hits the exact 1 mA sine peak; `AVG` of the region
  flag lands at 1.5 (above threshold exactly half the period).
- **`.dc` sweeps**: per-point recording; `ids == V/1k` exact at every
  point and the integer region flag steps exactly where `V > 0.5`.
- **`.ac`**: opvars record (op value per frequency point) and two
  instances of one model stay distinct (`@n1` = 1 mA vs `@n2` = 0.5 mA
  with `r=2k`).
- **`.meas WHEN @n1[ids]=0.5m RISE=1`**: 83.3334 ns against the
  analytic asin(0.5)/2π µs — measurement logic works on opvar vectors
  exactly as on node voltages.
- **String opvars**: displayed by `show <inst>`; the *vector* path
  (`print @n1[strvar]`) is inherently numeric and fails with the clear
  `can not handle string value` message — pinned as the expected
  behavior (ngspice vectors cannot hold strings), not a defect.

## Examples (`opvar_examples/`, 11 checks, ALL PASS)

`verify_opvar.py` covers the six paths above with exact expected values;
`opvar_demo.va` (real + integer + hidden variables) and `opvar_str.va`
(string opvar) are the two models.

## Regression

No compiler/ngspice source changes; the Enhancement-68 regression state
stands, plus this suite's 11 checks.
