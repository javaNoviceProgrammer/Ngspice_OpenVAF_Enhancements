# Enhancement-336 — OSDI descriptor and parameter-binding integrity

Three defects in how a compiled model is described to, and bound by, the simulator.
None crashed; each silently produced the wrong value or the wrong array size.

## 1. An instance parameter named `M` was consumed as the multiplier

```verilog
(* type="instance" *) parameter real M = 2.0;
analog I(a, b) <+ V(a, b) * M;
```

```
n1 a 0 mm M=7      ->  i(va) = 14 = 7 x (1 V x 2)
```

`M=7` was applied as the **device multiplier** while the model's own `M` kept its
default of 2. Root cause is in ngspice: `osdiregistry.c` decided whether to synthesize
its `m` alias for `$mfactor` using a case-**sensitive** `strcmp(name, "m")`, so a model
declaring `M` never suppressed it — while that same `M` was lowercased to `m` when
registered. Both ended up as `m`, and the alias won.

The inconsistency was visible in the same loop: the `dtemp`/`dt`/`temp` tests two lines
below already used `strcasecmp`. Now `m` does too, and `M=7` reaches the model's own
parameter (`i(va) = 7`).

## 2. Parameters differing only in case silently lost a value

Verilog-A is case-**sensitive**, so `GAIN` and `gain` are two distinct parameters.
SPICE is not. Both fold to the same keyword when registered, and one silently loses:

```
.model cc casecollide GAIN=3 gain=7   ->  7.001
```

decoding as *both* names routed to one parameter (last wins → 7) while the other kept
its default of 1000 (contributing 1e-3).

**This cannot be resolved in the loader** — a SPICE netlist is lowercased when parsed,
so by the time a value arrives the two names are indistinguishable. What it must not be
is *silent*. It now warns, naming the module and the parameter, so the model author
learns the names are unreachable instead of debugging a wrong answer. The binding
behaviour is deliberately unchanged; only the silence is fixed.

## 3. `num_resistive_jacobian_entries` exceeded the entry list

For a model with three contributions across three nodes the descriptor reported
`num_resistive_jacobian_entries = 8` against `num_jacobian_entries = 7` — a count
larger than the entire array it describes, which an OSDI consumer trusting it would use
to walk past the end.

`num_jacobian_entries` and the entry list are both derived from the **current**
`dae_system.jacobian`, but the resistive/reactive counts came from a value cached by
`count_jacobian_entries()` while the DAE system was still being built. The jacobian can
lose entries after that point (node collapsing), leaving the cached number stale.

Both counts are now derived from the same map that produces the entry list, so they are
consistent by construction rather than by timing.

## Verified

- `M=7` sets the model's own `M` (`i(va) = 7`, was 14).
- A case collision is reported: *"model parameter 'gain' is declared more than once
  differing only in case"*.
- An independent OSDI descriptor reader reports **0 violations** on the two models that
  previously showed 2 and 1, and still reports 0 on ordinary models — so the checker is
  specific, not blanket-passing.
- The affected model compiles and simulates cleanly.

## Scope

Defects 1 and 2 are ngspice-side (`src/osdi/`), defect 3 is openvaf-side
(`osdi/src/metadata.rs`). They are grouped because they are one story: what the
descriptor promises and what the simulator binds must agree with what the model
actually declared.

## Files

- `ngspice-46/src/osdi/osdiregistry.c` — case-insensitive `m` detection.
- `ngspice-46/src/osdi/osdiinit.c` — the case-collision warning.
- `OpenVAF-master-20260610/openvaf/osdi/src/metadata.rs` — counts derived from the
  emitted entry list.
- `examples/osdiparam_examples/` — all three (`verify_osdiparam.py`, 3 checks).
