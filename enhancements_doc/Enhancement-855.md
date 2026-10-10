# Enhancement-855: AVG and INTEG integrate by one rule — AVG used trapezoids and INTEG Simpson's rules, so INTEG/(to−from) and AVG over one window differed by 2e-3 on a sampled sine

**Scope:** F11 of the
[second robustness and correctness campaign of 2026-10-10](../docs/bug_hunts/2026-10-10_ngspice-openvaf-r-second-robustness-campaign.md).

ngspice: `frontend/com_measure2.c`:
- `measure_quad`, the integral that INTEG, RMS and AVG now share;
- `measure_rms_integral` calls it;
- `measure_minMaxAvg` collects AVG's points and calls it.

`examples/measquad_examples/` (new). **ngspice only.**

**Suites:**
- [`measquad_examples`](../examples/measquad_examples/): 7 of 7 per solver. On the E-852
  binaries checks [1], [3], [4] and both [5] fail; [2] and [6] are controls.
- The campaign's Family C, rerun: every flagged AVG now matches a model of ngspice's quadrature, as
  INTEG and RMS already did.
- The full sweep: 560 of 560.

## What was wrong

AVG integrated by trapezoids. INTEG and RMS used Simpson's 3/8 or 1/3 rule on runs of equal
steps, and trapezoids elsewhere. So INTEG/(to−from) and AVG over the same window differed:
- by 2.0e-3 on a sampled sine, where INTEG was closer to the analytic integral;
- by 4e-4 over a whole run;
- by 7e-5 on a dc sweep of a sine.

[Enhancement-302](Enhancement-302.md) calls them "the same quantity".

## The change

The rule INTEG used is now `measure_quad`: Simpson's 3/8 or 1/3 rule on runs of equal widths, and
the trapezoid elsewhere. INTEG and RMS call it, unchanged.

AVG collects the points of its window and divides their `measure_quad` integral by the window's
span. The points are the same as INTEG's:
- the value at `from`;
- the samples;
- the value at `to`.

A dc sweep may descend; INTEG walks it upward ([Enhancement-304](Enhancement-304.md)), so AVG's
points are put in that order and the rule groups the same steps. AVG's trapezoid sum, which
nothing else read, is gone.

For smooth data Simpson's rule is the better of the two. The sine's AVG is now 1.4e-4 from the
analytic average, against 1.9e-3. On straight segments the two rules agree. MIN, MAX and PP are
unchanged.

## The checks

`measquad_examples`:
- **[1]** A sampled sine: AVG = INTEG/(to−from) over a window, to 1e-14.
- **[2]** (control) The same across PWL corners, where the rules already agreed.
- **[3]** The same over the whole run, without a window.
- **[4]** The sine's AVG is within 5e-4 of the analytic average.
- **[5]** A dc sweep, rising and falling: AVG = INTEG/(to−from).
- **[6]** (control) A constant and a ramp: AVG exact.
