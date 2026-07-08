# Enhancement-12 — the last Verilog-A system functions: probe / alias / plusargs

This document describes the source-code changes made to **OpenVAF-r** in the
`version11/` directory, implementing the **final** group of previously-gated
Verilog-AMS system functions, on top of Enhancement-11 (file I/O + string
functions, same folder):

- `$simprobe`
- `$analog_node_alias`, `$analog_port_alias`
- `$test$plusargs`, `$value$plusargs`

After this, **no system function is gated as unsupported** in
`hir_def::BuiltIn::is_unsupported()` -- it now always returns `false`.

All work is in `version11/` only; verification uses `version11/ngspice-46`'s own
binary and `version11/OpenVAF-master`'s own `openvaf-r`.

## 1. Why these are "mechanism-unavailable" fallbacks, not full features

Unlike the I/O functions, these five have **no underlying mechanism in the
OSDI/ngspice target**, so there is nothing to wire them to:

- **plusargs** (`$test$plusargs`, `$value$plusargs`) query simulator
  *command-line* `+args`. OSDI models are loaded objects, not invoked with a
  command line, and ngspice passes no plusargs to them -- so no plusarg is ever
  present.
- **`$simprobe`** reads an arbitrary named simulator quantity of another
  instance. OSDI exposes no such generic cross-instance probe API.
- **`$analog_node_alias`/`$analog_port_alias`** establish a runtime hierarchical
  *alias* for a node/port (a `connectmodule`/hierarchy feature). OSDI compact
  models have no runtime hierarchical-aliasing mechanism.

The LRM defines a well-behaved result for each when the mechanism is
unavailable, and that is exactly what Enhancement-12 emits. So these functions
now **compile and run with predictable, defined semantics** (a model that uses
them is no longer rejected), which is the correct outcome for this target -- the
same fallback other simulators give for OSDI models. There is deliberately **no
runtime callback and no ngspice change**: each lowers to a compile-time
constant.

## 2. Implementation

Ungated in `hir_def/src/builtin.rs` (the `is_unsupported()` match body is now
just `_ => false`), and lowered in `hir_lower/src/expr.rs` to constants:

| Function | Return type | Lowers to |
|---|---|---|
| `$test$plusargs(str)` | Bool | `FALSE` -- no plusarg present |
| `$value$plusargs(str, str)` | Bool | `FALSE` (OpenVAF's signature has no in-out value arg, so there is nothing to extract into) |
| `$analog_node_alias(node, str)` | Integer | `0` -- no alias created |
| `$analog_port_alias(port, str)` | Integer | `0` |
| `$simprobe(inst, quant)` | Real | `0.0` -- probe unavailable |
| `$simprobe(inst, quant, default)` | Real | the supplied `default` (via `lower_expr(args[2])`) |

The node/port arguments are type-checked as `Node`s during inference but are not
lowered (the result is a constant), so referencing them adds nothing to the
device topology.

Naming note: the plusarg functions use the IEEE `$`-separated spelling
`$test$plusargs` / `$value$plusargs` in Verilog-A source (registered that way in
`syntax/src/name.rs`), not underscores.

## 3. Verification (`examples/alias_examples/`)

`alias_demo.va` calls all five (with and without a `$simprobe` default) and
writes the results to `alias_out.txt`; `verify_alias.py` runs a `.op` and checks
them:

```
test_plusargs=0   value_plusargs=0
node_alias=0      port_alias=0
simprobe=0        simprobe_default=3.5
```

```
$ python3 verify_alias.py
...
ALL PASS (6/6)
```

Regression: `sim_back` unit tests 24/24; `hir_*` data-tests unchanged;
Enhancement-10 `verify_rng.py` 24/24, Enhancement-11 `verify_fileio.py` 9/9 and
`verify_stringio.py` 6/6 all still pass.

## 4. Diff summary

| File | Kind of change |
|---|---|
| `openvaf/hir_def/src/builtin.rs` | Ungated the last five functions; `is_unsupported()` is now unconditionally `false` (§2) |
| `openvaf/hir_lower/src/expr.rs` | Constant lowering for `$test$plusargs`/`$value$plusargs` (→ `FALSE`), `$analog_node_alias`/`$analog_port_alias` (→ `0`), `$simprobe` (→ default or `0.0`) (§2) |
| `examples/alias_examples/` | New verified example suite (`alias_demo.va`, `verify_alias.py`, `README.md`) (§3) |
