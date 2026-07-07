# Enhancement-87 — block-scoped parameters (version11)

This document describes Enhancement-87: block-scoped parameters (LRM 6.3,
the page-112 example) — `parameter`/`localparam` declared inside a named
`begin: label` block. The investigation found the feature already works
end-to-end; the deliverable is a runtime-verified example suite plus a fix
for the one genuine rough edge — the LRM's own `#(.myscope.p2(4)) //
error` case, which produced a confusing parser cascade instead of a
targeted diagnostic.

## The feature already works

A named block may declare its own parameters and localparams; they are
compile-time constants local to the block, referenced hierarchically
(`label.name`) from the enclosing analog code, and derivable from the
module's parameters. All of this is supported by the existing hir_def
name-resolution machinery (`block_def_map`, block `ScopeId`s):

```verilog
analog begin
   begin: s
      parameter real g2 = gain * gain;   // block param, from a module param
      localparam real base = 1.0;         // block localparam
      real contrib = g2 + base;           // block var uses both
   end
   vout = s.contrib;                       // hierarchical read
end
```

Runtime-verified in ngspice (`blockparam_examples`, 6/6): with the module
parameters at their defaults `vout = gain² + 1 + offset·10 = 10 V`, and a
**model-card override of the module parameters flows into the
block-scoped parameters** that depend on them (`gain=3, offset=0.2` →
`12 V`). Nested blocks work too — an inner block parameter derived from an
outer block parameter resolves correctly (`7 V`).

## The fix: the illegal hierarchical override

The LRM page-112 example deliberately includes an illegal case:

```verilog
example #(.p1(4))         inst1();   // allowed  -- p1 is module-level
example #(.myscope.p2(4)) inst2();   // error    -- p2 is block-scoped
```

The `#()` instance parameter override binds to a module's *parameter
ports*, which are only its module-level parameters; a block-scoped
parameter is local to its block and cannot be reached this way (LRM
6.3.2). openvaf-r previously choked on the dotted name `.myscope.p2`
with a bare `unexpected token ')'` **and** a spurious cascade (a false
`'myscope' was already declared` on the block below).

Two small changes fix this:

- **Parser** (`param_assign`): consume the extra `.segment`s of a
  hierarchical override target so the parse stays clean (no cascade), the
  extra names collected as additional `Name` children of the
  `PARAM_ASSIGN` node.
- **Elaboration** (`resolve_param_bindings`): a named override with more
  than one segment is reported with a targeted diagnostic naming the
  offending path and the target module — collected and bailed like the
  E-84 unknown-module and E-59 port-concat errors (the illegal override
  is flattened away during elaboration, so the check must live where the
  instantiation is semantically processed, not in CST validation).

The page-112 example now yields exactly one clear error:

```
error: instance parameter override '.myscope.p2' targets a
hierarchical/block-scoped parameter, which cannot be overridden this way;
only a module-level parameter of 'example' may be named in an instance
parameter assignment
```

## Scope decision: overriding block-scoped parameters

A block-scoped `parameter` (as opposed to `localparam`) is nominally
overridable, but the LRM only demonstrates that the `#()` route is
illegal. openvaf-r treats block-scoped parameters as
hierarchically-visible compile-time constants: they take their value from
their initializer (which may reference the enclosing module's parameters,
so a module-parameter override propagates into them), and they are not
overridable through an external mechanism — neither `#()` (now a targeted
error) nor `defparam` (`defparam inst.s.p2 = …` reports "did not resolve
to any parameter", since block-scoped parameters are not hoisted to
module-level defparam targets). This is a documented scope decision,
consistent with the localparam-like treatment the LRM's own example
implies, and mirrors the parameter-shaped-generate decision of E-67.

## Verification

- `blockparam_examples` 6/6: compile, defaults, module-override
  propagation into block params, nested-block derivation, and the
  targeted rejection of a block-scoped `#()` override (no cascade, no
  crash).
- LRM suite: `lrm_p112_1`'s pin updated from the old parser cascade
  (`unexpected token`) to the clean diagnostic; the file stays a correct
  limitation (it contains the LRM's own intentional error). Suite 7/7,
  counts unchanged (40 / 19 / 21).
- Full regression: all version11 verify suites + 28 integration tests;
  parser/syntax snapshot tests green.

## Gotchas recorded

- A semantic error about a construct that elaboration *flattens away*
  (an instance parameter override) cannot be surfaced from CST
  validation on the original file — after elaboration, `root_file` is the
  synthesized flattened file, and the original's validation errors are
  not re-collected. Such checks belong in the elaboration pass, alongside
  the E-84/E-59 collected-error vecs.
- The feature "already works" was only visible by probing the *legal*
  construct in isolation; the LRM example's bundled `// error` case made
  the whole file look unsupported. Verify the minimal legal form before
  assuming a pinned limitation reflects a missing feature.
