# Enhancement-106 — string relational comparison (`<`, `<=`, `>`, `>=`)

Gap-hunt round 4 extended the runtime-value batteries into output formatting,
`ddx`, `$table_model` interpolation and extrapolation, `laplace` AC response,
and integer/division edge cases — all of which **checked out exactly**. The one
genuine inconsistency it surfaced is in the string comparison operators.

## The gap

String **equality** (`==` / `!=`) works, but the **relational** operators
(`<`, `<=`, `>`, `>=`) rejected string operands:

```verilog
if (mode < "low") ...   // error: typed mismatch invalid function arguments
```

Equality already carried a string signature (`STR_EQ`); the relational
operators were still numeric-only. Since ordering strings lexicographically is a
well-defined, commonly-useful operation (comparing corner/mode names, sorting),
this was a real hole in the comparison surface.

## The implementation

The relational operators now accept two strings and compare them
lexicographically, reusing the same lightweight stdlib-callback pattern as the
file/string helpers (no new MIR opcode):

- **`hir_ty`**: the relational operators' signature set becomes
  `RELATIONAL_COMPARISON = [INT, REAL, STR]` (the string signature appended last
  so the int/real indices stay stable); `STR_REL` names the string branch.
- **`hir_lower`**: when the resolved signature is `STR_REL`, `a <op> b` lowers
  to `strcmp(a, b) <op> 0` via a new `StrCmp` callback and an integer compare
  against zero.
- **`osdi`** (`compilation_unit.rs` + `stdlib.c`): the `StrCmp` callback binds
  to a new `osdi_strcmp` runtime function (`strcmp`, NULL treated as empty).

Numeric relational comparison and string equality are untouched.

## Verification

`stringcmp_examples` (8/8): a device evaluates `"abc" < "abd"` (=1),
`"abd" > "abc"` (=1), `"abc" <= "abc"` (=1), `"abc" >= "abd"` (=0),
`"abc" < "abc"` (=0), `"abc" == "abc"` (=1, equality still works), and uses a
string relational as an `if` condition (`"high" < "low"` → true). The wider
gap-hunt batteries behind this enhancement — `$strobe` output formatting across
all conversions, `ddx` partial derivatives, `$table_model` interpolation and
extrapolation, and the `laplace_nd` AC transfer function — matched their
analytic expectations exactly. Full regression: all verify suites plus the
OpenVAF integration tests remain green.
