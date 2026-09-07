# Enhancement-578: `%x`/`%t` conversions, the task named in a missing-argument error, lint L026 on literal formats, and `1.0 % 0.0` as a compile error

**Scope:** three compiler findings of the 2026-09-07 hunt
([`docs/bug_hunts/2026-09-07_openvaf-r-language-semantics.md`](../docs/bug_hunts/2026-09-07_openvaf-r-language-semantics.md),
F5, F6 and F7), all in the front end. `openvaf/hir_ty/src/inference/fmt_parser.rs` (the
conversion set and its candidate lists), `openvaf/hir_ty/src/inference.rs` (the bare-form
fast path, the argument type per conversion, the task name carried by `MissingFmtArg`),
`openvaf/hir_ty/src/diagnostics.rs` (the message), `openvaf/hir_lower/src/fmt.rs` (the C
format each new conversion lowers to), `openvaf/hir_ty/src/validation/body.rs` (the L026
walk and a new `fmt_operand_count`; the constant-divisor check for a real `%`),
`openvaf/test_data/ui/formatting.log` (the candidate list the UI test expects).
**OpenVAF-r only.**

**Suites:** new [`fmtdiag_examples`](../examples/fmtdiag_examples/) (40 checks, 16 of
them passing against the shipped compiler); `display`, `lrmexpr` and `scanfmt`, which pin
the neighbouring wording, unchanged at 22/22, 22/22 and 31/31; full sweep 477 of 477.
Compiler crate tests (`syntax`, `hir_def`, `hir_ty`, `hir`, `hir_lower`, `openvaf` with
`llvm18`) 37 of 37; the `--workspace` build still stops in `verilogae`, which has drifted
behind two callback additions from earlier enhancements and is not touched here.

## F6 — `%x`, `%X`, `%t`, `%T` were "unexpected character"; a missing argument blamed `$display`

IEEE 1364-2005 17.1.1.2, which Verilog-AMS 2.4 inherits for the display tasks, lists
`%x` as a synonym of `%h` and `%t` as the time conversion. The format parser's
terminator set did not include either, so `$strobe("%x", i)` was refused with "failed to
parse format specifier; unexpected character x" — while the scanner side (`$sscanf`)
had accepted `%x` since Enhancement-11. The four characters join the conversion set in
the parser, the bare-form fast path in inference, the per-conversion argument type
(`%x`/`%X` an integer, `%t`/`%T` a real), and the lowering, where `%x`/`%X` map onto C's
own `%x`/`%X` and `%t` renders as `%g`: analog time is a real number of seconds and this
compiler has no `$timeformat` scaling, so the value prints as it is. Flags, width and
precision apply as to every other conversion (`%5x`, `%-6X`, `%08x`, `%8.3t`), and
`$sformat`/`$write` take the new forms because they share the same code.

The missing-argument report was built from a diagnostic that carried no task name and
said `$display system task is missing an argument` for a `$strobe`, a `$write`, a
`$fatal` or a `$sformat`. `MissingFmtArg` now carries the name of the task that was
called, handed down from the one place that knows it (the builtin dispatch into
`infere_display`), and the message names it.

## F7 — lint L026 fired on a literal format whenever a string argument was not the last

Enhancement-507's L026 warns when a `$display`-family call hands a *run-time* string
where a format is expected with operands after it: the lowering reads a format only from
a literal, so `f = "MARK %g"; $strobe(f, 2.5)` prints `MARK %g 2.5`, and the warning
says so. Its first version looked at every argument in turn and flagged any string-typed
non-literal that had another argument after it — which is exactly the string operand of
a `%s` in the most ordinary call there is:

```verilog
parameter string nm = "abc"; parameter real k = 2.0;
$strobe("name=%s k=%g", nm, k);     // warned: "this format string is not a literal"
```

The format is a literal and the output was right; the lint was reading `nm` as a
nested format. The check now walks the arguments the way `hir_lower::fmt` does: a
literal is a format and its conversions consume the arguments after it, so the walk
steps over those operands (`fmt_operand_count`: `%%`, `%m`, `%l` take none, each `*` in
a `[flags][width][.prec]` prefix takes one integer, every other conversion takes one)
and only a string-typed argument that no format consumed, with an operand following it,
is reported. The literal test is the lowering's own (`Expr::Literal`), not `const_str`,
so a `localparam string` used as a format — which the lowering prints by type — is now
reported too rather than silently skipped. A run-time format with an operand still
warns exactly once; a run-time string alone, `$sformat`'s destination, star widths and
a literal `%s` operand are quiet.

## F5 — `1.0 % 0.0` folded to NaN and said nothing

Every other domain the body validator judges on a constant argument — `sqrt(-1.0)`,
`ln(0.0)`, `asin(2.0)` (Enhancement-455), `pow(-2.0, 0.5)` and `x ** y`
(Enhancement-489) — is a compile error "the result would be NaN"; the integer `%` by a
literal zero is Enhancement-333's "integer remainder by zero"; and a deck-supplied zero
on either path is Enhancement-509's run-time `$fatal` naming LRM 4.2.4. The one gap was
a real `%` whose zero divisor the compiler could see: `1.0 % 0.0` and `V(p,n) % 0.0`
compiled clean and produced NaN in the value. A `BinaryOp::Remainder` arm beside the
`**` arm now reports

```
error: %: the second operand (the modulus divisor) is 0, which LRM 4.2.4 makes an error; the result would be NaN
```

when the expression is not integer-typed and `const_num` folds the divisor to zero — a
literal, `-0.0`, a `localparam` or one that folds to zero (`3.0 - 3.0`), in a body or a
parameter default. `const_num` never folds an overridable `parameter`, so `1.0 % z` with
`parameter real z = 0.0` compiles as before and is the run-time fatal, with the same LRM
reference in both messages.

## Verification

`fmtdiag_examples` compiles each shape and, for the conversions, runs the module through
ngspice and reads the `OSDI n1:` lines: `A: ff FF ff FF`, `B:    ff|FF    |000000ff`,
`C: t=2.5e-06 T=2.5e-06  2.5e-06`, `$sformat` and `$write` alike; `%v` is still refused
and the candidate list names the four new characters; six missing-argument shapes name
their task; ten literal-format shapes are quiet and two run-time-format shapes warn
exactly once; six constant-zero divisors are errors, four non-zero or overridable shapes
compile, the integer form keeps its own message, and the parameter zero still aborts the
operating point with the run-time message. The UI test `formatting.va` reproduces its
log with only the candidate list changed.
