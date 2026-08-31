# Enhancement-526: analog behavior and contributions, audited against the LRM

**Scope:** Accellera VAMS-2023 clause 5 (analog behavior), from the full
LRM conformance audit — the hierarchical-contribution branch-identity
bug, two unenforced indirect-assignment rules, parameter vector
indices, and the clause's deliberate relaxations disclosed.

**Suite:** [`examples/lrmcontrib_examples/`](../examples/lrmcontrib_examples/)
— 19 checks, both solvers, plus the extended
[`vafconstidx`](../examples/vafconstidx_examples/) suite (27 checks)
covering the new index-freeze semantics. The `indirect_assignment`,
`portflow`, `multianalog`, `hiername` and `casexz` suites all still
pass.

## Hierarchical contributions merged into the child's branch (compiler)

LRM 5.6.8.1: a contribution between local and hierarchical nets creates
"a new unnamed branch ... in the module containing the direct
contribution statements" — and 5.5.4 stresses it is distinct even when
the child already has an unnamed branch between the same nodes. The
textual flattening rewrote `c1.mid` to the child's net name, so the
parent's `V(p, c1.mid) <+ 0.5` landed on the child's own branch: the
potential/flow retention rule then *discarded* the child's flow
contribution — warning L022 firing on fully legal code — and the
child's mirror of its own branch flow read the merged potential-source
current (1.0 mA where the LRM requires the child's 0.5 mA flow value).

Each hierarchical contribution target now synthesizes its own named
branch over the final flattened node pair (named branches are distinct
identities even over the same nodes), declared alongside the implicit
nets. Probes in the contributing module over the same pair alias onto
that branch (5.5.4's same-module rule, reversed order negated);
references to a child's *named* branch keep merging, which is exactly
5.6.8.2's rule; hierarchical *port* members keep their honest
documented resolution error. The transform composes with the E-525
multiplicity machinery — a hierarchical contribution inside a
`#(.$mfactor(2))` child solves to the exact ×2 value.

## Guarded indirect assignments were singular matrices (compiler)

LRM 5.6.7: "Indirect branch contributions shall not be used in
conditional or looping statements, unless the conditional expression is
a constant expression" — and 5.6.5 keeps every contribution out of
event controls. The validator applied its context checks only to `<+`:
an indirect assignment under a solution-dependent `if`, or inside
`@(initial_step)`, compiled with no diagnostic, and whenever the guard
was off its implicit equation degenerated to 0 = 0 — ngspice's
singular-matrix regularization then invented an answer. Both placements
are compile errors now; the ctx machinery already encodes the
constant-expression carve-out (a constant condition never switches the
context), so the legal shapes pass untouched.

## Direct <+ onto an indirectly-assigned branch was absorbed (compiler)

LRM 5.6.7.2: "Once a value is indirectly assigned to a branch, it
cannot be contributed to using the branch contribution operator <+."
Both lowered onto one branch, where the constraint equation pinned the
value and the solver moved the implicit unknown to soak up the direct
contribution — zero observable effect, zero diagnostics. A whole-body
scan (branch identity = the resolved destination, unnamed pairs
normalized for orientation) now reports the direct statement with a
secondary label on the indirect one.

## Parameter expressions as vector signal indices (compiler)

LRM 5.5.2: a signal-access index "must be a constant expression" — and
a constant_expression includes parameters, yet `V(in[width-2])` was
refused ("index must be a constant") while `V(in[1+1])` and genvars
worked. A new elaboration pass folds a vectored-NET bit-select whose
index reads integer parameters and freezes the *transitive parameter
support* structural (the index selects a node of the frozen OSDI
descriptor), exactly as parameter-shaped widths already froze — so a
netlist override of a baked parameter is refused with the standard
warning instead of silently ignored, including through a derived
localparam. Array-variable indices are untouched: runtime access,
parameters overridable.

## Disclosure

Compliance §5 now carries the clause's deliberate relaxations as ⚠️
extensions: contributions inside runtime loops (LRM 5.9 allows them
only in the genvar `analog_for`), `do…while` (absent from Annex
A.6.8), the generalized indirect-equality LHS, the L017-warned
both-natures probe read, and upward/absolute hierarchical signal paths
being out of scope for the single-design OSDI target.
