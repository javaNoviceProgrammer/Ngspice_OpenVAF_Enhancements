# lrmudf — analog user-defined functions vs. the LRM (Enhancement-521)

An LRM-2023 conformance audit of clause **4.7** found two compiler crashes,
one silent semantic deviation, and the LRM's own example failing to parse.
This suite pins the fixes end-to-end:

- **Function-local `parameter`s** (4.7.1): `parameter real k = 3.0;` inside
  a function crashed codegen. It is a compile-time local now, with the
  clause's exact scoping: a local shadows the same-named module parameter,
  other module parameters read through — a netlist override of those
  propagates into the function (and into local defaults derived from them),
  an override of the shadowed one does not leak in — and `$param_given` on
  a local is constantly false.
- **Output-array semantics** (4.7.2.3): a pure `output` array is
  zero-initialized at entry and an unassigned one resets the caller's array
  to zeros (it had inout copy-in semantics: the body read the caller's
  values). `inout` arrays keep copy-in/copy-out.
- **LRM 4.7.1 Example 3 verbatim**: `inout [0:1]a; input [0:1]b;
  real a[0:1], b[0:1];` compiles and computes 816 exactly — the range on
  the direction line was "unexpected token `[`", and the compiler's own
  name-then-range rewrite generated that very form.
- **The 4.7.1 restriction list stays enforced**: recursion, access
  functions, zero-argument functions; a function-local parameter *array*
  is a clean error, not a crash.

String returns/output arguments and the `return` statement are covered by
`examples/lrmjump_examples/` (Enhancement-520).

Run `python3 verify_lrmudf.py` — 15 checks, both solvers.
