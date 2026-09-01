# Enhancement-533: `sweep` hands eligible op-point sweeps to one dc analysis

**Scope:** with the default `-analysis op`, a single dc-sweepable knob and
evenly spaced points, the `sweep` command no longer solves npt independent
**cold** operating points — a full `op` job, the whole gmin/source-stepping
fallback chain, and one retained plot per point — it runs **one dc analysis**
under the hood (a warm NIiter continuation from point to point, E-258) and
serves the sweep's outputs from the dc plot. Measured on the motivating deck,
a 1000-device OSDI Monte-Carlo ladder swept over 9900 resistance points:
**21.2 s → 2.16 s**, bit-identical to a direct `.dc`, within Newton tolerance
of the per-point loop. `-perpoint` forces the old loop.

**Suites:** [`examples/sweepdc_examples/`](../examples/sweepdc_examples/)
(new, 15 checks, both solvers). Two existing suites were re-pointed at the
machinery they actually pin: `loopbar`'s op-sweep vehicles now carry
`-perpoint` (the point-loop progress bar needs a point loop; a new check pins
that the eligible default hands over and draws none), and `reusedev`'s
eligible knobs likewise (the E-471/E-503 setup-reuse decision lives in the
loop; the handover itself is sweepdc's to pin). Full sweep **447/447** ALL OK.

## Why one dc is the right engine

The per-point loop restarted Newton from zero at every point. `.dc` walks the
same points inside one analysis: the first point is a cold OP, every later
point starts `MODEINITPRED` from the previous solution and typically converges
in a couple of iterations — plus one setup, one plot, no per-point command
dispatch. For a many-point sweep that difference *is* the runtime.

The handover is safe because the two engines were already built as
complements, each pointing at the other:

* `.dc` **refuses** a point that moves an OSDI node collapse or leaves a
  model bin (E-495 — its message says to use `sweep`), aborts when a device
  rejects a value (E-427), and stops on non-convergence. Every one of those
  outcomes reaches the handover as a failed run and **falls back to the
  per-point loop unchanged** — which re-decides topology per point and is the
  correct instrument for exactly those sweeps. Fast when the circuit
  cooperates, the old behavior to the letter when it does not (pinned: an
  instance-parameter sweep across a collapse boundary falls back and lands on
  closed-form series-resistance values exactly).
* both engines set the swept value through the **machine-write** path and
  restore it afterwards, so neither recenters `osdimc` nominals (E-531), and
  frozen `agauss()` draws stay frozen — no re-source on either path.

## What qualifies, and what deliberately does not

Eligible: a bare source or resistor name, a non-wildcard `@inst[param]`
(E-62 taught `.dc` that spelling), or `temp` — with **evenly spaced** points,
judged from the values themselves, so the positional form, `lin`, and a
uniform `list` all qualify while `dec`/`oct`/uneven lists stay on the loop
(`.dc` regenerates its points as start + k·step and cannot represent them).
`@r2[resistance]` and `@v1[dc]` are rewritten to the bare spelling so `.dc`'s
classic resistor/source arms apply — those step the value directly instead of
routing every point through `CKTsetInstParam` + a full `CKTtemp` pass over
every device in the deck.

Staying on the loop by design: model-parameter and `.param` knobs (no dc
arm), `-vs` families, `-overlay`, live `@dev[param]` outputs (only the loop
can read the circuit at each point — prescreened before any dc is run), and
**`sweep temp` whenever the deck contains an OSDI device**: `dc temp` holds
one setup for the whole sweep and never rebuilds a temperature-moved node
collapse — a known-open finding the `sweeptemp` suite pins, with its own
check stating that the per-point path is the correct instrument. Built-in
devices cannot re-decide topology after setup, so a built-in-only deck keeps
the temp speedup.

Two float details worth their ink: `.dc` accumulates `value += step` and
terminates on an *absolute* overshoot test, so a step derived as span/(N−1)
can lose the endpoint to accumulated rounding — the handover pads the issued
stop by 0.49·step (the endpoint always lands, the point after always exceeds
the pad and is dropped) and then **adopts the dc plot's own scale values**
into the sweep scale rather than assuming them; if the count still disagrees,
it falls back. And the announce line names the engine, so a log always says
which path computed the numbers.

## Semantics that change with the engine, stated honestly

dc points run under `MODEDCTRANCURVE`: a Verilog-A `analysis("dc")` is true
where the loop's op had `analysis("static")` — both readings are LRM Table
4-22 rows, and the dc reading is what this sweep now is. A warm continuation
**tracks a solution branch** where independent cold OPs re-decide it at every
point — for a bistable circuit that is `.dc`'s answer, hysteresis included.
`-perpoint` restores the old reading of either. Converged values agree with
the loop within Newton tolerance (measured ~2e-4 relative on a clamped diode
divider) and are bit-identical to `.dc`, because they *are* `.dc`.
