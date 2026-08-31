# lrmcontrib — analog behavior & contributions vs. the LRM (Enhancement-526)

An LRM-2023 conformance audit of clause **5** found one branch-identity
bug and two unenforced indirect-assignment rules. This suite pins the
fixes:

- **Hierarchical contributions get their own branch** (5.6.8.1 with
  5.5.4): the parent's `V(p, c1.mid) <+ 0.5` was aliased onto the
  child's own unnamed branch — the retention rule then discarded the
  child's flow contribution (a spurious L022 on fully legal code) and
  the child's mirror read the merged current (1.0 mA). A synthesized
  named branch keeps the identities distinct: the mirror reads the
  child's own 0.5 mA, no warning, and the transform composes exactly
  with `#(.$mfactor(2))` (−3 mA pinned).
- **Indirect placement rules enforced** (5.6.7/5.6.5): an indirect
  assignment under a non-constant `if` or inside an event control
  compiled silently and left its constraint as 0 = 0 when guarded off —
  a singular matrix. Both are compile errors; the constant-condition
  carve-out passes, and the legal forms still solve exactly (follower
  1.3 V, inverting −2.0 V with a 0 V virtual ground).
- **Direct + indirect on one branch errors** (5.6.7.2): the direct
  value was silently absorbed by the implicit unknown; the error names
  both statements.
- **Parameter vector indices fold** (5.5.2): `V(in[width-2])` selects
  in[2] with `width` frozen structural (the extended `vafconstidx`
  suite covers the freeze semantics, including derived localparams).
- The shipped relaxations stay shipped and are now documented:
  contributions in runtime loops (accumulation pinned), `do…while`,
  the generalized indirect-equality LHS, and out-of-scope named-block
  writes.

Run `python3 verify_lrmcontrib.py` — 19 checks, both solvers.
