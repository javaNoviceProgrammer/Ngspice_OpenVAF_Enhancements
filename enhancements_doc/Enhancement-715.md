# Enhancement-715: an element of an array-valued parameter can be read in any constant context — another parameter's default, a range bound, a `localparam`, another array parameter's literal, a variable's initialiser — where it was "'pa' was not found in the current scope"; the declaration-order rule covers element reads, so a forward reference to one is refused like a scalar's instead of crashing the compiler

**Scope:** F1 of the
[correctness campaign of 2026-09-25](../docs/bug_hunts/2026-09-25_openvaf-r-correctness-campaign.md).
**Compiler only.** `hir_ty/src/inference.rs` (`owner_module`, `find_param_array`,
`find_var_array`, `module_genvars`), `hir_ty/src/validation/body.rs` (the `BitSelect`
arm of the declaration-order check).
[`examples/array_examples/`](../examples/array_examples/) (`array_const.va`, 7 checks,
11 in all). The hunt page.

**Suites:** `array` 11 of 11 (4 of 11 on the E-714 binaries: the module is refused
there), `mdarray`, `paramarrayarg`, `arrayscale` 38 of 38, `modelparamset` 7 of 7,
`paramsetlrm`, `tablearray`, `langguard` 132 of 132, `vafcrash2` 22 of 22,
`cubic_table` and `filterforms` 100 of 100 unchanged; the compiler workspace tests green
apart from the three pre-existing sourcegen drift failures (221 passed), no build
warnings; full sweep, run alone.

## What was wrong

With `parameter real pa[0:2] = '{1.5, 2.5, 3.5};` declared, every one of

| form | E-714 |
|---|---|
| `parameter real pb = pa[1];` | `error: 'pa' was not found in the current scope` |
| `localparam real lq = pa[0] * 2;` | the same |
| `parameter real pb = 1.0 from [pa[0]:pa[2]];` | the same, twice |
| `parameter integer pb = pa[0] + pa[1];` (an integer array) | the same, twice |
| `parameter real pq[0:1] = '{pa[0], pa[1]};` | the same, twice |
| `real x = pa[2];` (a variable's initialiser) | the same |
| `parameter real pb = pa;` (the whole array) | the same |

was refused, the caret under `pa`, while the analog block read `pa[pi] + pa[2]`
without a word, and a scalar parameter in the same places was fine.

An array parameter is one item per element since E-14 (`pa[0]`, `pa[1]`, … in the
item tree; `pa` itself is no item but a `BusDecl` in the module's `param_arrays`).
Reading `pa[1]` is a `BitSelect` whose base the inference resolves by first asking
`find_param_array` for the module's array of that name, then the synthesised element
name. `find_param_array` — and `find_var_array` and `module_genvars` beside it —
answered only when the body's owner was the module itself (`DefWithBodyId::ModuleId`).
A parameter's default and range are a body of their own, owned by the parameter
(`param_body_with_sourcemap_query`), and a variable's initialiser likewise
(`VarId`); for those owners the lookup returned nothing, the base fell through to a
scalar path resolution, and `pa` is not an item.

Once the lookup answered, a second gap showed: E-414's declaration-order rule
("parameters may only refer to parameters textually defined before them") was
checked on `Expr::Path` reads only. `parameter real pb = pa[1]; parameter real
pa[0:2] = …` then passed validation, reached the lowering, and the lowering read the
not-yet-defined element's value — `BuilderVal::Undef`, "attempted to read undefined
value", a compiler crash with a crash log.

## What changed

**The inference finds the module through the body owner's scope**
(`hir_ty/src/inference.rs`, `owner_module`): the module's own body is the module;
a parameter's and a variable's body sits in the module's scope, or in a block scope
inside it, and the scope's origin — walking block parents — names the module.
`find_param_array`, `find_var_array` (for every owner but a function, whose arrays are
its own since E-18) and `module_genvars` use it. A function-local parameter's scope
is the function's and sees no module array, as before. Nothing else in the resolution
changes: a constant index reads the element parameter, a dynamic one
(`pa[pi]` with `pi` a parameter, legal in a default) builds E-328's select over the
elements, the value follows a card override of the element it reads, and E-555's
range check judges `from [pa[0]:pa[2]]` with the elements' card values.

**The declaration-order check covers element reads**
(`hir_ty/src/validation/body.rs`): a `BitSelect` read in a parameter's own body is
held to E-414's rule — the element it resolves to (a constant index: the expression
is typed as that element parameter) or every element it may select (a dynamic index:
`dynamic_param_index_refs`) must be declared before the parameter, and must not be
the parameter itself; the message names the element:

```
error: definition of 'pb' references parameter 'pa[1]' defined afterwards
  |    parameter real pb = pa[1]; parameter real pa[0:2] = '{1.5, 2.5, 3.5};
  |                   -----^^^^^                 --------- .. to parameter 'pa[1]' defined here
  = help: parameters may only refer to parameters (textually) defined before them
```

The indices are walked as expressions of their own. As a consequence of the same
resolution, the whole-array form `parameter real pb = pa;` now says `'pa' requires a
bit-select [i]` instead of "not found".

## Verification

`array` section "Enhancement-715", a buffer whose gain is assembled from parameters
derived from its tap array `w`: the defaults give 1.5; `w[1]=0.7` on the card moves
the derived `gsum = w[1] + w[2]` (2.0) and `gsum=0.9` given wins (1.9); `w[0]=0.05`
moves a `localparam`, an array literal `'{w[3], w[0]}` and a range bound at once
(1.35); `glim=0.5` is refused at setup as outside `[w[0]:w[3]]` and accepted once
`w[3]=0.6` moves the bound (1.95); `n[1]=7` moves an integer default (1.54). The
four checks of E-14 unchanged.

By hand: the seven forms of the table and a 2-D element (`pm[1][0]`), an
instance-typed source array (the derived parameter promoted with E-546's lint), a
`localparam` beside a default, an `exclude pa[1]`, each with the card overrides
above; the forward references — a constant index, a dynamic index (`pa[pi]`
declared before `pa`), and an element reading a later element of its own array
(`'{pa[1], 2.0}`) — all refused with the message above; a dynamic index in a
default following `pi=2` and `pi=0 pa[0]=9` on the card; the ten suites; the
workspace tests; the sweep.

## What this does not do

- A whole array is still not a value: `parameter real pb = pa;` and
  `localparam real lq[0:2] = pa;` are refused (the first now with "requires a
  bit-select", the second with the element-count mismatch as before). An array
  literal of the elements is the way to copy one.
- An element whose default reads a later element of the same array (`'{pa[1], 2.0}`)
  is a forward reference under the declaration-order rule, since the elements are
  ordered items; the LRM has no word on it.
- A function-local parameter sees no module array, as before.
