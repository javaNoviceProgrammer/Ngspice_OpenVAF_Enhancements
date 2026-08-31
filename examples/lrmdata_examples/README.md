# lrmdata — data types & parameters vs. the LRM (Enhancement-517)

An LRM-2023 conformance audit of clauses **3.1–3.5** found a bug, a missing
conversion, a missing override form, and two alias rules downgraded to
warnings. This suite pins the fixes end-to-end:

- **Block-level output variables** (3.2.1): a `desc` variable inside a named
  block is no longer exported as an OSDI operating-point variable ("units and
  descriptions specified for block-level variables shall be ignored");
  module-scope opvars still work.
- **String literal → integral** (3.3): `integer i = "A"` is 65, `"AB"` is
  0x4142, `"ABCDE"` truncates on the left — it was a hard type error. A
  string **value** still cannot be assigned to an integer.
- **Whole-array overrides at instantiation** (3.4.4/3.4.8):
  `leaf #(.cf('{9,8,7}))` distributes to the per-element parameters, 1-D and
  multi-dimensional, with "the sizes shall match" enforced.
- **`aliasparam` error rules** (3.4.7): original name *and* alias on one
  `.model` card or instance line is an **error** (was a warning that let one
  value silently win), and referencing the alias in module equations is a
  targeted compile error.
- **Lossy integer rounding warns** (3.4.1 deviation made audible): a
  non-integral netlist value rounded into an integer parameter draws a
  warning on both the `.model` and instance paths.
- **String continuation**: backslash-newline inside a string literal joins
  lines (BSIM4's `$strobe` idiom); a bare newline stays an error.

Run `python3 verify_lrmdata.py` — 20 checks, both solvers.
