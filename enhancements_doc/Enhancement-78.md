# Enhancement-78 — `casex` / `casez`: the don't-care case statements (version11)

This document describes Enhancement-78: the `casex`/`casez` case-statement
variants — the one "not implemented" row the Enhancement-73 handbook audit
left on the language matrix, now flipped to supported. Front-end only — no
OSDI/ngspice change.

## Semantics in the 2-state analog world

Verilog-A values are 2-state, so the don't-cares live in the **literals**:
`x`/`X`, `z`/`Z` and `?` digits of a based literal written directly as a
`casex`/`casez` item form a **comparison mask** — the arm matches when the
discriminant equals the item on every *care* bit:

```verilog
casex (sel)
    4'b1xxx: grant = 8;   // matches 8..15: bits 2..0 are don't-cares
    4'b01xx: grant = 4;   // the classic priority-encoder idiom
    ...
endcase
```

`casex` treats `x`, `z` and `?` as don't-cares; `casez` only `z`/`?`
(per the LRM). Don't-care digits are legal in the power-of-two bases
(`'b`, `'o`, `'h`), each masking its digit's bit positions.

## Implementation (the E-19/E-34 pipeline-threading recipe)

- **lexer**: the based-literal digit runs admit `x/X/z/Z/?` in binary,
  octal and hex (not decimal), for both the sized and unsized forms;
- **tokens/parser**: new `CASEX_KW`/`CASEZ_KW` keywords; all three
  keywords share the one `CASE_STMT` grammar rule — the keyword token on
  the node carries the flavor;
- **syntax**: `parse_based_int_masked` decodes a based literal to
  `(value, x_mask, z_mask)` (don't-care digits contribute zero value
  bits); the old `parse_based_int` delegates to it;
- **hir_def**: `Stmt::Case` gains a `CaseKind` and each arm a parallel
  `CaseMask { care, had_x }` list, computed at collection from item
  literals; every don't-care literal *not* consumed as a casex/casez item
  lands in a `stray_dontcare_literals` list on the body;
- **hir_ty validation**: three new diagnostics (below);
- **hir_lower**: an item with a partial mask compares
  `(discr & care) == (item & care)` — two `iand`s feeding the existing
  `Ieq`; full-mask items take the unchanged equality path, as do plain
  `case`, arrays, strings, and reals.

## The three diagnostics

- *"don't-care digits are only allowed in casex/casez items"* — a `'b1x0`
  spelled anywhere else (an assignment, a plain-`case` item, a nested
  expression) is rejected instead of silently reading its x-bits as zeros;
- *"'x' digits are not don't-cares in casez"* — with the `casex` hint;
- *"casex/casez requires an integer discriminant"* — bit masks are
  meaningless on `real`/`string` discriminants.

## Verified (`casexz_examples/`, 7 checks, ALL PASS)

[1] an 8-way self-checking bitmask module (the E-37 audit technique) pins
the semantics at exactly **63/63**: casex x/z/? masking, casez z/?-only,
fully-specified mismatch falling to default, first-match-wins arm order,
and plain `case` unchanged; [2] a casex **priority encoder** whose 4-bit
request word comes from the model card — the highest set bit wins at all
nine probed values including the default arm; [3] all three diagnostics
as clean, located compile errors.

## Regression

Zero-warning build maintained; all 70 example verify suites pass, the
integration suite 28/28, the VA_TEST corpus compiles 92/92.
