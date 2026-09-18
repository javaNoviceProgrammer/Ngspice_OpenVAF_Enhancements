# Enhancement-661: `do … while` and a `disable` outside an event block are said to be openvaf extensions (L011), and a named block inside an analog function no longer crashes the compiler

**Scope:** F18 of the
[bug hunt of 2026-09-18](../docs/bug_hunts/2026-09-18_openvaf-r-corners-and-run-control.md),
re-read against VAMS-2023. Compiler: `openvaf/hir_ty/src/validation/body.rs`
(the two diagnostics, an event-depth counter), `openvaf/hir_ty/src/validation.rs`
(their reports under `non_standard_code`), `openvaf/hir/src/lib.rs` and
`openvaf/hir/src/rec_declarations.rs` (a named block without a definition map
is an empty scope, not a panic). `examples/dowhile_examples/` (two checks added)
and `examples/disable_examples/` (five). Handbook
[§2.11](../docs/handbook/02-verilog-a-language.md) rows. **Compiler only.**

**Suites:** [`dowhile_examples`](../examples/dowhile_examples/) and
[`disable_examples`](../examples/disable_examples/) green on both solvers (one
and three of the new checks fail on the E-659 compiler); `lrmjump`, `funclocal`
unchanged; the compiler's workspace tests green (the three sourcegen rewrites
are the known drift); full sweep 529 of 529.

## What the hunt said, and what the LRM says

F18 listed `break`, `continue`, `do … while` and `disable` as "SystemVerilog
and digital Verilog" accepted in an analog block without a word, against the
`>>>` shift, which is warned as an openvaf extension. Read against VAMS-2023:

- **`break` and `continue` are Verilog-AMS.** LRM 5.11 *Jump statements*
  provides them, A.6.4 lists `jump_statement` under `analog_statement`, and
  [E-520](Enhancement-520.md) implemented them with 5.9.3's exclusion from
  genvar loops enforced (`break` inside an unrolled `analog for` is refused,
  once per unrolled copy). The finding was wrong there; nothing changes.
- **`disable` is Verilog-AMS inside an event block only.** A.6.4 lists
  `disable_statement` under `analog_event_statement`, not under
  `analog_statement` or `analog_function_statement`. The [E-9](Enhancement-9.md)
  loop idioms — a named block around a `for`, `disable` as a break — are an
  openvaf extension, and one that ends the analog block itself when the block
  disabled is the outer one: the contributions after it are skipped in silence.
- **`do … while` is not Verilog-AMS.** LRM 5.9 has `repeat`, `while` and
  `for`; [E-19](Enhancement-19.md) added the post-test loop as an extension and
  said nothing at compile time.

## What changed

- **Two L011 warnings** (`non_standard_code`, the lint the `>>>` shift uses;
  `-A non_standard_code` silences them), raised by the body validation pass,
  which already tracks loops and now counts enclosing event controls:
  - *`do ... while` in an analog context is an openvaf extension* — help: LRM
    5.9 has `repeat`, `while` and `for`; a `do ... while` runs its body once
    before the first test, which other Verilog-A compilers refuse.
  - *`disable` outside an event control is an openvaf extension* (or *in an
    analog function*) — help: VAMS-2023 A.6.4 allows `disable <block>` only
    inside an `@(...)` event block; a loop exit is `break` or `continue` (LRM
    5.11), and a block ended by `disable` here skips the contributions after
    it in silence. Inside an event block: no word.
- **A named block inside an analog function compiles.** Probing `disable` in
  a function found the compiler crashing on *any* `begin : b … end` in a
  function body — a legal `analog_function_seq_block` — with or without a
  `disable`: E-646's walk of a function's local variables reaches every named
  block, and a named block that declares nothing has no definition map, which
  the scope lookup treated as impossible (`expect("block is named")`). The
  lookup is optional now; such a block is an empty scope. `f(1)` with
  `begin : b f = 2*x; end` gives 2; with `begin : b f = x; disable b; f = 2*x;
  end` gives 1, under the function-worded warning.

No corpus model uses `do … while` or `disable`, so nothing in the model
library gains a warning.

## Verification

| check | result |
|---|---|
| `dowhile_demo.va` | one L011 with the LRM 5.9 note; `-A non_standard_code` silences it; n=3 → 3 |
| `break_demo.va` (E-9's idiom) | one L011 naming `break`/`continue` |
| `disable` inside `@(initial_step)` | no word |
| `begin : b f = 2*x; end` in an analog function | compiles (crashed), runs: −2 mA |
| `begin : b f = x; disable b; f = 2*x; end` in a function | L011 worded for a function; runs: −1 mA |
| `break` in a genvar loop | refused, as before (E-520) |
| the E-659 compiler on the same suites | 1 of 2 and 3 of 5 new checks fail |

Full sweep 529 of 529 on both solvers.

## What this does not do

- `break`, `continue`, `return` are untouched.
- A `break` inside a genvar loop is reported once per unrolled copy, under the
  generated file's name; that is hunt F11's slip, not this one.
