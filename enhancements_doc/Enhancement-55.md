# Enhancement-55 — simulation-control tasks + `$discontinuity` rejection

This document describes the changes made to **OpenVAF-r** and **ngspice-46**
in the `version11/` directory for the remaining simulator-behavior audit
items: the simulation-control system tasks (`$finish`, `$stop`, `$fatal`),
the `$discontinuity` eval-return-flag path, and two documented decisions
(`Opcode::Exit`, `is_voltage_src`).

## What the probe found

| task | before E-55 |
|---|---|
| `$finish` in tran | **ignored entirely** (ran to tstop; the FINISH return flag was never checked in the load path) |
| `$stop` in tran | **timestep collapse**: `E_PAUSE` returned mid-Newton-iteration was treated as a step failure → rejection loop |
| `$fatal` under an op-dependent condition | **silently deleted at compile time** (never fired at all) |
| `$fatal`'s `E_PANIC` | swallowed by the transient's nonconvergence retry (step ground down) |
| `$discontinuity(n>=0)` | E-24's sentinel clamps the NEXT step only; the event step itself extrapolates across the jump |

## The fixes

### 1. Deferred `$finish`/`$stop` (ngspice)

Acting mid-Newton-iteration is what broke `$stop` — the correct point is the
**accepted-point boundary**. `OsdiExtraInstData` gains `point_eval_flags`:
the eval-return flags OR-ed over **all** Newton iterations of the current
timepoint attempt (an event may fire on an intermediate iteration only;
`eval_flags` holds just the last eval's). Reset on
`MODEINITJCT|MODEINITPRED|MODEINITTRAN` — a rejected attempt's requests are
discarded with it. A new `OSDIpendingRequests(ckt)` (declared in
`osdiitf.h`, codes `OSDI_REQ_FINISH/STOP`) reports them; the mid-NR
`return E_PAUSE` on STOP is removed.

- `dctran.c`: once a point is accepted and output, FINISH → Note, fire
  `@(final_step)` (LRM: `$finish` completes the analysis — E-53 synergy),
  end the plot, return OK; STOP → Note, `E_PAUSE` (resumable).
- `dctrcurv.c`: same per accepted sweep point (FINISH exits through the
  normal restore/endplot path via an `osdi_finish` label).

### 2. `$fatal` fixes

**(a) Compile-time silent deletion.** `$fatal`'s lowering emits a Fatal
print + `SetRetFlag(Abort)` + `exit`. Neither call takes an op-dependent
argument, so the init/eval split classified them op-independent and hoisted
them to instance-init — where the op-dependent branch is rewritten to its
else edge, leaving them in an unreachable block: deleted from **both**
functions. The taint propagation *should* have control-tainted the branch
arm, but the shared post-dominator tree roots at the `exit` **sink**
(`ipdom(branch) = the exit arm itself`), so `taint_block(arm, end=arm)`
inserted nothing — and `compute_postdom_frontiers` walks up to the same
bogus ipdom, so the frontier row was empty too. Rather than re-rooting the
shared pdom machinery (consumed by ADCE, the topology pass, …), the fix in
`context.rs::refresh_op_dependent_insts` computes the needed control
dependence directly: for every op-dependent branch, blocks reachable from
exactly **one** of its two arms are controlled by it (exact for the
structured CFGs the lowering emits — and always exact for early-exit arms,
which never reconverge). Side-effecting callbacks (`SetRetFlag`, prints) in
op-controlled blocks are marked op-dependent and stay in eval.
Parameter-only `$fatal` still hoists to init and **validates at setup**
(instance rejected), as designed.

**(b) `E_PANIC` swallowed.** `NIiter` propagates the load's `E_PANIC`, but
`dctran`'s `if (converged != 0)` treated it as nonconvergence and retried
with a smaller step. An explicit check now aborts the transient with a
clear error. (`dctrcurv`/`dcop` already propagate errors out.)

### 3. `$discontinuity(n>=0)` step rejection

The lowering additionally raises a new return flag
(`RetFlag::Discont` → stdlib `set_ret_flag_discont` →
`EVAL_RET_FLAG_DISCONT = 16`, **additive — not an OSDI ABI break**; both
`osdi_0_4.h` and ngspice's `osdi.h` define it). `OSDItrunc` checks the
converged attempt's `point_eval_flags`, **edge-triggered and once per
onset**: only when the flag is NEW versus the last *accepted* point
(`prev_point_eval_flags`, latched in `OSDIaccept`) and the per-point retry
latch is clear (and `CKTdelta > 20*CKTdelmin`) does it request `CKTdelta/8`
— the integrator **rejects the too-large event step and retries**. The
edge/one-shot condition matters: a model announcing a discontinuity over a
whole REGION (every eval while a condition holds — the E-24 example does
exactly this) must not have every step of the region rejected down to the
delta floor (the first cut of this fix, without the latch, made the E-24
regression suite crawl indefinitely). The E-24 sentinel (clamp the *next*
step) is kept unchanged.

### 4. Documented decisions

- **`Opcode::Exit => todo!()`** in `mir_llvm/builder.rs` was dead code, not
  a missing feature: `InstructionData::Exit` is intercepted by
  `build_inst`'s instruction-data match (which emits the function's `ret`)
  before the value-producing opcode dispatch can see it. Replaced with
  `unreachable!` and a comment.
- **`is_voltage_src` OSDI exposure** (the dae-builder TODO for switch
  branches): the static metadata is already correct (`Switch` residuals emit
  `NATREF_NONE`), ngspice derives nothing from residual natures at runtime,
  and no OSDI consumer exists for a per-iteration switch-state export.
  Deferred until a consumer exists — an eval-output + descriptor array would
  be an ABI change with zero users today.

## What now works (`simctrl_examples/`, 17 checks)

See the README: `$finish` ends the transient exactly at the requesting
point with `@(final_step)` firing there; `$stop` pauses cleanly; `$fatal`
prints and aborts (tran) or rejects the instance at setup (parameter
validation); a DC-sweep `$finish` ends the sweep at the requesting value;
and the `$discontinuity` A/B twins show the event step ≥ 4× smaller with a
sharper, no-later jump.

`verify_simctrl.py`: 17/17 PASS. Regression: all 51 example verify suites
ALL PASS; 28/28 crate tests.

## Notes

- Requests latch per instance; any OSDI instance requesting FINISH/STOP is
  honored (multiple instances OR together).
- `$finish` in a lone `.op` has nothing to cut short (the analysis is one
  point); it completes normally. `$stop` there is likewise a no-op.
- With `autostop` semantics unchanged; `$finish` takes the same clean exit
  path as reaching the stop time.
- The env-gated `OPENVAF_TAINT_DEBUG=1` dump (op-dependence statistics at
  the init/eval split) was kept from the investigation.
