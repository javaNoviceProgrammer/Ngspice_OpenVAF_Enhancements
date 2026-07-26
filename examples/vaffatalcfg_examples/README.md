# `$fatal` control flow (Enhancement-324)

`$fatal` used to lower to "print, set the abort flag, **`exit()`**, then create a
fresh block with no incoming edges and carry on lowering into it".

That is unsound for a *compiled* device model. All three simulator-control tasks
are only flags the simulator inspects **after** the OSDI eval function returns —
none of them can jump out of the middle of an evaluation — and that eval function
has a mandatory epilogue (store the residual/jacobian outputs) which the ABI
requires to run. `$finish` and `$stop` were already lowered correctly as
"set the flag and continue"; `$fatal` was the outlier, and terminating the MIR
function early stranded code in an unreachable block. It crashed the **shipped**
compiler two different ways:

| Model shape | Pre-fix crash |
|---|---|
| `$fatal(0); I(a,c) <+ …;` | the contribution was lowered into the unreachable block but stayed referenced by the contribution bookkeeping, so aggressive DCE hit an instruction belonging to no block — `Option::unwrap()` on `None` in `mir_opt/dead_code_aggressive.rs` |
| `I(a,c) <+ …; $fatal(0);` | the eval **epilogue** landed in the unreachable block, where the residual value does not dominate, so codegen read an undefined value — `mir_llvm/builder.rs` |

The fix makes `$fatal` set its flag and fall through, exactly like `$finish` and
`$stop`. The CFG stays connected, so neither situation can arise.

## Files

- `fatal_after.va` — a statement after an unconditional `$fatal` (crash shape 1).
- `fatal_before.va` — a contribution before an unconditional `$fatal` (shape 2).
- `fatal_guard.va` — the realistic usage: a parameter validity guard. This one
  compiled before the fix too, and is here to prove the **run-time** meaning of
  `$fatal` is unchanged (message printed, run aborted).
- `verify_vaffatalcfg.py` — 6 checks. The first two fail on the pre-fix binary
  (compiler panic, no `.osdi` produced); the rest are forward guards.

## Run

```
python3 verify_vaffatalcfg.py
```

## Scope

Only `$fatal`'s control flow changed. Across the 462-model corpus the emitted
MIR is byte-identical for 460 models; the two that differ
(`simctrl_examples/simctrl_demo.va`, `vafcodegen_examples/staleuse.va`) are
exactly the ones that exercise `$fatal` in a reachable analog context, and both
suites still pass in full — including the `$fatal` abort/setup-rejection checks
in `simctrl` and the Enhancement-294 `staleuse` simulation check.
