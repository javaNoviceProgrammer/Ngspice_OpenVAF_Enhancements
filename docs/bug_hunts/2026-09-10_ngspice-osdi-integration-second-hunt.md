# ngspice + OSDI integration — a second one-hour hunt

**Date:** 2026-09-10, 19:58 to 20:58 local time (probing to 20:45, the rest on this write-up), about 190 decks and 75 small Verilog-A
models (many generated for the F1 bisection), both solvers where a value was compared. **Rule:** probe, record, move on;
nothing was fixed. Every deck and model is in the scratchpad (`hunt5/`). This follows the
2026-09-04 integration hunt and the 2026-09-02 general and untouched-areas hunts; the
aim was the surfaces those left open — every analysis type on an OSDI device against
its built-in twin, temperature and `m` in hierarchy, the parameter-access grammar
(`alter`, `altermod`, `.dc`, aliases, binning), the deck-level I/O of OSDI vectors
(`.probe`, `.save`, `write`, `load`, `-r`), the instance-line and model-card parsers on
malformed input, and the `$simparam` channel end to end.

**Toolchain:** commit abeddbe8 (E-595), `ngspice-46/build/src/ngspice` and
`OpenVAF-master-20260610/target/opt/openvaf-r` as built.

## Summary

| # | Finding | Severity |
|---|---|---|
| F1 | A model that reads `$simparam("gmin")` **without a default** and then nine more `$simparam` names with defaults gets the **wrong value for the tenth**: `$simparam("vntol", -1)` returns gmin (3e-11 with `.option gmin=3e-11`), `$simparam("reltol", -1)` in the same slot returns gmin too. The literal `vntol` is absent from the compiled object. Compiler side. | wrong value, silent |
| F2 | A **bare parameter word** at the end of an OSDI instance line — `n1 a b am w=2 m` — is taken as `m=0` and the device vanishes without a message; `temp` alone gives 0 °C; a bare `w` after `w=2` gives `w=0` and the range refusal names no value. Built-in devices do the same for `m`, but print "can't find model 'm'" first. | silent wrong result |
| F3 | `$simparam$str(name, default)` — the two-argument form — is refused at compile time ("expected 1 arguments but found 2") although the backend has the non-fatal `simparam_str_opt` callback (E-215 uses it for plusargs). A model has no way to ask for a string simparam without a `$fatal` on the names ngspice does not serve. | language gap |
| F4 | A card-level default of an **instance** parameter (`.model am alias width=3`, honoured: the instance without `w` reads 3) is invisible to `showmod am` and cannot be moved by `altermod am width=5`, whose refusal text itself says "write width=... on the .model card, where it is the instances' default". | inconsistency |
| F5 | **A `pre_osdi -f` written after a mid-block `shell` recompile runs before it and says "reloaded".** Every `pre_osdi` line, wherever it sits in a control block, is hoisted into the pre-pass (`inpcom.c`), so the one written after `shell ./rebuild.sh` reloads the *old* object before the circuit is parsed, prints "reloaded (3 devices)", and at execution time is skipped; `@ma[r]` stays 1000 after `reset` and for a freshly sourced deck. `osdi -f` in the same place works as E-229 documents. Typed interactively, `pre_osdi` is "no such command". | misleading success |
| D1 | `save @n1[opvar]` before any analysis prints **two** warnings for the one item ("is an operating-point variable and no operating point has been computed" and "has no value yet ... recorded per point once an analysis runs"), and prints them for a save `.option saveused` inferred and the user never wrote — the case E-496 silenced for the unmatched-name warning. | noise |
| D2 | An `n` line whose `.model` type belongs to no loaded OSDI file gets "Unable to find definition of model ma" — the card *is* there; the unknown **type** is the cause, and a plain `osdi` in the control block (which runs after parsing) is the way a user lands here. The binning miss (no bin covers `l=50u`) gets the same sentence. | diagnostic gap |
| D3 | Reading an operating-point variable through the model name (`@km[lvo]`) answers with E-560's *instance parameter* message, "declared (* type="instance" *) ...", for something that is not a parameter at all. | misleading text |
| D4 | The integer range refusal omits the value ("out of bounds; range from [1:3]!") where the real one shows it; for a rounded integer the rounded value is what the reader needs. A line with both a duplicate and an alias conflict (`w=2 w=3 width=4`) gets the generic "parameter value out of range or the wrong type" instead of either specific message. | diagnostic slips |
| N1 | `showmod x1.tm` / `showmod x1:tm` find nothing while `altermod` accepts both spellings and `showmod x1.n1` shows the model. Stock, built-in models too. | not OSDI |
| N2 | A device-internal node (`n1#mid`, `d1#internal`) is invisible to `.ic`, `.nodeset`, `pz` and `tf` ("non-existent node"), though `print v(n1#mid)` and `save` see it. Stock: internal nodes are created at setup, after pass 3. E-45's net initializer is the Verilog-A route. | not OSDI |
| N3 | A `.probe` card **after a `.control` block** prints ".save: no such command available in ngspice" (the `.probe`→`.save` rewrite lands in the earlier block). The probe still works. Every OSDI deck has a leading `pre_osdi` block, so every OSDI user with a `.probe` sees this. | not OSDI, cosmetic |
| N4 | The raw-file writer names a current-typed `@dev[param]` vector `i(@n1[i_p])`; after `load` neither `@n1[i_p]` nor `i(@n1[i_p])` reaches it. Stock (`@r1[i]` the same); every OSDI port current written with `write`/`-r` is affected. | not OSDI |
| N5 | `w=nan` or a trailing `w=` on an instance line is a numparam "fatal error in ngspice, exit(1)" — the process exits, built-in lines too — where `1e400` gets a line-level refusal. | not OSDI, harsh |
| N6 | **Two dot cards naming the same vector for different analyses lose the second analysis.** `.print dc v(a)` beside `.print tran v(a)` in a batch deck: "no data saved for Transient analysis; analysis not run" — `settrace`'s dedup keeps one `save` per node name and ignores the analysis restriction, so the transient has no save at all. `.meas dc ... v(a)` beside a `.tran` does the same to the transient, and beside a `.dc` a `.meas tran` kills the dc. The sibling of the `ft_getSaves` dedup E-594 fixed today. Stock. | **analysis lost**, not OSDI |
| N7 | Batch `.noise` with `.print noise onoise_spectrum`: the integrated-totals plot (noise2) is refused "no data saved for Noise analysis" because the print's saves are restricted to NOISE and name only spectrum vectors, with two spurious "can't parse 'onoise_spectrum'" warnings on the way; the spectrum table prints. Stock. | plot lost, not OSDI |

