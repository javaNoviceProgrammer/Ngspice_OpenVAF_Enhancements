# Enhancement-645: a parameter array is an array argument, and a paramset binds an array parameter (2026-09-16 hunt F1)

**Scope:** F1 of the
[2026-09-16 hunt](../docs/bug_hunts/2026-09-16_openvaf-r-functions-conversions-and-events.md),
both faces. Compiler: `openvaf/hir_ty/src/inference.rs` (the call-site
pre-resolution of a whole-array argument knows parameter arrays; two new
diagnostics), `openvaf/hir_ty/src/diagnostics.rs`,
`openvaf/hir_def/src/item_tree/lower.rs` (a paramset override of an array's
base name binds every element; the length check; E-398's range check per
leaf), `openvaf/hir_def/src/item_tree.rs` + `item_tree/diagnostics.rs` (the
length diagnostic), `openvaf/hir_def/src/body.rs` (a bound element takes its
leaf of the override literal). New suite
[`paramarrayarg_examples`](../examples/paramarrayarg_examples/) (23 checks
per solver). **Compiler side.**

**Suites:** `paramarrayarg_examples` 23 of 23 per solver, both solvers (on the E-644
compiler 16 of the 17 checks that run fail -- every parameter-array call, every
paramset array assignment -- and six dependent checks are skipped); `funcarray`, `arrayout`, `arrayret`, `paramarray`,
`paramset`, `paramsetlrm`, `paramsetoverload`, `paramsetinst`, `cardbound`
green; workspace `cargo test` green; full sweep 518 of 518.

## What was wrong

**The function face.** LRM 4.7.1 Example 3 declares an array formal as
`inout [0:1]a; input [0:1]b; real a[0:1], b[0:1];` and the call binds a
caller's array to it. E-18 made that work for a *variable* array by
pre-resolving the bare array name at the call site into its element
variables before the generic argument matcher runs (the matcher refuses a
bare array name with "requires a bit-select [i]"). The pre-resolution looked
only at variable arrays, so `parameter real c[0:2]` fed to `sum3(c)` fell
through to the generic path and was refused as `'c' requires a bit-select
[i]` — while lowering had been able to read a parameter array's elements
since the filter arguments learned them (`array_param_ref`), and every other
array consumer (`laplace_*`, `noise_table`, `$table_model`, `$param_given`)
already accepted one. A caller array of the wrong size took the same road:
the pre-resolution `return`ed on a length mismatch, so `real c[0:3]` into
`input [0:2] a` got the identical "requires a bit-select" sentence instead of
a word about the size.

**The paramset face.** An array parameter is lowered as one element
parameter per leaf (`c[0]`, `c[1]`, `c[2]`, each carrying its `array_index`)
plus a `BusDecl` for the base name. A paramset override `.c = '{10.0, 20.0,
30.0};` is matched against the target's parameters *by name*, and no
parameter is named `c`, so it matched nothing and was reported as "paramset
assigns 'c', which module 'm' does not declare" — while a child instantiation
`leaf #(.c('{...})) l1(p,n)` binds the same array without trouble. A paramset
over any module with an array parameter (a coefficient vector, a bin table)
could bind none of it.

## What changed

- **`pre_resolve_array_call_arg`** takes the formal's direction and resolves a
  parameter array through a new `array_elem_params_flat` (the twin of
  `array_elem_vars_flat`), recording the elements in `array_param_refs` and
  the array shape exactly as the filter path does, so `lower_array_elems`
  reads them and the Jacobian flows through the argument. A length mismatch —
  variable or parameter — is reported as `array argument has 4 elements but
  the function's formal declares 3` with the LRM 4.7.1 shape in the help, and
  the argument is still recorded so the generic path stays silent. A
  parameter array bound to an `output`/`inout` formal is refused as `output
  argument bound to parameter array 'c', which cannot be written` (the
  copy-back of LRM 4.7.2.2 needs a variable); the signature builder treats a
  recorded parameter array like a recorded variable array so that error stands
  alone.
