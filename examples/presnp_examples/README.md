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
