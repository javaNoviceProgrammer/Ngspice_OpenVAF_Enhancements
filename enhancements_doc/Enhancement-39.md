# Enhancement-39 — derived natures & deriving natures from disciplines (version11)

This document describes the changes made to **OpenVAF-r** in the `version11/`
directory to make **derived natures** — `nature X : Parent;` and
`nature X : discipline.potential / discipline.flow;` (LRM 3.4.1.3) — actually
work. Three small fixes across `parser`, `syntax` validation and the OSDI
nature-descriptor builder; the substantial inheritance machinery already existed.

## The bugs

A derived nature inherits every attribute (units, access, abstol,
`ddt_nature`/`idt_nature`) it does not override. OpenVAF's `hir_ty::NatureTy`
implements all of this — parent resolution, base-nature chains, units/ddt/idt
inheritance, attribute lookup through parents, and access-function compatibility
by units. **None of it was reachable:**

1. **The parent link was silently always `None`.** The parser emitted a
   `NAME_REF` node for the `: parent` clause, but the AST accessor
   (`NatureDecl::parent()`) looks for a `Path` child — so `lower_nature_path`
   never saw a parent. Consequences: a derived nature without its own
   `units`/`access` never inherited them, so the parent's access function was
   rejected on its disciplines ("illegal access of branch") — making the
   canonical `nature TightCurrent : Current; abstol = 1e-15;` pattern unusable.

2. **`nature X : electrical.flow;` did not parse at all** ("unexpected token
   '.'") — same root cause, since a bare name-ref cannot carry a qualifier —
   and behind the parse there was a second gate: the syntax validation
   whitelisted only `ddt_nature`/`idt_nature` as qualified nature-path segments,
   rejecting `potential`/`flow` ("illegal nature identifier").

3. **Discipline-qualified `ddt_nature`/`idt_nature` attribute values
   hard-panicked the OSDI nature-descriptor builder**
   (`"Nature's ddt must be a nature reference."` in `osdi/src/ndatable.rs`):
   the `OsdiNature` descriptor encodes `ddt`/`idt` as bare nature indices, and
   the builder refused to resolve a discipline-qualified reference to its
   underlying nature.

## The fixes

- **`parser/src/grammar/items.rs`** — the parent of a nature is parsed as a
  **path** (`Current` or `electrical.flow`), producing the `Path` node the AST
  and the (already-complete) item-tree lowering expect. This single change
  lights up the whole dormant inheritance machinery.
- **`syntax/src/validation.rs`** — `check_nature_path` also accepts
  `potential`/`flow` as the qualified segment.
- **`osdi/src/ndatable.rs`** — a new `resolve_nature_index` resolves
  discipline-qualified `ddt_nature`/`idt_nature` references through the
  discipline to the underlying nature's index instead of panicking.

## Verification — `derivednature_examples/`

`derivednature_demo.va` packs the full feature matrix (5 modules):
derive-from-nature with inherited units+access, derive-from-discipline
(`electrical.flow`/`electrical.potential`), derived nature with its **own**
access name, a **two-level** derivation chain, and a discipline-qualified
`ddt_nature` attribute. `verify_derivednature.py` (ALL PASS):

1. the matrix **compiles** (three of the five constructs used to fail or crash);
2. runtime conductances are **exact** for every module — proving the inherited
   access functions genuinely resolve end-to-end through ngspice
   (`dn_nature` 1 mS via inherited `I`, `dn_discipline` 2 mS,
   `dn_access` 5 mS via its own `I2`, `dn_chain` 3 mS through two levels);
3. the `ddt_nature = electrical.potential` module's OSDI descriptor builds and
   loads (used to panic the compiler).

Regressions: all **35** version11 example verify suites ALL PASS and all **77**
example models recompile (the parser change makes every file reparse).
