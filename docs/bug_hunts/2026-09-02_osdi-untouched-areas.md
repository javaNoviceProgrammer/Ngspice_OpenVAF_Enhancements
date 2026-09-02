# Bug hunt — the areas the general hunt left untouched

**Date:** 2026-09-02 · **Commit under test:** `3d496817` · **Binaries:**
`ngspice-46/build/src/ngspice` and `OpenVAF-master-20260610/target/opt/openvaf-r`
as committed.

The [general hunt](2026-09-02_ngspice-osdi-general.md) went deep on one seam and
listed what it had not looked at: parameter and `alter`/`altermod` paths, node
collapse, temperature, AC and noise, `$limit`, `absdelay`/`last_crossing`,
terminal currents, the solver layer. This hunt goes there.

**Result: one finding, of a defect class the project has already named.** It is
recorded with that prior art rather than as a discovery.

---

## P1 — a refused parameter write leaves the rejected value in the accessor

**Class:** stale reported state · **Status:** confirmed · **Severity:** low-to-
moderate — the physics stays correct and the refusal is printed on **stdout**

When a parameter write — `alter`, `altermod`, or a `.dc` sweep point — gives an
OSDI parameter a value the model's `from` range forbids, the device correctly
refuses it and keeps the accepted value. The **accessor keeps reporting the
rejected one**, indefinitely, until the next valid write.

Fixture: `parameter real r = 1000 from (0:inf)` and
`(* type="instance" *) parameter real rs = 0 from [0:inf)`, in a 1 kΩ divider
so the physics is a closed form.

```
P0                      rs=0    v=0.5      <- 1000/(1000+1000), correct
alter @n1[rs]=-5        ->  "Parameter rs ... is out of bounds (value -5)!"
P1_after_refused_alter  rs=-5   v=0.5      <- accessor rejected value, physics still rs=0
P2_after_refused_dc     rs=-5   v=0.5      <- persists
```

The same holds for a model parameter via `altermod`: `@m[r]` reports `-1` while
`v(mid)` stays at `0.5`, i.e. the device is still using `r=1000`. A later valid
write recovers cleanly — `altermod m r=3000` reports `3000` and moves the answer
to `0.75`, exactly `3000/4000`.

**Prior art, which matters here.**
[Enhancement-427](../../enhancements_doc/Enhancement-427.md) already named this
class: *"leaving the instance holding the rejected value is the
E-381/E-382/E-385 state-restoration class of defect"*, and its own text observes
that after a refused value `print @n1[r]` "shows it back". E-427 fixed the
**`.dc` sweep** path so that a device refusal reaches the sweep loop and aborts
it — a different thing from what the accessor reports afterwards.

**The accessor is left holding a rejected value on both paths.** From a clean
start (`rs=0`), `dc @n1[rs] -500 -100 200` leaves the accessor reading `-500`,
with or without an intervening `op`, while the physics stays at `rs=0`
(`v=0.5`). So this is not specific to `alter` — it is how the OSDI parameter
store behaves after any refused write.

A first draft of this section claimed the `.dc` restore "does work" because one
deck read back `-5` rather than `-500`. That was a misreading: in that deck an
earlier `alter` had already left `-5` behind, so the sweep merely restored one
stale value over another. Re-run from a clean start, `.dc` leaves `-500`. The
claim was corrected before this document was committed.

**Why it is not higher severity.** The refusal is loud and, unlike the
[osdimc equivalent](2026-09-02_osdimc-trial-policy.md#m1), it reaches
**stdout** — a pipeline capturing data also captures the complaint. The
simulation never uses the rejected value. The exposure is a script that logs
`@dev[param]` alongside results and records a number the run did not use.

---

## What did not yield a finding

**The init/eval split, swept more widely.** [Enhancement-540](../../enhancements_doc/Enhancement-540.md)
came from that boundary, so it was worth asking what else crosses it. Eight
constructs were run in the analog body reading a value set in `@(initial_step)`
— plain assignment, `$limit`, `$bound_step`, `absdelay`, `last_crossing`,
`ddt`, `$discontinuity` — and every one exits 0 **and** lands on the correct
`0.3333333333` (= 500/1500 for the fixture's conductance). No further instance
of the E-540 class.

**The E-540 bug class is contained.** Its cause was a protocol whose dependency
lived in runtime globals rather than MIR values. Every other mutable global in
`stdlib.c` was enumerated — the file tables, the multichannel tables, the
written-name list, the deferred-write buffer — and each is **keyed by a
descriptor that flows through the IR**, so the calls that touch them are tied
together by real dataflow. The scan cursor was the only unkeyed one.

**File-operation ordering survives the split.** Tested directly rather than
assumed: a `$fdisplay` with an eval-dependent argument next to an `$fclose`
whose argument is init-computable. A hoisted close would have truncated the
write; the file contains `V=0.5`.

**OSDI parameter range enforcement is clean.** Out-of-range values on a model
parameter, an instance parameter, an integer parameter, and exactly on an open
bound are each refused with the device's own located error, no crash, and the
session survives.

---

## Coverage, honestly

* This hour was spent on **parameter paths** and on re-testing the **init/eval
  boundary** more widely. Of the areas the previous hunt listed as untouched,
  **node collapse, temperature, AC and noise, terminal currents and the solver
  layer remain untouched** — they were named again here and again not examined.
* P1 is **not a new discovery**. The project had already named the defect class
  and fixed one of its paths; this records that a second path still shows it.
  Stating that is the point — the alternative is a write-up that reads as a
  finding and is really a re-finding, which this project has been burned by
  before.
* One self-inflicted error worth recording: an early instance-parameter probe
  reported `v=0`, which looked like a defect. The deck was missing its title
  line, so SPICE consumed `v1 1 0 dc 1` as the title and the circuit had no
  source. Caught and redone before it reached a conclusion.
