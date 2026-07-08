# Enhancement-21 — Verilog-AMS `paramset` blocks

This document describes the source-code changes made to **OpenVAF-r** in the
`version11/` directory to support **Verilog-AMS `paramset` blocks** — named,
instantiable models that specialise an existing behavioural module by binding
some of its parameters. `paramset` was previously a hard parse error
(`paramset` was lexed as an identifier and the top-level parser rejected it).

## Syntax and semantics

```verilog
paramset <name> <target_module>;
    parameter real <p> = <default>;   // the paramset's own (card) parameters
    .<target_param> = <expr>;         // bind a target-module parameter
endparamset
```

`<name>` becomes its own OSDI model — usable as `.model foo <name>` in a netlist
— with the **same terminals and analog behaviour** as `<target_module>`. Each
bound target parameter takes the value of its `<expr>` (which may reference the
paramset's own parameters and constants) and is no longer settable from the
model card; unbound target parameters remain settable (pass-through). This is
the Verilog-AMS way of shipping a *model library*: one behavioural module plus
several named, pre-configured variants.

## Implementation: the "twin module"

The key idea is that a `paramset` is lowered into a synthetic **twin module**
that *reuses the target module's declaration verbatim* rather than duplicating
any behaviour. Concretely, in `hir_def`'s item-tree lowering
(`lower_paramset`), a `paramset` produces a new `Module` that:

1. **shares the target module's `ast_id`** — so its ports and analog body (and
   branches, functions, nets) are exactly the target's, resolved through the
   twin's own scope;
2. carries the paramset's own parameters as its (card) parameters; and
3. replaces each **bound** target parameter with a fresh parameter that is
   marked `localparam` and whose initializer is the override expression.

Because item identity is `(scope, item-tree-index)`, the twin gets its own
module scope and re-interns the shared item-tree entries as fresh parameters,
variables, etc., under that scope — so the twin is a fully independent module
that happens to share the target's syntax. Everything downstream (name
resolution, type inference, MIR lowering, autodiff, OSDI descriptor emission)
then treats the twin as an ordinary module, so DC, AC (Jacobian), noise, and
transient all work with no further changes.

Modelling a bound parameter as a **localparam whose value is the override
expression** is what makes this cheap: the existing `localparam` machinery
already (a) computes the value inline from the analog body, referencing other
parameters, and (b) keeps it off the model card. No change to parameter
initialization, the OSDI ABI, or ngspice was required.

## Files changed

- **tokens** (`tokens/src/parser/generated.rs`) — `paramset`/`endparamset`
  keywords and the `PARAMSET_DECL` / `PARAMSET_OVERRIDE` syntax kinds.
- **parser** (`parser/src/grammar.rs`, `parser/src/grammar/items.rs`) — parse a
  top-level `paramset … endparamset` (name, target, parameter declarations, and
  `.<param> = <expr>;` overrides).
- **syntax** (`syntax/src/ast/generated/nodes.rs`) — `ParamsetDecl` /
  `ParamsetOverride` AST nodes and the `Item::ParamsetDecl` variant.
- **basedb** (`basedb/src/ast_id_map.rs`) — give `ParamsetOverride` nodes ast-ids
  so their override expressions are addressable.
- **hir_def**:
  - `item_tree.rs` — `Param::override_expr` field; the `UnknownParamsetTarget`
    diagnostic.
  - `item_tree/lower.rs` — `lower_paramset` (the twin-module construction).
  - `item_tree/diagnostics.rs` — render the unknown-target diagnostic.
  - `data.rs` — an overridden parameter reports `is_local = true`.
  - `body.rs` — an overridden parameter's default is its override expression,
    lowered in the twin's scope.

## Verification

`examples/paramset_examples/verify_paramset.py` — one module `conductor` = `g0*(1+k*V)`
and three paramsets (`res_1k`, `res_kohm`, `varistor`). `ALL PASS`:

- constant bindings take effect (`res_1k` = 1 kΩ);
- a binding computed from a card parameter takes effect
  (`res_kohm`: `g0 = 1/(kohm*1000)`);
- an unbound parameter stays settable while a bound one is driven by the paramset
  (`varistor`: `g0` pass-through, `k` = `kv`);
- a **bound** parameter is **not** settable from the card (`k=9` is ignored);
- the derivative flows through the paramset — the AC conductance
  `gm = g0*(1 + 2*k*V)` is exact (autodiff Jacobian on the shared body);
- the base module `conductor` still works independently.

Every prior example folder still passes (notably `instantiation_examples`, which
exercises the same item-tree/parameter machinery), and the `hir_def`/`hir_ty`
unit-test suites pass with no regressions.

## Known limitations

- The target module must be declared in the same file.
- Multiple `paramset`s sharing one name with instance-based **selection**, and
  `aliasparam`/statement-based selection blocks, are not supported — each
  `paramset` maps to exactly one model.
- An override naming a parameter the target module does not declare is silently
  ignored rather than diagnosed.
