# Enhancement-398 — `paramset` was the one supply path nobody checked

Four defects in `paramset`, all silent. A paramset
([Enhancement-21](Enhancement-21.md)) wraps a module and binds some of its
parameters — it is how a PDK ships a validated, pre-configured view of a compact
model. Which makes it the worst place for validation to be missing.

## 1. It was the only supply path that bypassed range validation

With `parameter real k = 1.0 from (0:inf);` in the target:

```verilog
paramset dut basemod; .k = -1.0; endparamset
```

puts **−1.0 into the model**, and neither the compiler nor ngspice says a word.
The same value by any other route is rejected:

| how the value is supplied | before |
| --- | --- |
| `.model mm basemod(k=-1)` | ✅ *"Parameter k is out of bounds!"*, run aborts |
| instance line | ✅ rejected |
| `altermod @mm[k]=-1` | ✅ rejected |
| `alter @n1[k]=-1` | ✅ rejected |
| `.param` into the model card | ✅ rejected |
| subcircuit parameter forwarded | ✅ rejected |
| **`paramset`** | ❌ **accepted, silently** |

Six paths enforced the range. One did not.

`exclude` and integer `from [1:3]` were bypassed identically, as was the
open-bound value `.k = 0.0`.

### Why nothing caught it

Binding an override turns the target parameter into a **localparam**, and
`param_body_with_sourcemap` returned

```rust
ParamExprs { default, bounds: Vec::new().into() },
```

for it — the constraint was discarded before anything could check it. So
`insert_param_init` had nothing to emit, and because a localparam is not
settable from a netlist, ngspice's runtime validation never saw the parameter at
all. The value fell into the gap between the two.

The check now runs in `lower_paramset`, where the override and the target's
constraints are both still syntax. It folds **literal values only** — an override
built from the paramset's own netlist-settable parameters is not knowable there,
and pretending otherwise would reject legitimate paramsets. That boundary is
pinned by an accept-half case.

### This is not Enhancement-56 again

[Enhancement-56](Enhancement-56.md) deliberately refuses to range-check a
parameter's **default**, because CMC models use an out-of-range default to mean
"feature disabled" — `diode_cmc` declares `CORECOVERY = 0.0 from (0.0:1.0]` and
gates on `if (CORECOVERY > 0)`. That reasoning does not reach here: a paramset
override is a **supplied value**, not a default, and a declared range exists
precisely to bind supplied values. The distinction is the whole reason the
netlist path checks and the default path does not.

## 2. An override naming a parameter the target does not declare

```verilog
paramset dut basemod; .nosuch = 1.0; endparamset
```

The binder looks each override up among the target's parameters; a name that
matches nothing simply never bound anything, and nothing said so. The netlist
path reports the same mistake — *"unrecognized parameter (nosuch) - ignored"* —
and [Enhancement-392](Enhancement-392.md) established exactly this check for
`#(.param())` on module instantiation.

## 3. The same parameter assigned twice

```verilog
paramset dut basemod; .g = 1e-3; .g = 9e-3; endparamset
```

Accepted, and the **first** assignment wins, because the binder takes the first
match. Nothing indicated the second had been discarded.
[Enhancement-395](Enhancement-395.md) reports this for netlist lines.

## 4. `$param_given` reported false for a paramset-supplied value

| how `g` is supplied | model receives | `$param_given(g)` before |
| --- | --- | --- |
| netlist `basemod(g=5e-3)` | 0.005 | given |
| paramset `.g = 5e-3` | 0.005 | **NOT given** |
| nobody | 0.001 (default) | NOT given |

A bound parameter is a localparam, so it has no runtime given-flag and
`ParamKind::ParamGiven` resolved to false.

`$param_given` is the standard CMC idiom for *"did the user specify this, or is
this my default?"* — typically to derive one parameter from another only when the
user did not set it. Through a paramset, every such derivation silently took the
default branch while the model ran the paramset's value. It reports **given**
now. An ordinary `localparam`, which nobody supplied, still reports not-given.

## Scope, stated rather than hidden

Paramset **binning** clauses — `.w from [0:10]`, LRM 6.4's mechanism for
selecting among several paramsets by device geometry — remain unsupported and
are a clean parse error. That is a missing feature rather than a silently wrong
answer, and it is not what this release is about.

## Verification

`examples/paramsetguard_examples` — **41/41 fixed, 22/41 against the shipped
binary**. Nineteen checks pin real defects.

Every rejection is checked twice: that it *is* rejected, and that the message
names the offending value and the range or the parameter and the target module.
The accept half pins the seven ways a paramset must keep working — a value inside
the range, both **closed** bounds (`[0:10]` accepts 0 and 10), a parameter with
no range declared, a value outside an `exclude`, an override that is an
expression, two different parameters, and a paramset of a paramset.

The suite also re-checks that the six paths which *were* already enforcing the
range still do, because this release's whole argument is that they were right and
the seventh was wrong.

**Corpus differential.** All 124 `VA_TEST` files compiled with the shipped binary
and with this one: **107 compiled by both, 0 return-code differences, 0 byte
differences, and 0 models trip any of the new checks.** No corpus model uses a
paramset, so that last number confirms the checks are aimed at a mistake rather
than at practice.

`cargo test --workspace` **209/0**, full regression **322/322**.
