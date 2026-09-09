# Enhancement-590: `$param_given` on an array, lint L030 for lossy integer constants, lint ids on the command line, and six diagnostic slips

**Scope:** `openvaf/hir_ty/src/inference.rs` (`$param_given(arr)`),
`openvaf/hir_lower/src/expr.rs` (its lowering, and the string-constant folder),
`openvaf/hir/src/body.rs` (the E-555 side table), `openvaf/basedb/src/lints.rs` (L030),
`openvaf/syntax/src/ast/expr_ext.rs`, `openvaf/hir_def/src/body.rs` and `body/lower.rs`
(the overflowing literal is recorded), `openvaf/hir_ty/src/validation/body.rs` and
`validation.rs` (the two L030 checks, the axis-count warning, the concatenation fold),
`openvaf/hir_def/src/nameres.rs` and `nameres/diagnostics.rs` (the function-scope
message and the notes), `openvaf/hir_ty/src/diagnostics.rs` (notes on resolver errors),
`openvaf/hir/src/elaborate.rs` (instance-name collisions),
`openvaf/openvaf-driver/src/cli_def.rs` and `cli_process.rs` (lint ids),
ngspice `src/frontend/numparam/xpressn.c` (the quoting hint),
`examples/hunt3diag_examples/` (new, 42 checks per solver). Hunt finding F8 of
2026-09-08, nine items; two of its parts were withdrawn (below).

**Suites:** [`hunt3diag_examples`](../examples/hunt3diag_examples/) 42 of 42 per
solver, both solvers; `portconnected_examples` updated to the new wording of one
message; full sweep 485 of 485; every compiler crate test passes.

## What was wrong, and what changed

**(a) `$param_given(arr)` on an array parameter** was refused with "'arr' requires a
bit-select [i]". LRM 9.19 takes a parameter identifier, and an array parameter is
one. The generic call path infers the argument first, and a bare array name fails
there; the call now takes the same pre-resolution the filters use for whole-array
arguments and answers for the array: true when any element was given. The elements
are separate OSDI parameters, so lowering ORs their given flags. The E-555 side table
of `$param_given`-tested parameters lists every element. `$param_given(arr[0])`
keeps working.

**(b) A constant an `integer` cannot hold was folded without a word.** The literal
`3000000000` does not fit 32 bits, so body lowering read it as the real 3e9 (that was
deliberate: a bare digit string is a fine real where a real is wanted), and stored
into an integer it saturates to 2147483647; `parameter integer half = 2.5` ran with
3. The same values on a model card are refused (out of range) or warned (rounded).
Lint **L030 `lossy_integer_constant`** (warn) now reports the literal — "integer
literal 3000000000 does not fit a 32-bit integer", labelled with the real it became
and the saturated value, with the LRM 3.2 range in a note — and an `integer`
parameter whose constant default has a fraction ("rounded to 3") or does not fit
("clipped to 2147483647"). An overflowing literal that *is* the default is reported
once, at the literal. `-2147483648` and integer defaults are quiet; the check reads
the folded value, so a saturating `2**40` (the documented E-5 rule) stays quiet too.

**(c) Lint ids on the command line.** Diagnostics print `warning[L022]`, but
`-A L022` was "invalid value" and `--lints` listed names only, so nothing on the CLI
led from the id to the flag. `-A`, `-W` and `-E` accept the id (hidden from the
possible-values list, so the names stay the documented spelling), and `--lints`
prints the id beside each name.

**(d) A branch probe inside an analog function** (`f = x + V(p,n)`) was "'V' was not
found in the current scope" — a name that exists, one scope up. The resolver's
function-scope miss now looks the name up in the enclosing module and says what it
is: "'V' cannot be used inside an analog function: it is a nature access function of
the enclosing module", with the LRM 4.7.1 note that a probe is evaluated by the caller
and passed in as an argument; a net is "a node", a module variable "a variable", each
with the fitting advice. Module parameters were and are visible in functions; a name
that exists nowhere keeps "was not found".