Everything else probed held, and the table at the end says what.

## F1 — `$simparam` returns the wrong slot after nine reads

```verilog
(* desc="g" *) real g;  (* desc="o0" *) real o0; ... (* desc="o8" *) real o8;
analog begin
  g  = $simparam("gmin");                    // no default -- the fatal form
  o0 = $simparam("iteration", -1);
  o1 = $simparam("sourceScaleFactor", -1);
  o2 = $simparam("abstol", -1);
  o3 = $simparam("reltol", -1);
  o4 = $simparam("tnom", -1);
  o5 = $simparam("noSuchParam", 42);
  o6 = $simparam("maxIntegOrder", -1);
  o7 = $simparam("timeStep", -1);
  o8 = $simparam("vntol", -1);               // <-- returns gmin's value
```

With `.option vntol=1e-5 gmin=3e-11`: `o8 = 3e-11`. Every other read is right (o2 =
abstol, o3 = reltol, o5 = 42, o7 = -1). What was established by bisection, forty models:

- The misread is the **tenth** `$simparam` call when the **first** is the no-default
  form. Nine calls in total: right. Ten with every call in the default form: right. Two
  no-default calls and eight default ones: right. Reading `vntol` *first*: right. The
  no-default read placed sixth or last among eleven: every read right — only the
  first-position form breaks the tenth call.
