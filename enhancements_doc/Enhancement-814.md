# Enhancement-814: an output variable's `multiplicity` attribute scales its report by `$mfactor` — with `m=4` every current, conductance and capacitance was reported per device, and every resistance four times too large

**Scope:** F23 of the
[ngspice + OSDI hunt of 2026-10-08](../docs/bug_hunts/2026-10-08_ngspice-osdi-hierarchy-sweeps-events-and-outputs.md).
openvaf:
- `sim_back/src/module_info.rs`: `OpVar` carries the attribute (`Multiplicity`) and, for an
  inlined child's variable, the child's multiplicity variable. `MultiplicityIgnored` names an
  attribute that cannot take effect.
- `hir_lower/src/lib.rs`, `ctx.rs`: a new output, `PlaceKind::OpVarReport`.
- `hir_lower/src/state.rs`: `insert_opvar_multiplicity` computes the report at the end of
  the function.
- `sim_back/src/lib.rs`: calls it before Enhancement-44's paramset composition.
  `context.rs` keeps the child multiplicity variables alive.
- `osdi/src/inst_data.rs`: the operating-point slot stores the report.
- `hir/src/elaborate.rs`: a child instance with a `$mfactor` override gets a hidden
  `<prefix>$mfactor`.

`examples/opvarmult_examples/` (new, 14 checks per solver). **openvaf only:** ngspice is
unchanged.

**Suites:** [`opvarmult_examples`](../examples/opvarmult_examples/) 14 of 14 per solver (13
fail on the E-813 binaries; the one that passes is the check that unmarked variables stay
unscaled). The corpus census below. The workspace tests. The full sweep, 541 of 541.

## What was wrong

LRM 3.2.1 lets an output variable say how its value is scaled "in any report of
operating-point values" when the instance stands for several devices in parallel:

```verilog
(* desc="current", units="A",   multiplicity="multiply" *) real itot;   // times $mfactor
(* desc="reff",    units="Ohm", multiplicity="divide"   *) real reff;   // over $mfactor
```

`"none"` (no scaling) is the default. openvaf-r read the attribute nowhere. With
`n1 1 0 mum m=4` at 2 V:
- `print @n1[itot] @n1[reff]` and `show n1` gave 2e-3 and 1000, the per-device values;
- the LRM's report is 8e-3 and 250;
- the terminal current itself, `i(v1)` = -8 mA, was scaled right.

The attribute is how standard models declare their operating point. Twenty model families
in the bundled corpus use it, nearly all through `OPM`/`OPD` macros, on about 1,400
operating-point variables across their versions:
- BSIM-CMG, BSIM-BULK, BSIM-IMG;
- PSP 103/104, PSP-HV, L-UTSOI;
- MEXTRAM, HICUM L0/L2;
- HiSIM2, HiSIM-HV, HiSIM-SOI, HiSIM-SOTB;
- MVSG, ASM-HEMT, EKV, R2/R3 CMC, MOSVAR.

The hunt page counted only the attribute's text (about ninety), which is mostly the macro
definitions. For a device with `m > 1` every one of these reports was wrong by the factor m:
drain current, gm, gds and the capacitances too small, the resistances too large.

## The change

The compiled model stores the scaled value in the operating-point slot. The LRM's scaling
belongs to the report, and the slot is only ever read by a report. So every simulator that
loads the `.osdi` reports it the LRM's way, with no flag for it to interpret.

- The variable itself is untouched. The model's own reads of it see the per-device value, as
  does a hidden state it carries between evaluations and a parent's hierarchical reference to
  it. Only the report is scaled: `itot * $mfactor` or `itot / $mfactor`, computed after the
  model's code and kept in its own slot.
- The factor is the effective multiplicity:
  - a netlist `m=`, or the `m=` of a subcircuit that holds the instance (ngspice passes it
    to the device);
  - a paramset's `.$mfactor = 8`, multiplied in. The report is built before Enhancement-44
    composes the paramset value into every read of `$mfactor`, so it is composed too.
  - for a Verilog-A child instance, its `#(.$mfactor(4))`, composed with every enclosing
    instance's. After flattening, that value exists only inside the rewritten reads of
    `$mfactor` in the child's body. The elaborator now keeps it in a hidden variable
    `c1__$mfactor` beside the child's variables. The compiler matches each child output
    variable to it by the flattened prefix (`c1__itot` to `c1__$mfactor`). The variable
    is only added when the child declares a `multiplicity`.
- Values and placements that cannot take effect get a warning, and the attribute is then
  ignored:
  - a value other than `"multiply"`, `"divide"` or `"none"`, or one that is not a string;
  - an integer, string or array variable;
  - a variable with no `desc` or `units`, which is not an output variable;
  - a variable in a named block.

## The checks

`opvarmult_examples`:
- **[1]** `m=4` at 2 V:
  - `itot` reports 8e-3;
  - `reff` (a constant) and `rr` (the parameter `r`) report 250;
  - a variable with no attribute and one with `"none"` are unscaled;
  - `show` agrees;
  - a running peak `vpk`, which the model carries from one evaluation to the next, reports
    8 after one `op` and after a second. A report fed back into the model would read 32.
- **[2]**
  - With no `m`, the reports are unchanged (2e-3, 1000).
  - After `alter n1 m=2` they are 4e-3 and 500.
  - A `.save @n1[itot]` vector in a transient holds 8e-3.
- **[3]** The multiplicity composes:
  - a subcircuit called with `m=3` gives 6e-3 and 333.3;
  - a paramset's `.$mfactor = 8` with `m=3` gives 48e-3 and 41.67;
  - Verilog-A children under `m=2`: the top's own 4e-3, `c1` under `#(.$mfactor(4))` 16e-3
    and 125 Ω, and its child `c2` under `#(.$mfactor(2))` 32e-3.
- **[4]** `m=0` disables the instance: a multiplied report is 0 and a divided one is infinite.
- **[5]** Five misplaced attributes give five warnings, and the module compiles. At `m=2` the
  ignored ones report unscaled, and the one good `"divide"` is divided.
- **[6]** HICUM L0 (`VA_TEST`) at `m=3` against `m=1`:
  - the collector current, `G_Mi` and `C_JEop` are three times larger;
  - `R_PIi` is a third.

  The E-813 binaries report the same per-device opvars at both.

**Corpus census.** Every directory of `VA_TEST` and `integration_tests` that uses the
attribute was compiled with the E-813 compiler and with this one: 106 standalone files. Each
gives the same exit status and the same diagnostics on both, so no model gains a warning.

## Limits

- The report of an integer, string or array output variable is not scaled (warned).
- An opvar read after `alter n1 m=...` and before the next analysis still holds the value the
  last analysis computed, scaled by the multiplicity that analysis ran with. That is true of
  every opvar.
- `"divide"` with `m=0` reports an infinity: no device has an infinite resistance.
