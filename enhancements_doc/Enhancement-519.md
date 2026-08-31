# Enhancement-519: natures, disciplines and branches, audited against the LRM

**Scope:** Accellera VAMS-2023 clauses 3.6–3.13 (natures, disciplines,
nets, branches, namespaces) and Annex D, from the full LRM conformance
audit. Three bugs — one of them locking out a whole class of legal
models — two new warnings, and the 2023 constants file.

**Suite:** [`examples/lrmdisc_examples/`](../examples/lrmdisc_examples/) —
21 checks, both solvers, including a committed dlopen harness
(`dump_nda.c`) that reads the emitted OSDI metadata directly. The
`derivednature`, `domainbind`, `signalflow`, `bus`, `netinit`, `ground`,
`implicitnet` and `annexe` suites all still pass.

## Discipline compatibility rejected what the LRM declares compatible (3.11.1)

The LRM defines discipline compatibility by six rules, and its worked
example spells the consequence out: "electrical and sig_flow_v are
compatible disciplines because the nature for potential is same for both
disciplines and the nature for flow does not exist in sig_flow_v." The
stock signal-flow discipline `voltage` **is** sig_flow_v — so a branch
between an electrical net and a voltage net is legal Verilog-A.

`DisciplineTy::compatible` required every nature binding to be
both-present-or-both-absent (`(Some, None) => false`), rejecting exactly
that pairing, every natureless connection (the Natureless Discipline
Rule: compatible with the whole domain), and every domainless one. The
rewrite implements all six rules, including effective-domain resolution
per 3.6.2.2/3.6.2.3 (natures default the domain to continuous; no
natures and no domain is "domainless", compatible with everything).
Genuinely incompatible pairs — `electrical` vs `rotational`, potentials
from different base natures — are still rejected, and the diagnostic's
help text no longer states a units-only rule that was never the LRM's.

One consequence needed care: compatible disciplines used to be
interchangeable, so `BranchKind::discipline` picked the first node's
arbitrarily. With one-sided bindings legal that breaks — a branch
between `electrical` and `voltage` must take **electrical**, or `I(br)`
has no flow nature. The picker now prefers the discipline with more
nature bindings; the suite verifies the mixed branch as a live 1 kΩ
element (`I(br) <+ V(br)/1k` in series with a real 1 kΩ divides 2 V to
exactly 1 V).

## The nature-attribute checks were dead code (3.6.1.2)

`validate_nature_decl` contained the intended checks — `access` "shall
be an identifier (by name, not as a string)", `ddt_nature`/`idt_nature`
"shall be the name (not a string) of a nature" — but iterated
`nature.attrs()`, the accessor for `(* ... *)` annotation attributes,
which a nature declaration never has. Zero items visited, checks never
run; item-tree lowering then silently *dropped* the malformed value, so
`access = "SA"` compiled clean and the model died later with an
unrelated "SA was not found in the current scope". One word
(`nature_attrs()`) makes the checks live: all four malformed shapes are
located errors at the declaration.

Two more 3.6.1.2 rules became **warnings**: a *derived* nature declaring
`units` (the value is silently discarded — "the derived nature always
inherits its parent nature units" — so `units = "furlong"` staying `"V"`
deserved a voice), and an `idt_nature`/`ddt_nature` override unrelated
(no shared base nature) to the link the parent uses. Warnings, not
errors, matching this project's deliberately permissive derived-nature
stance: E-39's derived-access extension and E-422's optional-attribute
decision — both implemented once and withdrawn under their own suites —
stand, and are now recorded in the compliance doc as the deviations they
are.

## Every OSDI nature descriptor over-counted its attributes

Building `OSDI_NATURES`, the attribute-range end was computed as
`attr_vec.len() + 1` — the discipline path right below does it without
the `+1`. Every nature's `num_attr` claimed one attribute more than it
owns, so a consumer walking `attrs[attr_start .. attr_start+num_attr]`
read the first attribute of the *next* nature, and past the region for
the last one. ngspice never reads this table, which is why nothing
crashed — but the emitted 0.4 metadata was wrong for any consumer. The
suite now pins it structurally: the committed `dump_nda.c` dlopens the
compiled `.osdi`, and the verify script asserts every range is exact,
contiguous, and in-bounds.

## The VAMS-2023 constants.vams (Annex D.2)

The compiler shipped the 2.4.0 file: no `P_*_NIST2018` values and no
`PHYSICAL_CONSTANTS_NIST2018` selection branch, so a user opting into
the 2023 exact-SI constants silently got NIST1998 numbers. The shipped
file is now the Annex D.2 content (verbatim redistribution is expressly
permitted): the opt-in yields `P_Q` = 1.602176634e-19, `P_K` =
1.380649e-23, `P_H` = 6.62607015e-34, `P_EPS0` = 8.8541878128e-12 and
the *measured* `P_U0` = 1.25663706212e-6; the default without the
define stays NIST1998 — exactly the backward compatibility the 2023 LRM
specifies — and `P_U0` = 4π×10⁻⁷ there. Both branches verified
numerically at run time. One preprocessor token-stream snapshot moved
with the file and was inspected before updating.

## Documented, not implemented

**Vector branches** (3.12: `branch (a,b) br;` over whole vector nets)
stay rejected with the located "use a bit-select" diagnostic and are now
listed among unsupported constructs, alongside **out-of-module
discipline declarations** (3.10) — meaningless in a single-module OSDI
compile.
