# Enhancement-722: the small-signal linearisation of an `.ac` or `.noise` job carries the sweep's flags, `analysis("static")` 0 — it ran with the operating point's, so an `idt` asserted on "static", LRM 4.5.5's own idiom for an integrator pinned at the bias point, had no integrator in `.ac` and `.noise`: a 1 nF capacitor behind 1 kΩ read 1/R, a short; its dual an open; a topology switched on "static" linearised its static branch

**Scope:** F1 of the
[second correctness campaign of 2026-09-25](../docs/bug_hunts/2026-09-25_openvaf-r-correctness-campaign-2.md).
**ngspice only.** `src/osdi/osdiload.c` (`OSDIload`, the analysis flags of the
`MODEINITSMSIG` evaluation).
[`examples/idtassert_examples/`](../examples/idtassert_examples/) (`idtac.va`, section 5,
6 checks, 23 per solver); [`examples/lrmnoise_examples/`](../examples/lrmnoise_examples/)
(section [1], 3 checks, 28 in all). The hunt page; handbook §2.11's `analysis()` row.

**Suites:** `idtassert` 23 of 23 per solver, both solvers (18 of 23 on the E-719
binaries); `lrmnoise` 28 of 28 (26 of 28); `analyses` 37 of 37, `analysis`, `lrmfuncs`
229 of 229, `finalstep`, `evtnoise` 18 of 18, `opvarac` 19 of 19, `idtic`, `dcstate` 11 of
11, `rfanalyses` 15 of 15 and `vafidtcfg` 2 of 2 unchanged; no new build warnings; full
sweep, run alone.

## What was wrong

A 1 kΩ resistor from a unit-ac source into the module, `.ac` at 1 kHz; the analytic
current is 1/\|R + 1/(jωC)\| = 6.283e-6 A:

| module | `.ac` \|i\| before | after |
|---|---|---|
| `V(a,b) <+ idt(I(a,b), 0.0, analysis("static")) / 1e-9` | **1.000e-3** (1/R: a short) | 6.283e-6 |
| the same asserted on `analysis("dc")`, on `analysis("ic")`, or unasserted | 6.283e-6 | 6.283e-6 |
| `I(a,b) <+ 1e-3 · idt(V(a,b), 0.0, analysis("static"))` (a 1 kH inductor) | **0** (an open) | 1.5915e-7 |
| `if (analysis("static")) V(a,b) <+ 0; else I(a,b) <+ ddt(1e-9 · V(a,b));` | **1.000e-3** | 6.283e-6 |
| the same switched on `analysis("ic")` | 6.283e-6 | 6.283e-6 |

`.noise` at the same node: the output spectrum of the first module was 0 (the node
pinned) where the RC's 4.07e-9 V/√Hz was due. The operating points and the transients
of every module were right — the transients match ngspice's own capacitor to 1e-14 —
and a `$strobe` of the flags printed `static=1 dc=0 ac=1` for the `.ac` job and
`static=1 noise=1` for `.noise`.

ngspice runs a small-signal job in three phases: the operating point (`MODEDCOP`),
one linearisation evaluation (`MODEDCOP | MODEINITSMSIG`, `acan.c`) whose resistive
and reactive Jacobians the whole sweep then uses (`OSDIacLoad`, the noise load, the
E-412 bias restore for the op variables), and the sweep itself, which never
evaluates the model. `OSDIload` derived the linearisation's flags from `MODEDCOP`:
`ANALYSIS_DC | ANALYSIS_STATIC`, then E-53 and E-684's job consultation replaced the
DC bit with the job's name and, deliberately, kept STATIC — right for the *operating
point* of the job, which is LRM Table 4-22's AC-OP column (static 1, ac 1), wrong for
the linearisation, which stands for the *sweep*: the AC column (static 0, ac 1), the
NOISE column (static 0, noise 1). The compiler lowers `idt(x, ic, assert)` as a select
between `ic` and the integrator state and a topology switched on `analysis("static")`
the same way, so with the static bit on the linearisation had no reactive part for
them: the `idt` was the constant `ic`, a potential source of 0 V — a short — and the
`I <+ g·idt(V)` form a flow source of 0 — an open.

## What changed

One clause in `OSDIload`: when the job's name is `ac` or `noise` (E-684's list: `.ac`,
`.sp`, `.pz`, `.disto`, an AC `.sens`; `.noise`), the `MODEINITSMSIG` evaluation drops
`ANALYSIS_STATIC` as it already dropped `ANALYSIS_DC`. The operating point keeps the
AC-OP column (static 1, its name), and so do `@(initial_step("ac"))`, the final step
(`OSDIfinalStep`'s own flags), the op variables (E-412 restores them from the bias
point) and the events. The plain `op` keeps `static=1 dc=1` for its own
`MODEINITSMSIG` evaluation — it *is* an equilibrium point — and so do the passes of
the PSS family, which E-684 gives no small-signal name.

## Verification

`idtassert` section 5, `idtac.va`: the first module's `.ac` magnitude and phase equal
the analytic value and the `"ic"` form's (1 mA and π before); the 1 kH dual's
1.5915e-7 A (0 before); the switched topology's 6.283e-6 A (1 mA before); the `.noise`
output spectrum equal to the `"ic"` form's 4.07e-9 V/√Hz (0 before); the transient at
1 µs equal to the `"ic"` form's, as before. `lrmnoise` [1]: the `$strobe` line the
sweep's evaluation prints reads `dc=0 ac=1 noise=0 ic=0 static=0` for `.ac` and
`dc=0 ac=0 noise=1 ic=0 static=0` for `.noise` (static 1 before), and the plain `op`
still prints `dc=1 static=1`. The `analyses` suite's row of flags per analysis
(read from the op variables after each job) is unchanged, which is E-412's restore
at work: the op variables report the bias point.

By hand: the campaign's eight `.ac` decks and four flag decks rerun (the table above);
the twelve suites; the sweep.

## What this does not do

- The operating point of an AC or NOISE job still answers `analysis("static")` = 1,
  `analysis("ac")` = 1: Table 4-22's AC-OP and NOISE-OP columns, and E-53's contract
  for `@(initial_step("ac"))`.
- The PSS family (`.pss`, `.pac`, `.pnoise`, …) runs `MODEINITSMSIG` passes of its own
  under no small-signal name; their flags are as they were. Whether `.pac` and
  `.pnoise` should count as "ac"/"noise" is E-684's list to extend.
- A model that reads `analysis("static")` into an op variable sees the bias point's
  1 after `.ac` (E-412), not the linearisation's 0.
