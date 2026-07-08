# Enhancement-23 — array return values from analog functions

This document describes the source-code changes made to **OpenVAF-r** in the
`version11/` directory to support **array return values** from `analog function`s
(`analog function real[0:n] f;`), completing the array-in-functions arc:
Enhancement-18 (array **arguments**, input) → Enhancement-20 (array
**output/inout** arguments) → Enhancement-23 (array **return values**).

Before this, `analog function real[0:n] f;` was a parse/resolve error (the array
dimensions after the return type were unexpected, and a call `c = f(...)` reported
the call as "not found").

## Syntax and semantics

```verilog
analog function real[0:n] f;   // the return type carries array dimensions
    ...
    f[i] = ...;                // the body writes the return array's elements
endfunction
...
real c[0:n];
c = f(args);                   // the whole returned array is copied into c
```

An array-returning call is valid only as the entire right-hand side of an array
assignment (`c = f(...)`); the destination is a writable array variable of the
same length.

## Implementation: the return array as a function var_array

The design reuses the Enhancement-18/20 array machinery. The return array is
modelled as a **function-scoped array variable named after the function**: its
element variables `f[0]`, `f[1]`, … are registered in the function's `var_arrays`
(exactly like an array argument's element variables), so inside the body `f[i] =
…` resolves and writes them via the existing bit-select / dynamic-index paths.
`function_array_arg_vars(_, f, f.name)` then resolves those element `VarId`s at
the call site.

At the call site `c = f(args)`, inference recognises the right-hand side as a call
to an array-returning function and records an `ArrayAssign::ReturnCall`. Lowering
then:

1. lowers the call — which **inlines the function body**, writing the return
   element variables; and
2. copies each return element variable into the destination array element.

Because the body is inlined as ordinary MIR (as for every user function), the
Jacobian flows through the array return automatically — the AC conductance of a
table/polynomial device defined this way is exact. No OSDI ABI change and no
ngspice change.

### Files changed

- **parser** (`grammar/items/module.rs`) — parse the `[msb:lsb]` return
  dimensions after the type in `func_decl`.
- **syntax** (`ast/generated/nodes.rs`) — `Function::widths()` accessor.
- **hir_def**:
  - `item_tree.rs` — `Function::ret_dims` field.
  - `item_tree/lower.rs` — `lower_fun` expands the return array into element
    variables (a var_array named after the function) and records `ret_dims`.
  - `data.rs` — `FunctionData::ret_len`.
  - `body.rs` / `nameres.rs` — tolerate the synthetic return element variables,
    which have no `ast::Var` node (they carry the function's ast-id as a
    placeholder): `var_body` falls back to the type default and nameres uses the
    erased id, rather than casting to `ast::Var`.
- **basedb** (`ast_id_map.rs`) — `AstId::from_erased`.
- **hir_ty** (`inference.rs`) — `ArrayAssign::ReturnCall`; the array-returning-call
  case in `try_infere_array_assignment` (with a length-mismatch diagnostic).
- **hir** (`lib.rs`, `body.rs`) — `Function::returns_array` / `return_array_elems`;
  the `Stmt::ArrayReturnAssignment` HIR statement.
- **hir_lower** (`stmt.rs`) — lower `ArrayReturnAssignment` (inline the call, then
  copy the return elements into the destination).

## Verification

`examples/arrayret_examples/verify_arrayret.py` (`ALL PASS`) — a cubic polynomial device
`I = c0 + c1·V + c2·V² + c3·V³` built two ways: `polyret` (a function returns the
power array `{1,V,V²,V³}`, summed at the call site) and `polyret_arg` (the returned
array is fed straight into an array-**argument** function, composing E-23 with
E-18). For both, across a bias sweep, the DC current matches the closed form
(~1e-9) and the AC conductance matches the exact derivative `gm = c1 + 2·c2·V +
3·c3·V²` (~1e-9) — the autodiff Jacobian flows through the array return.

A length mismatch (`real c[0:1]; c = f3(...)` where `f3` returns 3 elements) is a
clean compile-time type error, not a crash. Every prior example folder still
passes (notably `funcarray`, `arrayout`, `array`, `mdarray`), and the
`hir_def`/`hir_ty`/`hir_lower` unit-test suites pass with no regressions.

## Known limitations

- An array-returning call is only valid as the entire RHS of an array assignment,
  not as a sub-expression.
- Multi-dimensional return arrays parse and expand (via the N-D var_array
  machinery) but are exercised less than the 1-D case.
