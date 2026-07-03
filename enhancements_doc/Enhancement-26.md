# Enhancement-26 — `ac_stim(...)` baseline (crash fix + correct large-signal semantics)

This document describes the change made to **OpenVAF-r** in the `version11/`
directory for **`ac_stim([name][, mag][, phase])`**, the Verilog-AMS small-signal
AC stimulus source. This is the **baseline** step: it eliminates a compiler crash
and gives `ac_stim` its correct large-signal value. Full small-signal AC injection
is a larger follow-up (scoped below).

## The bug

`ac_stim`'s signatures were declared (so it type-checked), and the lowering had a
`no_equations` fallback returning 0. But any **contributing** use of `ac_stim`
(`I(a,b) <+ ... + ac_stim(...)`, in the normal has-equations path) matched no
dedicated arm and fell through to the builtin match's `_ => unreachable!()`,
**panicking the compiler** with `internal error: entered unreachable code`.

## The fix

`hir_lower/src/expr.rs` now has a dedicated `BuiltIn::ac_stim => F_ZERO` arm. Per
the Verilog-AMS LRM, `ac_stim` evaluates to **0 in the large-signal (DC and
transient) domain** and injects `mag∠phase` only during small-signal (AC)
analysis. Returning `F_ZERO` is therefore the correct large-signal value, and it
stops the crash — a model using `ac_stim` (in any of its four signature forms)
now compiles and simulates. One-line change; no OSDI ABI change, no ngspice change.

## Verification

`examples/acstim_examples/verify_acstim.py` (`ALL PASS`):

- the model **compiles** (it previously crashed `openvaf-r`);
- DC and transient currents equal `g*V(a,b)` and are **identical** with the
  `ac_stim` terms included vs excluded — i.e. `ac_stim` correctly contributes 0 in
  the large-signal domain.

Every prior example folder still passes.

## Known limitation — AC injection (the follow-up)

The one thing this baseline does **not** do is the actual small-signal **AC
injection**: during AC analysis, `ac_stim(name, mag, phase)` should inject
`mag∠phase` into the AC right-hand side (it currently contributes 0 there too, so
a testbench using `ac_stim` as its AC source sees no excitation).

Implementing that is a substantial, ABI-touching subsystem — essentially the
*noise* infrastructure rebuilt for AC:

- **hir_lower** — a new `CallBackKind::AcStim` producing a recognized small-signal
  source value;
- **sim_back** — recognise it in `topology`/`lineralize` (like `Noise::new`), mark
  it small-signal, and carry a new `ac_sources` list (node pair + complex value)
  through `dae`/`builder`;
- **OSDI (ABI addition)** — a new descriptor entry (a `load_spice_rhs_ac` function
  or `ac_source_infos` + offsets) with codegen in `load.rs`/`inst_data.rs`/
  `metadata.rs`/`eval.rs` and `osdi_0_4.h`;
- **ngspice** — `OSDIacLoad` stamps the complex `CKTrhs`/`CKTirhs` via the node
  mapping, with `OSDIsetup`/`osdidefs.h`/`osdi.h` support.

Because that modifies the AC load/descriptor path shared by every OSDI device, it
warrants its own focused, per-layer-tested enhancement rather than being folded in
here.
