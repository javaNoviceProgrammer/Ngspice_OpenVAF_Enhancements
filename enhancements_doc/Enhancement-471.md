# Enhancement-471 — a repeated analysis keeps the circuit standing

`sweep`, and every command built on it, tore the whole circuit down and built it
again for each point, even though only a parameter *value* had changed. `.dc`
has never done that — including the parameter sweeps of Enhancement-427, it
sets the circuit up once and walks its points inside the analysis.

Enhancement-470 removed the quadratic teardown that dominated that rebuild.
What remained was still most of the run:

| 1001-point sweep, 2448 unknowns | |
|---|---|
| rebuild every point | 6.33 s |
| keep the setup | **1.34 s** |

**4.7×.** One number of 5005 differs, by 4.7e-09 relative: the LU ordering is
reused across points exactly as `.dc` has always reused it, so a solve can land
on a slightly different Newton path. That is five orders of magnitude inside
`reltol`.

## Why this could not simply be done

**Node collapse.** A device may decide, at setup and from its parameters, to
merge two of its nodes; the matrix is then built for that topology. Reuse the
setup and the topology freezes at whatever the first point decided, and the
sweep quietly draws the wrong curve.

A first version of this change did exactly that. `cs_gate` — the model
Enhancement-417 wrote for this — collapses its internal node when `rd == 0`.
Swept across that point it returned:

```
0.5   0.5   0.5   0.5   0.5        <- frozen at the first point's topology
```

where the answer is

```
0.5   0.3333   0.25   0.2   0.1667
```

No error, no warning, a plausible-looking flat line. That version was measured
at 3.5×, confirmed numerically sound on the deck that motivated the work, and
**reverted** — the deck that motivated the work was simply not one where the
collapse moved.

## What makes it safe

Two different answers for two different kinds of device.

**OSDI.** The collapse is already re-decided on every `CKTtemp` and compared
against the snapshot the matrix was built from (Enhancement-417). Until now a
mismatch could only be reported:

> node collapse of model type '%s' changed at %.4g K, but the matrix was built
> for the collapse decided at setup and **cannot be rebuilt here**.

`CKTdoJob` now does exactly what that message said was impossible. On a reused
point it skips the unsetup/setup pair but still runs `CKTtemp` — so the
collapse is *always* re-decided, never assumed — and if any instance reports a
change it throws the reused matrix away and does a genuine
`CKTunsetup`/`CKTsetup`/`CKTtemp`. That is safe by construction rather than by
argument: the fast path is taken only where the topology provably did not move.
While the request is live the warning is suppressed and its once-per-instance
flag is left unburned, because here the rebuild actually happens; a later
temperature sweep with no reuse still gets the message.

**Built-in devices.** These decide their collapse in `DEVsetup` and nowhere
else, so there is nothing to re-check and no honest way to detect a change.
Rather than guess, reuse is offered only to circuits built entirely from device
types whose topology is known to be fixed — resistors, capacitors, inductors,
mutual inductors, the four controlled sources, `ASRC`, and the independent
sources, all of which create their branch equations unconditionally — plus
OSDI. A circuit holding anything else keeps the old behaviour exactly. The list
grows as a type is verified, never by assumption.

## A failed point hands nothing on

The regression found this, not the design. A point whose analysis **fails**
leaves the circuit in a state nothing downstream can characterise — a matrix
factored to NaN, a rejected operating point, states half-written. Reusing it
carried the wreckage into every later point: `examples/guardgaps_examples`
(Enhancement-445) sweeps a parameter across values its `from` range forbids and
requires the three forbidden points to come back NaN **and the two legal ones to
keep real values**. With the first cut of the reuse, all five were NaN, and
under KLU the whole sweep failed.

Reuse is now declined after any point that failed, which confines the damage to
the point that earned it. The sweep already knew — `sw_run_failed()` exists from
Enhancement-438, which counts exactly these points — so the fix was to carry
that answer one iteration forward.

## The pivot order

Reusing the setup also reuses the matrix ordering, which is what Enhancement-439
found to be hazardous in `klu_refactor` — it reused the old pivot order with no
pivoting and no singularity test, and produced a NaN solve where SPARSE
succeeded.

That is not this. `NIiter` already refactors with the existing ordering as its
normal path between Newton iterations, and **both** solvers respond to a
singular refactor by forcing a full reorder (`niiter.c`, the `E_SINGULAR` arms
of the KLU and SPARSE branches). Reuse across sweep points puts the solve on the
same footing `.dc` has always had, with the same fallback, and Enhancement-439's
`klu_rcond` guard still applies.

## The option

Default on. `.option reusesetup=0`, `set reusesetup=0` and
`.option noreusesetup` turn it off, so a user chasing a difference can settle
its cause in one line.

Four options in this codebase — Enhancements 450, 451, 454 and 466 — shipped
with **every off-spelling silently meaning ON**, because the value was never
read. The value is therefore read as a number and a string *before* `CP_BOOL`
(a bare `set` publishes a bool, `=0` a number, `=false` a string, and a
CP_BOOL-first cascade short-circuits on all three), the `no` prefix is honoured,
and each spelling is a check rather than a claim.

## Verification

`examples/reusesetup_examples/verify_reusesetup.py` — **34/34**, both solvers.

Comparing the same deck with the reuse on and off is the strongest assertion
available, but a build where the reuse never engaged would pass every such
check. Under `set ngdebug` ngspice now reports what it did:

```
sweep: setup reused at 3 of 5 points, 1 rebuilt after a node collapse moved
```

which pins the decision exactly: a sweep whose collapse never moves keeps every
point after the first; one whose collapse moves once rebuilds exactly that
point; a sweep whose collapse moves at its *end* is caught too, so the check is
re-armed per point rather than done once; with the reuse off nothing is kept;
and a circuit holding a built-in device declines reuse entirely — which nothing
but this report can show, since the answer is identical either way.

A sweep drives whatever `-analysis` names, and each analysis leaves different
state behind, so `tran`, `ac`, `noise` and `dc` are each checked identical with
the reuse on and off. So is a sweep whose points fail, and its decision count.

The circuits are far too small for timing to separate the two paths, so no
check uses a clock.

Full regression **385/385**, both solvers. ngspice-only.
