# Enhancement-639: a contribution to a port declared `input` is warned (L031)

**Scope:** F5 of the
[2026-09-14 hunt](../docs/bug_hunts/2026-09-14_openvaf-r-parameters-arrays-and-hierarchy.md).
`input p; … I(p,n) <+ V(p,n)/1k;` compiled without a word. Compiler:
`openvaf/basedb/src/lints.rs` (lint L031 `contribution_to_input_port`,
warn), `openvaf/hir_ty/src/validation/body.rs` (`lint_input_port_write` on
every contribution destination), `openvaf/hir_ty/src/validation.rs` (the
report and its lint source). New suite
[`inputport_examples`](../examples/inputport_examples/) (6 checks per
solver). **Compiler side.**

**Suites:** `inputport_examples` 6 of 6 per solver, both solvers; the
`hir_ty` and `basedb` crate tests green; the 26 bundled industry models
compile with zero L031 hits; full sweep 512 of 512.

## What the LRM says

VAMS-2023 §5.6.1, on branch contribution statements: *"Implementations may
issue a warning if a contribution is made to an analog port declared with an
input direction. There are no restrictions on the probing of an analog port
declared with an output direction."* (The standard's change list records
that an earlier edition made it an error; it is a warning now.) The
signal-flow chapter puts the same rule more strongly for its own
disciplines (§1.3.4: potential and flow contributions "may not be made to
input ports").

The compiler enforced none of it. An `input` port is one the module reads;
a contribution drives it, and the interface the module declared was untrue
with nothing said — `port_without_direction` (L016) refuses a port with no
direction, but a port with the wrong one passed.

## What changes

Lint **L031 `contribution_to_input_port`** (warn by default, as the LRM has
it) fires once per contribution statement whose branch has a port declared
`input` — and only `input`; an `inout` is both — at either end: `I(p,n) <+`,
`V(p,n) <+`, `V(p) <+`, a named branch `(p,n)` or `(p)`, a branch to an
internal node. Probes are not judged (the clause restricts nothing about
probing, and `I(<p>)` of an input reads what the port carries), and an
`output` or `inout` port is not an input:

```
warning[L031]: contribution to the input port 'p'
  --> in1.va:3:57
  |
3 | module m(p,n); input p; inout n; electrical p,n; analog I(p,n) <+ V(p,n)/1k; endmodule
  |                                                         ^^^^^^ a flow contribution to a branch on 'p', which is declared `input`
  |
  = LRM 5.6.1: an `input` port is one the module reads; a contribution drives it, and 'implementations may issue a warning if a contribution is made to an analog port declared with an input direction' -- this is that warning
  = help: declare 'p' `inout` if the module drives it, or keep the declaration and silence this with (* openvaf_allow="contribution_to_input_port" *) on the statement
```

The build continues; `-A contribution_to_input_port` (or `-A L031`), the
statement attribute, and `-E` behave as for every lint, and `--lints` lists
it under the warnings. The check lives in body validation beside the
port-flow and ground checks, on the destination of a contribution
(`self.write`), so it costs nothing at run time and cannot change what the
model computes.

## Verification

| check | result |
|---|---|
| `I(p,n) <+`, `V(p,n) <+`, `V(p) <+`, `branch (p,n)`, `branch (p)` on `input p` | each warned once, naming `p` and LRM 5.6.1 |
| `V(p,n)`, `I(<p>)` probes on an input; a contribution to an `output` or `inout` port | silent |
| the warned model | compiles and runs (1 mA) |
| `(* openvaf_allow=… *)`, `-A`; `-E L031` | silent, silent; an error that fails the build |
| `--lints` | `contribution_to_input_port L031` under WARNINGS |
| a branch `(p,x)` to an output node beside a clean `(x,n)` | one warning, naming `p` |
| the 26 bundled industry models | zero L031 hits |
| `inputport_examples` | 6 / 6, both solvers |
| full sweep | 512 of 512 |
