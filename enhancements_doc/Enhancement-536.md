# Enhancement-536: the osdimc ledger closed — interrupt safety, nested holds, weighted high-sigma, and the `.dc` restore

**Scope:** E-535 shipped the osdimc loop-command policy with an honest
known-open ledger: nine findings the hunt round had proved but the release
did not fix. This enhancement closes **all nine**, each with the repro deck
that found it now a pinned check. The through-line is state that outlived
its command — a keyboard interrupt that skipped every cleanup path, a hold
that a nested command released early, a preserve flag that dangled into a
user's next `reset`, a `.dc` failure that left earlier levels applied — plus
the one genuinely missing piece of arithmetic: `highsigma -scale` inflated
the OSDI draws without weighting them.

**Suites:** [`examples/mcpolicy_examples/`](../examples/mcpolicy_examples/)
grows from 12 to **18 checks** (both solvers), each new one a former ledger
entry. `osdimc` **29/29**, `optimize` **43/43**, `montecarlo`, `highsigma`,
`wcd`, `sweepdc` **17/17**, `dcxsweep` **20/20**, `sweeptemp` **20/20**,
`nestedsweep` green; full sweep ALL OK. **No openvaf-r change.**

## An interrupt no longer leaves the session poisoned

`ft_sigintr` `LONGJMP`s straight to the prompt. Every loop command's cleanup
— the code that clears the osdimc hold, the sigma inflation, the sampling
mode, `ft_optimizing`, the progress bar — sat *after* the point of no
return, so a Ctrl-C during `sweep`/`optimize`/`wcd`/`highsigma`/`loadpull`
silently corrupted whatever the user did next:

* an interrupted `highsigma -scale 5` left the **inflation armed**: every
  later osdimc draw in the session used 5× sigmas, with nothing on any
  channel to say so;
* a dangling **hold** froze all later runs on one Monte-Carlo sample;
* a dangling **preserve** carried the interrupted run's trial sequence
  through a *user* re-source (measured: a fresh `source` continuing at
  trial 91828);
* `mc_wcd_off()`/`mc_sss_off()` never ran, so the netlist gaussians stayed
  pinned to a chosen u-vector or an inflated density;
* `ft_optimizing` left `TRUE` muted every later analysis banner;
* `aging_internal_reset` left elevated made later **user** `reset`s keep age
  records they must drop;
* a half-drawn progress bar kept the terminal line.

`ft_sigintr_cleanup()` — which already exists for exactly this purpose,
"processing of asynchronous signals which require user process context" —
now resets all of it: `OSDImcInterruptReset()` (hold depth, held-advanced,
preserve, inflation, pins), `mc_wcd_off()`, `mc_sss_off()`,
`ft_optimizing`, `aging_internal_reset`, and a new `outp_loop_abort()` that
unwinds the bar's nesting depth and releases the line.

## The hold is a depth, not a flag

