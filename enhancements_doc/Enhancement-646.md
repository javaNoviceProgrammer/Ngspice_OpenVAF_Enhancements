# Enhancement-646: an analog function's local variables start every call afresh (2026-09-16 hunt F2)

**Scope:** F2 of the
[2026-09-16 hunt](../docs/bug_hunts/2026-09-16_openvaf-r-functions-conversions-and-events.md).
Compiler: `openvaf/hir/src/lib.rs` (`Function::local_vars`: every variable
the function declares, the named blocks' included, less the array arguments'
elements), `openvaf/hir_lower/src/expr.rs` (`lower_user_fun_impl` defines each
of them to its declared initializer at the inlined entry). New suite
[`funclocal_examples`](../examples/funclocal_examples/) (12 checks per
solver). **Compiler side.**

**Suites:** `funclocal_examples` 12 of 12 per solver, both solvers (2 of 12
on the E-644 compiler); `funcarray`, `arrayout`, `arrayret`, `lrmudf`,
`lrmfuncs`, `funcarity`, `paramarrayarg` green; workspace `cargo test` green;
full sweep 519 of 519.

## What was wrong

An analog function is inlined at each call site, and its local variables are
ordinary module variables: a read that the call's own writes have not yet
reached resolves, like any module variable's, to the hidden-state parameter
that carries a value from one evaluation to the next (E-7). So a local that a
function reads before writing held whatever the previous call — or the
previous Newton iteration — had left in it:

```verilog
analog function real cnt; input x; real x; integer n; begin n = n + 1; cnt = n; end endfunction
real a;
analog begin a = cnt(1.0); $strobe("cnt = %g", a); I(p,n) <+ a + V(p,n)*0; end
```

printed `cnt = 1074` at a single operating point and reached it only through
dynamic gmin stepping — the model was a moving target, its value growing with
every iteration. Two calls in one evaluation continued each other's count; a
declared initializer, `integer n = 5;`, was applied once at the initial step
(the E-7 rule for module variables) and never again; a named block's local
behaved the same. LRM 4.7.2.1 zeroes the function's identifier variable on
every call and 4.7.2.2 zeroes its output arguments — both were already done at
the inlined entry — so the locals were the one kind of function variable a
call did not start afresh, and the asymmetry was invisible: nothing warned.

## What changed

`Function::local_vars` walks the function's def map — its own scope and, through
the block declarations, every named block's — and returns the variables it
declares, minus the element variables of an array argument (the call binds
those: an input takes the caller's values, an output is zeroed). The return
array's elements are included. `lower_user_fun_impl` now defines each of them,
right after the return variable, to its declared initializer body — zero, or
`""` for a string, when the declaration has none — so every read inside the
call sees the call's own value. The `$limit` path goes through the same code. A
local that is written before it is read lowers to the same SSA as before.

## Verification

| check | result |
|---|---|
| the counter local at the operating point | `cnt = 1`, I = −1 A, no gmin stepping (1074 before) |
| the same in `tran 1u 10u` | I = −1 A at every point |
| two calls in one evaluation, `s = s + x` | a = 1, b = 1 (1 and 2 before) |
| `integer n = 5;` inside the function, two calls | 6 and 6 (the initializer used to apply once) |
| a string local read first | `[]` on every call |
| a named block's local `begin : blk integer k; … k = k + 7;` | `k=0` at every call, a = b = 8 (42, 49 before) |
| a local array `real t[0:2]` accumulated within one call | starts at zeros, −3 A |
| an array-returning function called twice with partial writes | `a = 5,0` then `b = 0,3` (LRM 4.7.2.1) |
| a local in a `$limit` limiting function | converges to 1e-3 e¹⁰ |
| two instances | each `cnt = 1` |
| a local written before it is read | unchanged |
| workspace `cargo test` (verilogae and `sourcegen` excluded as before) | green, no generated file rewritten |
| `funclocal_examples` | 12 / 12 per solver, both solvers; 2 / 12 on the E-644 compiler |
| full sweep | 519 of 519 (no model in the corpus relied on a persistent function local) |

## What this does not do

The choice is per-call initialization, not a lint on a read-before-write: the
LRM does not state a rule for locals, and Verilog-2005's static function
variables are what the inlining happened to give; a function is a
computation, and 4.7.2's treatment of the identifier variable and the output
arguments is the rule a reader expects for its locals too. A model that wants
state across calls keeps it in a module variable, as before. Array
declarations inside a named block of a function remain unsupported (a
pre-existing limit, reported as such). The hunt's F3, F4 and the rest are
separate enhancements.
