# Enhancement-911: `cross` and `above` land in the box of their tolerances, and the "accepted but not honored" warning is retired — a 1 ms `time_tol` with a 0.2 `expr_tol` fired 5.6 ms late and a 1 mV `expr_tol` fired 67 mV past the threshold, while the compiler said the tolerances did nothing at all

**Scope:** found while folding [E-909](Enhancement-909.md). The events audit's warning dates from
before [E-759](Enhancement-759.md).

Compiler:
- `hir_lower/src/stmt.rs`: `localise_crossing` lands in the LRM's box.
- `hir_ty/src/validation/body.rs`: `EventTolIgnored` and its check are replaced by
  `EventExprTolAlone`.
- `hir_ty/src/validation.rs`: the report.

**Compiler only.**

**Suites:**
- [`evttol_examples`](../examples/evttol_examples/) (new): 8 checks per solver, 6 of which fail on
  E-908.
- `lrmevents`: [17], [18] and [20] reversed (no tolerance warns now), and [23], [24] added, for 28
  checks.
- The event suites, unchanged: `evtedge`, `evtretry`, `simctrl`, `idtassert`, `discontinuity`,
  `finalstep`, `eventcond`, `opargs`, `varinit`, `multianalog`, `intstate`, `analoginit`,
  `deckdomain`, `hiername`, `lrmcorner`, `lrmkernel`, `domainrt`, `defaulttransition`, `evtnoise`,
  `rtdomain`, `cardbound`, `hunt13slips`, `constfold`, `rebinfinal`.
- The full sweep: 599 of 599.

## What was wrong

LRM 5.10.3.1 (Figure 5-6):
- "The event shall occur after the threshold crossing, and while the signal remains in the box
  defined by actual crossing and expr_tol and time_tol."
- "If expr_tol is specified, time_tol shall also be specified and both tolerances shall be
  satisfied at the crossing."

The events audit found that neither tolerance did anything, and made every nonzero one warn:

```
warning: @(cross): the time tolerance is accepted but not honored
   = help: event detection is evaluation-granular and does not bound the timestep ...
```

E-759 made the event land the step on its crossing, and `time_tol` became its margin, so the
warning was false. It still printed for every tolerance in every model. Nor was the box honoured:
- **The time box.** A request landed on the box's END (the crossing plus `time_tol`). An iterate
  was accepted up to half a width past it, and a landing up to a whole width past it.
- **The value box.** `expr_tol` was used only to stop a landing: when the overshooting iterate was
  within `expr_tol` of the threshold, no landing was requested, however late it was.

On this build before the change:

| model | event after the crossing | expression there | in the box |
|---|---|---|---|
| a 1 MHz sine, `time_tol` = 10 ns, 20 ns step | 10.72 ns | | no |
| a ramp, `time_tol` = 1 ns, 100 ns step | 1.000 ns (the box's end) | | on its edge |
| a slow ramp, `time_tol` = 1 ms, `expr_tol` = 0.2 | **5.6 ms** | 5.6e-3 | no |
| the sine, `time_tol` = 10 ns, `expr_tol` = 1 mV | 10.72 ns | **−67 mV** | no |
| `above` on the sine, the same | 2.2 ns | **+13 mV** | no |

## What changed

**The box.**
- *Its width in time* is `time_tol`. When `time_tol` is not given, or is 0.0 ("the simulator shall
  apply a suitable value"), it is two thousandths of the step.
- *With `expr_tol` given*, it is no wider than the time the expression takes to move `expr_tol`
  along the chord between the accepted sample and the iterate.

**The landing.** A request lands in the middle of the box. An iterate is outside the box when it
is past the box's end, or (with `expr_tol`) more than `expr_tol` beyond the threshold, and then
it asks to land. E-759's rules on who may ask are unchanged: one refinement per landing, and
E-909's single chase of a short landing.

**The default box.** When no tolerance is given, the request aims a thousandth of the step past
the crossing, where E-759 aimed. An interim build used a box one thousandth wide, aiming at half a
thousandth. The chord of a curved expression then landed short of the crossing more often (a
1 MHz sine's falling crossings, every period), and the chase was raised to E-504's step floor
(10 ps there), which put those crossings 1.86e-3 of the step late where E-908 had 4e-4. With the
wider default, that deck gives E-908's landing errors and point counts exactly: 2018 points, 30
rejected.

**The warning.** It is gone. LRM 5.10.3.1 asks one thing of the model here, "If expr_tol is
specified, time_tol shall also be specified", so an `expr_tol` that is not provably 0.0 written
without a `time_tol` (or with a null one) now warns:

```
warning: @(cross): an expression tolerance needs a time tolerance beside it
   = help: LRM 5.10.3.1: 'If expr_tol is specified, time_tol shall also be specified and both
     tolerances shall be satisfied at the crossing'; the simulator's own time tolerance is used
     with it. ...
```

## Measured

The table above, on this build:

| model | event after the crossing | expression there |
|---|---|---|
| sine, `time_tol` = 10 ns | 5.0 ns | |
| ramp, `time_tol` = 1 ns | 0.50 ns | |
| slow ramp, 1 ms and 0.2 | 0.50 ms | 5.0e-4 |
| sine, 10 ns and 1 mV | 0.08 ns | −0.51 mV |
| `above`, 10 ns and 1 mV | 0.12 ns | +0.70 mV |

The campaign's family C, 40 decks of `cross` with the default tolerances:
- every count is still exact;
- the worst crossing per deck, as a median fraction of the step, is 1.2e-3 (`dir` = −1), 1.8e-3
  (0) and 1.0e-3 (+1), within the default box of 2e-3. E-910 gave 9.9e-4, 1.6e-3 and 1.0e-3;
- the worst of all decks is 2.2e-2, the E-504 floor's case of E-909.

## The checks

`evttol_examples` (new), under both solvers:
- **[1]** `time_tol` = 10 ns on the sine: within 10 ns (E-908: 10.72 ns).
- **[2]** `time_tol` = 1 ns on the ramp: 0.5 ns after the crossing (E-908: 1.000 ns).
- **[3]** The slow ramp: within 1 ms (E-908: 5.6 ms).
- **[4]** The sine with `expr_tol` = 1 mV: within 1 mV and 10 ns (E-908: 67 mV).
- **[5]** `above` the same, at both rises (E-908: 13 mV).
- **[6]** Control: the default tolerances count all 20 crossings, each within 2e-3 of the step.
- **[7]** The model's nonzero tolerances draw no warning (E-908: four).

`lrmevents`:
- **[17]** A nonzero `time_tol` draws no warning.
- **[18]** A 0.0 tolerance draws none.
- **[20]** Null tolerances draw none.
- **[23]** An `expr_tol` without a `time_tol` warns, for `cross` and for `above`.
- **[24]** With a time tolerance beside it (1n, or 0.0), no warning.

## Limits

- **E-504's step floor.** A request below the floor (the analysis span over 10⁶) is declined, and
  the crossing fires at the next point. A box narrower than the floor cannot be met.
- **The chord.** Both widths are measured along the chord, so a strongly curved expression can
  leave the box. Its landing then asks once more (E-759's refinement), and a refinement that still
  misses fires where it lands.
- **`timer`.** Its `time_tol` is not warned about and needs nothing: it lands exactly on its
  schedule through the bound-step channel (E-415).