A loop command nested as another's `-analysis` — `optimize -param r1 …
-analysis sweep v1 lin 2 0.9 1.1`, a swept-curve objective, entirely
reasonable usage — had the inner `sweep`'s `HoldTrial(FALSE)` release the
**outer** optimizer's bracket. The next evaluation's inner sweep re-armed
with `held_advanced` false and took a fresh trial: measured trials 2…15
across 14 evaluations, one Monte-Carlo sample **per evaluation** — precisely
the stochastic-objective bias E-535 exists to eliminate, reintroduced
through nesting.

`OSDImcHoldTrial` now counts depth: only the outermost `TRUE` resets
`held_advanced` and clears the pins, and only the outermost `FALSE` releases.
Every caller keeps a local `mc_held` flag and releases exactly what it took,
so an error path that never reached the bracket (a parse failure, the
E-533 `sweep`→`dc` handover) cannot pop someone else's hold. The nested case
now draws exactly one trial.

## `optimize` joins the preserve protocol

E-535 taught `sw_run_cmd` (the `sweep`/`montecarlo`/`highsigma` runner) that
an *internal* reset preserves the trial sequence, but `opt_run_cmd` — the
optimizer's own identical runner — never got the call. Two consequences,
both measured:

* a **`-dparam` fit** re-sources per evaluation (`alterparam` + `reset`),
  which zeroed the counter: the first evaluations ran at the held sample and
  every later one at the nominal, the objective silently changing mid-search;
* **`-center`** — whose objective *is* an inner Monte-Carlo — saw **zero**
  osdimc variation: every sample of every candidate computed the nominal, so
  the yield it reported ignored the model's own declared statistics
  entirely.

`opt_run_cmd` now calls `OSDImcPreserveTrial()` on its internal resets, and
`-center` gets the treatment its objective actually needs: it runs *without*
the hold (its samples must draw), and instead **rewinds the trial counter to
a checkpoint** taken before the search, so every candidate replays the same
window of trials. The yield objective therefore samples osdimc variation
*and* is deterministic across candidates — the same property the seeded
netlist draws already had. Draws being pure functions of `(seed, trial,
owner, id)` is what makes the replay exact.

## `highsigma -scale` now weights the draws it inflates

E-535 let `-scale` inflate the attribute-declared sigmas, which made
rare-failure analysis over osdimc variability *possible* — and estimated it
under the **wrong density**. `mc_sample_weight()` accumulates likelihood
ratios only for the netlist `.param` draws, so a metric depending on an OSDI
statistical parameter got every sample at weight 1: the reported P(fail) was
just the λ-inflated failure fraction. Measured on a deck with OSDI-only
variability: **0.42 reported where the true value is 0.354**, with a
confident ±0.03 error bar under it.

`OSDImcSampleLogLR()` supplies the missing term. For every gauss statistical
parameter the applier drew this trial, it recomputes the same standard-normal
deviate `n` (pure functions again) and sums the per-dimension log ratio

```
log[ φ(z) / ((1/λ) φ(z/λ)) ]  with  z = λn   =   log λ − n²(λ²−1)/2
```

which `highsigma` multiplies into the sample weight beside the netlist term.
Recomputing rather than accumulating during apply makes a double application
(the E-471 rebuild path runs `OSDIsetup` twice) harmless by construction.
Uniform draws are now explicitly **not** inflated, matching the netlist SSS
policy exactly — an inflated uniform can land where the true density is
zero, which no finite weight represents. Validated against a closed-form
single-dimension case: quadrature says 0.29670536, the suite's seeded
1000-sample run reports 0.341 where the raw inflated fraction is 0.454.

## Ctrl-C stops a loop command

None of the loop commands polled `ft_intrpt`. With `ft_setflag` set during a
run, an interrupt aborts only the *inner analysis it lands in*, and the next
`dosim()` clears the flag — so the loop marched through every remaining
point as insta-aborted analyses stitched into a plot that was then reported
as a **success**: measured, a Ctrl-C mid-`sweep` still announced "100000
points into plot 'sweep1'". Every loop now polls at its own iteration
boundary, before the next run can clear the flag: `sweep` marks the
un-run points `nan` (E-445's existing honest marker) and says how far it
got, `montecarlo`/`highsigma` report over the samples that completed,
`wcd` refuses to report a half-converged MPFP, `loadpull` stops the grid,
and the optimizer methods break out and report the best point so far
(`opt_eval` also short-circuits, so a population method owes no further
analyses). *Documented limitation:* an interrupt that arrives **inside** a
long inner analysis is consumed by that analysis's own `OUTstopnow()`, which
clears the flag — a second Ctrl-C stops the loop. That consume-and-clear
contract is ngspice's, shared by every multi-analysis command, and is left
alone here.

## The `.dc` restore, completed

Resolution *applies* each nest level's start value as it walks the levels —
a temperature propagated through `inp_evaluate_temper` + `CKTtemp`, a
source's dc value overwritten, a parameter written through the DEV tables.
A failure at a **later** level returned without putting the earlier ones
back, so a typo in the second sweep variable silently changed the circuit:
`dc v1 0.5 1.5 0.5 @n1[nonesuch] 1 2 0.5` left `v1` parked at **0.5 V**, and
a `temp` outer level left every temper-baked expression at the sweep's start
temperature. The reverse-order restore E-535 wrote for its clash refusal is
now a shared helper (`DCTunwindLevels`) that **every** resolution-failure
path calls — the temperature-range refusal, both integer refusals, the
unknown-parameter and unknown-device errors, the resolver's own errors, and
the three keyword-scale validation failures — with the clash refusal reusing
it too.

Two smaller repairs alongside: the same-knob clash guard now also catches a
**wildcard instance level covering a source/resistor level's principal
parameter** (`dc v1 0.5 1.5 0.5 @#*[dc] 0 2 1` moved `v1`'s dc from both
levels, passed the guard, and left `v1` corrupted at the sweep start), using
the same principal-keyword identity the cross-kind check already used; and
`DCTresolveXParam`'s two integer-refusal paths now drop the collected target
list, as their sibling error paths already did, instead of leaving a stale
list of dangling owner pointers on the job.
