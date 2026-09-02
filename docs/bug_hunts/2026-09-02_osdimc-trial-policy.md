# Bug hunt — the `osdimc` trial-policy layer

**Date:** 2026-09-02 · **Commit under test:** `204d6555` · **Binaries:**
`ngspice-46/build/src/ngspice` and `OpenVAF-master-20260610/target/opt/openvaf-r`
as committed.

This is the surface the
[previous hunt](2026-09-02_autobus-autoadapt-osdimc-saveused.md) explicitly
recorded as untested: the E-535–E-538 policy machinery — `osdimc_hold_depth`
nesting, `OSDImcPreserveTrial`, `OSDImcInterruptReset`,
`OSDImcTrialCheckpoint`/`Rewind`, `osdimc_scale_for` — whose source had never
been read. That hunt tested only the *draw engine* and found it excellent.

**Result: one confirmed finding.** The policy layer itself held up under every
structural attack; the finding is at its boundary, in what a *user's own loop*
observes when a trial fails. Method note, learned the hard way last time: the
source was read first this time, and the finding still came from reading it.

`mcpolicy_examples` (34 checks) was green throughout and does not catch it.

---

## M1 — a range-failed trial reports a (parameter, response) pair that never coexisted

**Class:** silent wrong data, in the idiom the handbook documents ·
**Status:** confirmed, reproducible · **Built-in commands are NOT affected**

`osdimc`'s contract says a draw that violates the parameter's Verilog-A range
"fails that run with the device's own located range error", and that the
previous run's result vectors then remain current. Both hold. What is not
handled is that `@card[param]` still reports the **rejected** draw, so a manual
loop pairs a parameter value the circuit refused with the response from the
*previous* trial.

Fixture: `r = 1000 from (900:1100)` with `(* std=100 *)`, so roughly a third of
draws fall outside; a 1 kΩ divider makes the response a closed form,
`vmid = r/(r+1k)`, so every pair can be checked rather than eyeballed:

```
trial  1: r=1000      v=0.5       r/(r+1k)=0.5
trial  2: r=818.129   v=0.5       r/(r+1k)=0.449984   <-- v is trial 1's
trial  3: r=1008.95   v=0.502228  r/(r+1k)=0.502228
trial  4: r=1054.29   v=0.513214  r/(r+1k)=0.513214
trial  5: r=849.235   v=0.513214  r/(r+1k)=0.459236   <-- v is trial 4's
trial  6: r=916.5     v=0.478216  r/(r+1k)=0.478215
trial  7: r=942.379   v=0.485167  r/(r+1k)=0.485167
trial  8: r=822.828   v=0.485167  r/(r+1k)=0.451402   <-- v is trial 7's
```

The three mismatches are exactly the three trials ngspice reported as failed.

**Why it matters.** The vulnerable pattern is the one the handbook gives as
*the* way to use `osdimc`:

```spice
repeat 301
  op                       ; every run-class command = one trial
  print @mm[r] @n1[dr] ...
end
```

And the two streams separate. The warning
`osdimc: trial N FAILED during setup` goes to **stderr**; the data goes to
**stdout**. Verified by splitting them: `ngspice -b deck.cir > data.txt`
captures all ten rows above, including the three false pairs, with **no marker
of any kind** in the captured file.

**What is not affected.** The built-in `montecarlo` handles this correctly and
says so — on the same fixture, 40 samples:

```
  yield  : 100.000%  (28 / 28 pass)
  NOTE   : 12 of 40 samples failed to simulate and are EXCLUDED from the yield above
```

E-537's exclusion fix works. The gap is that a hand-written loop has no
**in-band** way to learn that the trial it just ran was rejected — nothing it
can test between `op` and `print`.

**Shape of a fix** (not implemented — it is a design choice, not a repair):
either make `@card[param]` report the value actually in force after a failed
setup rather than the rejected draw, or expose the failure in-band so a loop
can skip the sample, as `montecarlo` already does internally.

---

## What did not yield a finding

Each of these was attacked and held. Evidence rather than verdicts:

**The HOLD bracket is leak-proof on every path.** All 16 `OSDImcHoldTrial`
sites were read. `loadpull` has no early return in its 236-line bracket span;
`sweep`'s two `goto cleanup` exits both land on a label that releases under an
`mc_held` guard, so a command that never took the bracket cannot pop another's;
`wcd` releases on each of its eight error paths. Even `wcd`'s *refusal* path
("the deck draws no Gaussian .params") consumed exactly one trial and left no
hold behind — probed as 1000 → 1000.25 → 1015.74 across it.

**No sigma-inflation leak.** Draws before and after a `highsigma 30 -scale 4`
both show the declared σ=25 spread, not σ=100.

**The E-538 `-inflate` scope cannot silently scope a later command.**
`OSDImcInterruptReset` does *not* clear `osdimc_scope` — E-538 added the scope
after E-536 wrote that reset — but it is inert: the reset sets `osdimc_scale`
back to 1.0, and `osdimc_scale_for()` returns early on `scale == 1.0`, while
`highsigma` clears the scope at entry (`com_sweep.c:3983`) before parsing its
own specs. Worth knowing as defence-in-depth rather than a defect.

**The trial sequence advances past a failed trial** rather than stalling or
retrying it — trials 2, 5 and 8 failed and 3, 4, 6, 7, 9, 10 drew normally.

**The E-533 sweep→`.dc` handover consumes trials identically to the per-point
loop.** This is an interaction between two features and was not pinned
anywhere. Same deck, same seed: both engines report `1000` before, `1000.25` at
every one of four points (one held sample), and `1015.74` on the next run. The
E-495 refusal fallback also consumed exactly one trial.

**Two model cards of one type draw independently** — per-card process
variation, `rA` and `rB` uncorrelated and both moving.

**OSDI model-card accessors are case-insensitive**, matching built-ins:
`@Mixed[r]`, `@mixed[r]` and `@MIXED[r]` all return 1000.

---

## Coverage, honestly

Better than last time, but bounded in ways worth naming:

| not exercised | why |
|---|---|
| **Ctrl-C interrupt paths** (`OSDImcInterruptReset`) | cannot be driven from a batch deck; the reset was read and reasoned about, not run |
| **`OSDImcTrialCheckpoint`/`Rewind`** | read only. `mcpolicy` covers `optimize -center` and I did not re-derive it independently |
| **the `pinned` mechanism** | exercised only indirectly, through the sweep/`.dc` statistical-knob paths the suite already pins |
| **`loadpull` holding one sample** | bracket span read and found clean; not run end-to-end |

The honest summary: **the policy state machine survived every structural attack
I could construct — its brackets, counters, leaks and engine interactions are
sound.** The one finding sits where the machinery hands off to the user: a
failed trial is announced on a stream the documented idiom does not capture,
and the parameter accessor keeps reporting a value the circuit rejected.
