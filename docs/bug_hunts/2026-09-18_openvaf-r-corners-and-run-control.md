# openvaf-r bug hunt — process corners end to end, run control, literals and the diagnostics around them

**Date:** 2026-09-18, one hour (07:47–08:47; the probes ran until 08:35, the write-up
was interleaved from 08:10 on), at head `da166378` (after E-654…E-656, the corner
design). **Binaries:** the repo's `OpenVAF-master-20260610/target/opt/openvaf-r`
and `ngspice-46/build/src/ngspice`. **Method:** ~560 small Verilog-A modules and decks
written for the hour (460 module files, several reused), compiled and (where they
compile) run on ngspice through a throw-away harness in the scratchpad (`hunt17/h.py`,
`p1.py … p74.py`), each probe checked
against the VAMS-2023 text (`pdftotext -layout docs/VAMS-LRM-2023.pdf`). Nothing was
fixed; this is the list. The ground chosen: the three corner enhancements landed this
week (the attribute, `.option corner=`, the `corners` command, `.option autocorner`) and
their interplay with `osdimc`, `savemc`, the loop commands and batch mode — new code,
where defects are cheapest to find — then integer folding, literals, the preprocessor,
run-control tasks, natures, contributions, hierarchy, analog functions and the display
tasks. Areas the earlier hunts already covered (parameters and arrays, events and noise
in depth, `$table_model`, the IHP paramset library, the E-650 diagnostic slips) were
only touched in passing.

## Summary

