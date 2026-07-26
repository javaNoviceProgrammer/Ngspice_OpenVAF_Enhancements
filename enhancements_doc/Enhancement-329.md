# Enhancement-329 — a GRAVESTONE phi operand crashed the small-signal network builder

From the seven-strategy fuzz campaign. A `ddt` of a negated flow probe, combined
with a statically-false branch containing a loop, crashed the **shipped**
compiler:

```verilog
r0 = ddt(-I(a,b));
if ((1*s0)-s0) begin lc3 = 0; while (lc3 < 4) lc3 = lc3 + 1; end
I(b,c) <+ r0*r1;
```

```
thread 'main' panicked at sim_back/src/topology/small_signal_network.rs:
  internal error: entered unreachable code
```

## Root cause

The value reaching the analysis is `GRAVESTONE` — `Value(0)`, whose `ValueDef` is
`Invalid`. It is the compiler's own placeholder, declared in `mir/src/dfg/values.rs`
as *"place holder for unused values that must remain (in phis)"*: the SSA
re-builder puts it in a phi for an edge that has **no reaching definition**, i.e.
an edge coming from a block unreachable from the entry that `simplify_cfg` cannot
delete.

The small-signal network builder assumed such a value could never reach it, and
said so with `unreachable!()` in two arms — one in `analyze_value`, one in
`analyze_dependency`. That assumption is wrong, and asserting it crashed the
shipped compiler on legal input.

## The fix

A GRAVESTONE phi operand sits on a dead edge and therefore **cannot be used at
run time**, so it contributes nothing to the small-signal network. Both arms now
say exactly that, mirroring the neighbouring "contributes nothing" arms:

- `analyze_value` → `FlatSet::Zero` (the same answer the `F_ZERO` arm gives);
- `analyze_dependency` → `Dependency::Independent` (the same answer the
  `Param(_) | Const(_)` arm gives).

## Not a miscompile — proven, not assumed

An `unreachable!()` that fires usually means something upstream is malformed, so
the guard is only legitimate if the code it lets through is *correct*. It is:
the crash shape and a reference model with the crash ingredients removed produce
**identical** results —

| | crash shape | clean reference |
|---|---|---|
| source current | `-5.00000e-04` | `-5.00000e-04` |
| node voltage | `5.000000e-01` | `5.000000e-01` |

i.e. `r0*r1` contributes exactly zero, which is precisely what the guard assumes
(`r1` is never assigned, so it reads as the uninitialized default).

## Honest scope — what is fixed and what is not

This fixes the **shipped crash**. A deeper defect remains, and is *not* addressed
here: the MIR that carries a GRAVESTONE phi operand is SSA-invalid, so the
assertions build still trips `debug_assert!(cx.func.validate())` in
`sim_back/src/lib.rs` on this input. That is an assertions-only failure — the
release compiles it and, as shown above, computes the right answer — of the same
family as Enhancement-310. The root fix is in the SSA re-builder
(`mir_build/src/ssa.rs`), which should not mint an `Invalid` operand for an edge
with no reaching definition in the first place; that touches SSA construction for
every model and is deliberately left to a dedicated change rather than bundled
into a crash fix.

## Output preservation

Both arms were `unreachable!()`, so no model that compiles today can execute
them — changing what they return therefore cannot change the MIR of any working
model. Output-preserving by construction, and confirmed against the corpus with
the deterministic `--dump-mir` oracle.

## Files

- `OpenVAF-master-20260610/openvaf/sim_back/src/topology/small_signal_network.rs`
  — the two `ValueDef::Invalid` arms.
- `examples/vafssngravestone_examples/` — the crashing shape compiles and its
  operating point matches a reference model with the ingredients removed
  (`verify_vafssngravestone.py`, 3 checks).
