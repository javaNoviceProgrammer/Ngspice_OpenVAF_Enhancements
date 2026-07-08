# Enhancement-72 — Touchstone round 2: MA/DB formats, frequency units, Y/Z export, and the `rdsnp` reader

This document describes Enhancement-72, completing the Touchstone arc
begun in Enhancement-64. ngspice-only — no compiler/OSDI change.

## Writer options (`wrsnp <file> [ri|ma|db] [s|y|z] [hz|khz|mhz|ghz]`)

The generalized writer (`spar_write_np`) now covers the full Touchstone
v1 option surface, any combination, any order after the file name:

- **formats**: `RI` (real/imaginary, the default), `MA`
  (magnitude / angle in degrees), `DB` (20·log₁₀ magnitude / angle);
- **parameters**: `S` (default), **`Y` and `Z`** — exported from the sp
  plot's `Y_i_j`/`Z_i_j` vectors, **normalized to Rbase** (`Y·R`, `Z/R`)
  as the Touchstone v1 spec requires;
- **frequency units**: Hz (default), kHz, MHz, GHz — the frequency column
  is scaled and the option line says so (`# GHz S DB R 50`).

The bare 2-port default (`wrs2p file` / `wrsnp file`) still goes through
the byte-identical classic path; every optioned case (and every N ≠ 2)
uses the generalized writer, which also handles the Touchstone 2-port
column order (S11 S21 S12 S22 on one line) and the N ≥ 3 row-major /
4-pairs-per-line layout from E-64.

## The reader: `rdsnp <file> [nports]`

Reads a Touchstone v1 file into a **new plot** (`Touchstone import
<file>`) holding a real `frequency` scale in Hz plus complex `S_i_j`
(or `Y_i_j`/`Z_i_j`) vectors that match the `.sp` plot's conventions —
so imported measurement data compares 1:1 against simulated vectors
(`let err = maximum(mag(S_2_1 - {sp1}.s21sim))`).

- parses the `#` option line (any token order): frequency unit, parameter
  type, format, `R n` — missing option line assumes `Hz S RI R 50` with a
  warning;
- converts MA/DB back to real/imaginary and **de-normalizes Y/Z** back to
  absolute values;
- handles the 2-port column order and the general row-major layout;
- port count from the `.sNp` extension, or explicitly (`rdsnp file 3`);
- publishes `Rbase` in the imported plot so it round-trips back through
  `wrsnp`;
- a number count that doesn't divide into frequency blocks is a clear
  error naming the suspected wrong port count.

## Verified (touchstone_examples grows to 17 checks, ALL PASS)

The five E-64 sections are unchanged; round 2 adds: [6] option lines and
math for MA (= polar of the RI values), DB (= 20·log₁₀ magnitude) with
GHz scaling, and Y/Z headers; [7] a **full write-MA → `rdsnp` → compare
round-trip** — max |S21(read) − S21(simulated)| = 4e-8, below the file's
own 6-digit precision; [8] a hand-written measurement-style MA/MHz file
read back with exact values (0.5∠−90° → −0.5j) through the 2-port column
order and unit scaling.

## Regression

All 65 example verify suites pass with the rebuilt ngspice; the openvaf
integration suite 28/28; no compiler change.
