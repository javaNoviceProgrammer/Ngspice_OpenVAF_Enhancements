# Enhancement-215 — `$test$plusargs` / `$value$plusargs` productionized

Command-line **plusargs** are Verilog's mechanism for passing `+name[=value]`
arguments from the simulator invocation into a model. They are the natural way to
pick a **corner** or toggle a **feature flag** at run time, without editing the
netlist:

```
ngspice -b amplifier.cir +corner=ff
ngspice -b amplifier.cir +gain=25
ngspice -b amplifier.cir +boost
```

[Enhancement-12](Enhancement-12.md) had gated these as "mechanism-unavailable"
fallbacks: `$test$plusargs` always returned `false` and `$value$plusargs` never
wrote its output, because ngspice had no notion of a command-line plusarg. E-215
gives them a real mechanism. It is **additive** — no OSDI ABI change, no version
bump; existing `.osdi` files load and behave exactly as before.

## The idea: ride the simparam channel

ngspice already hands each model an `OsdiSimParas` string/number channel on every
evaluation — that is how [Enhancement-25](Enhancement-25.md)'s `$simparam$str`
reads `"analysis_name"`. E-215 injects the command-line plusargs onto that same
channel as **namespaced simparams**, so the compiler can serve the plusarg
builtins with the machinery that already exists, and no new descriptor field is
needed.

For each `+name[=value]` on the command line ngspice publishes:

| simparam | kind | value |
|---|---|---|
| `$test$plusargs$name` | number | `1.0` (the name is present) |
| `$valset$plusargs$name` | number | `1.0` iff given as `name=value` |
| `$valnum$plusargs$name` | number | the value parsed as a `double` |
| `$value$plusargs$name` | string | the value as text |

## Compiler side (openvaf-r)

`$test$plusargs("name")` and `$value$plusargs("name=%fmt", var)` take a
compile-time string literal, so the namespaced key is built at compile time and
the value is read directly by the target's type:

- **`$test$plusargs("name")`** → `simparam("$test$plusargs$name", 0.0) != 0`
  (a `Bool`).
- **`$value$plusargs("name=%d", var)`** (integer target) →
  `var = (int) simparam("$valnum$plusargs$name", 0.0)`, return
  `simparam("$valset$plusargs$name", 0.0) != 0`.
- **real target** (`%g`/`%e`/`%f`) → the same via `$valnum`, without the cast.
- **string target** (`%s`) → `var = simparam_str_opt("$value$plusargs$name", "")`.

Because the value is read directly from the (op-dependent) simparam channels,
`$value$plusargs` does **not** go through the `$sscanf` scanner. That matters:
the scanner threads its state through a hidden module-global cursor, so
`scanf_begin`/`scan_*` have no explicit data dependency and the setup/eval
partitioner can hoist a `scan_*` away from its `scanf_begin` (into instance setup)
— the scan then reads a NULL cursor and segfaults. The direct-simparam design has
no such split.

Two small pieces of new compiler machinery support this:

- `hir_ty`: `$value$plusargs`'s second argument is now an **output target**
  (`Var(Integer)`/`Var(Real)`/`Var(String)`, one signature each, mirroring
  `$random`'s seed and `$fgets`'s buffer) instead of the read-only `Val(String)`
  that made it impossible to extract into.
- A **non-fatal** string simparam lookup `simparam_str_opt` (stdlib + the
  `SimParamStrOpt` callback). The existing `simparam_str` raises a fatal error on
  an unknown name — fine for `$simparam$str`, but `$value$plusargs("corner=%s", …)`
  must be able to ask for a plusarg that was not supplied and get an empty string
  back rather than aborting.

## Simulator side (ngspice)

`main.c` treats a `+`-prefixed command-line argument as a plusarg rather than an
input file (in both the batch and interactive file loops) and registers it.
`get_simparams` (`osdiload.c`) splices the namespaced plusarg entries onto the base
simparam arrays the first time it is called with any plusargs present — so a run
with **no** plusargs allocates nothing and is byte-for-byte unchanged.

Plusargs are constant for the whole run, so `$value$plusargs` matches only the
`name=value` form (a bare `+gain` is a *presence* for `$test$plusargs` but not a
*value* for `$value$plusargs`, per the LRM).

## Verification (`examples/plusargs_examples`)

`plusargs_demo.va` maps plusargs onto a conductance, observable as the DC current
through a 1 V source. `verify_plusargs.py` (12 checks, both solvers) runs
`ngspice -b deck +args…` and asserts the current for each: baseline (1 mS),
`+boost` (10, presence), `+gain=25`/`+gain=3` (integer value), `+scale=2.5` (real
value), `+corner=ff`/`+corner=ss` (string value → 5 / 0.2), an unmatched
`+corner=tt` and an unrelated `+foo` (both fall through to baseline), `+boost
+gain=7` (last applicable wins), and a bare `+gain` with no value (correctly *not*
a value match). Full regression: 175/175.

## Scope

`$test$plusargs` and `$value$plusargs` for integer, real and string targets. The
node/port alias functions (`$analog_node_alias`/`$analog_port_alias`) and
`$simprobe` remain E-12 fallbacks — they need runtime hierarchical mechanisms OSDI
does not provide, unlike plusargs, which only needed a channel that was already
there.
