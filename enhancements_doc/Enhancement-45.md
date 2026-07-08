# Enhancement-45 — net initialization + net attribute access

This document describes the changes made to **OpenVAF-r** and **ngspice-46**
in the `version11/` directory to implement two LRM features that were both
completely missing: **net nodeset initializers** (LRM 3.6.3.2) and
**net/branch attribute access** (LRM 5.5.3).

## Half A — accessing net and branch attributes (LRM 5.5.3)

```verilog
I(a,b) <+ c*ddt(V(a,b), a.potential.abstol);   // the LRM's twocap example
x = n1.flow.abstol;
y = br.potential.abstol;                        // branch form (LRM prose)
```

Every spelling failed with "expected a scope but found node/branch/nature" —
the E-39 "scaffolded-but-unwired" pattern at yet another boundary: nameres had
`ResolvedPath::{Flow,Potential}Attribute` arms for **branches**, but only in
the cross-scope `resolve_names_in` traversal; the module-body `resolve_path`
entry rejected any non-scope qualifier first, so even the branch form was
unreachable from where models actually use it.

**Fix** (front-end only):

- `hir_def/nameres.rs`: the module-body entry gains `NodeId`/`BranchId` arms
  for 3-segment `.potential`/`.flow` attribute paths, with two new
  `ResolvedPath` variants (`NetPotentialAttribute`/`NetFlowAttribute`).
- `hir_ty/lower.rs`: `net_nature_attr` — net → discipline → potential/flow
  nature → attribute, through `NatureTy::lookup_attr` (E-39's
  inheritance-aware lookup, so attributes of derived natures resolve).
- `hir_ty/inference.rs`: the new variants type as `Ty::NatureAttr`; lowering
  needed **nothing** — `Ref::NatureAttr` reads already lower to the
  attribute's constant value body.

Unknown attributes get the existing clean diagnostic ("'nonsense' was not
found in 'Voltage'").

## Half B — net discipline initial (nodeset) values (LRM 3.6.3.2)

```verilog
electrical a = 5.0;                      // nodeset for a's potential
electrical [0:2] b = '{0.5, -1.0, 2.0}; // per-bit leaves
```

Previously a parse error. The initializer is a constant used as a **nodeset**
value — an initial Newton-Raphson guess, not an enforced constraint.

**Pipeline** (both stacks):

- **parser**: each net declarator accepts an optional `= expr`; the expression
  is a direct `NET_DECL` child after its `NAME` (new `NetDecl::declarators()`
  AST accessor pairs them).
- **hir_def**: `Net`/`NodeData` carry the const-folded value (`OrderedFloat`);
  bus declarators split the `'{...}` literal into per-bit leaves in ascending
  bit order (matching the bus expansion). Non-constant initializers get a new
  named diagnostic (`NonConstantNodeset`) — parameter-dependent nodesets are
  out of scope.
- **OSDI ABI**: `OsdiNode` gains a `double nodeset` field (NAN = none), filled
  for Kirchhoff-law unknowns from the net's value. Because this changes the
  **node-array stride** — which the `OSDI_DESCRIPTOR_SIZE` mechanism does not
  cover — the **OSDI version is bumped to 0.5**, and ngspice's loader now
  requires ≥ 0.5, rejecting stale `.osdi` files with "Recompile the model with
  the matching openvaf-r" instead of misreading them.
- **ngspice** (`osdisetup.c`, landing exactly on a pre-existing
  `// TODO nodeset?` marker): at instance setup, internal nodes created with a
  non-NAN nodeset get `node->nodeset`/`nsGiven` set; connected **terminal**
  nodes get the same treatment unless the netlist already gave one
  (`.nodeset` wins, matching the LRM's hierarchical-declaration-wins spirit).
- **elaboration** (`hir/elaborate.rs`): the E-5 flattening re-renders net
  declarations when filtering out port names — it now preserves each surviving
  net's initializer text, so submodule nets keep their nodesets.

## What now works (`netinit_examples/`, all verified)

Bistable `x = tanh(5x)` (solutions 0, ±0.999909), the nodeset selecting the
branch:

| case | result |
|---|---|
| no initializer | 0 (trivial solution) |
| `electrical m = 1.0;` / `= -1.0;` (internal) | +0.999909 / −0.999909 |
| port initializer `electrical q = 1.0;` | +0.999909 on the terminal |
| netlist `.nodeset v(q)=-1` vs port initializer | netlist wins (−0.999909) |
| bus `'{0.5, -1.0, 2.0}` | per-bit: weighted sum 90.99 |
| initializer in flattened submodule | preserved (−0.999909) |
| `1e6·q.potential.abstol + 1e12·q.flow.abstol + 1e6·br.potential.abstol` | 3.0 exactly |
| `electrical m = 2*p;` / `a.potential.nonsense` | clean named diagnostics |

`verify_netinit.py`: 11/11 PASS. Regression: all 41 example verify suites ALL
PASS; crate tests (`hir_def`/`hir`/`hir_ty`/`hir_lower`/`sim_back`/`osdi`/
`parser`/`syntax`) 57/57.

## Notes

- **Breaking ABI note**: `.osdi` files compiled before E-45 must be recompiled
  (clean version error, not silent corruption). All committed example `.osdi`
  binaries and prebuilts are regenerated.
- Null bus-literal slots (`'{2.3,4.5,,6.0}`, LRM) remain a parse error —
  use an explicit value per element; extra/missing leaves simply leave the
  remaining bits without a nodeset.
- Nature-qualified spellings (`Voltage.abstol`) stay rejected: the LRM BNF
  (Syntax 5-4) allows net qualifiers only; the abstol-for-`ddt()` use passes
  the nature identifier directly, which already worked.
