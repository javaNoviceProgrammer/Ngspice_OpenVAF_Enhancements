# Enhancement-58 — `defparam` hierarchical parameter override (version11)

This document describes the changes made to **OpenVAF-r** in the `version11/`
directory to implement `defparam` (legacy Verilog-2001 compile-time
parameter override, LRM 2.6). Front-end only — no OSDI/ngspice change.

## What the probe found

`defparam` did not parse at all. It was listed as a reserved word
(`syntax::name`), but had no keyword token and no grammar rule, so
`defparam u1.r = 2e3;` tokenised `defparam` as an ordinary identifier and
tripped the net-declaration path — surfacing after elaboration as the
misleading `'defparam' was not found in the current scope`. The idiomatic
instance overrides `#(.r(2e3))` and `#(2e3)` already worked; `defparam` is
the deprecated hierarchical form.

## The implementation

A `defparam` is a compile-time hierarchical override, so it is handled
**entirely in the E-5 elaboration pass** (the same source-to-source stage
that flattens instances) and never reaches the semantic compiler stages.

### 1. Token (`tokens`)

`DEFPARAM_KW` added to the `SyntaxKind` enum, `from_keyword`, `is_keyword`,
the `Display` table, and the `T![defparam]` macro; plus a `DEFPARAM` node
kind. (`defparam` was already reserved, so making it a keyword breaks no
valid model.)

### 2. Parser (`parser`)

A `DEFPARAM_KW` arm in `module_items` dispatches to `defparam_decl`, which
parses `defparam <path> = <expr> [, <path> = <expr>]* ;` into a `DEFPARAM`
node, reusing the existing `path()` and `expr()` grammar. **`DEFPARAM` is
deliberately not a member of the typed `ast::ModuleItem` enum** — so
`module_items()` (the typed iterator every later stage walks) simply skips
it, and no hir_def / hir_ty / lowering change is needed. The node exists
only for the elaboration pass to read.

### 3. Elaboration (`hir/elaborate.rs`)

- **`collect_defparams`** runs at the start of `render_items` for every
  module (top and inlined instances), scanning that module's `DEFPARAM`
  syntax children. Each target path is resolved to its **final flattened
  name** through the very same instance-chain rewrite E-49 uses for
  hierarchical references (`find_instance_path_holes`): `u1.r → u1__r`,
  `u1.u2.r → u1__u2__r`, a single-segment same-module target to itself.
  The map is keyed by that flattened name (`u1__u2__r → "4e3"`), which is
  exactly the name the target parameter receives when its instance is
  inlined, so depth doesn't matter. The value expression is rename-applied
  (it may reference the enclosing module's own parameters).
- The **`ParamDecl` arm** of `render_items`, for each parameter, computes
  its flattened name and — if a `defparam` targets it — rewrites its
  default via the existing `render_with_holes` hole mechanism. `defparam`
  is checked **before** the instance `#(...)` binding, giving it the higher
  precedence LRM 2.6 requires.
- Any `defparam` whose target never matched a rendered parameter is a
  **hard error** (`defparam target(s) did not resolve to any parameter:
  u1.typo`), reported with the original source path.

## What now works (`defparam_examples/`, 4 checks, all exact)

| case | result |
|---|---|
| `defparam u1.r = 2e3` (1k default) | 2 kΩ → I = 0.5 mA |
| deep `defparam u1.u2.r = 4e3` + multi-assign `defparam up.r=2e3, up.g=1e-3` overriding `#(.r(5e3))` | 2k (not 5k) + g + 4k → I = 1.75 mA |
| `defparam u1.r = 2.0*scale` (scale = 3k) | 6 kΩ → I = 1/6 mA |
| `defparam u1.typo = 5e3` | compile error naming `u1.typo` |

`verify_defparam.py`: 4/4 PASS. Regression: all 54 example verify suites
ALL PASS; crate tests (parser, syntax, hir, hir_lower, sim_back, osdi) all
pass; the VA_TEST corpus still compiles.

## Notes

- **Machine-portability fallout (found by the pre-fold path check):** the
  elaboration pass named its synthetic virtual file after the VFS's
  canonicalized ABSOLUTE root path, and that name is embedded in the
  compiled `.osdi` as source provenance — any model using instantiation
  (which `defparam` requires) leaked the build machine's layout into the
  artifact. The synthetic name is now `/<basename>__elaborated.va` (the
  VFS requires a leading `/`). Relatedly, the macOS linker embeds the
  `-o` output path AS GIVEN into the dylib, so every verify script now
  passes a relative `-o` (they already run with `cwd` at the example dir).

- **Scope**: `defparam` targeting a same-module parameter in a module that
  contains *no* instantiation is not rewritten (the elaboration pass only
  runs when the file has instantiations); the parameter's declared default
  applies there. The hierarchical instance-override use case — the actual
  reason `defparam` exists — always involves instantiation and is fully
  supported.
- **Precedence**: `defparam` > instance `#(...)` > declared default, as the
  LRM specifies. A model-card (SPICE `.model`) parameter value still
  overrides all of these at simulation time, unchanged.
- This reuses the E-49 hierarchical-path resolver and the E-21/`#()`
  parameter-hole mechanism wholesale; the only genuinely new machinery is
  the token, the one parser rule, and the collection/application glue —
  "scaffolded-but-unwired at the node-kind boundary" turned into a small,
  self-contained enhancement.
