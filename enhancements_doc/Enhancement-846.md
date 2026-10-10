# Enhancement-846: the first transient step is checked against the truncation error — it was accepted unchecked, up to 32 % off at reltol 1e-7, and its bad point made a linear L–C network collapse

**Scope:** F2 and F3 of the
[second robustness and correctness campaign of 2026-10-10](../docs/bug_hunts/2026-10-10_ngspice-openvaf-r-second-robustness-campaign.md).
F3's last case, under KLU, is [Enhancement-847](Enhancement-847.md).

ngspice: `spicelib/analysis/dctran.c`:
- the first step's truncation check;
- the t = 0 solution kept for a retry of the first step, on a rejection or a non-convergence.

Examples:
- `examples/firststep_examples/` (new);
- `loopguard_examples` [20], `reusestate_examples` [20] and `scaleguard_examples` [5], which
  pinned the old first step's grid.

**ngspice only.**

**Suites:**
- [`firststep_examples`](../examples/firststep_examples/): 9 of 9 per solver. On the E-844
  binaries the 6 checks of the defect fail; the 3 others are controls.
- The campaign's Family D (292 random linear networks against their exact solution, each at
  default and at tight tolerances):
  - at its extreme tight settings (`abstol=1e-15`, `chgtol=1e-20`), 2 runs collapse, against 7
    on E-844;
  - at `reltol=1e-7` with the default `abstol` and `chgtol`, none collapses, as on E-844. At
    those settings it is F3's reduced network that collapsed;
  - 26 `uic` runs still have a first-step error over the limit, against 42.
- The full sweep: 553 of 553.

## What was wrong

```spice
* from the operating point: a sine into a 1 ns RC
i1 0 1 sin(0 1m 100meg)
r1 1 0 1k
c1 1 0 1p
.option reltol=1e-7
.tran 1u 10u
```

`dctran.c` accepted the first time step without a truncation check, under the comment "no
check on first time point". The estimate needs a point before t = 0, and there was none. The
step is a fixed fraction of the run, 1 ns for `tran 1u 10u`. It ignores the circuit's time
constants and the tolerances, and it is integrated by backward Euler.

Here it spans a whole time constant. `v(1)` at 1 ns was 0.2939 where the exact value is 0.2227:
32 % high at `reltol=1e-7`. With `uic` the start is far from equilibrium, and it was worse: the
same RC charged by 1 mA from `.ic v(1)=0` gave 0.500 at 1 ns against 0.632. In the campaign's
Family D, 42 runs had a first-step error over the limit.

The bad point did not stay at the start. Every later truncation estimate takes divided
differences over the last few points, and they all included it. On a linear L–C network that
was enough to collapse the run. Seven elements, reduced from Family D:
- the first step was 538 ps;
- the second, 47 fs;
- from there the steps shrank geometrically, and the run ended "Timestep too small" at
  `reltol` 1e-6 and below.

It ran at 1e-5 and at the defaults. A dummy PWL source with a breakpoint at 10 fs, 1 ps or
10 ps forces a small first step, and with it the same deck ran at 1e-6. All 7 of Family D's
collapsed runs had inductors.

## The change

**After an operating point, the circuit was at rest before t = 0.** That is the missing
history, and `dctran.c` already copies the t = 0 state into states 2 and 3 after the first step
converges. The first step is now checked by `CKTtrunc` like any other, with that history spaced
at the step's own width. The check is exact for a smooth start from the operating point. A
rejected first step is retried from t = 0, with the step the estimate asks for.

**The t = 0 solution is kept** while the first step is under way. In `MODEINITTRAN` the devices
take their history, a capacitor's charge or an inductor's flux, from `CKTrhsOld`. A retry
started from the rejected step's solution would build that history at the wrong instant. The
same was already true of the existing retry after a non-convergence, which now restores it too.

**A kink at t = 0 is told apart from a step that is too long.** For a smooth start the estimate
is the step's own error, so a shorter step answers it: `newdelta/delta` grows, and one retry
settles. Some starts make the estimate scale with the step instead:
- a voltage ramp that starts at t = 0 and drives a capacitor, whose current jumps;
- a jump, such as an `.ic` that a voltage source across the capacitor contradicts;
- a `uic` state that is already moving at t = 0.

