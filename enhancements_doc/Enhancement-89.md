# Enhancement-89 — name-then-range ports and the Annex E primitives

This document describes Enhancement-89, two related pieces of LRM
coverage: the **name-then-range** form of vectored net/port declarations,
and a small **Annex E SPICE-compatibility primitives** library.

## Part 1 — name-then-range net/port declarations

The LRM allows a vectored net or port to be declared in two orders. The
*range-then-name* form (Enhancement-3) was already supported:

```verilog
output [0:3] out;
electrical [0:3] out;
```

Enhancement-89 adds the *name-then-range* (unpacked-array) form the LRM's
page-45 example uses:

```verilog
input  in[0:2];        // port direction
output out[0:2];
electrical in[0:2];    // net / discipline
electrical out[0:2];
```

It is purely a syntactic alternative, so it is handled by a textual
pre-pass (`normalize_name_range_decls`, `hir/src/elaborate.rs`) that
rewrites `<head> <name>[range]` to `<head> [range] <name>` before parsing —
reusing all of the existing bus/port machinery unchanged (parser, item
tree, node expansion). The disambiguation from an instance array is exact:
an instantiation always has a `(port list)` after the range, so a
`<head> <name>[range]` followed by `;` is a declaration, not an instance.
Scope: single-name 1-D declarations (the LRM form); a multi-name or
multi-dimensional name-then-range declaration is left as-is. Complements
E-3 (range-then-name buses) and E-18 (name-then-range *variables*).

Runtime-verified (`arrayport_examples`, 7/7): a name-then-range output bus
drives per-bit taps to their exact fractions, a name-then-range input port
compiles, and the form is confirmed equivalent to its range-then-name
twin.

## Part 2 — the Annex E SPICE-compatibility primitives

LRM Annex E defines the SPICE primitives a Verilog-AMS simulator provides
for interoperability. Several LRM examples instantiate them
(`spice_nmos`/`spice_pmos`, `resistor`, `capacitor`, …). This enhancement
provides them as a small, reusable Verilog-A library
(`examples/annexe_examples/annex_e_primitives.va`):

- linear one-ports `resistor` / `capacitor` / `inductor`;
- independent sources `vsource` / `isource`;
- square-law (SPICE level-1) `spice_nmos` / `spice_pmos` (3-terminal).

They are ordinary modules meant to be **instantiated and flattened**
(Enhancement-5) into a top module — the names `resistor`/`capacitor`/
`inductor` deliberately match ngspice's built-in device names, so they may
never be registered directly as a `.model` device (openvaf-r warns, L018).

Runtime-verified (`annexe_examples`, 6/6): an RC lowpass (DC pass-through
+ the RC charging time constant to 63.2 %), and a CMOS inverter (rail-to-
rail from the two square-law MOS primitives).

## LRM suite

Two examples graduate with the primitives provided as context: the
page-152 transmission gate (`spice_nmos`/`spice_pmos`) and the page-153
instance-parameter forms (`mosp`/`spice_pmos`). The page-45 example's
name-then-range parse is fixed but it stays a limitation on its undefined
`gen`/`sink` modules and a multi-dimensional parameter-array literal. Suite
now **42 compile / 17 limitations / 21 AMS** (7/7).

## Verification

- `arrayport_examples` 7/7, `annexe_examples` 6/6 (both with ngspice
  runtime pins); LRM suite 7/7.
- Full regression + 28 integration tests; parser/hir snapshot tests green.
- Confirmed the name-then-range pre-pass leaves instance arrays and
  variable/parameter declarations untouched (the head-keyword exclusion
  and the `(`-after-range instance rule).

## Gotchas recorded

- A multi-bit *input* bus port read (`input [0:2] in; … V(in[k])`) has a
  pre-existing OSDI terminal-mapping oddity (independent of E-89 — the
  range-then-name twin behaves identically); the demo therefore drives a
  bus *output* and reads a scalar input, the shape E-3's own bus example
  uses.
- Annex E primitive modules must stay sub-modules; naming a top-level
  OSDI device `resistor` collides with ngspice's built-in (the E-29
  create_model gotcha).
