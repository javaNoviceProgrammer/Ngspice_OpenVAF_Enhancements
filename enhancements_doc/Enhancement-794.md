# Enhancement-794: lint L039 `inclusive_infinite_bound` reports `from [0:inf]`, the spelling the CMC's VAMPyRE refuses — allowed by default, because standard models' range macros write it

**Scope:** D4 of the
[openvaf-r hunt of 2026-10-04](../docs/bug_hunts/2026-10-04_openvaf-r-run-time-domains-filters-and-instances.md).
openvaf:
- `basedb/src/lints.rs`: `inclusive_infinite_bound`, L039, default level Allow.
- `hir_ty/src/validation/body.rs`: `check_param_default_range` checks the bounds before the
  default; new `InclusiveInfiniteBound` diagnostic.
- `hir_ty/src/validation.rs`: the lint mapping and the report.

`examples/vafslips_examples/` (section [4], twelve checks). **openvaf only.**

**Suites:** [`vafslips_examples`](../examples/vafslips_examples/) 67 of 67 per solver (11 of the 12
in [4] fail on the E-790 binaries; the default-silent one passes); the workspace tests; the corpus
census (below); the full sweep, 537 of 537.

## What was wrong

`parameter real r = 1 from [0:inf];` compiled without a word. LRM 3.4.2: a bracket includes its
end point, and `inf` "indicates infinity". `[0:inf]` therefore claims to admit infinity itself,
which no parameter value is: ngspice refuses a non-finite model-card value (`1e400`, `inf`), and
E-640 refuses a non-finite default. So the range admits exactly what `[0:inf)` admits. Every
example in the LRM writes the infinite bound with a parenthesis. The CMC's Verilog-A checker
VAMPyRE treats the bracket as an error. Its trace is in the corpus's `hisim2.va`:

```
// resolved VAMPyRE ERROR (Invalid range [0:inf] for parameter 'MUPT'; should be [0:inf))
```

## The change

Lint L039, `inclusive_infinite_bound`, reports a `from` or `exclude` range that closes an
infinite bound with a bracket: `[-inf:`, `:inf]`, or a constant that folds to an infinity. It
points at the bound:

```
warning[L039]: the `from` range of parameter 'r' closes the infinite bound inf with `]`
  |
3 | parameter real r = 1 from [0:inf];
  |                              ^^^ write `)` here: the range admits the same values either way
```

**It is allowed by default.** The first cut warned. A compile of every bundled Verilog-A file with
the old and the new binary then found it in 16 files: fourteen of OpenVAF's reference models in
`integration_tests/` (PSP103's three variants among them) and two `osdi` test files. EKV has 33
instances, DIODE 7, BSIMBULK and HICUM L2 4 each, PSP103 2. Most come through the CMC's own range
macros: PSP103's `` `MPRcc(SAREF, 1.0e-6, "m", 1.0e-9, inf, ...) `` expands to `from [1.0e-9:inf]`.
The CMC macro file shipped with r3_cmc and VBIC defines `IPM` with `from(0.0:inf]`. A default
warning would print on every compile of those models, about source the reader cannot change, for a
spelling that changes nothing.

So L039 is opt-in, like `const_simparam`:
- `-W inclusive_infinite_bound` reports it;
- `-E inclusive_infinite_bound` refuses it, which is VAMPyRE's verdict;
- `openvaf_allow` on a declaration silences it there.

## The checks

vafslips [4]:

- `from [0:inf]` compiles silently by default;
- with `-W`, L039 for:
  - `[0:inf]` and `[-inf:0]`;
  - `[-inf:inf]` (twice);
  - an integer parameter's `[1:inf]`;
  - `exclude [5:inf]`;
  - the IPM spelling `(0.0:inf]`;
- with `-W`, none for:
  - `[0:inf)` and `(-inf:inf)`;
  - a finite `[0:1e300]`;
  - an `openvaf_allow`ed declaration;
- `-E` makes it an error.

## Limits

- Being allowed by default, it does not make `from [0:inf]` say anything unless asked; the hunt's
  "without a word" stands for a default compile, by choice. A one-line change in `lints.rs` makes
  it a warning if the trade-off is judged the other way.
