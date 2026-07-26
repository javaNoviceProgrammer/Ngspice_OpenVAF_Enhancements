# Enhancement-324 — `$fatal` stranded code in an unreachable block (two shipped crashes)

Found by a diverse-strategy fuzz campaign against the assertions build
(~75 000 generated well-typed models across seven generation strategies). Both
crashes reproduce on the **shipped release**, not just the instrumented build.

## The two crashes

| Model | Crash |
|---|---|
| `analog begin $fatal(0); I(a,c) <+ V(a,c)/1k; end` | `mir_opt/src/dead_code_aggressive.rs:112` — `Option::unwrap()` on `None`, from `self.func.layout.inst_block(inst).unwrap()` in `mark_inst_live` |
| `analog begin I(a,c) <+ V(a,c)/1k; $fatal(0); end` | `mir_llvm/src/builder.rs:143` — `unreachable!("attempted to read undefined value")` in `BuilderVal::get`, reached from `store_residual` |

Different passes, different symptoms — but **one root cause**.

## Root cause

`$fatal` lowered to *print → set the abort flag → `exit()` → create a fresh block
with no incoming edges → keep lowering into it* (`hir_lower/src/expr.rs`), with
the comment "Because it has no incoming edges it will be removed from MIR".

That is unsound for a compiled device model. All three simulator-control tasks
are only **flags the simulator inspects after the eval function returns** —
`RetFlag::Abort`/`Finish`/`Stop` all lower to `set_ret_flag_*` callbacks
(`osdi/src/compilation_unit.rs`) — and none of them can jump out of the middle of
an evaluation. The OSDI eval function additionally has a mandatory epilogue that
stores the residual/jacobian outputs the ABI requires. Terminating the MIR
function early therefore stranded things in the predecessor-less block:

* **statement after `$fatal`** — the contribution was lowered into the
  unreachable block yet stayed referenced by the contribution bookkeeping (values
  held *outside* the DFG are not reached by the CFG cleanup), so aggressive dead
  code elimination marked live an instruction that belongs to no block;
* **statement before `$fatal`** — the *epilogue itself* was emitted into the
  unreachable block, where the residual value does not dominate, so codegen read
  an `Undef`.

Notably `$finish` and `$stop` were already lowered correctly as "set the flag and
continue" (`expr.rs`, `BuiltIn::finish` / `BuiltIn::stop`) — no `exit()`, no
unreachable block. `$fatal` was the lone outlier, and in fact the **only**
producer of `Opcode::Exit` in the entire front end.

### A latent soundness bug in the *working* case, too

`InstructionData::Exit` codegens to a bare LLVM `ret` (`mir_llvm/src/builder.rs`).
So even in the *conditional* `$fatal` case — which compiled fine and never
crashed — the eval function returned **before `build_store_results` ran**,
silently skipping the epilogue that the OSDI contract requires to fill the
residual/jacobian/opvar slots. That went unnoticed only because ngspice discards
those slots when the fatal flag is set (`osdiload.c`: `if (eval_flags &
EVAL_RET_FLAG_FATAL) return E_PANIC;`).

The codebase already carried a band-aid for this exact root cause on the *setup*
path — `osdi/src/setup.rs` has a guard commented "Unconditional `$fatal()`
eliminates some values so that the corresponding cache entries are left
undefined". Only the eval path was left unguarded. Removing the `exit()` fixes
the root, so that class is closed rather than patched per-path: after the fix the
"setup MIR value undefined in cache" warning no longer fires on the reproducers,
and no `Opcode::Exit` is produced by the front end at all.

## The fix

Make `$fatal` set its flag and fall through, exactly like `$finish`/`$stop`:
drop the `exit()` and the freshly created unreachable block. The CFG stays
connected, so neither failure mode can arise. One hunk, one file.

## Trigger surface (measured)

Crashes required an **unconditional** `$fatal` *and* a contribution in the module.
A conditional `$fatal` (`if (…) $fatal(0);`) never crashed — the join block is
still reachable through the else path — nor did `$fatal` with no contribution,
nor `$finish`/`$stop` in any position.

## Behaviour is unchanged

`$fatal`'s run-time meaning lives entirely in the `set_ret_flag_fatal` callback,
which this change does not touch. Verified on the existing suites:

* `simctrl_examples` (Enhancement-55) — **all pass**, including "`$fatal` message
  printed", "abort error printed", "transient aborted early", and "parameter-only
  `$fatal`: setup rejected".
* `vafcodegen_examples` (Enhancement-294) — 19/19, including the `$fatal` arm
  guarded by a parameter compare, which still *simulates* correctly (`I = V/1k`).
* A realistic guard (`if (r <= 0) $fatal(...)` followed by a `V/r` divide) still
  aborts cleanly at setup with its message, with no NaN leaking out.

The one semantic difference: statements after a `$fatal` now execute instead of
being dead. This is exactly what `$finish`/`$stop` have always done, and the
simulator aborts as soon as eval returns, so it is not observable — as the guard
test above demonstrates.

## Output preservation

MIR (`--dump-mir`, deterministic — unlike `.osdi` bytes) over the full
462-model corpus: **460 byte-identical**. The two that differ are exactly the
models that use `$fatal` in a reachable analog context —
`examples/simctrl_examples/simctrl_demo.va` and
`examples/vafcodegen_examples/staleuse.va` — and both suites pass in full.
The two `hisim2` industry models also use `$fatal` and are **unchanged**.

## Files

- `OpenVAF-master-20260610/openvaf/hir_lower/src/expr.rs` — `BuiltIn::fatal`.
- `examples/vaffatalcfg_examples/` — the two crash shapes (fail on the pre-fix
  binary) plus a run-time behaviour guard (`verify_vaffatalcfg.py`, 6 checks).
