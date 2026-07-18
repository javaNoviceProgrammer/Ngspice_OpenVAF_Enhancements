# Enhancement-224 — reference array/bus node voltages in `print`/`plot`

[Enhancement-221](Enhancement-221.md) added array/bus **node ranges** to the
netlist (`R1 a[0:1]` → `R1 a[0] a[1]`), naming the nodes with **literal
brackets** — the vector is stored as `a[0]`. But the ngspice frontend expression
parser uses `[...]` as its **vector-index operator**, so in `print`/`plot`/`let`
the token `a[0]` was read as *"element 0 of a vector named `a`"*. There is no
vector `a`, so `print v(a[0])` and `print a[0]` silently failed (with a
`vector a is not available` warning) even though the node existed and solved
correctly. This enhancement makes those references work.

## The fix

A **literal-node fallback**: when the base name of an index expression is an
**unresolved** name (a zero-length placeholder) and a node/vector named
`base[index]` exists, use that node instead of indexing. It only fires when the
base name does not resolve, so ordinary vector indexing (`realvec[3]`) is
untouched. Three frontend spots, because `a[0]` reaches the machinery three ways:

| Site | Path | Change |
|---|---|---|
| `frontend/parse.c` `checkvalid` | pre-evaluation validity check rejected the term because base `a` is zero-length | for an `INDX` node over an unresolved base, accept it when the literal node `base[index]` exists |
| `frontend/evaluate.c` `op_ind` | evaluates `a[0]` (bare form) | before evaluating the bare base, resolve the literal node name `base[index]` (so no spurious `no such vector a` is emitted) |
| `frontend/evaluate.c` `apply_func` | the `v()` node-access path needed `arg->pn_value`, which an `INDX` node lacks (`bad v() syntax`) | reconstruct the literal node name from the `INDX` argument and resolve it |

The index must be a constant (it always is for a node reference); the base must
be an unresolved zero-length placeholder (which is exactly the array-node case,
and never a real vector).

## What now works

```
print a[0]                 -> a[0] = 1              ; bare form
print v(a[0])              -> v(a[0]) = 1           ; v() form
print v(a[0]) - v(a[1])    -> -2                    ; array nodes in expressions
plot v(a[0]) v(a[1])                                ; and in plot/let
```

Branch current through the bus resistor `R1 a[0:1]` remains the device parameter
`@r1[i]` (ngspice has no "current between two nodes" syntax; `i()` takes a source
name). `print a[0]` / `v(a[0])` are the node-**voltage** counterparts that were
missing.

## Verification (`examples/arraynodeprint_examples`)

`verify_arraynodeprint.py` (8 checks, both solvers) asserts `print a[0]`,
`print v(a[0])`, `print v(a[1])`, an array-node expression `v(a[0])-v(a[1])`, and
the bus branch current `@r1[i]` all read the correct DC values; that ordinary
vector indexing (`unitvec(4)[2]`) is unchanged; and that a genuinely-missing node
`v(a[9])` stays a clean miss (no value, no crash). Full regression: 183/183.

Scope: ngspice frontend only, two files (`frontend/parse.c`,
`frontend/evaluate.c`); no device, solver, or OSDI change.