**(e) `localparam string f = {"t1", ".tbl"}`** as a `$table_model` file name was
refused as "must be a compile-time constant string". Both string-constant folders
(hir_ty's validation and hir_lower's, which must agree) now fold a concatenation of
constant strings. The first fix alone let the model compile and read an empty table:
the two folders are twins on purpose, and both are covered.

**(f) A control string naming more axes than the table has inputs** (`"3L,1L"` on a
1-D table) compiled without comment. E-395's `langguard` suite documents that extra
sub-strings on the 1-D runtime form still compile, so this is a **warning**, not an
error: "control string "3L,1L" names 2 axes but the table has 1 input", labelled
"the sub-strings after the first 1 are ignored". An `I` sub-string names a data
column to ignore and is not counted (`"I,1L,1L"` on a 2-D file is right).

**(g) `leafx l1;`** — an instance without a connection list — is read as a net
declaration and refused as "expected discipline but found module 'leafx'". That
error now carries the note that a module instance needs a port connection list,
`leafx <instance>(<ports>);`.

**(h) An instance sharing its name with a net, parameter or variable** compiled
without a word, and two instances with one name surfaced later as "'l2__r' was
already declared" (the mangled parameter of the second). Elaboration now checks
the source before the instantiations are rewritten out of it: "instance 'l1' has the
same name as a net, parameter, variable, branch, function or genvar of module
'he40'" and "instance 'l2' is declared twice in module 'h4'".

**(i) ngspice: `s=b` on a model card** was "Undefined parameter [b] / Cannot compute
substitute". The card's bare word is wrapped as the expression `{b}` before numparam
sees it, so numparam is where the two readings meet: when the fragment that failed is
a bare identifier, the message adds "'b' is not a .param name; if it is meant as a
string value, quote it: "b"". A broken expression keeps the plain message.

**Withdrawn from F8:** the "empty help line" for a non-ASCII identifier was the
hunt's own grep dropping the help's second line (`é instead of e` is printed), and the
"unsupported control string without a list of what is supported" already carries the
full list in a note.

```verilog
g = $param_given(arr);                      // true when any element was given
parameter integer big = 3000000000;         // warning[L030]: ... does not fit a 32-bit integer
localparam string f = {"t1", ".tbl"};       // a constant table file name
```

```
openvaf-r -A L022 model.va
openvaf-r --lints        ->    discarded_contribution             L022
```

## Verification

| check | result |
|---|---|
| `$param_given(arr)` with nothing, one element, two elements, only a scalar given | 0, 1, 1, 0; the scalar's own flag unchanged |
| L030 on a body literal and a parameter default of 3000000000, a 2.5 default | once each at the literal, "rounded to 3" for 2.5; none for 3 or -2147483648; `-A lossy_integer_constant` silences, `-E L030` makes it an error |
| `-A L022`, `-E L022`, `-W discarded_contribution`, `-A L999` | silenced, error, warning, "invalid value" |
| `--lints` | `discarded_contribution  L022`, `lossy_integer_constant  L030` |
| `V(p,n)`, a module variable, a net inside a function; a module parameter; a name that exists nowhere | the three messages with LRM 4.7.1; compiles; "was not found" |
| `{"t1", ".tbl"}` file name | compiles and reads the table: 2.5 at 1.5 |
| `"3L,1L"` on 1-D, `"1L,1L,1L"` on 2-D, `"1L,1C"` and `"1L"` on 2-D, `"1L,1L,I"` on a 2-D file, `"1L,1C"` on the runtime form | warned with the counts, warned, quiet, quiet, quiet, warned and still compiling |
| `leafx l1;` | the error plus the port-connection-list note |
| an instance named like a net, a parameter, a variable; two `l2`; distinct names | refused by name, refused by name, refused, "declared twice", compiles |
| ngspice `s=b`, `s="b"`, `s={1+}` | the quoting hint; the string set (2 kΩ, −0.5 mA); the plain message |
