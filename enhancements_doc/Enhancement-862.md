# Enhancement-862: `$vt` uses the model's own `P_K` and `P_Q` — `$vt(T)` sat 1.05e-6 below `` `P_K*T/`P_Q `` inside one model

**Scope:** F7 of the
[third robustness and correctness campaign of 2026-10-10](../docs/bug_hunts/2026-10-10_ngspice-openvaf-r-third-robustness-campaign.md).

openvaf-r:
- `preprocessor/src/processor.rs`: `numeric_macro`, a macro's numeric value at the end of
  preprocessing, following `` `define P_K `P_K_NIST1998 `` to the number.
- `preprocessor/src/lib.rs`: `Preprocess::vt_constants`.
- `hir/src/db.rs`: `CompilationDB::vt_constants`.
- `hir_lower/src/expr.rs`: the `$vt` arm.

`examples/vtconsts_examples/` (new). **openvaf-r only.**

**Suites:**
- [`vtconsts_examples`](../examples/vtconsts_examples/): 5 of 5 per solver. On the E-861
  binaries 3 fail; [2] and [5] are controls.
- `cargo test -p preprocessor -p hir_lower`: all pass.
- The full sweep: 568 of 568.

## What was wrong

LRM 9.15 defines `$vt` only as kT/q. openvaf-r's `$vt` took the 2019 exact SI values,
k = 1.380649e-23 and q = 1.602176634e-19, whatever the model included. Its comment said the
shipped `constants.vams` defaulted `P_K` and `P_Q` to the same set. It does not: the default
branch is NIST 1998 (1.3806503e-23, 1.602176462e-19), as
[Enhancement-519](Enhancement-519.md) kept it because the 2023 LRM asks for that backward
compatibility. The 2019 values are the `PHYSICAL_CONSTANTS_NIST2018` opt-in.

So inside one model `$vt(300.15)` and `` `P_K*300.15/`P_Q `` differed by 1.05e-6. A model that
writes its thermal voltage both ways, which compact models do, used two of them.

## The change

When the compilation defines both `P_K` and `P_Q` as numbers, `$vt` uses them:
- **Reading them.** At the end of preprocessing, `numeric_macro` reads an argument-less
  macro's body as one positive number. It follows a body that is a single argument-less macro
  call, so `` `define P_K `P_K_NIST1998 `` reaches 1.3806503e-23. Any other body (an expression,
  arguments) gives none.
- **The value.** `$vt(T)` is computed as (k·T)/q, the order `` `P_K*T/`P_Q `` evaluates in, so
  the two agree to the bit. That holds for the header's default branch, for its NIST2018,
  NIST2010, SPICE or OLD branches, and for a model's own definitions.
- **No constants named.** A model that defines neither keeps the 2019 SI values and the old
  formula, bit for bit.

ngspice's own constants are CODATA 2014 (`CONSTboltz`, `CHARGE`). A model on the default header
now has a `$vt` 1.4e-6 above ngspice's kT/q, where it was 3.4e-7 below; its `P_K` was already
that far. A model that wants ngspice's value defines `P_K` 1.38064852e-23 and `P_Q`
1.6021766208e-19, and its `$vt` is then ngspice's `boltz*T/echarge` to the bit (check [4]). The
header's SPICE branch is SPICE 3F5's older pair, not ngspice-46's.

A Verilog-A resistor's `white_noise(4*`P_K*$temperature/r)` still sits 1.3e-6 above the built-in
resistor's 4kT/R, by the ratio of NIST 1998's k to CODATA 2014's. That is the two standards, not
`$vt`.

## The checks

`vtconsts_examples`:
- **[1]** The default header: `$vt(300.15)` is `` `P_K*300.15/`P_Q `` to the bit (1.05e-6 apart
  on E-861).
- **[2]** (control) With `PHYSICAL_CONSTANTS_NIST2018`: the same, at the 2019 values.
- **[3]** `$vt` without an argument and `` `P_K*$temperature/`P_Q ``, at 27 °C and 85 °C.
- **[4]** A model's own `P_K` and `P_Q`, ngspice's CODATA 2014 pair: `$vt` is ngspice's
  `boltz*T/echarge`.
- **[5]** (control) No constants named: `$vt` is the 2019 SI kT/q, as before.