- **Paramset binding.** In the target-parameter loop an element (its
  `array_index` set) is matched by the array's base name (`array_base_name`,
  `c` for `c[1]` or `m[1][0]`). On a match every element is bound —
  `is_local`, `override_expr` set — and the base name is what enters
  `bound_names`, so the unknown-name check and the "assigns it more than
  once" check keep working per array. On the first element the override's
  value is flattened (`flatten_pattern`, so replications count) and must have
  exactly `elem_count` leaves: otherwise `paramset assigns array parameter 'c'
  a value with 2 elements but the array has 3` (a scalar is "1 element"). The
  E-398 range check takes an optional leaf position and judges each element's
  own leaf against the declaration's constraints, naming the element: `paramset
  assigns 'c[1]' the value 50, which its declared range [0:10] forbids`. A
  `localparam` array target is refused once, as a scalar one is.
- **Body lowering** of a bound parameter with an `array_index` takes the leaf
  at that position of the override literal, exactly as an element's default is
  picked from its declaration's literal; the length check above guarantees the
  leaf exists.

Not changed: `.c[0] = 10.0;` in a paramset stays a parse error — LRM 6.4.1's
paramset statement assigns a parameter, not an element — and the message
("unexpected token '['; expected '='") says where the form ends.

## Verification

| check | result |
|---|---|
| `parameter real c[0:2]` into `input [0:2] a; real a[0:2];` (and into a formal declared without the range on the `input` line) | compiles; I = −6 A; `c[1]=20` on the card gives −24 A |
| a 2-D parameter array into a 2-D formal; an integer parameter array into an integer formal | −10 A; −6 A |
| `ddx(poly(c, V(p,n)), V(p))` with `poly = a[0]*x + a[1]*x*x` | 5 = c0 + 2 c1 V; I = −3 A |
| `real c[0:3]` and `parameter real c[0:1]` into `[0:2]` | "array argument has 4 (2) elements but the function's formal declares 3"; no "bit-select" |
| a parameter array into an `output` formal, into an `inout` formal | "output argument bound to parameter array 'c', which cannot be written", one error each |
| `paramset ps m; .c = '{10.0, 20.0, 30.0}; endparamset` | c = 10 20 30, I = −60 A; `c[1]=5` on the card is refused as a fixed value and the binding kept |
| `.c = '{10.0, 20.0}`; `.c = 5.0` | "a value with 2 elements but the array has 3"; "1 element" |
| `from [0:10]` on the array, `.c = '{1.0, 50.0, 3.0}` | "assigns 'c[1]' the value 50, which its declared range [0:10] forbids" |
| `parameter real k = 1; .c = '{k, 2*k, 3.0};` with `k=2` on the card; `alter @na1[k]=3` on the instance (E-644 route) | c = 2 4 3, −9 A; c = 3 6 3, −12 A |
| a 2-D array `.m = '{'{10.0, 20.0}, '{30.0, 40.0}}` | −100 A, row-major |
| an out-of-module reference beside the array (`.r = corner_x.rr;`, the E-563 fold) | c = 10 20 30, r = 7, −60/7 A |
| a `localparam` array target; `.zz = 1` beside a bound array | refused once as not a parameter; the unknown name still reported |
| workspace `cargo test` (verilogae and `sourcegen` excluded as before) | green, no generated file rewritten |
| `paramarrayarg_examples` | 23 / 23 per solver, both solvers; 1 of 17 run on the E-644 compiler |
| full sweep | 518 of 518 |

## What this does not do

The hunt's F2 (function locals static across calls), F3 (real→integer
conversion refused for an integer formal and a `case` label), F4 (an event
under a non-constant condition) and the rest of the list are separate
enhancements. A paramset still cannot assign an element on its own, which the
LRM does not provide for either.
