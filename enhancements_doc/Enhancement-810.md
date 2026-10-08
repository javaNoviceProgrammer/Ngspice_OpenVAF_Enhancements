# Enhancement-810: a saved OSDI parameter or opvar is typed by the `units` it declares — `units="W"` is power, not voltage

**Scope:** D17 of the
[ngspice + OSDI hunt of 2026-10-08](../docs/bug_hunts/2026-10-08_ngspice-osdi-hierarchy-sweeps-events-and-outputs.md).
ngspice:
- `osdi/osdiparam.c`: new `OSDIparamUnits`.
- `include/ngspice/osdiitf.h`.
- `frontend/outitf.c`: `guess_type` asks it (`e810_osdi_units_type`) before the name heuristics.

`examples/osdislips_examples/` (section [16], ten checks). **ngspice only.**

**Suites:** [`osdislips_examples`](../examples/osdislips_examples/) 93 of 93 per solver (5 of the 10
in [16] fail on the E-795 binaries); the full sweep, 538 of 538.

## What was wrong

A saved `@dev[param]` vector's type, which `display`, `plot` axes and the raw file show, was
guessed from the parameter's name:

| starts with | type |
|---|---|
| `[g` | admittance |
| `[c` | capacitance |
| `[i` | current |
| `[q` | charge |
| exactly `[p]` | power |
| anything else | voltage |

For an OSDI opvar, whose Verilog-A declaration states its units, this was mostly wrong. A
`(* desc="power", units="W" *) real pw;` was `@n1[pw] : voltage`. `units="Ohm"`, `"furlong"` and
no units were voltage too. An opvar was "current" only because its name began with `i`: an
`ifoo` with no units was current, and an `iop` with `units="A"` was current by accident.

## The change

For a saved vector of an OSDI instance's parameter or opvar, `guess_type` asks the descriptor
for its declared units (`OSDIparamUnits`, aliases included):

| units | type |
|---|---|
| `A` | current |
| `V` | voltage |
| `W` | power |
| `Ohm`, `Ohms`, `ohm`, `ohms`, `Ω` | impedance |
| `S`, `mho`, `Mho`, `A/V` | admittance |
| `F` | capacitance |
| `C` | charge |
| `s` | time |
| `Hz` | frequency |
| `dB` | decibel |
| `rad` | phase |
| `V/sqrt(Hz)`, `A/sqrt(Hz)` | the two densities |

Units are compared exactly, so `s` (seconds) and `S` (siemens) stay apart. No units, or units
ngspice has no type for, give `notype`. A name the descriptor does not hold keeps the old
heuristics: the synthesized terminal currents `@n1[i_a]`, `temp` and `dtemp`, and every built-in
device. A device inside a subcircuit is found by its flattened name or by E-410's `x1.n1`.

## The checks

osdislips [16]: after a `tran`, `display` types the vectors as follows.

| vector | units | type |
|---|---|---|
| `@n1[pw]` | `W` | power |
| `@n1[rr]` | `Ohm` | impedance |
| `@n1[cc]` | `F` | capacitance |
| `@n1[gg]` | `S` | admittance |
| `@n1[iop]` | `A` | current |
| `@n1[vv]` | `V` | voltage |
| `@n1[nounit]` | none | notype |
| `@n1[ifoo]` | none | notype (current before) |
| `@n1[odd]` | `furlong` | notype |
| `@n1[i_a]` | terminal current | current |

## Limits

- Temperatures (`K`, `degC`) map to `notype`: ngspice's only temperature type is the
  Celsius-labelled sweep scale.
