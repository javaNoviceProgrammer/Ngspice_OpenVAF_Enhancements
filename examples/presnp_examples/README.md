# Built-in `pre_snp` command (Enhancement-200)

Enhancement-199 shipped `snp2va.py`, a standalone Python converter from a Touchstone
`.sNp` S-parameter file to a **Verilog-A n-port model**. Enhancement-200 folds that
converter into **ngspice itself** as a C command, `pre_snp`, so no external script —
and no Python — is needed. Point `pre_snp` at a `.sNp` file (just like `pre_osdi`
points at an `.osdi`) and it does the whole pipeline in one line:

```
.control
pre_snp bandpass.s2p          * parse .s2p -> vector-fit -> write bandpass.va,
                              *   then run openvaf-r -> write bandpass.osdi
pre_osdi bandpass.osdi        * load the freshly compiled n-port model
.endc
```

then instantiate it like any OSDI model:

```
N1 p1 p2 mm
.model mm bandpass            * the module name pre_snp emitted
```

`pre_snp <file.sNp> [module]` — the optional second argument names the Verilog-A
module (default: the file's base name). The `.va` and `.osdi` are written next to the
`.sNp`.

## Runs before `pre_osdi`, always

`pre_snp` is a `pre_` command, so — like `pre_osdi` — it runs *before* the circuit is
parsed. On top of that, **every `pre_snp` is forced to run before every other `pre_`
command**, regardless of deck order. That means the `.osdi` a `pre_snp` generates is
guaranteed to exist by the time a `pre_osdi` tries to load it, even if you write the
`pre_osdi` line first. (Internally the pre-command list is executed in two passes:
all `pre_snp` commands first, then the rest.)

## Finding the compiler

`pre_snp` shells out to `openvaf-r`, which it locates via, in order:

1. the `openvaf` ngspice variable — `set openvaf=/path/to/openvaf-r` **in `spinit`
   or on the command line** (a `set` inside `.control` runs too late — after the
   pre-commands);
2. the `OPENVAF` environment variable;
3. `$SPICE_LIB_DIR/openvaf-r`;
4. `PATH`.

If none resolve, `pre_snp` reports the failing command and lists these four options.

## The converter

Identical numerics to `snp2va.py` (see `../nport_examples/`), reimplemented in C:
common-pole **vector fitting** (Gustavsen) with automatic order selection, the
strictly-proper part realized through `laplace_nd` and the improper `e·s` (shunt-C)
term split out as an explicit `ddt`, right-half-plane poles reflected for
BIBO-stability. Touchstone coverage: any port count; `S`/`Y`/`Z` data; `MA`/`DB`/`RI`
formats; `Hz`/`kHz`/`MHz`/`GHz`; arbitrary reference impedance.

## Verification

`verify_presnp.py` — 5 checks. Each builds a Touchstone file from a network whose
response is known *exactly*, lets `pre_snp` do the whole convert+compile+load **inside
ngspice**, and confirms the device matches the ORIGINAL network: `pre_snp` writes the
`.va` and compiles the `.osdi`; the device matches an R-L-C resonator in **AC**
(including the transmission peak) and in **transient** (one compiled block, both
analyses); a **3-port** star network compiles and matches on both coupled outputs; and
— with `pre_osdi` written **before** `pre_snp` — pre_snp still runs first so the model
loads (the **ordering guarantee**).

## Running

```sh
python3 verify_presnp.py            # exports OPENVAF so pre_snp finds the compiler
```

## Limitations

The same as the `snp2va.py` converter: frequency-domain rational fitting cannot invent
behavior outside the tabulated band (keep the `.sNp` band wider than the simulation's
spectral content), and pure-delay / distributed blocks take many poles and ring on
sharp edges (use a `T`/`LTRA` line for a clean delay). Lumped/rational blocks —
filters, resonators, notches, couplers, packages — fit to near machine precision in
both AC and transient. See `../nport_examples/` for the underlying converter's details.

## Round 4 (Enhancement-741) — Touchstone 2, and the v1 Y/Z forms

F1, F10 and F11 of the 2026-09-26 Touchstone-import hunt. The parser behind
`pre_snp` (both backends share it) treated a Touchstone 2 keyword line as
data: the numbers on `[Version] 2.0`, `[Number of Ports] 2`, `[Number of
Frequencies] 21` and `[Reference] 50 50` entered the number stream, every
frame was misaligned, the frame count dropped its remainder in silence and the
vector fit ran on garbage — 16 poles, rms error 6e-2 and an S21 of −66.7 for
a file whose v1 form fits to 2 poles and 4e-4. A `.y2p` or `.z2p` written by
`wrsnp` was read as a 1-port (only an `.sNp` extension counted the ports, and
the divisor fallback answers 1 for every two-port frame of 9 numbers), and a
v1 Y or Z file's data, which the specification normalizes to R, was taken as
absolute.

Now `pre_snp` reads Touchstone 2 — `[Version]`, `[Number of Ports]`,
`[Two-Port Data Order]`, `[Number of Frequencies]`, a per-port `[Reference]`
continued over lines, `[Matrix Format] Full/Lower/Upper`, an information
block, `[Network Data]`, `[Noise Data]` (skipped), `[End]` — refuses
`[Mixed-Mode Order]`, the G/H parameter types, an unknown keyword and a number
count that is not a whole number of frames by name (a v1 file's
noise-parameter rows are named as the usual cause), counts ports from a
`.yNp`/`.zNp` extension, de-normalizes v1 Y and Z and takes v2's as absolute,
and carries a per-port reference into the S-to-Y conversion.

The ten `[E-741]` checks use `pre_snp -native` (no compiler) and compare each
block against the original network's AC response: a v2 two-port in `12_21`
order with a split `[Reference]` and an information block; a per-port
`[Reference] 50 75`; the 3-port star as a `.ts` file in `Lower` format; a
`21_12` file with a `[Noise Data]` section; a v1 file with noise rows refused
by name with nothing written; a `.y2p` and a `.z2p` as `wrsnp` writes them; a
v2 Y file; and the three refusals (`[Mixed-Mode Order]`, a two-port without
its data order, a `[Number of Frequencies]` that disagrees with the frames).
19 checks in all; 9 of 19 on the E-739 binary.

## Round 5 (Enhancement-745) — the fit's acceptance limit

The converter reported its rms relative error and emitted the model whatever
the value. Now a fit whose worst element's relative rms error is above 0.1
is refused before anything is written, with the number, the pole count, the
limit, the usual causes and the flags: `pre_snp -maxerr <x>` raises the
limit for that command, `-force` removes it, and a fit accepted that way
above the default says so. The five `[E-745]` checks: a seeded random
(unfittable) file refused with nothing written, `-maxerr 2` and `-force`
accepting it, `-maxerr abc`/`-maxerr 0` refused naming the flag, and
`-maxerr 1e-9` refusing even the clean resonator. 24 checks in all; 19 of
24 on the E-744 binary.
