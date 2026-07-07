# Enhancement-85 — `__FILE__/`__LINE__ and connection part-selects (version11)

This document describes Enhancement-85: the last two open findings of
E-84's LRM example sweep, implemented. With F4 and F6 closed, **all
eight defects the sweep exposed are fixed**, and the sweep's findings
directory contains only regression pins.

## F4 — the predefined source-location macros (LRM 10)

`` `__FILE__ `` and `` `__LINE__ `` were "macro has not been declared"
errors. They cannot be ordinary preprocessor macros in this compiler:
preprocessor tokens are (kind, span) pairs into *existing* source text,
so there is nowhere for a synthesized literal to live. The fix is a
textual pre-pass (`expand_source_location_macros` in
`hir/src/elaborate.rs`, run before the generate/instantiation passes),
the same mechanism E-58 established:

- `` `__FILE__ `` → a string literal holding the root file's
  **basename** — not the full path, for the same provenance reason E-58
  names its synthetic files by basename: the expansion is baked into
  the compiled `.osdi`, and an absolute path would leak the build
  machine's layout (the repo's standing machine-portability rule).
- `` `__LINE__ `` → the 1-based line of the occurrence in the user's
  file. Replacements are inline, so every later line number stays
  exact. The scanner skips string literals and comments.
- A use inside a `` `define `` body expands at the **definition site**
  (textual semantics; C's "line of use" would need real preprocessor
  tokens). Documented, and pinned by the verify suite.

Runtime-verified in ngspice: `$strobe("%s:%0d", `__FILE__, `__LINE__)`
prints `srcloc.va:18` for the direct use and `srcloc.va:11` for the
`` `define ``-site use (`filemacro_examples`, 5/5).

## F6 — part-selects in instance connections (LRM 6, pages 163–164)

`adc2 hi (out[3:2], in);` was a parse error. Three small pieces:

- **Parser**: the bit-select bracket accepts an optional `: expr`; the
  colon token stays in the CST and is what distinguishes a part-select
  from E-15's multi-dimensional `[i][j]` indexing — no new node kind.
- **Guard**: part-selects are only legal in port connections (which
  elaboration consumes textually and never body-lowers), so body
  lowering collects any that reach it into `stray_part_selects` —
  E-78's stray-don't-care pattern — and hir_ty reports a dedicated
  diagnostic pointing at the connection form.
- **Elaboration**: `bind_port` recognizes a constant `base[msb:lsb]`
  actual and slices those bits of the caller's bus onto the port,
  ascending-to-ascending (the same bit-order convention as the existing
  full-bus slicing); a width-1 slice onto a scalar port degrades to the
  bit-select it denotes; width mismatches fall through to the ordinary
  path and its standard diagnostics. Positional and named (`.i(v[1:0])`)
  forms both work. Bounds are integer literals (parameter-dependent
  selects are the same class as parameter-dependent bus widths —
  documented limitation).

Runtime-verified in ngspice (`partselect_examples`, 5/5): a 4-bit bus
with V(v[k]) = k volts wired via `v[3:2]` (positional), `.i(v[1:0])`
(named), and `v[2:2]` (width-1) produces exactly 8 V / 2 V / 2 V — the
outputs 2·V(msb)+V(lsb) pin the per-bit routing.

## Suite graduations

- `micro_file_line.va`, `micro_partselect.va`: findings → must-compile
  regression pins.
- `lrm_p163_1.va` (binary ADC tree, positional part-selects): compiles
  verbatim.
- `lrm_p164_1.va` (named part-selects): compiles with the 1-bit `adc`
  context stub the LRM references but never defines.
- LRM suite counts: **39 compile / 20 limitations / 21 AMS**; verify
  7/7. All eight sweep defects (F1–F8) now fixed.

## Verification

- `filemacro_examples` 5/5, `partselect_examples` 5/5 (both with
  ngspice runtime pins), `lrm_examples` 7/7.
- Full regression: all version11 verify suites + 28 integration tests;
  parser/hir_def/hir_ty dev+snapshot tests green.

## Gotchas recorded

- Preprocessor tokens cannot carry synthesized text — anything that
  must *invent* source (like `__FILE__`'s literal) has to happen at the
  textual pre-pass layer where a virtual file can hold it.
- The CST tolerates extra tokens: the part-select colon rides inside
  the existing BIT_SELECT_EXPR node, avoiding the full new-SyntaxKind
  pipeline threading; the AST accessor (`is_part_select`) just looks
  for the token. Consumers that iterate `indices()` MUST check it —
  a two-expr part-select is otherwise indistinguishable from a 2-D
  index.
