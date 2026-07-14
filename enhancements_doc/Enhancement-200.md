# Enhancement-200 — built-in `pre_snp` command

[Enhancement-199](Enhancement-199.md) shipped `snp2va.py`, a standalone converter
that turns a Touchstone `.sNp` S-parameter file into a Verilog-A n-port model. It
works, but it is an *external* step: the user runs Python, then `openvaf-r`, then
writes a deck. Enhancement-200 folds the whole thing into **ngspice itself** as a C
command, `pre_snp`, so the workflow collapses to one line next to `pre_osdi` — no
Python, no external script, nothing to install.

```
.control
pre_snp bandpass.s2p          * parse .s2p -> vector-fit -> write bandpass.va,
                              *   then run openvaf-r -> write bandpass.osdi
pre_osdi bandpass.osdi        * load the freshly compiled n-port model
.endc
```

then instantiate it like any OSDI device:

```
N1 p1 p2 mm
.model mm bandpass            * the module name pre_snp emitted (default: file base name)
```

`pre_snp <file.sNp> [module]` — the optional second argument names the Verilog-A
module; the `.va` and `.osdi` are written next to the `.sNp`.

## The converter in C

`snp2va.c` is a faithful C port of `snp2va.py` — same numerics, same order-selection
logic, same output. It is self-contained (only `stdio`/`stdlib`/`string`/`math`/
`ctype`/`complex`), using C99 `double _Complex` (typedef'd `cplx`) so it does not
collide with ngspice's own `complex.h` macros. The three primitives vector fitting
needs are reimplemented:

- **least-squares** via Householder QR (`lstsq_real`),
- **complex matrix inverse** via Gauss–Jordan (`mat_inv_c`),
- **polynomial roots** via Durand–Kerner (`poly_roots`).

The pipeline is unchanged from E-199: parse Touchstone → `S(f)` → `Y(f) =
(1/z0)(I−S)(I+S)⁻¹` → common-pole **vector fit** in normalized frequency (Gustavsen)
→ emit `I(p_i) <+ Σ_j [ laplace_nd(V(p_j), num_ij, den) + e_ij·ddt(V(p_j)) ]`, with
the improper `e·s` (shunt-C) term split out as an explicit `ddt` because `laplace_nd`
cannot represent an improper rational. Automatic order selection climbs the pole
count and returns the best **stable** fit (right-half-plane poles reflected → always
BIBO-stable). Numerically it was checked identical to the Python reference:
resonator RMS 4×10⁻⁶, ladder 7×10⁻⁷, 3-port 3×10⁻⁸.

The public entry point is `snp2va_convert(snpfile, vafile, module, msg, msglen)`; the
command wrapper `com_pre_snp` (in `com_presnp.c`) calls it, then shells out to
`openvaf-r` to compile the `.osdi`.

## Runs before `pre_osdi`, always

`pre_snp` is registered as a command named `snp`, so writing `pre_snp …` in a deck
triggers ngspice's existing `pre_` mechanism (`inp.c`): every `pre_`-prefixed control
line is stripped of its prefix and executed **before the circuit is parsed**. That
alone would not be enough — `pre_snp` must run before the `pre_osdi` that loads its
output, and control lines otherwise execute in deck order.

The fix is a **two-pass** execution of the collected pre-commands: pass 0 runs every
`snp` command (in deck order), pass 1 runs all the rest. So the `.osdi` a `pre_snp`
generates is guaranteed to exist by the time any `pre_osdi` tries to load it — even
if the deck lists the `pre_osdi` line *first*. The ordering is a guarantee, not a
convention the user has to remember.

```c
for (pass = 0; pass < 2; pass++)
    for (wl = pre_controls; wl; wl = wl->wl_next) {
        int is_snp = ciprefix("snp ", wl->wl_word) ||
                     strcasecmp(wl->wl_word, "snp") == 0;
        if (pass == 0 ? !is_snp : is_snp) continue;
        cp_evloop(wl->wl_word);
    }
```

(`snp` / `pre_snp` are also added to `inpcom.c`'s case-preservation list, alongside
`osdi` / `pre_osdi`, so the file path in the argument keeps its original case on
case-insensitive input handling.)

## Finding the compiler

`pre_snp` shells out to `openvaf-r`, which `find_openvaf()` locates via, in order:
the `openvaf` ngspice variable (`set openvaf=…` in **`spinit`** or on the command
line — a `set` inside `.control` runs too late, *after* the pre-commands), the
`OPENVAF` environment variable, `$SPICE_LIB_DIR/openvaf-r`, then `PATH`. If none
resolve, `pre_snp` reports the failing `openvaf-r` invocation and lists all four
options.

## Verification

[`examples/presnp_examples/verify_presnp.py`](../examples/presnp_examples/verify_presnp.py)
— 5 checks. Each builds a Touchstone file from a network whose response is known
*exactly*, lets `pre_snp` do the whole convert+compile+load **inside ngspice**, and
confirms the device matches the ORIGINAL network: `pre_snp` writes the `.va` and
compiles the `.osdi`; the device matches an R-L-C resonator in **AC** to 5×10⁻⁶
(including the transmission peak) and in **transient** to 5×10⁻³ (one compiled block,
both analyses); a **3-port** star network compiles and matches on both coupled
outputs to 4×10⁻⁹; and — with `pre_osdi` written **before** `pre_snp` — pre_snp still
runs first so the model loads, proving the ordering guarantee. Full example
regression: 164/164.
