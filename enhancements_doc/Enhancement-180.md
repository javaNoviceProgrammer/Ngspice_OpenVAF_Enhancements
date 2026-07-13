# Enhancement-180 — checkpoint/restart under KLU (the last Sparse-only feature falls)

Since [E-131](Enhancement-131.md), `savestate`/`loadstate` rejected `.option klu` with a guard, and the solver notes recorded the reason as *"KLU's symbolic/numeric factorization objects are absent on the restore path."* A review question — *why* doesn't it work? — prompted the actual diagnosis: that explanation was wrong, the crash it rationalized was an **option-ordering bug in the checkpoint flow itself**, and fixing it makes checkpoint/restart work under both solvers — and even **across** them.

## The real mechanism

`.option klu` lives in the *task* (`TSKkluMODE`) and is copied into the circuit only inside `CKTdoJob`, at analysis dispatch. But `loadstate` calls `CKTsetup` *directly* — before any dispatch — so the matrix was built with `ckt->CKTkluMODE` still 0: a **Sparse** matrix, `SMPkluMatrix = NULL`, regardless of the deck's option. `loadstate` then drives the continuation through `if_run(ckt, "resume", …)` → `CKTdoJob`, which *now* copies `TSKkluMODE = 1` — but resume deliberately skips re-setup to preserve the restored integration state, so the circuit claims KLU over a Sparse matrix. The first `NIiter` executes `ckt->CKTmatrix->SMPkluMatrix->KLUloadDiagGmin = 1` and dereferences NULL (reproduced: `EXC_BAD_ACCESS` at offset 0x90 in `NIiter`, with the guards removed). `savestate` was never broken at all — its guard was over-broad, since the checkpoint file contains only solver-agnostic state (solution vector, device state history, time/step/order, breakpoints).

## The fix

`com_loadstate` copies the task's solver selection (and the [E-152](Enhancement-152.md) KLU knobs — ordering, scaling, BTF, memgrow) into the circuit *before* calling `CKTsetup`, exactly the block `CKTdoJob` runs. `CKTsetup` then builds the KLU matrix, converts COO→CSC, and binds the devices as in any normal run; the later dispatch copy becomes a no-op. Both guards are removed.

## Cross-solver restore

Because the checkpoint file is solver-agnostic, the fix yields more than parity: a state saved under one solver restores under the other. All four save×load combinations — in **fresh processes** — continue exactly on the uninterrupted run's trajectory (diode + RC transient, compared at t = 3.5 ms of a 4 ms run, ≤1e-9 relative):

| save under | load under | continuation |
|---|---|---|
| Sparse | Sparse | ≡ uninterrupted |
| Sparse | KLU | ≡ uninterrupted |
| KLU | Sparse | ≡ uninterrupted |
| KLU | KLU | ≡ uninterrupted |

With this, **nothing in the simulator remains Sparse-only**: E-172 closed the last analysis (balanced-output pole-zero), E-180 the last feature.

## Verification

[`examples/checkpoint_examples/verify_checkpoint.py`](../examples/checkpoint_examples/verify_checkpoint.py) — the E-131 suite's "KLU rejected" robustness check is replaced by the full solver matrix (4 combos, fresh-process restores, ≡ uninterrupted reference), alongside the existing scenarios (RC step/pulse breakpoints, built-in and OSDI diode, same-session save/load, mismatched-circuit rejection): 22/22. Solver-notes and gap-analysis tables updated (the ⚠️ row was this feature). Full example regression: 148/148.
