# Enhancement-50 — domain binding validation (version11)

This document describes the change made to **OpenVAF-r** in the `version11/`
directory to enforce the one missing rule of **discipline domain bindings**
(LRM 3.6.2.2). One validation check in `syntax`; no OSDI/ngspice change.

## Probe verdict (domain was substantially implemented)

- `domain continuous;` / `domain discrete;` parse and are stored on
  `DisciplineData` (the std header's `ddiscrete`/`logic` disciplines exercise
  `domain discrete` in every compilation);
- nature-bound disciplines default to the continuous domain;
- the domain participates in discipline-compatibility checks, with domainless
  disciplines treated permissively (LRM 3.6.2.3);
- discrete-domain nets are rejected in analog accesses ("illegal access of
  branch");
- a custom continuous discipline with natures compiles and simulates exactly.

## The gap and the fix

LRM 3.6.2.2: *"It is an error for a discipline to have a domain binding of
discrete if it has nature bindings."* Previously accepted silently:

```verilog
discipline bad
  domain discrete;
  potential Voltage;   // ← no diagnostic
enddiscipline
```

`validate_discipline_decl` now tracks the `domain discrete` binding and the
first (unqualified) `potential`/`flow` nature binding, and emits a two-label
error — "the domain is bound discrete here" / "... but a nature is bound
here" — with a help note citing the rule and both remedies (drop the natures
for a digital discipline, or bind `domain continuous`). Qualified attribute
*overwrites* (`potential.abstol = ...`) are not nature bindings and don't
trigger it.

## Verification

`domainbind_examples/verify_domainbind.py`: 5/5 PASS (continuous discipline
simulates at −1 mA exactly; natureless discrete accepted; the error case
diagnosed; discrete-net analog access still clean). Regression: all 47
example verify suites ALL PASS; `syntax`/`basedb`/`hir_def`/`hir_ty` crate
tests 24/24.