- It is not the name. The tenth slot returns the no-default read's value whatever the
  tenth name is: `reltol` there → gmin; and with `$simparam("abstol")` as the first read,
  `vntol` there → abstol's value (7e-13).
- ngspice's side is clean: `sim_params[]` and the value fill in `get_simparams`
  (`osdiload.c`) are aligned, and the stdlib lookup (`SCMP`) is an exact match.
- The compiled object does not contain the string `vntol` at all (`strings vx9.osdi`
  lists the other nine names and the codegen's `unknown $simparam ` prefix); the pointer
  handed to `simparam_opt` for the tenth call therefore names another literal. Adding
  unrelated string literals to the module (a string parameter, a `$strobe` format) makes
  `vntol` appear and the read correct — the defect is in how the literal table is laid
  out or indexed when the no-default callback's own literal is added, not in the
  lookup.

Reproducer: `hunt5/f1_repro.va` (= `vx9.va`) with `vx9.cir`. Where to look:
`mir_llvm/src/context.rs` (`const_str`, `str_lit_cache` keyed by `Spur`) and whoever
interns `unknown $simparam ` for the fatal callback — the literal may be interned into
a different `Rodeo` than the one the codegen resolves against. A real compact model
that reads ten simparams is not exotic (gmin, iniLim, sourceScaleFactor, tnom, scale,
plus a few tolerances), and the symptom is a silently wrong tolerance or scale.

**Status (2026-09-10):** resolved by Enhancement-596. The cause was one word in the
optimiser: global value numbering's equality test for a call expression read both payloads
from `self`, so any two side-effect-free calls that met in the same hash-table probe were
"equal" whatever the callee and arguments -- the threshold and the position dependence
were the probe sequence. Every such callback (`ddx`, string compares, `$simparam$str`,
`%m`, `$port_connected`, `$param_given`) was exposed. Fixed, with the GVN test module
wired in and two tests that fail on the old line.

## F2 — a bare word on the instance line is a zero

| line | result |
|---|---|
| `n1 a b am w=2 m` | `@n1[m] = 0`, `i(v1) = 0`; no message |
| `n1 a b am w=2 temp` | `@n1[temp] = 0` (0 °C); no message |
| `n1 a b am w=2 dtemp` | `dtemp = 0`, harmless by luck |
| `n1 a b am w=2 w` | E-480's duplicate warning, then "1 errors occurred during initialization ... OSDI setup_instance" — the range refusal for `w=0` gives no value |
| `n1 a b am m w=2` (bare word first) | "can't find model 'm'" — refused |
| `r1 a 0 1k m` (built-in) | "warning, can't find model 'm'", then `@r1[m] = 0`: the same zero, with a warning that names the wrong cause |

A parameter name without `=value` after a `name=value` is a typo (`m 2`, `m=`, a lost
`=2`) and the parser turns it into `name=0`. For `m` that deletes the device from every
analysis silently. An OSDI line should refuse a bare word ("parameter 'm' given without
a value") — or, if ngspice's built-in grammar is to be kept, at least say what it did.

**Status (2026-09-10):** resolved by Enhancement-597. A scalar parameter whose value is
missing or did not parse is refused on the instance line and on the card's instance
defaults, with the shape named; the deck reader keeps the card a trailing bare word
hides, so `n1 a 0 im k` is explained as a parameter without a value rather than a
missing model `k`. An integer that does not fit is refused on the line as it was on the
card. `tag=""`, the `off` flag and `m=0` are unchanged.

## F3 — `$simparam$str` cannot take a default

```
error: invalid argument count: expected 1 arguments but found 2
   $strobe("module=%s", $simparam$str("module", "dflt"));
```

`$simparam(name, default)` is the documented non-fatal form and works; the string
variant has the same optional second argument in the LRM's syntax (9.15.1), and the
backend already carries `CallBackKind::SimParamStrOpt` → `simparam_str_opt` for the
plusargs lowering (E-215). Only the front end's arity for `simparam_str` is 1. Without
it, `$simparam$str("instance")`, `"module"` and `"path"` — which ngspice deliberately
does not serve (`osdiload.c`) — are a run-time `$fatal` at the operating point, with no
way for a portable model to ask politely. (`analysis_name`, `analysis_type`, `cwd`,
`simulator` are served and were verified.)

**Status (2026-09-10):** resolved by Enhancement-598. `$simparam$str` takes the LRM's
optional default; the two-argument form lowers to the callback E-215 already carried, the
L025 check applies to the one-argument forms only, and its help is spelled in the calling
form.

## F4 — the card-level default of an instance parameter

`.model am alias width=3 r=1k` with `n1 a 0 am w=2` and `n2 a 0 am`: `@n1[w] = 2`,
`@n2[w] = 3` — the card's value is the instances' default, as E-546's write-up says.
But `showmod am` lists `r` and `rg` only, and `altermod am width=5` is refused with
E-560's text, whose last clause recommends the very card that cannot be changed. Either
the card default is a model-level quantity (then `showmod` should list it and
`altermod` move it, for the instances that did not give their own) or it is not (then
the card should not accept it). The first is what a user sweeping a PDK's card-level
`w` default expects.

**Status (2026-09-10):** resolved by Enhancement-599. The parser records which instances
took the card's default and which set their own, so `altermod` moves the default onto the
followers, records it on the card and says what it did; `showmod` lists the card's
instance defaults; the read-side refusal names the card's value.

## F5 — `pre_osdi -f` after a recompile reloads before it

```
.control
op
print @ma[r]              -> 1000
shell ./rebuild.sh        (the .va now says r = 4k; openvaf-r rebuilt two.osdi)
pre_osdi -f two.osdi      -> Note(osdi): reloaded ".../two.osdi" (3 devices)
op
print @ma[r]              -> 1000   (osdi -f here: refused, "built against the previous ...")
reset
op
print @ma[r]              -> 1000   (osdi -f: 4000)
source again.cir          -> 1000   (osdi -f: 4000)
.endc
```

The note is printed **before** `op` runs — before the circuit is even parsed. `inpcom.c`
collects every line that begins with `pre_` from every control block and runs them in the
pre-pass, whatever their position, so the `pre_osdi -f` reloads the unchanged object, and
the `shell` that rebuilds it runs later. At execution time the line is gone (`pre_osdi`
typed at the prompt answers "no such command available in ngspice"). Re-`source`-ing a
deck whose leading block carries `pre_osdi -f` after the rebuild works, and so does
`osdi -f` at execution time, exactly as E-229 and hunt F16 pinned. The trap is that the
spelling every deck uses reports a reload it did not do at the point the deck says it did.
Two fixes fit: make `pre_osdi` an ordinary command at execution time as well (the
hoisting stays for the leading block), or have the hoisted `-f` say "in the pre-pass,
before the circuit".

**Status (2026-09-10):** resolved by Enhancement-599. A `pre_osdi -f` behind other commands
in its block gets a Note at the pre-pass naming `osdi -f` as the form that acts there;
`pre_osdi` is a live command at the prompt; and the forced reload's staged copy resolves a
relative name the way the first load did.

## D1 — the opvar save warns twice, and under saveused

```
Warning: @n1[rt] is an operating-point variable and no operating point has been computed for n1, so it has no value.
Warning: save '@n1[rt]': 'rt' has no value yet -- it is an operating-point variable and no analysis has computed one. It is recorded per point once an analysis runs.
```

Both for one `save @n1[rt]` before the sweep — the first from the accessor read, the
second from E-418's save check. And with `.option saveused` and `print @n1[gd]` after a
`dc`, both still print, for a save the deck never wrote; E-496 marks inferred saves
precisely so their noise is not reported. The per-point recording is right in every case
(the `dc temp` table below).

**Status (2026-09-11):** D1 resolved by Enhancement-600 -- the device is quiet under
beginPlot's probe, so the E-418 sentence is the only one, and an inferred save gets none.

## D2, D3, D4 — diagnostic slips

- `osdi file.osdi` in the control block instead of `pre_osdi` → the netlist is parsed
  first, the card `.model ma resa` has an unknown type, and the instance line fails with
  "Unable to find definition of model ma". Nothing says the type is unknown, nothing
  mentions `pre_osdi`. An instance outside every bin of a binned OSDI model
  (`nv.1`, `nv.2`, E-495) gets the same sentence; "no bin of nv covers w=1u l=50u" is
  what the reader needs.
- **Status (2026-09-11):** D2 resolved by Enhancement-600 -- pass 1 remembers the cards it
  dropped for an unknown type and `INPgetMod` names the card, its line, the type and
  `pre_osdi`; a bin miss lists the bins and the instance's `l` and `w`.
- `print @km[lvo]` for an opvar → "'lvo' is an INSTANCE parameter of model 'km'
  (declared (* type="instance" *) ...)".
- `k=0.4` on an integer `from [1:3]` → "Parameter k of 'rm' is out of bounds; range
  from [1:3]!" — the rounded value 0 is the point. `n1 a b am w=2 w=3 width=4` →
  "parameter value out of range or the wrong type"; alone, `w=2 w=3` gets the duplicate
  warning and `w=2 width=4` the LRM 3.4.7 alias error, both precise.

## N6 — one save per node name, whatever the analysis

```
.dc v1 0 1 0.5
.tran 10u 1m
.print dc v(a)
.print tran v(a)
```

```
Error: no data saved for Transient analysis; analysis not run
Error: .print: no tran analysis found.
```

Swap the two cards and it is the dc that is not run. `.print dc v(a)` beside `.print tran
v(b)` runs both. `ft_savedotargs` registers each card's vectors as a `save` restricted to
the card's analysis; `settrace` (`breakp2.c`) refuses a second `save` of a node name it
already holds, without looking at `db_analysis`, so `a` stays restricted to DC and the
transient's `beginPlot` finds nothing to save. A `.meas` card registers its vectors the
same way, so `.meas dc vmax max v(a)` beside a `.tran` — a common deck — silently loses
the transient, and beside a `.dc` a `.meas tran` loses the dc; only `.save all` or a
control block rescues it. The E-594 fix made `ft_getSaves`'s dedup respect the analysis;
this is the same defect one level up, at insert time, and the fix is the same test.

**Status (2026-09-11):** D3 and D4 resolved by Enhancement-601 -- a read-only entry of
the instance table is named as an operating-point quantity, read and write, on the model
and on the instance; an integer or string out of range shows its value; the
duplicate-plus-alias line reaches the alias error since Enhancement-597.

**Status (2026-09-11):** N6 resolved by Enhancement-602 -- `settrace`'s dedup respects the
analysis restriction as `ft_getSaves`'s does since E-594, a batch run evaluates the `.meas`
cards of every analysis it produced, and the measure header names the analysis being
evaluated.

**Status (2026-09-11):** N7 resolved by Enhancement-603 -- the noise analysis tells the front
end how many plots follow, a plot of the sequence the saves do not reach is kept whole, the
unmatched-name warning is deferred and printed once, the false "can't parse" is gone, the
integrated plot's `OUTpBeginPlot` result is checked, and a `.print noise` card prints from
each plot what it holds.

## What held

| area | probes | result |
|---|---|---|
| analog operators in tran | `idt`, `idtmod`, `laplace_nd`, `transition`, `slew`, `absdelay` on a pulse | every value matches the closed form (0.632 at one τ for the lowpass, 5e-9 for the integral, the delayed edge at 2 µs) |
| every analysis vs the built-in twin | `pz` (pole −2·10⁶), `tf` (0.5, 500 Ω, 2 kΩ), `sens` DC and AC (every entry identical incl. the complex ones), `noise` (onoise/inoise totals to 6 digits), `ac`, `disto`, `sp` with `NF` (13.222 dB), `tran` and `tran uic` — KLU and Sparse | identical |
| temperature | `.temp`, `.option temp`, instance `temp`, `dtemp`, `set temp`, `dc temp` per point, `.option tnom` → `$simparam("tnom")`, `$vt`, a model caching T in `initial_step` across `dc temp`/`alter temp`/`tran` | right everywhere; the model's own `tnom` parameter is independent of `.option tnom` (Verilog-A semantics; noted below) |
| `m` | instance `m`, `$mfactor`, nested `x1 m=5 → x1 m=2 → n1 m=3` = 30, `m=2` vs two instances vs built-in `m=2` for op/noise/ac, `m=0.5`, `m=0` | identical; `m=0` is silent like the built-in |
| parameter access | `.param`/`.func` into subckt instance and card params, `@x1.n1[p]`, `@x1.tm[p]`, `alter @x1.n1[..]`, `altermod x2.tm` (dot and colon), `alter x1.n1 temp`, `aliasparam` on card, line, `@`, `alter`, `altermod`, `$param_given` via card vs line, `localparam` refusal, keyword-named params (`off`, `ic`, `area`, `Rs`, `Level`), mixed case, long names, `n.dot` | all right |
| `.dc` sweeps | instance and model params through hierarchy, alias names, reversed direction, nested with another OSDI param and with a source | every point right; the swept value is restored after the sweep |
| deck I/O | `.option savecurrents` (`@n1[i]`, `[i_p]`, `[i_n]`), `.probe i(n1)` (→ `n1#branch`), `meas integ` on all three spellings, `fourier`, `wrdata`, `write`, `load`, `-r` with `.save`/`.print` cards | right except N3/N4 |
| loading | three modules in one file with one instantiating the others, `pre_osdi` in an `.include`d file, a card in a `.lib` section, `.if/.else` around instances, two decks sourced with the same file (skip note), `setcirc`/`remcirc`, a module named like the XSPICE `gain` (E-542's collision handling, both usable), binning by `l` | right |
| runtime | `alter`/`altermod` between `stop` and `resume` (picked up), `$warning`/`$error` per timepoint, `$fatal` aborting the transient with the 33 points kept and the deck continuing, `$bound_step` 1p (10⁵ steps) and 1e-20 (capped at 10⁶ with a warning), `ddx` vs the AC conductance (4.5899e-3) | right |
| formats and ranges | `$strobe` `%d %5.2f %e %g %s %% %m %b %h %o %c`, an integer given 2.7 (rounded with a warning), extra arguments printed in default format, `from (0:10] exclude 5`, `exclude (2:3)`, `1e-320`, `1e-400` (→ 0, refused), `1e400` (refused by name), `1k5`, `2u5` | right |
| noise names in hierarchy | `onoise_n.x1.n1_thermal`, `onoise_r.x1.r1_thermal` — dotted names print, `let` and `[0]` index them | right |
| `$simparam` | `gmin` (max of gmin and diaggmin), `iteration` (cumulative solver count), `sourceScaleFactor`, `abstol`, `reltol`, `tnom`, `epsmin`, `gdev`, `iniLim`, `scale` (from `.option scale`), `abstime` (0 outside tran), `analysis()`; `$simparam$str` `analysis_name`/`cwd`/`simulator` | right (apart from F1) |
| stepping seen from the model | a twelve-diode chain at 100 V that fails plain Newton: the model's running minimum of `sourceScaleFactor` reads 0 and its maximum of `gmin` 1e-9 — both ladders reach the device | right |
| noise scaling | `flicker_noise` and `white_noise` under `m=2` (power doubles, output impedance shifts: 4.714e-4 and 1.919e-9 against 5.0e-4 and 2.036e-9 at m=1) | exact |
| mixed signal | `adc_bridge` → `d_buffer` → `dac_bridge` driving an OSDI resistor divider (1.5 V) | right |
| card syntax | `$` and `;` comments and `+` continuations on OSDI instance and model lines | right |
| paths | `pre_osdi alias.osdi` and `.include m.inc` relative to the deck's directory with a different working directory | resolved against the deck |
| loading twice | a second file defining `resa`/`resb`/`pair`: "already registered; keeping the existing device" per module, the first file's values used | right, and said |
| integration | `.option method=gear` on an OSDI `ddt` (0.6326 vs trap's 0.6318 at one τ); `.ic` with and without `uic` on an OSDI capacitor node, identical to the built-in | right |
| `alter` grammar | two pairs on one line (both applied, F1 of 2026-09-07 fixed), a quoted value on a real (refused by name), a bare word ("no such vector"), an unknown parameter or device (refused), `@am[r]` through `alter` (pointed to `altermod`) | right |

## Smaller notes (not pursued)

- A module's own `parameter real tnom = 27` is a parameter like any other: `.option
  tnom=100` moves `$simparam("tnom")` but not it, so a model that writes `tnom` as a
  parameter (the CMC convention) ignores the option unless the card sets `tnom=`. Correct
  by the LRM, surprising beside the built-ins, whose `tnom` defaults to the option.
- `$simparam("iteration")` is the solver's cumulative count (122 after a 30-point
  transient), not the Newton iteration within a point.
- `%m` inside a subcircuit prints `n.x1.n1`, the device-type-prefixed internal name,
  where the user wrote `x1.n1`; the `OSDI n.x1.n1:` message prefix repeats it.
- `show n1` lists both `_mfactor` and `m` with the same value.
- `.model ... level=7 LEVEL=8` warns "set more than once; only one value takes effect"
  without saying which (the last).
- The string `$simparam$str("type")` is not a served name (the table has
  `analysis_type`); the LRM's Table 9-28 spells it `analysis_type` as well, so no gap.
- `@n1[p]`, the power accessor built-in devices have, is "no such parameter" on an OSDI
  instance.
- `alter @n1[w] = [1 2 3]` — a vector value on a scalar parameter — does nothing and says
  nothing; `w` stays 1.
- A batch `.meas tran ipk max @n1[i_p]` needs a `.save all @n1[i_p]` beside it (the
  measure's own message says so, in full); `.print` cards register their `@dev[param]`
  vectors, `.meas` cards do not. Built-in `@r1[i]` is the same.
- `.probe i(n1,p)` wants the netlist node, not the port name ("Node p is not available").
- `.option savecurrents` stores a subcircuit instance's currents under the device-letter
  prefix, `@n.x1.n1[i_p]` (59 points), while the spelling the user wrote, `@x1.n1[i_p]`,
  reads the live scalar — a `.meas` on the natural spelling fails "holds 1 point". Stock:
  `@r.x1.r1[i]` against `@x1.r1[i]` is the same.
- OSDI transient noise (E-364, on when a `trnoise` source is in the deck) measures an rms
  of 0.82 × the `sqrt(S/(2 ts))` of its amplitude law, for every grid tried — and so does
  ngspice's own `trnoise(1m 1u 0 0)` (0.82 mV): the transient interpolates linearly
  between noise samples, whose rms is sqrt(2/3) of the sample deviation. The two agree
  with each other, and the low-frequency density the law targets is unaffected; the
  write-up's "deviation Q" is the sample value, not the waveform rms.
- `pre_osdi alias.va` (a source file) fails with the raw `dlopen` text; "compile it with
  openvaf-r first" would be the hint.
- A three-terminal OSDI device has no bare `@n1[i]` (E-394 defines it for two terminals
  only); `i_d`, `i_g`, `i_s` are there, and `savecurrents` records all three.
- A model parameter written on an instance line is still "unknown parameter" (F8 of the
  2026-09-04 workflows hunt); a model parameter is not readable through the instance
  (`@n1[r]`), as for built-ins.

## Coverage, honestly

Not reached: `sp` with
an OSDI thermal or multi-port model; noise of `flicker_noise`/`noise_table` under `m`;
`.option klu` versus Sparse on a collapse-changing sweep; XSPICE digital bridges around
an OSDI device; any of the `osdimc`/`autobus` layers (four hunts already); ten thousand
instances (the large-circuits hunt). The F1 bisection took a third of the hour; it is
the one finding here that silently changes an answer, and it earned it.
