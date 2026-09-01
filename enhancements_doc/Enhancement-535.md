# Enhancement-535: the osdimc trial policy for loop commands — and the hunt round that made it honest

**Scope:** `.option osdimc` (E-530/531) draws a fresh Monte-Carlo trial for
every run-class command — right for a lone `op`, wrong at both ends of the
loop-command spectrum. This enhancement gives the loop commands a policy
(**HOLD** one sample per `sweep`/`optimize`/`wcd`/`loadpull`, **PRESERVE**
the sequence across a command's own internal resets, **SCALE** sigmas for
`highsigma`), then a one-hour adversarial hunt over the first cut produced
seventeen findings — and this release ships the policy **with the five
correctness fixes the hunt proved necessary**, the display/monitor repairs,
a nested-`.dc` same-knob guard, and an honest known-open ledger for the
rest. Everything is pinned by a new 12-check suite whose expectations are
closed-form functions of the run's own parameter readbacks.

**Suites:** [`examples/mcpolicy_examples/`](../examples/mcpolicy_examples/)
(new, 12 checks, both solvers, two fixture models — one with statistics used
directly in eval, one whose statistic feeds *only* a hoisted init-resident
assignment). `osdimc` **29/29**, `montecarlo`, `highsigma`, `wcd`,
`optimize` **43/43**, `sweepdc` **17/17**, `dcxsweep` **20/20** all green,
both solvers; full sweep ALL OK.

## The policy: three levers on the trial counter

The measured failures that motivated it: a swept "curve" under osdimc was
**N different samples stitched together** (each per-point analysis advanced
the trial); `optimize` fit a **stochastic objective** — measured "converged"
2.4 % off a closed-form optimum, reported with full confidence; and
`montecarlo`, the one command that *wants* a fresh draw per sample, got
**none** — its per-sample internal reset restarted the counter, so every
sample recomputed the nominal baseline.

* **HOLD** (`OSDImcHoldTrial`): a deterministic loop command brackets its
  inner analyses; the whole loop consumes exactly ONE trial. The first held
  run advances the counter, every later one re-applies the same trial's
  draws — they are pure functions of `(mcseed, trial, owner name, id)`, so
  they survive even an internal re-source that handed the devices their
  nominals back.
* **PRESERVE** (`OSDImcPreserveTrial`): an INTERNAL reset — the machinery
  `montecarlo`/`highsigma`/`wcd` use to redraw netlist `.param` randoms, and
  `sweep` uses for a `.param` knob — keeps the trial sequence running, where
  a USER `reset` or re-source still restarts it at the baseline.
* **SCALE** (`OSDImcSigmaScale`): `highsigma -scale` could inflate only the
  netlist `.param` sigmas it owns; attribute-declared `(* std *)` sigmas
  were un-inflatable. The factor now multiplies every drawn sigma (gaussian
  and uniform half-width alike) for the sampling window.

## The headline fix: draws landed after the physics was already computed

The first cut applied a preserved trial's draws at the **end of
`OSDItemp`** — after every `setup_instance` had already cached its
parameter-dependent intermediates from the *nominals*. For a parameter that
feeds only init-resident (hoisted) code — `geff = 1/rr; I <+ geff*V(a,b);` —
the draw was visible in storage and invisible in the physics: `op;op;op`
varied the node voltage, but **every `montecarlo` sample computed the exact
nominal** while `osdimc_verbose` logged distinct draws per trial
(measured: 5/5 threshold violations where the drawn samples give 3 — the
log said the samples differed; the answers said they were all the same
circuit). Worse than the all-nominal bug it replaced, because now the
*report* looked right.

The fix moves the application to the **end of `OSDIsetup`**: its own setup
loops have just resolved the deck-default nominals (the reason capture
cannot happen earlier), and `CKTtemp`/`OSDItemp` — where the hoisted code
runs — comes after in every job. `OSDImcNewRun` flags the trial *pending*
when the table is empty at run start (the signature of an internal
re-source); `OSDIsetup` captures, applies, and the init-resident code then
evaluates the drawn values. Node collapse is still decided on nominals; if
a draw moves it, `OSDItemp` re-decides and the E-417/E-495 machinery warns
or refuses, exactly as for any other between-setups parameter change.

## Machine writes now pin their parameter

The same late-apply ran on **every** `OSDItemp` — and `OSDItemp` runs per
point of a `.dc` parameter sweep and after every `sens` perturbation. Under
any drawn trial, the re-apply overwrote the machine's write with
nominal+delta: `dc @n1[dr] 0 1000 500` returned **one point three times**
(measured flat at 0.49596 where the curve runs 0.50→0.33), `sweep @n1[dr]`
likewise, and `sens` reported **~1e-14** for every statistical parameter
where −2.5e-4 was the closed-form answer. The held re-apply in
`OSDImcNewRun` did the same to the `sweep` command's per-point pushes.

