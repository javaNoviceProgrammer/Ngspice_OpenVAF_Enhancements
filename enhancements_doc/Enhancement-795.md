# Enhancement-795: `` `define include 7 `` is an error — a compiler directive's name cannot be a macro name (IEEE 1364-2005 19.3.1)

**Scope:** D5 of the
[openvaf-r hunt of 2026-10-04](../docs/bug_hunts/2026-10-04_openvaf-r-run-time-domains-filters-and-instances.md).
openvaf:
- `preprocessor/src/parser.rs`: the directive table is now `directive_named`, and
  `is_directive_name` uses it.
- `preprocessor/src/processor.rs`: `define_macro` refuses a directive's name.
- `preprocessor/src/diagnostics.rs`: `MacroNameIsDirective`.
- `basedb/src/diagnostics/preprocessor_error.rs`: its report.

`examples/vafslips_examples/` (section [5], ten checks). **openvaf only.**

**Suites:** [`vafslips_examples`](../examples/vafslips_examples/) 67 of 67 per solver (8 of the 10
in [5] fail on the E-790 binaries); `preproc`, `vafdefine` and `diagslips` within the full sweep (537 of 537);
the workspace tests (the preprocessor's own); the corpus census (below).

## What was wrong

`` `define include 7 `` was stored without a word, and so was a macro named after any other
directive: `ifdef`, `define`, `timescale`, `resetall`, `begin_keywords` and the rest. Such a macro
can never be called, because the lexer always reads `` `include `` as the directive. Writing
`` `include `` where the 7 was meant ran the directive, which then wanted a file name: "unexpected
token, expected 'a string literal'", and a second error for the `;` after it. Neither named the
definition.

LRM 10.4 leaves `` `define `` to IEEE 1364. IEEE 1364-2005 19.3.1: "All compiler directives shall
be considered predefined macro names; it shall be illegal to redefine a compiler directive as a
macro name." The LRM's own reserved names were already reported: a name beginning with `__VAMS_`,
and `__FILE__`/`__LINE__`/`__OPENVAF__`, as warnings.

## The change

`define_macro` refuses a name that the preprocessor reads as a directive. That is every name in
its directive table (`include`, `ifdef`, `ifndef`, `else`, `elsif`, `endif`, `undef`,
`undefineall`, `resetall`, `celldefine`, `endcelldefine`, `default_discipline`,
`default_transition`, `default_nettype`, `unconnected_drive`, `nounconnected_drive`, `timescale`,
`line`, `pragma`, `begin_keywords`, `end_keywords`) and `define`. The definition is not stored:

```
error: '`include' is a compiler directive and cannot be defined as a macro
  |
1 | `define include 7
  | ^^^^^^^^^^^^^^^ `include is always read as the directive
  |
  = help: IEEE 1364-2005 19.3.1 (adopted by LRM 10.4): every compiler directive is a predefined
    macro name, and redefining one is illegal; pick a different name
```

The parser's directive table and the check are one function, so a directive added to the
preprocessor is refused as a macro name with it. A `-D include=1` on the command line is refused
the same way: no predefined macro has a directive's name. It is an error rather than a warning
because the standard makes it illegal and the macro could never have worked.

## The checks

vafslips [5]:

- `` `define `` of `include`, `define`, `ifdef`, `timescale`, `resetall`, `begin_keywords` and
  `default_discipline`: one error each, naming the directive and 19.3.1;
- `-D include=1`: the same error;
- `includes` and `include_path` are ordinary macro names;
- `` `define __LINE__ `` keeps its warning.

None of the 1 026 bundled Verilog-A files defines a directive's name.

## Limits

- `__FILE__` and `__LINE__` stay warnings, as before. LRM 10.1 lists them among the directives,
  but they are predefined macros that a definition can shadow.
