# annexe_examples — Annex E SPICE-compatibility primitives (Enhancement-89)

`annex_e_primitives.va` is a small reusable library of the LRM Annex E
SPICE primitives as clean Verilog-A modules: `resistor`/`capacitor`/
`inductor`, `vsource`/`isource`, and square-law `spice_nmos`/`spice_pmos`.
Include it with `` `include "annex_e_primitives.va" ``.

Because the names match ngspice's built-in devices, they may only be used as
**sub-modules** flattened into a top module (Enhancement-5), never as a
top-level `.model` device (openvaf-r warns, L018). Two demos:

- `rc_lowpass` (resistor + capacitor): DC pass-through + the RC charging
  time constant (63.2 % at t = RC);
- `cmos_inv` (spice_pmos + spice_nmos): rail-to-rail inversion.

Run: `python3 verify_annexe.py` (6 checks).