| # | finding | kind |
|---|---|---|
| [F1](#f1--under-option-osdimc-the-first-run-at-a-corner-corners-only-the-parameters-that-carry-statistics) | *(fixed in [E-658](../../enhancements_doc/Enhancement-658.md))* under `.option osdimc`, the **first run at a corner** after a nominal run corners only the parameters that also carry statistics; the corner-only ones stay nominal until the next run | wrong result, silent |
| [F2](#f2--a-quoted-word-on-the-corners-line-keeps-its-quotes) | *(fixed in [E-659](../../enhancements_doc/Enhancement-659.md))* a quoted word on the `corners` line keeps its quotes: `-analysis "dc v1 0 1 0.5"` becomes an unknown command and every corner is NaN, `-output "g=…"` likewise; `sweep` and `montecarlo` unquote the same spelling | wrong result |
| [F3](#f3--a-corner-named-tt-is-accepted-and-unreachable-and-the-loop-runs-the-nominal-twice) | a corner named `tt`, `nom` or `nominal` in a model is accepted by the compiler and unreachable in ngspice; the `corners` loop then lists the nominal twice; `-list` duplicates are not folded | silent no-op |
| [F4](#f4--a-corner-on-a-parameter-the-model-tests-with-param_given-flips-its-branch) | *(fixed in [E-657](../../enhancements_doc/Enhancement-657.md))* a corner on a parameter the model tests with `$param_given` marks it given and flips the model's branch — the E-555 gate covers only parameters with statistics | wrong result, silent |
| [F5](#f5--l030-folds-an-integer-division-as-real) | L030 folds an integer division as real: `parameter integer a = 7/2` is warned as "the default 3.5", the value is 3 | wrong diagnostic |
| [F6](#f6--finish-and-stop-in-the-analog-block-are-silent-no-ops) | `$finish` and `$stop` in the analog block are silent no-ops at the operating point and in a transient | LRM conformance |
| [F7](#f7--the-corner-loops-under-osdimc-redraw-the-other-parameters-per-corner) | `corners` and `autocorner` under `.option osdimc` let every corner be a fresh trial: the uncornered statistical parameters redraw between corners, so the corner effect is confounded with a draw | design gap |
| [F8](#f8--autocorner-follow-on-gaps) | `autocorner` follow-on gaps: a raw-file `run` reports every corner as "made no plot"; `meas tran` refuses the combined plot; `writemc` has no row to land on; the devices are left at the last corner without a word | usability |
| [F9](#f9--wcd-counts-cornered-parameters-as-dimensions) | `wcd` counts the cornered parameters as free dimensions and then reports "zero gradient" where three of four axes are held by the corner | misleading |
| [F10](#f10--a-corner-that-moves-a-paramsets-own-parameter-out-of-its-member-aborts-with-a-generic-error) | a corner that moves a paramset's own parameter out of the selected member's range aborts the run at setup with a generic message that names neither the corner nor the member | diagnostic |
| [F11](#f11--diagnostic-slips) | diagnostic slips: `1e3n`, `0.5e` and `1meg` die as "expected 'exclude' or 'from'"; a bus-index error names an internal file `x.va__namerange.va`; a nature whose access function has the nature's name is "already declared" plus four cascades; `forever`; a non-ASCII identifier; junk after an `` `ifdef `` name; `(* desc= *)`; the knock-on `;` error after an undeclared macro; `corner="ss=0.5 %"` blames `%` | diagnostics |
| [F12](#f12--run-time-domain-silences) | run-time domain silences: `absdelay` with a negative delay from a parameter or a variable, `$bound_step` negative from a parameter, `$discontinuity(-1)` — the literal forms are refused, the deck-fixed and run-time ones say nothing | silent |
| [F13](#f13--three-declaration-checks-that-do-not-fire) | three declaration checks that do not fire: a string parameter whose default is outside its `from` set (L027 skips strings); a base nature without `abstol` (LRM 3.6.1 requires it); an escaped identifier with an operator character becomes an unreachable ngspice parameter name | conformance |
| [F14](#f14--more-than-64-corners-or-a-name-of-80-characters-cannot-be-selected) | more than 64 distinct corner names in a circuit: the 65th and later are refused by `.option corner=` as "no loaded model declares" and dropped by `corners`/`autocorner` without a word; a corner name of 80 characters or more can never be selected (ngspice's variable limit), and the compiler accepts any length | capacity, silent |
| [F15](#f15--the-nesting-limit-trips-on-a-flat-sum-of-a-thousand-parameters-and-recovers-with-nonsense) | a flat sum of 999 parameters trips "expression nests too deeply" and the recovery then reports `'p997' was not found in the current scope` and `'p998' was already declared in this scope`; 600 terms compile | diagnostic |
| [F16](#f16--a-strobe-with-solution-independent-arguments-runs-in-the-setup-pass-not-per-point) | *(fixed in [E-660](../../enhancements_doc/Enhancement-660.md): the double print and the stale pre-draw, pre-corner copy; a hoisted task keeps its once-per-setup timing by design, see the write-up)* a `$strobe` whose arguments depend on nothing the solver computes runs in the setup pass: twice per analysis (setup and temperature) and never per point — two lines for a 73-point transient, where a strobe reading `V(p,n)` prints 73; `$info`/`$warning`/`$error` with constant arguments the same | wrong output |
| [F17](#f17--noautocorner-is-a-known-option-that-turns-nothing-off) | `noautocorner` is registered as a known option (no "unknown option" warning), but neither `.option autocorner noautocorner` nor a later `set noautocorner` turns the loop off; only `unset autocorner` does — and `noosdimc` behaves the same against `osdimc`, so this is the shared `no`-spelling contract, not E-656's alone | silent no-op |
| [F18](#f18--break-continue-and-disable-are-accepted-in-an-analog-block-without-a-word) | `break`, `continue`, `do … while` and `disable <block>` are accepted in an analog block without a word and act with their SystemVerilog meaning (`disable` ends the block's evaluation, contributions after it included); `>>>` in the same position gets an "openvaf extension" warning, these get none | silent extension |

Dropped after checking the LRM: `casex`/`casez` in an analog block (A.6.7 lists them),
several analog blocks in one module (§6.2 allows them, combined in order), a `timer`
period of zero or less (8.7.2: fires once), `$rdist_*` domain checks (all present, the
literal ones at compile time, the parameter ones as a run-time `$fatal`), `noise_table`
with a concatenation (a decided refusal with a clear message), unknown parameters on an
OSDI `.model` card and a negative multiplier (both warned exactly as for a built-in
device), the `$mfactor` double scaling (the model's own error, LRM 6.3.6).

## What was read and run

LRM sections read for the probes: 2.5–2.6 (literals: `.5`, `5.`, exponent and scale
factor are alternatives in the grammar, based numbers), 2.8.4/10 (directives, macros with
arguments, `` `__LINE__``), 3.4 (parameter ranges, forward references), 3.6.1 (nature
attributes, `abstol` required, `access`), 4.2 (integer division, `%`, `**` Table 5-6,
shifts), 4.5 (`absdelay`, `transition`, `slew`, `laplace`, `limexp`, `ddx`), 5.6.5
(switch branches), 6.2 (multiple analog blocks), 6.3.6 (`$mfactor`), 8.7 (`cross`,
`timer`, `above`, `initial_step`), 9.4 (display formats), 9.7 (`$finish`, `$stop`),
9.13 (`$rdist_*`), 9.16 (`$bound_step`, `$discontinuity`), A.6.7 (`casex`). Probe families:
p1 the corner attribute and `.option corner=` (array, `tt`, alias, value formats, gating,
uniform, `-list` case, string/integer parameters, malformed entries); p2 macros and
directives; p3 integer overflow, folding of math, literals, division and shifts, strings;
p4 analog operators and events; p5 L030, negative delays and periods, formats; p6
contributions, ground, port branches, indirect assignment, declarations, `analog
initial`, loops, hierarchy, disciplines; p7 corners with `wcd`, `highsigma`, `alter`,
`montecarlo -lhs`, `savemc`, raw files, `repeat`; p8 hierarchy names, system-task
domains, `case` forms, block forms; p9 attributes, identifiers, comments, strings; p10
paramsets with corners, model-card edges; p11 noise; p12 natures (three attempts: the
first two collided with disciplines.vams and with the access-name rule, which is F11's
third item); p13 the ngspice side of unknown parameters, multipliers, messages; p14
analog functions; p15 corners under `osdimc`, instance-given nominals, `-lhs`,
`writemc`; p16 `$fatal`/`$finish`/`$stop`, arrays, loops, `$port_connected`,
`$param_given`, attributes on nodes; p17 `$finish` in a transient, bus errors; p18 the
quoted analysis in `sweep` and `corners`, `autocorner` with batch `.meas` and the `meas`
command; p19 parameter ranges; p20 the other analyses under `autocorner`; p21 the
`$rdist` family; p22 display tasks; p23 `corners` option parsing; p24 `autocorner` with
two analyses and loops; p25 `$limit`, `analog initial`, localparam attributes; p26 the
minimal F1 sequences; p27 corner sequences under `osdimc`; p28 ports and connections;
p29 string ranges at run time, saved opvars, arrays with statistics and a corner; p30
operators, events with five arguments, `defparam`, genvar forms; p31 `corners -mc` with
`-track`/`-writemc`, batch `.noise`; p32 the random functions' string forms; p33 every
batch print card under `autocorner`; p34 `analog initial`; p35 more macro forms; p37
string `case`; p38–p39 analog operators in conditionals, `laplace` array forms, the LRM on
`===`; p40 capacity (90-character names, 70 and 1500 corners); p41 `$simparam` names;
p42–p43 events with parameter arguments, `generate`, duplicate declarations, `foreach`
corner loops; p44–p45 corners on paramset-bound parameters, operators under `ac`; p46–p48
large models, the CLI, the loader, the nesting limit; p49–p53 how often `$strobe`,
`$display`, `$bound_step` and `$discontinuity` run; p54–p57 hoisting corollaries, the
corner gate with statistics, sigma corners through lognormal and truncation, the run-time
range judgement; p58–p60 `corners -output` forms, the `no` spellings, temperature and
parameter sweeps under a corner; p61–p65 loop control and other SystemVerilog forms,
casts, `**` associativity (left, both folded and at run time); p66–p68 `reusesetup`,
corners in a child instance, a reloaded object, an uninstantiated model.

## F1 — under `.option osdimc`, the first run at a corner corners only the parameters that carry statistics

```
.option osdimc
.control
op                       * the nominal baseline
set corner=ss
op
print ...                * rsh 100, k 2, ri 1000 (should be 115, 2.2, 1200); vth 0.51 (right)
op
print ...                * now 115, 2.2, 1200
.endc
```

With the E-654 model (`rsh` absolute, `k` a percentage, `ri` an instance absolute, `vth`
a sigma corner on `std=0.02`), a nominal run followed by `set corner=ss` gives, on the
first cornered run, `vth` at its corner and `rsh`, `k`, `ri` at nominal; the second run
at the same corner has all four. Without `.option osdimc` the first run is right. The
same sequence through the loop commands: `corners -output` under `osdimc` prints `ss`
with `rsh` 100 and `ff` with 88 (by `ff` the capture had happened); `autocorner` under
`osdimc` records its first `ss` row with 1000/100/2 and the second pass's with
1200/115/2.2; a `sweep` as the first cornered run shows the same in its `savemc` row.
`montecarlo` and an `altermod` before the corner are not affected (their reset or stale
mark takes the pending path).

Cause, from the E-654 code: the nominal table is filled by `osdimc_capture`, which under
`osdimc` captures the statistical parameters at every setup and the cornered ones only
while a corner is on. After a nominal run under `osdimc` the table is populated (with the
statistical parameters) and not stale, so `OSDImcNewRun` takes the direct path — draws,
then `osdimc_corner_run` — rather than flagging the trial pending for the setup; the
corner writer finds no entry for a corner-only parameter (`!e`) and returns in silence.
The next setup captures them, and the next run applies them. The fix is either to capture
corner-only parameters at every setup as the statistical ones are, or to flag the run
pending when a cornered parameter has no entry yet.

## F2 — a quoted word on the `corners` line keeps its quotes

```
corners -list tt ss -analysis "dc v1 0 1 0.5" -output v(out)
corners: 2 corners (tt ss), analysis '"dc v1 0 1 0.5"'
  0    tt                      nan
  1    ss                      nan
sweep: unknown command '"dc v1 0 1 0.5"'
```

The same spelling on a `sweep` line runs (`analysis 'dc v1 0 1 0.5'`), and `corners
-mc 2 -analysis "tran 1u 3u"` reaches montecarlo intact because the forwarding keeps a
word that already starts with a quote. In plain mode the `-analysis` word is copied
verbatim, quotes included, and `sw_run_cmd` sees a command called `"dc v1 0 1 0.5"`. The
same for `-output "g=v(out) / v(in)"` (recorded as never resolved, the expression carrying
a trailing quote) and `-list "ss ff"` ("'\"ss' is a corner no loaded model declares"). The
E-655 suite tested the quoted form only under `-mc`.

## F3 — a corner named `tt` is accepted and unreachable, and the loop runs the nominal twice

`(* corner="tt=5, nom=6, ss=7" *)` compiles without a word. In ngspice `corner=tt`,
`nom` and `nominal` are the nominal by rule (E-654), so the declared `tt` and `nom`
values can never be selected; and the `corners` command's default set, which puts `tt`
first and then every declared name, becomes `tt tt nom ss` — the nominal run twice under
two names, `nom` a third time. `corners -list TT,SS,ss` runs `ss` twice as well: the
listed names are folded but not deduplicated. The compiler should refuse (or warn on)
the three reserved spellings, and the loop should fold duplicates.

## F4 — a corner on a parameter the model tests with `$param_given` flips its branch

```
(* corner="ss=2" *) parameter real a = 1;
real g;
analog begin g = $param_given(a) ? a : 10; ... end
```

At `corner=ss` with `a` never given, the model computes with `g = 2`: the corner's write
through the setter marks `a` given, and the model takes its given branch. For draws this
is exactly the E-555 hazard, and the compiler exports a gated bit for such parameters —
but only inside the statistics table; a parameter with a corner and no `std` has no
entry there, so the corner writer's gate (`info && osdimc_gated_off(info, e)`) never
fires. The compiler knows the parameter is `$param_given`-tested (`given_tested`); the
corner table needs the same bit, and the writer the same skip and note. With `std` beside
the corner the gate does fire — and its note reads "a draw would switch the model to its
'given' branch … not drawn. Give it on the card, or altermod it, to vary it", which for a
corner names the wrong mechanism.

## F5 — L030 folds an integer division as real

```
parameter integer a = 7/2;      warning[L030]: ... has the default 3.5, which an integer cannot hold
parameter integer b = -7/2;     ... the default -3.5 ...                    (value -3)
parameter integer c = 3*2/4;    ... the default 1.5 ...                     (value 1)
```

The run-time value follows LRM 4.2 (`7/2` is 3, `-7/2` is -3, `3*2/4` is 1) and
`$strobe` prints it so; the lint's own folding evaluates `/` on two integers as a real
division and then complains that the result is not an integer. `7 % 2`, `2 ** -1`,
`(-2) ** -1`, `(-1) ** -3` and `1 << 31` are folded right. A lint that mis-folds teaches
the user to ignore it.

## F6 — `$finish` and `$stop` in the analog block are silent no-ops

`if ($abstime > 3e-6) $finish;` in a transient to 8 µs: the run completes with all 52
points and no message; `$stop` the same; `@(initial_step) $finish(2);` at an operating
point: the point is computed and printed. LRM 9.7.1 says `$finish` "shall cause the
simulator to exit"; ngspice's OSDI runtime honours `$fatal` (aborts the analysis with a
located message) and, per the handbook, a `$finish` during *setup*, but a `$finish`
reached during the solve does nothing. A model that uses `$finish` to stop a transient at
a detected condition runs to `tstop` in silence.

## F7 — the corner loops under `osdimc` redraw the other parameters per corner

```
.option osdimc mcseed=3
corners -output sm:q sm:r
  0    tt                       10            100     * baseline, no draw
  1    ss                    7.196            110     * trial 2's draw of q
  2    ff                  10.4617             90     * trial 3's
  3    fs                  10.8352            100
```

Each corner run is a run-class command, so under `.option osdimc` each is a new trial:
the cornered parameters are pinned (E-654) but the uncornered statistical ones draw
afresh, and the corner-to-corner difference of any output carries a fresh mismatch draw
inside it. `sweep` holds one trial across its points for exactly this reason
(`OSDImcHoldTrial`); `corners` and `autocorner` do not, and nothing says so. Under
`-mc N` a fresh draw per sample is the point; in plain mode the corners should share one
trial (or the nominal), or the banner should say the draws move.

## F8 — `autocorner` follow-on gaps

- **A raw-file `run`** (`run n5.raw` under `.option autocorner`): each corner writes the
  raw file, the loop then reports `autocorner: corner tt: the run made no plot` four
  times and builds no combined plot. The runs did succeed, into the file; the file holds
  the last corner (documented) but the message is wrong.
- **`meas tran` after an `autocorner` transient:** `Error: meas tran: the current plot is
  'autocorner1', not a tran analysis.` The combined plot is typed `autocorner`, so the
  per-corner waveforms it holds (`v(out_ss)`) cannot be measured without `setplot tran2`
  first — and then the corner vectors are in a different plot. Batch `.meas` cards do
  work: they run on every `tran` plot (E-602), once per corner.
- **`writemc` after an `autocorner` run:** "the current plot autocorner1 was made after
  row 4 by a run that has no row; nothing is put on that row" — the combined plot is not
  a run's plot, so the natural `writemc y=v(out)` has nowhere to land.
- **Saved `@dev[param]` vectors get copies that only a quoted name reaches.** With a
  `.save all` card naming `@rm[rsh]`, the combined plot lists the copies `@rm[rsh]_ss`
  and `@rm[rsh]_ff` (`display` shows them); a bare `print` of such a name reads the
  parameter and a stray `_ss`, `let` refuses it as an invalid right-hand side, and only
  the quoted form `print "@rm[rsh]_ss"` prints the 115.
- **The devices are left at the last corner.** After the loop the parameters hold the last
  corner's values (`showmod rm` shows `rsh 88`) until the next run; `show`/`showmod` say
  nothing, while the current plot is the combined one.

## F9 — `wcd` counts cornered parameters as dimensions

Under `.option osdimc corner=ss` with three of the four model-declared statistical
parameters cornered, `wcd` announces "4 statistical dimensions (4 model-declared)" and
ends with "the metric does not respond to any statistical parameter (zero gradient) --
cannot locate an MPFP". E-654 consumes and ignores a walk coordinate on a cornered
parameter so the dimensions do not shift, but the count, the search and the message all
treat the held axes as free; the honest count is 1, and the honest message names the
three held by the corner.

## F10 — a corner that moves a paramset's own parameter out of its member aborts with a generic error

Two `rs` paramsets over one module, members `l from (0:2u]` and `l from (2u:inf)`, both
with `(* corner="ss=+20%" *)` on `l`; the instance gives `l=1.9u`, selecting the first
member at nominal. `.option corner=ss` writes `l = 2.28u`, outside that member's range,
and the run ends with `doAnalyses: 1 errors occurred during initialization detected in
routine "OSDI setup_instance (OSDItemp)"` — nothing names the corner, the parameter or the
member. Under the `corners` command the `tt` row is right and the `ss` row is "(the
analysis failed)". Either the selection should be re-judged with the cornered value, or
the failure should say "corner ss moves l to 2.28u, outside member 1's range (0:2u]".

## F11 — diagnostic slips

- `parameter real r = 1e3n;` → `unexpected token identifier; expected 'exclude' or
  'from'`; `0.5e` and `1meg` the same. The lexer ends the number before the letters and
  the parser complains about the leftovers in the range-clause vocabulary. E-650 gave the
  malformed-literal cases a located message of their own; these three fall through it.
  The refusal itself is right (the LRM grammar has an exponent or a scale factor, not
  both; `1meg` is SPICE).
- `electrical a[0:1]; analog I(a[2], n) <+ …` → `could not compile
  `r3.va__namerange.va` due to 3 previous errors`: the summary names an internal
  rewritten file. A bus *port* out of range (`a[5]` on `inout [0:1] a`) names the source
  file. The leak is specific to internal node arrays.
- A nature whose `access` function has the nature's own name (`nature Qx; access =
  Qx;`) → `'Qx' was already declared in this scope`, then `discipline 'dd' names 'Qx' as
  its flow, which is not a nature` and `illegal access of branch` — four errors, none
  saying the access name must differ from the nature's.
- `forever begin … end` in an analog block → `unexpected token 'begin'; expected ';'`
  and `'forever' was not found in the current scope`. It is not an analog statement
  (A.6.4: `repeat`, `while`, `for`); say so.
- `parameter real rö = 1;` → `encountered unexpected token!` twice, the only message in
  the compiler with no noun.
- `` `ifdef Z 6 `` → `unexpected token integer; expected 'discipline', 'nature' or
  'module'`: the `6` after the macro name is handed to the parser as source.
- `(* desc= *)` → `unexpected token '*)'; expected '(', ''{', '{', system function
  identifier, identifier, …` (the generic expression-start list).
- `` `undef X `` then `` `X `` → `macro '`X' has not been declared` and a knock-on
  `unexpected token ';'` (the macro-argument mismatches cascade the same way).
- `(* corner="ss=0.5 %" *)` → `corner entry '%' is malformed`: `ss=0.5` was accepted as
  an absolute value and the stray `%` blamed; the intent was a percentage.

## F12 — run-time domain silences

The literal forms are refused at compile time (`absdelay(V(p,n), -1e-9)`,
`$bound_step(-1e-9)`, `slew(…, 0.0)`, `transition(…, 0, -1e-9)`), but:

- `parameter real td = -1e-9; … absdelay(V(p,n), td)` and `real td; td = -1e-9;
  absdelay(V(p,n), td)` compile and run without a word (LRM 4.5.7: the delay must be
  non-negative);
- `parameter real bs = -1e-9; … $bound_step(bs)` the same;
- `$discontinuity(-1)` is accepted (the order must be ≥ 0).

E-651 named the deck-fixed projections for the distributions and noise; these three
operators are outside that guard.

## F13 — three declaration checks that do not fire

- `parameter string s = "z" from {"x", "y"};` compiles without L027 (the real and
  integer cases warn); at run time the default is accepted too (only a given value is
  judged), so the parameter runs at a value its own range excludes.
- A base nature with no `abstol` compiles and runs; LRM 3.6.1: "This attribute is
  required for all base natures". The node then carries the potential nature's tolerance
  alone.
- `parameter real \foo+bar = 1;` exports a parameter named `foo+bar`, which ngspice's
  expression parser reads as a subtraction; the E-652 lint covers `$` only.

## F14 — more than 64 corners, or a name of 80 characters, cannot be selected

A model declaring `c0 … c69` (70 corners compile without a word; 1500 do too):
`.option corner=c69` → `Error: .option corner=c69: no loaded Verilog-A model declares a
corner of that name (declared: c0, c1, …)` while `c63` selects. `autocorner` announces
"op at 64 corners (tt c0 … c62)" and `corners` the same 64: the names are collected into
a 64-slot array (`osdimc_corner_collect` with cap 64, `CO_MAXCORNERS`) and the overflow
is dropped in silence by the check, the loops and the "declared:" list alike — so a real
declared corner is reported as undeclared. A corner named with 90 characters compiles;
in ngspice `Warning: string length for variable corner is limited to 80 chars` truncates
the selection and the truncated name is then refused, and the `corners` loop's own
`set corner=` of that name fails the same way ("(the analysis failed)"). The compiler
should refuse a corner name longer than 79 characters and the simulator should either
grow the table or say that it is full.

## F15 — the nesting limit trips on a flat sum of a thousand parameters, and recovers with nonsense

`I(p,n) <+ … + 0*(p0+p1+…+p998)` over 999 declared parameters: `error: expression nests
too deeply`, then `'p997' was not found in the current scope`, then `'p998' was already
declared in this scope` — two follow-on errors about declarations that are fine. The same
sum over 600 parameters compiles, and 999 literal terms compile (folded). A left-associated
chain of `+` is a flat expression to the author and a deep tree to the parser; generated
models (a polynomial with many terms, a table unrolled into a sum) can reach it. The limit
is the E-6xx depth hardening doing its job; the cascade after it is not.

## F16 — a `$strobe` with solution-independent arguments runs in the setup pass, not per point

```
analog begin $strobe("S"); I(p,n) <+ V(p,n)*1e-3; end        -> op: 2 lines; tran of 73 points: 2 lines
analog begin y = 3; $strobe("S y=%g", y); ... end             -> the same
analog begin $strobe("S v=%g", V(p,n)); ... end               -> op: 1 line; tran: 73 lines
analog begin k = k + 1; $strobe("S k=%d", k); ... end         -> op: 1 line
```

An `ac lin 3` followed by a `dc` of 3 points gives four lines of the constant strobe.
The 09-07 hunt established "`$strobe` prints once per accepted point", and it does for a
strobe that reads the solution or a variable with state; a strobe whose arguments are
constants (or variables computed from constants) is carried by the init-resident
evaluation alone — the setup pass that E-476/E-535 run the solution-independent code in,
which ngspice performs twice per analysis (setup and the temperature pass) — so it prints
twice per analysis and never per point. LRM 9.4: `$strobe` executes at the end of every
time step it is reached in. `$info`, `$warning` and `$error` with constant arguments
double the same way (the p16 probe printed each twice per op), and every constant
`$strobe` in the hour's probes did too, before the cause was isolated. A strobe of a
parameter, of `$temperature` or of `$mfactor` is hoisted the same way (two lines per
transient); one of `$abstime` is not (73). A model's per-point trace that happens to
print only parameters is silent during the sweep. Under `.option corner=ss` the two
setup-pass lines straddle the corner's write: a banner of a cornered parameter prints
`rsh=100` and then `rsh=115` for one operating point. The hoisting follows the argument, not
the statement: a constant strobe inside a genvar loop prints its three lines twice per
transient, one inside an analog function called with a constant twice, one beside a
per-point strobe twice against the other's 73, and one under `if (analysis("tran"))` or
of a variable that a solution-dependent branch may assign prints per point.

## F17 — `noautocorner` is a known option that turns nothing off

E-656 added `autocorner` and `noautocorner` to the known-option list, following E-572's
rule that the documented `no` spelling of an option is honoured. `.option noautocorner`
alone is quiet (nothing was on); `.option autocorner noautocorner` on one card loops
every run, and `set noautocorner` in a control block after a deck's `.option autocorner`
loops too (`$autocorner_n` is set after the `op`). The hook reads only
`cp_getvar("autocorner", CP_BOOL)`, so the `no` spelling is accepted and ignored —
the failure E-445's note describes, a setting that is not reported and not honoured.
`.option osdimc noosdimc` and `.option osdimc` followed by `set noosdimc` draw on trial 2
just the same, so the contract is the shared one of every `no` spelling on the known list:
quiet, and effective only when the positive was never set. The handbook says `unset`;
the option reader could also let the `no` spelling win when both are present.

## F18 — `break`, `continue` and `disable` are accepted in an analog block without a word

```
for (i = 0; i < 5; i = i + 1) begin if (i == 2) break; s = s + 1; end      -> s = 2
for (i = 0; i < 5; i = i + 1) begin if (i == 2) continue; s = s + 1; end   -> s = 4
analog begin : blk  s = 1; disable blk; s = 2; $strobe(...); I(p,n) <+ ...; end  -> nothing printed
```

None of the three is Verilog-A (A.6.4 has `repeat`, `while`, `for`; `disable` and the
loop-control keywords are SystemVerilog and digital Verilog), and none draws a
diagnostic, while `>>>` in an analog block is warned as "an openvaf extension" (L0xx
non_standard_code). `break`/`continue` at least do what a SystemVerilog reader expects; a
`disable` of the analog block's own name ends the evaluation there, so the
contributions after it are skipped in silence, which is a model that compiles everywhere
and behaves differently here. `do … while` is accepted in silence too (`do s = s + 1; while
(s < 3);` gives 3). `return` outside a function, `goto`, `unique case`, `assign`, `wire`,
`initial`/`always` are refused.

## Smaller notes (not pursued)

- `parameter real r = 5.;` is accepted (the LRM wants a digit on each side of the point;
  `.5` is refused); `1e-400` becomes 0 in silence.
- `altermod mm k=2.5` on an integer parameter rounds to 3 without the note the `.model`
  card prints for the same value.
- A sigma corner on a uniform beyond one half-width (`+5sigma` on `dist="uniform"`)
  lands where no draw can (15 for a 10 ± 1) without a word.
- `$strobe("%d", 2.5)` is a type error; other simulators round. `$strobe()` with no
  arguments prints nothing, not an empty line. `%l` prints `__.__`.
- Duplicate `desc` attributes and a duplicate `case` item are silent (the last and the
  first win); an analog function that never assigns its return value returns 0 in silence.
- A corner on an array parameter applies to every element; `corners -analysis a
  -analysis b` takes the last; `corners -mc 2 -mc 3` forwards the second to montecarlo,
  which refuses it and the row reads "(montecarlo published nothing)".
- `$limit` with a user function passes `(value, old_value, args…)`, so a two-input
  function gets "expected 2 arguments but found 3" — right by LRM 9.17.4, surprising in
  the message.
- After `set corner=TT` the variable reads back as `tt` (the control block folds it).
- `laplace_zp` with an odd-length zero list (`'{-1e6, 0, 5}`) is refused as "numerator
  order 2 against a denominator of order 1" rather than as an odd number of (real,
  imaginary) values; the empty array literal `'{}` is accepted, only the concatenation
  `{}` is refused (consistently with `noise_table`).
- `===` and `!==` are accepted in an analog block and evaluate as `==`/`!=` on reals;
  LRM 7.3.2 lists them as the way to read X/Z of discrete nets, so this is legal.
- A corner on a target-module parameter that a paramset binds (`.r = …`) is dropped with
  the localparam warning: the paramset fold makes the bound parameter local, so the corner
  has to go on the paramset's own parameter (which works, and the binding follows it).
- `$simparam("nosuch")` with no default is warned at compile time (L025) and runs in
  silence; LRM 9.15 wants a run-time error when the name is unknown and no default given.
- `pre_osdi` of a file that is not a shared object prints the whole `dlopen` search list
  (six paths) before "couldn't be loaded"; the one useful phrase is "slice is not valid
  mach-o file".
- An unconditional `$discontinuity(0)` drives a 3 µs transient to 670,008 accepted points
  (against 73) in silence: the integrator restarts at every point, as the LRM says it
  must, and nothing notes that the model asks for it every time.
- `$corners_names` (and `$autocorner_names`, `$autocorner_plots`) is one word to
  `foreach`: `foreach c $corners_names` runs once with `c` = `tt ss`. A list variable
  (`set corners_names = ( tt ss )`) would iterate; the string form suits `echo`.
- Two `.option corner=` cards in one deck (`ss` then `ff`): the first wins, in silence
  (ngspice's rule for option variables, not E-654's); the `option` command in a control
  block and `set corner=` switch as expected, and a `set` before the first run overrides
  the deck's card.
- A `.model` card of a corner-declaring module with no instance: `corners` says "no loaded
  Verilog-A model declares a corner" — the model is loaded and declares two; it is not
  instantiated, which is what the message should say.
- `\<newline>` inside a string literal continues the string (`"abc\<nl>def"` prints
  `abcdef`); the LRM says a string is contained on one line.

## Coverage, honestly

Not touched this hour: `$table_model`, the IHP library, KLU, the RF analyses, the
statistics attributes beyond their corner interplay, the shared-library path of
`autocorner` (only `run` in a `.control` block stood in for it), interrupts inside the
corner loops, the `-b` raw-file path beyond one probe, `` `include `` search paths, and
the E-650 slips (all still as fixed). Checked and clean, for the record: every `$rdist`
domain, `noise` under every form tried, batch print and `.meas` cards under `autocorner`,
`analog initial`, `generate`, `defparam`, `foreach`-driven corner loops, `reusesetup`
under corners, a reloaded object, `**` associativity, the CLI's refusals. The nature probes cost three attempts (two on my
own harness), so nature/discipline coverage is thinner than planned: `ddt_nature` cycles
and a self `idt_nature` compile in silence, which may or may not matter (openvaf does not
consult them).
