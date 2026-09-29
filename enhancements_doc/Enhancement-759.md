# Enhancement-759: `@(cross)` and `@(above)` land the timestep on their crossing — the crossing was resolved to the step grid (a compiled switch closed 31 ns late at a 100 ns step, the same as a plain `if`, and `time_tol` was ignored); the body now runs at the crossing within a thousandth of the step, or within `time_tol`, a 500 MHz drive counts exactly, and a `$discontinuity` in the body restarts the integration after the event instead of redoing the approach

**Scope:** F2 of the 2026-09-28 speed, robustness and correctness hunt. Both trees.
Compiler: `hir_lower/src/stmt.rs` (`event_prev_sample`, `event_landing_context`,
`event_landing_record`, `localise_crossing`, `cross_edge`, `lower_cross`, `lower_above`)
and `hir_lower/src/lib.rs` (`HirInterner::event_attempt_flags`, three state slots shared
by a module's events). ngspice: `osdi/osdiaccept.c` (the accepted-point counter behind
the new `$osdi$point` simparam), `osdi/osdiload.c` (serves it), `osdi/osdidefs.h`,
`osdi/osditrunc.c` (the landing request: it replaces the step's truncation estimate and
forces the rejection; E-55's cut on a landing is the step after), `spicelib/analysis/
dctran.c` (`CKTforceReject`, `CKTlanding`: a converged landing is accepted whatever the
estimate says, the step after it floored at an eighth, a forced rejection does not feed
E-128's order bucket) and `include/ngspice/cktdefs.h`. Found on the way, in the
compiler's `mir/src/serialize.rs`: `--dump-json` wrote a non-finite float constant as a
bare `inf`, and every module with an event now has one (the bound-step slot's initial
value), so the `hunt13slips` dump stopped parsing; it is the JSON string `"inf"` now.

**Suites:** `evtedge` 24 of 24 per solver (18 of 24 on the E-757 toolchain: the new
section [9]), `simctrl` (check 6 rewritten for the landing: 4 checks), `constfold` (the
`d=-1` against `d=0` announcement check compares rows instead of assuming 132),
`idtassert`, `discontinuity`, `finalstep`, `lrmevents`, `eventcond`, `opargs`,
`varinit`, `multianalog`, `deckdomain`, `hiername`, `intstate`, `lrmcorner`,
`lrmkernel`, `domainrt`, `analoginit`, `defaulttransition`, `evtnoise`, `rtdomain`,
`cardbound` and `sweepbounds` unchanged; `hunt13slips` 9 of 9 (check [9] holds the
`"inf"` spelling); the full sweep 534 of 534.

## What was wrong

A compiled switch driven by a 0→1 V ramp over 1 µs (threshold 0.5 V, the crossing at
exactly 500 ns) with `@(cross(V(c) - vth, 0))` in its analog block, at a 100 ns step:
the output's own crossing came 31.2 ns late on the rise, the same as a model with no
event at all and as the built-in `sw`, with the same 62 timepoints and no rejected
point. `time_tol` changed nothing. LRM 5.10.3: the simulator shall place a timepoint at
the crossing, within `time_tol` when it is given. E-587's rule detects the edge between
consecutive evaluations, which is what makes the body run at all, but nothing told the
integrator where the crossing was; `osdi/osditrunc.c` acted on `$discontinuity` (E-55's
cut to an eighth, E-24's no-growth sentinel) and on `$bound_step`, and a modeller who
wanted the timing had to write `$discontinuity(0)` into the body (1.2 ns at a 100 ns
step, three rejected points) or `$bound_step(1n)` (0.1 ns at 30× the points).

Under a 500 MHz pulse drive over 2 µs the counters read 1001 rising, 1001 falling, 2002
either for 1000/1000/2000 crossings: every crossing's step was rejected by the
truncation error the switching brought, the retry landed short of it, and E-587's
evaluation-to-evaluation edge saw the expression walk back across the threshold on the
way (a phantom edge in the other direction, counted by the `-1` and `0` events).

## The protocol

Landing needs the model, which knows where its crossing is, and the integrator, which
places the points, to agree on which evaluations belong to which attempt.

- ngspice counts accepted points (`OSDIaccept`, one count per new `(time, mode)`) and
  serves the count as the simparam `$osdi$point`. From it and `$abstime` the compiled
  event tells a NEW POINT (the count moved), a RETRY (the time moved, the count did not:
  the last attempt was rejected) and the later iterates of the same attempt apart. A
  simulator that does not serve the count leaves the events exactly as E-587 built them.
- Every `cross`/`above` keeps, beside E-587's previous-evaluation sample, the sample at
  the last ACCEPTED point. When the crossing lies between that sample and the current
  iterate, the offset `delta · acc / (acc − cur)` from the accepted point is where it
  sits, and the event asks to land there plus a margin (`time_tol` when given, else a
  thousandth of the step, never below a billionth) by writing `−(2 + t)` into the
  bound-step slot, a value no bound can take (a bound is positive, E-24's sentinel is
  −1). The earliest of several requests in one evaluation wins. No request when the
  overshoot is within half the margin (the point is close enough already) or when
  `|cur|` is within `expr_tol`.
- `OSDItrunc` turns the request into the step of the attempt — replacing the truncation
  estimate, which at a crossing measures the discontinuity the switching brings, not the
  smooth interval before it (honouring a smaller cut would put a point short of the
  crossing and approach it again: two rejected points per crossing instead of one) —
  and sets `CKTforceReject`; `dctran` rejects the attempt even when the landing lies in
  the last tenth of the step (its 0.9 rule) and marks the retry as the landing.
- The landing attempt is ACCEPTED once converged, whatever the truncation estimate says
  of it (`CKTlanding`), for the same reason; the step after it follows the estimate,
  floored at an eighth. A forced rejection does not count toward E-128's order bucket.
- ngspice starts a redone attempt's Newton iteration from the REJECTED attempt's
  solution, so a retry's first iterate sees the expression past the crossing that made it
  ask, whatever the new time is. That iterate neither fires nor requests, and the next
  iterate is compared against the accepted sample — so the edge reappears at the landing,
  where the body belongs (`$abstime` is the crossing's, `$strobe` and `$finish` land with
  an accepted point), and a retry that landed short sees no phantom edge back.

## The rules

With the attempt structure known, the body's rule is E-587's edge with these additions
in a transient where the count is served:

- an iterate that asks for a landing does not fire; the attempt is about to be redone;
- a landing attempt may ask ONCE more when it still overshoots by more than the margin
  its request used: the linear interpolation over a curved expression (a sine over a
  60 ns step) lands 0.2 ns past the crossing, the second, over the short interval,
  within the margin (0.04 ns; within `time_tol` when given). The refinement's landing
  asks nothing further. An exact landing is not refined: it is judged against the
  margin the request used, not the shorter one the landing step would give;
- the module's ATTEMPT FLAGS, three state slots shared by all its events and stamped
  with the attempt's time: once any body has fired in an attempt no event asks for a
  landing until the attempt is over — an interpolation over an attempt whose bodies
  changed the model (a reset that drops the expression through a second threshold at the
  same instant, the `idtassert` relaxation oscillator) locates nothing, and that
  crossing fires as E-587 did; and once any event has asked, no later body fires in the
  attempt, which is being discarded;
- a request ngspice DECLINED (the landing would sit under E-504's step floor, or the
  step is already at its minimum) has passed the crossing without the body: it runs at
  the next point's first iterate, on the accepted solution;
- a landing that fell SHORT of its crossing (an exponential reset is not linear over the
  step) is not chased: the next attempt asks nothing and the crossing fires where it
  appears.

The operating point, dc sweeps and `above`'s initialization event are untouched.

## What `$discontinuity` in the body does now

E-55 cut the step to an eighth when the flag was new at a converged point, so the
integrator rejected the event's step and bisected onto it; that is what a landing does
better. On a landing attempt the eighth is no longer a rejection (the landing is accepted)
but the step AFTER the event: the restart the announcement asks for. The `simctrl` twins
show it: with and without `$discontinuity(0)` the event point sits at 833.37 ns for a
crossing at 833.33 ns (a 60 ns step); with it the next step is 4.6 ns, without 60 ns.
Before this change the twins differed in where the event point sat (the announced one
36.75 ns before the other) and the un-announced one sat on the grid.

## Measured

The hunt's table, on this build against the E-757 toolchain (the crossing error is the
first output point on the new side; the ramp is linear, so the landing is the margin):

| model | tstep | rise / fall error before | after | points, rejected |
|---|---|---|---|---|
| `@(cross(..., 0))` | 100 n | 31.2 / 0.0 ns | 0.04 / 0.00 ns | 64, 1 (62, 0) |
| `@(cross(..., 0))` | 10 n | 2.8 / 5.0 ns | 0.01 / 0.01 ns | 211, 2 (211, 0) |
| `@(cross(..., 0, 1p))` | 100 n | 31.2 / 0.0 ns | 0.001 / 0.000 ns | 64, 1 |
| plain `if`, built-in `sw` | 100 n | 31.2 / 0.0 ns | unchanged | 62, 0 |
| `@(cross(...)) $discontinuity(0);` | 100 n | 6.2 / 0.0 ns | 0.04 / 0.04 ns | 75, 3 (68, 3) |
| `$bound_step(1n)` | 100 n | 0.6 / 0.5 ns | unchanged | 2007, 0 |

The bodies' `$abstime` reads 500.04 ns and 1500.00 ns for crossings at 500 and 1500 ns,
and with `time_tol = 1p` 500.001 ns. A body's `$strobe` prints once per crossing with
that time. The 500 MHz pulse drive at a 1 ns step over 2 µs counts 1000/1000/2000
(30 005 points, 3167 rejected, 68 342 iterations; the old toolchain 1001/1001/2002 over
29 839 points, 4002 rejected, 69 682 iterations); at a 0.1 ns step 39 005 points, 4000
rejected and 88 008 iterations against 41 008, 4002 and 84 016 — the same work, one
forced landing and one truncation rejection per crossing instead of the one truncation
rejection that used to miss it. A sine through 0.5 V (`firewhen`) fires at 83.39 ns for a
crossing at 83.33 ns, after one refinement.

## Limits

- What a body changed in a rejected attempt persists (E-678's note): the landing rule
  removes the common source of such rejections, but a landing rejected for
  non-convergence, or by another instance's earlier request, leaves the body's variables
  as it set them.
- Two instances whose crossings fall in one step, one of which needs no landing (its
  overshoot within half the margin), can run the other's body twice — once in the
  attempt the first one's request discards, once at the real crossing. Rare (one crossing
  in two thousand at random phase) and noted rather than fixed.
- An event inside a conditional that is not reached on every evaluation keeps stale
  attempt bookkeeping for the evaluations it missed, as E-587's previous sample already
  did; the rule degrades to E-587's.
- E-504's floor (the span over 10⁶) declines a landing closer than that to the last
  accepted point; the body then runs at the next point.
- The new compiler on an ngspice that does not serve `$osdi$point` makes no requests.
- The crossing itself is still found by linear interpolation, refined once; an
  expression with two crossings in one step is seen as none or one, as before.
