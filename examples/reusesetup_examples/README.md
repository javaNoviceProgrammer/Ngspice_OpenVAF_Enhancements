# Enhancement-471 — a sweep keeps the circuit standing between points

```
python3 verify_reusesetup.py
```

37 checks, both linear solvers.

## What was wrong

`sweep`, and everything built on it, tore the whole circuit down and built it
again for every point, even though only a parameter **value** had changed.
`.dc` — including the parameter sweeps of Enhancement-427 — has never done
that: it sets up once and walks its points inside the analysis.

The reuse is **on by default**, which is why the guards below carry the weight.

After Enhancement-470 removed the quadratic teardown, what was left of that
per-point rebuild was still most of the run. On a 2448-unknown dielectric
stack, 1001 points:

| | rebuild every point | keep the setup | |
|---|---|---|---|
| SPARSE 1.3 | 7.24 s | **0.57 s** | **12.8×** |
| KLU | 6.35 s | 1.38 s | 4.6× |

Reusing the setup also reuses the matrix ordering, so a solve can land on a
slightly different Newton path — exactly as it can under `.dc`, which has always
reused both. On this deck that happened **only under KLU**, moving one number of
5005 by 4.7e-09 relative, five orders of magnitude inside `reltol`. **Under
SPARSE the results are byte-identical**, all 5005 of them.

> **That measurement holds for this deck, and is not the general bound.** This
> deck's sources register no breakpoints. Where one does — a `PULSE` or `PWL`
> source — reuse left the source's breakpoint cursor holding the previous run's
> value, so it scheduled none at all and the transient answer moved by up to
> 106 %. See [Enhancement-498](../../enhancements_doc/Enhancement-498.md) and
> `examples/reusestate_examples/`.

KLU was the faster solver on this deck before the change (6.35 s against
7.24 s); reuse lets SPARSE skip the `spOrderAndFactor` that Enhancement-470 left
dominating at 51%, so SPARSE is now 2.4× the faster of the two.

## Why it could not simply be done

**Node collapse.** A device may decide, at setup and from its parameters, to
merge two of its nodes, and the matrix is then built for that topology. Reuse
the setup and the topology freezes at whatever the *first* point decided — the
sweep quietly draws the wrong curve.

A first attempt did exactly that. Sweeping `cs_gate`'s `rd`, which collapses
its internal node when `rd == 0`, returned the same number at every point
instead of a falling curve, with no error and no warning. That case is check
`[1]` and it is the reason the rest of the design exists.

Two things make reuse safe:

* An **OSDI** device re-decides its collapse on every `CKTtemp` and compares it
  against the snapshot the matrix was built from (Enhancement-417). Until now
  a mismatch could only be *reported* — *"the matrix was built for the collapse
  decided at setup and cannot be rebuilt here"*. `CKTdoJob` now does what that
  message said was impossible: it notices and rebuilds for real. Collapse is
  therefore always re-decided, never assumed.

* A **built-in** device decides its collapse in `DEVsetup` and nowhere else, so
  there is nothing to re-check afterwards. Rather than guess, reuse was offered
  only to circuits built entirely from device types whose topology is known to be
  fixed — the linear elements and sources, which create their branch equations
  unconditionally — plus OSDI. Anything else kept the old behaviour exactly.
  The list grows as a type is verified, never by assumption.

  [Enhancement-503](../../enhancements_doc/Enhancement-503.md) later narrowed
  that from a per-**type** refusal to a per-**parameter** one: a BJT builds its
  internal nodes from `rc`, `rb`, `re` and `rco` and from nothing else, so a
  sweep of `bf` cannot move its topology. The sweep now declares which
  parameters it varies, and a deck holding a built-in semiconductor reuses its
  setup unless one of those parameters is a node-building one. A caller that
  declares nothing — Monte Carlo, or a `.param` knob — still gets the refusal
  described above.

## A failed point hands nothing on

The regression found this. A point whose analysis **fails** leaves the circuit
in a state nothing downstream can characterise, and reusing it carried the
wreckage forward: `guardgaps` (Enhancement-445) requires a sweep across values a
`from` range forbids to return NaN for the forbidden points **and real values
for the legal ones** — with the first cut of the reuse, all five were NaN.
Reuse is declined after any failed point, which is checks `[10b]`/`[10c]`.

`sweep` also drives whatever `-analysis` names, so `tran`, `ac`, `noise` and
`dc` are each checked identical with the reuse on and off.

## The option

Default on. `.option reusesetup=0` (or `set reusesetup=0`, or
`.option noreusesetup`) turns it off, which makes *"is this difference the
reuse?"* a one-line experiment.

Four options in this codebase — Enhancements 450, 451, 454 and 466 —
shipped with **every off-spelling silently meaning ON**, because the value was
never read. So each spelling is tested rather than trusted: checks `[16]`–`[25]`
run `0`, `false`, `no`, `off`, the `no` prefix, the four on-spellings, and the
`set` form.

## How the suite asserts the mechanism, not a stopwatch

Most checks compare the same deck run with the reuse on and off and require the
two to agree — but a build where the reuse never engaged would pass all of
them. Under `set ngdebug` ngspice reports what it actually did:

```
sweep: setup reused at 3 of 5 points, 1 rebuilt after a node collapse moved
```

so checks `[11]`–`[15]` pin the decision exactly: a sweep whose collapse never
moves keeps every point after the first `(4, 0)`; one whose collapse moves once
rebuilds exactly that point `(3, 1)`; with the reuse off nothing is kept
`(0, 0)`; a circuit holding a **built-in** device reuses `(4, 0)` when the swept
knob cannot build a node and still declines `(0, 0)` when it can (E-503) — none
of which anything but this report can show, since the answer is the same either
way.

The circuits here are far too small for timing to separate the two paths, which
is why no check uses a clock.
