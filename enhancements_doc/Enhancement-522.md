# Enhancement-522: analog events, audited against the LRM

**Scope:** Accellera VAMS-2023 clause 5.10 (analog event control), from the
full LRM conformance audit — the audit's largest remaining area. Five
bugs across both halves of the toolchain, one missing separator, two
deviations made audible or documented. (The area's break/continue finding
was already resolved by [E-520](Enhancement-520.md).)

**Suite:** [`examples/lrmevents_examples/`](../examples/lrmevents_examples/)
— 22 checks, both solvers, including the full five-analysis Table 5-1
matrix. `lrmcorner`, `finalstep`, `evtnoise`, `intstate`, and the
`analysis()`-pinning `deckdomain`/`domainrt`/`rtdomain` suites all still
pass.

## Step events fired for the wrong analysis names (ngspice)

LRM Table 5-1 gives every phase-qualified step event an exact row per
analysis: `initial_step("dc")` is 0 for *every* AC and NOISE point, and
`final_step("ac")` is 0 for NOISE. Neither held: the operating point of
an `.ac`/`.noise` job runs with `MODEDCOP` set, so it carried
`ANALYSIS_DC` *in addition to* the owning analysis's flag — and a noise
run ends with `MODEAC|MODEACNOISE` both set, so its final step answered
to `"ac"`.

The decisive observation is that the LRM *agrees with itself*: Table
4-22 (the `analysis()` function) defines `analysis("dc")` as 0 in the
AC-OP and NOISE-OP columns (only `"static"` stays 1 there — "any
equilibrium point calculation") and `analysis("ac")` as 0 for every
NOISE point. Since step-event phase filters and `analysis()` read the
same flag word, one derivation fix serves both channels: the op phase of
an AC/NOISE job drops `ANALYSIS_DC` when the job consultation adds the
owning name, and `MODEAC` raises `ANALYSIS_AC` only without
`MODEACNOISE` — in the eval path and in `OSDIfinalStep` both. The whole
matrix (`op`/`dc`/`tran`/`ac`/`noise`) now prints exactly Table 5-1's
rows, the multi-analysis session included, and the suites that pin
`analysis()` behavior all pass unchanged.

## cross fired in DC and at t = 0; above missed its mandated event (compiler)

LRM 5.10.3.2: "The cross() function will not generate events for
non-transient analyses, such as ac, dc, or noise" and "can only generate
an event after the simulation time has advanced from zero." The lowering
was pure evaluation-to-evaluation sign-change detection: a `.dc` sweep
crossing counted, and at t = 0 the Newton trajectory walking from the
zero initial guess through the threshold counted too. The FIRED bool is
now gated on `analysis("tran") && $abstime > 0` — the *state* still
tracks through DC and the operating point, so the first transient step
compares against the converged OP rather than replaying it.

`above()` is the deliberate contrast: the same clause says it *does*
fire during initialization and dc sweeps — "if the expression is
positive at the conclusion of the initial condition analysis … the
above() function shall generate an event." Seeding its previous-value
state with the current value made the first evaluation a non-edge *by
construction*, so an expression positive from the first iterate never
produced the mandated event; it fired only when the Newton trajectory
happened to cross the threshold (solver luck, not the rule). The fired
bool now ORs in `initial_step && expr > 0`. The suite pins the contrast
in one sweep: `above` fires crossing 0.55 mid-`.dc`, `cross` stays
silent.

## Unrecognized events silently ran the body on every evaluation (compiler)

Any `@(...)` whose expression was not literally `cross`/`above`/`timer`
or a step keyword was DROPPED — the guarded statement executed
unconditionally on every model evaluation, with no diagnostic on any
channel. That converted `@(absdelta(...))` (a digital-only event the
analog subset must reject, 5.10.3.4), `@(named_event)` (5.10.4, outside
the subset), and a plain typo `@(cros(...))` into run-always statements
— the audit measured 120 silent executions over a 10-point transient.
The malformed unit is now a distinct `Event::Invalid` variant:
`hir_ty::validation` rejects it with a targeted error (absdelta gets the
Annex C.7 citation, identifiers the named-events one), and lowering
never runs the body.

## Placement restrictions enforced (compiler)

Three normative sentences were accepted silently: **"Nested event
control statements are not allowed"** — the nested form lowered as ANDed
gates, so `@(initial_step) @(final_step) x = 1;` was a silently *dead*
statement; **cross/above under a runtime `if`/`case` or inside
`repeat`/`while`/`for`** — the event's state slot advanced only when the
branch executed, so detection compared against a value stale by any
number of timepoints (a genvar-conditioned `if` folds to a constant and
the genvar `analog_for` unrolls at elaboration, so both LRM-sanctioned
shapes pass untouched); and **analog filters in the event expression** —
the body-side check always existed, but the expression was validated
under the *enclosing* ctx, so `@(cross(ddt(V(p,n)), +1))` compiled
silently. The event expression is now validated under the event ctx.

## The comma separator (5.10.1) — and the bug the new suite caught

"A comma (,) can be used interchangeably with the keyword or to OR
event expressions." Only `or` parsed. The first cut accepted the comma
in the parser — and the new suite's check [8] immediately failed: the
hir_def unit splitter segments the event list on `or` tokens, so the
comma-joined units MERGED and the second member was silently dropped
(`@(initial_step, timer(2.5u))` counted 1, its `or` twin 2). A comma at
paren depth 1 now splits units — depth 2 commas are a step event's
phase-list separators, and a monitored event's argument commas live
inside its expression node and never reach that level.

## Made audible / documented

A **nonzero cross/above tolerance warns** that it is accepted but not
honored: detection is evaluation-granular and nothing bounds the
timestep, so the event fires at the first solver evaluation past the
crossing (the audit measured 5.6 µs against a requested 1 ns time_tol;
`timer`'s placement, by contrast, is exact via its bound-step channel).
A tolerance of 0.0 — "the simulator shall apply a suitable value" — is
exactly what happens and stays silent. The **strict out-of-range
direction** (E-506: compile error for a literal, runtime fatal from the
deck, where the LRM defines any other value as a disabled event) is kept
and now documented as the deviation it is, alongside the
evaluation-granularity design note (E-7/E-8). The handbook's false
"tolerances honored" claim is corrected.
