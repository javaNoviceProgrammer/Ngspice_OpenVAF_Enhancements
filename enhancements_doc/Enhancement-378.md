# Enhancement-378 — a Verilog-A `$fatal` now aborts the operating point

`CKTop` reads any non-zero return from `NIiter` as "did not converge", and answers
it by working through its ladder of convergence aids: gmin stepping, source
stepping, pseudo-transient continuation, optran. A Verilog-A fatal comes back
through that same channel as `E_PANIC`, so the operating-point solver could not
tell *"this model refuses to evaluate"* from *"this circuit is hard to solve"* —
and responded to a fatal by trying harder.

## What that looked like

Every aid re-evaluates every device, so the model re-raised the same fatal on each
pass. Measured before the fix, for a model with one unknown `$simparam` name:

| devices | fatal messages |
| --- | --- |
| 1 | 373 |
| 2 | 746 |
| 3 | 1119 |

Exactly 373 × N — one message per device evaluation, and 373 is how many
evaluations the whole ladder performs before giving up.

The damaging part is not the volume. The run ended with:

```
Note: Starting dynamic gmin stepping
Note: Starting true gmin stepping
Note: Starting source stepping
Error: Transient op failed, timestep too small
```

The verdict names **convergence**. Someone whose model has a typo'd `$simparam`
name is told their circuit will not converge, and the actual cause is buried
several hundred lines up.

## The same guard already existed, in the other path

[Enhancement-55](Enhancement-55.md) added exactly this check to the transient
time-stepping loop in `dctran.c`:

```c
/* Enhancement-55: a Verilog-A $fatal raised E_PANIC from the
   device load. That is an ABORT, not a convergence failure --
   without this check the error was swallowed by the retry
   logic below (timestep ground down, $fatal ignored). */
```

The operating-point path never got the same treatment. Counting the guards before
this change: `dctran.c` 2, `cktop.c` **0**. And a `.tran` is affected too, since a
transient computes its operating point first — which is why the transient case
still emitted 44 messages despite E-55's guard: it never reached the time-stepping
loop where that guard lives.

## The fix

`CKTop` now tests for `E_PANIC` after the plain Newton solve **and after each
aid**, and takes an abort arm that reports the real cause:

```
Error: a Verilog-A device raised $fatal during the operating point; aborting.
       This is not a convergence failure -- see the OSDI(fatal) message above
       for the cause.
```

The test is exact rather than a heuristic: `E_PANIC` is `1` and the
non-convergence code `E_ITERLIM` is `E_PRIVATE+3` = `103`. They are distinct
values, so the check cannot mistake a stalled Newton solve for a fatal. The guard
is repeated after each aid because a model may only fatal at a bias that a later
aid happens to reach.

Result:

| | before | after |
| --- | --- | --- |
| `$fatal` in an `.op` | 380 messages, "timestep too small" | 1 message, "aborting" |
| unknown `$simparam` | 373 messages, "timestep too small" | 1 message, "aborting" |
| `$fatal` through `.tran` | 44 messages, "timestep too small" | 1 message, "aborting" |

## Verification

`examples/opfatal_examples` — 8 checks.

```
   fixed:     8/8
   pre-fix:   2/8
```

The two that pass pre-fix are the **accept** checks, and that is the point of
including them: a guard that aborted too eagerly would break every circuit that
legitimately needs a convergence aid. They assert that an ordinary circuit still
solves, and that a circuit forced onto the aids with `.options noopiter` still
converges through gmin stepping. Both pass on either binary, so they are proof the
ladder is intact rather than padding.

Regression 302/302 → 303/303.
