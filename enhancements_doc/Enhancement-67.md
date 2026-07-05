# Enhancement-67 — generate audit: genvar-substitution fix, nested loops, `generate if`/`case` (version11)

This document describes the changes made to **OpenVAF-r** in the
`version11/` directory following a systematic audit of the
`generate`/`genvar` machinery (built in Enhancement-5, never audited
since). Front-end only — no OSDI/ngspice change.

## The audit (13 probe forms)

Already correct: the basic labelled `generate for` ladder, non-trivial
bounds (`start ≠ 0`, `step 2`, `<=`), per-iteration net declarations,
genvar reuse across regions, bit-select indices with genvar arithmetic
(`n[i+1]`), and the descending-loop / non-constant-bound rejections.

**One defect and three gaps:**

| finding | before |
|---|---|
| **DEFECT**: genvar in an ordinary expression (`#(.r(1e3*(i+1)))`) | substituted through the identifier-renaming path, which re-escaped the numeral into a broken **escaped identifier**: `1e3*(\0 +1)` → "error: '0' was not found". Bit-selects only worked because they had a dedicated pre-fold. |
| nested `generate for` loops | parse error (the block grammar had no `for` arm) |
| anonymous `begin` (no `: label`) | parse error — the label was mandatory (1364-2005 allows anonymous blocks) |
| `generate if` / `generate case` | mis-parsed into a broken `GENERATE_FOR` with **misleading errors** ("generate for: missing loop condition" for an `if`) |

## The implementation

### Grammar (`parser`), AST (`syntax`), tokens

New `GENERATE_IF` / `GENERATE_CASE` / `GENERATE_CASE_ARM` node kinds with
typed AST nodes and `ModuleItem` variants (full pipeline threading, the
E-34 recipe). After `generate`, the parser dispatches on `for`/`if`/`case`;
the same tail rules are reused for **nested** constructs inside a generate
block (which have no `generate`/`endgenerate` of their own). `begin`'s
`: label` is now optional. `generate if` supports `else` and `else if`
chains; `generate case` supports multi-value arms and `default`.

The unelaborated-generate safety net in `hir_def`'s item-tree lowering
covers the new node kinds too (a generate construct that survives to
`hir_def` is a diagnostic, never a miscompile).

### Elaboration (`hir/elaborate.rs`) — recursive per-item rendering

`render_generate_for` now recurses through a shared
`render_generate_block(block, env, suffix, scope)`:

- **`env`** holds *every* genvar in scope (outer loops included), so inner
  bounds may reference outer genvars and all folds see the full picture;
- **`suffix`** accumulates per-iteration name disambiguators (`_0_2` two
  loops deep) — each block suffixes its *own* directly-declared names, so
  nested declarations flatten collision-free;
- **the genvar fix**: bit-select indices keep their whole-index constant
  fold (the bus machinery requires literal indices), and every *remaining*
  bare genvar identifier becomes a literal-value hole — genvars never pass
  through identifier renaming (whose escaping was the defect) anymore;
- **`generate if`/`case`** fold their condition/discriminant with a new
  `eval_cond_expr` (comparisons, `&&`/`||`/`!`, non-zero test) and emit
  only the chosen branch. Conditions must be **elaboration-time constants
  (integer literals and genvars)** — e.g. triangle structures
  `if (j <= i)`. A condition on a module **parameter** is a clear, honest
  error: parameters bind at *simulation* time under OSDI (model cards!),
  so they fundamentally cannot shape generated structure. The
  non-constant-bound message explains the same reasoning.

## What now works (all verified numerically exact)

nested 2×3 loops (6 mS), genvar param-override expressions (1k∥2k∥3k =
11/6 mS), triangle `generate if` on genvars (6 mS), if/else (1.5 mS),
`generate case` with a multi-value arm and default (2.75 mS), anonymous
blocks with per-iteration nets (1 mS), `i = 2; i <= 6; i = i + 2`
(3 mS) — plus the original E-5 ladder pinned bit-identical to its
hand-written twin.

## Examples (`generate_examples/`, 9 checks, ALL PASS)

The folder finally gets a verify script: `verify_generate.py` — [1] the
E-5 ladder twin regression; [2] the seven Enhancement-67 feature checks
above; [3] the honest parameter-condition error naming the OSDI reason.

## Regression

All version11 example verify suites pass; crate tests pass; the VA_TEST
corpus compiles 92/92.