No step satisfies such an estimate, and shrinking the first step for nothing is not free.
Under trap, a stiff mode that no step resolves keeps a shorter first step's startup residue
undamped to the end of the run. In `collapsecur_examples`, 1 nF through 1 µΩ (1 fs) driven by
a ramp, the final current moved by 6e-6 when the first step shrank from 0.4 ns to 0.4 ps. The
same happens on the E-844 binaries when a breakpoint forces the first step down: 5e-4 at 4 fs.

So if a retry does not at least double the ratio, the estimate is measuring the kink. The first
step then goes back to the size SPICE gave it, and the check stops.

That leaves `uic` only partly fixed. With nothing known before t = 0, a state already moving
looks like a kink unless the charge tolerance, which grows as the step shrinks, settles the
estimate. The 1 ns RC charged under `uic` settles, at 1 ps. In Family D, 26 `uic` runs still
have a first-step error over the limit, against 42 on E-844. For those, a smaller `tstep` or
`tmax`, or an operating-point start with `.ic` and no `uic`, gives the start the check needs.

**An estimate that asks for too little is distrusted too.** If it wants less than a billionth
of SPICE's first step (or ten times `delmin`), the first step goes back to SPICE's size, as for
a kink. After ten rejections the check stops. At extreme tolerances, such as `abstol=1e-15` with
`chgtol=1e-20`, the steps the estimate asks for reach its own rounding. A first step taken
there and still judged too long poisons the next estimates, exactly as F3's did. Family D
measured the choice at those tolerances:

| first-step rule | tight runs that collapse |
|---|---|
| unchecked (E-844) | 7 of 292 |
| floor 1e-3, the step accepted at the floor | 10 |
| floor 1e-6, accepted at the floor | 5 |
| floor 1e-9, SPICE's step below it (this) | 2 |

The 2 left accept a first step of about 10 fs and then collapse; each has an inductor. At
realistic tight settings (`reltol` 1e-6 or 1e-7 with the default `abstol` and `chgtol`) nothing
collapses.

**An inductor's tolerance** is [Enhancement-847](Enhancement-847.md). `CKTterr` floored every
state's error at `abstol`, a current, which for an inductor's flux acts on a voltage. With this
enhancement alone, F3's network at `reltol=1e-7, chgtol=1e-20` runs under Sparse but not under
KLU.

The check applies to trap, Gear and Adams. Adams at order 1 is trap's step with trap's error
constant, and Enhancement-419 has `adams maxord=2` reproduce trap byte for byte. It does not
apply to `newtrunc`, which has no predictor at the first step, to Enhancement-181's fixed-order
mode, or to the staged TR-BDF2 and SDIRK methods.

| | first step | first sample's error |
|---|---|---|
| sine into a 1 ns RC, `reltol=1e-7`, E-844 | 1 ns | 7e-2 V of a 0.22 V swing |
| the same, now | 1 ps | 3e-7 V |
| `uic` charge of a 1 ns RC, E-844 | 1 ns | 0.13 V |
| the same, now | 1 ps | 5e-7 V |
| a ramp into 1 nF through 1 µΩ, trap | 0.4 ns | unchanged: a kink |

Starting smaller costs the doublings back up to the run's step, about ten steps.

**Three suites assumed the old first step:**
- `loopguard_examples` [20] pinned three sampled peaks to 12 digits. It now compares each
  overlay peak with the same run made alone, which is what the check is about.
- `reusestate_examples` [20] asked that every sweep point take the same first step. It now
  asks that each take a standalone run's.
- `scaleguard_examples` [5] pinned a transient's point count. It now compares with the data's
  own length.

## The checks

`firststep_examples`:
- **[1]** A sine into a 1 ns RC from the op at `reltol=1e-7`: the first sample within 1e-5 of
  the swing, and the whole run within 1e-4.
- **[2]** The `uic` charge: the first sample within 1e-3 V.
- **[3]** The reduced L–C network runs to tstop:
  - at `reltol=1e-6` and 1e-7;
  - at 1e-7 with `chgtol=1e-20`, under KLU with Enhancement-847;
  - at the defaults (control).
- **[4]** (control) An inconsistent `.ic` still runs.
- **[5]** (control) An RC step response at the default tolerances, against the exact value.