E-531 established that machine writes must never *recenter* a nominal; the
complementary rule was missing: they must **win over the draw**. Every
successful `OSDIparam`/`OSDImParam` store now pins the parameter's osdimc
entry; the draw applier skips pinned entries; pins clear at every
loop-command bracket edge and at every un-held run — so a fresh standalone
trial still redraws everything, and `alter`-recentering lands on the very
next run exactly as check 19 of the osdimc suite pins. The pinned curves
are verified against `1k/(r+dr+1k)` computed from the same run's `@mm[r]`
readback — no magic values, and the swept point wins at *every* point,
first included.

## The baseline is explicit now

"Trial 1 never draws" was enforced by an accident: the apply loop found an
empty table on the first run. Two ordinary flows defeat that — an
`optimize` whose resets park the counter while `OSDItemp` keeps capturing,
and a plain `unset osdimc` / `set osdimc` toggle (the disable path zeroes
the trial but keeps the table) — and both then **drew on the run every
contract calls the nominal baseline**, `osdimc: trial 1:` lines and all. A
`trial < 2` guard in `OSDImcNewRun` replaces the accident; the toggle now
gives exact nominals on the re-enabled first run and draws on the second.

## Setup display and `$monitor` history

Two LRM 9.4.6 bookkeeping repairs in the same round:

* **init-resident display printed once per session.** `display_managed`
  latched true at the first Newton iteration and never released, so every
  re-setup's hoisted `$strobe` was deferred and then dropped as a superseded
  iteration. `OSDIsetup` and `OSDItemp` now re-enter setup-phase display —
  the `OSDItemp` half matters because a `.dc temp` sweep re-runs it through
  `CKTtemp` alone: previously the sweep printed the *first* point's strobe,
  dropped points 2..N, and then flushed the end-of-sweep *restore* strobe
  into the output where it read like a sweep point. Now every point prints
  at its own temperature.
* **`$monitor` change-detection compared across runs.** The k-th monitor
  line of a new analysis's first accepted point was suppressed whenever its
  text matched the k-th line of the *previous* run's last flush — a second
  identical `op` printed nothing. The history now resets per ANALYSIS
  (`OSDIsetup`), and deliberately *not* per temperature point, so a
  `.dc temp` sweep keeps its legitimate cross-point suppression.

## A nested `.dc` cannot fight itself over one knob

`dc v1 0 1 0.5 @v1[dc] 0 2 1` — the same knob on both nest levels —
mislabeled the first point (computed with the outer start, labeled with the
inner value) and corrupted the restore (the outer level had captured the
inner's start as its "nominal"). Resolution now refuses the overlap for
every kind pair it can prove: same element for the source/resistor/instance
kinds in any spelling (`v1` versus `@v1[dc]`, `r2` versus
`@r2[resistance]` — the principal-parameter identity is checked against the
device's own parameter table), same element and parameter for the
`@inst[param]` kinds, any shared target between `@`-wildcard lists, and
wildcard-versus-`@inst[param]`. The refusal restores every level already
applied, in reverse order, so the aliased knob lands back on its true
pre-sweep value. Alongside: `lin|dec|oct` point counts are kept apart from
the parsed N (`TRCVnTotal`), so a re-run of a still-loaded dec/oct card no
longer re-derives its multiplier from the previous total — the 5-then-11-
then-23-points self-refining grid is gone. And `evaluate.c` warns, once per
operation, when two genuine multi-element vectors of different lengths meet
in an expression — the silent flat-extension of a truncated import now says
what it is doing.

## Known-open, recorded honestly

The hunt's remaining findings ship as a ledger, not as silence. The
sharpest: **(a)** an interrupt (Ctrl-C) longjmps past every bracket clear,
so `osdimc_hold`, a `highsigma` sigma inflation, and a dangling
preserve flag survive into later commands (an interrupted `highsigma` was
measured continuing its trial sequence *through a user re-source*);
**(b)** `optimize`'s own internal runner lacks the preserve call `sweep`'s
has, so `-center`'s inner Monte-Carlo sees no osdimc variation and a
`-dparam` fit's resets park the counter; **(c)** `highsigma -scale` inflates
the osdimc draws but `mc_sample_weight()` carries no likelihood-ratio term
for them, so P(fail) is estimated under the wrong density when the metric
depends on an OSDI statistical parameter (measured 0.42 reported where the
true value is 0.354 — use netlist `.param` statistics with `-scale` until
the weight channel exists); **(d)** the hold is a flag, not a depth
counter, so a loop command nested as another's `-analysis` releases the
outer bracket (measured: an `optimize` over a swept-curve objective drew a
fresh trial per evaluation); **(e)** the loop commands never poll
`ft_intrpt`, so with `ft_setflag` an interrupt lets the remaining points
march through as insta-aborted analyses stitched into a "successful" plot;
**(f)** a failed resolution of a *later* `.dc` nest level leaves earlier
levels applied (a mistyped second knob left `v1` at the sweep start), and
the reset-path sweep's restore leaves the preserve flag dangling for the
next user reset. Each was reproduced with a minimal deck during the hunt;
none is load-bearing for the shipped policy's documented semantics.
