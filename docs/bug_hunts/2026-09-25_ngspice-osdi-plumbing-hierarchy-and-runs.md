# ngspice + OSDI bug hunt — parameter plumbing, hierarchy, run control and the vectors a Verilog-A device publishes

**Date:** 2026-09-25, one hour (19:13–20:13; the probes ran until 19:53, the
write-up was made alongside and finished by 19:56), at head `e3fac9a1` (sources at E-730). **Binaries:** the
repo's `ngspice-46/build/src/ngspice` (built 18:48, E-730) and
`OpenVAF-master-20260610/target/opt/openvaf-r`. **Rule of the hour:** probe, record,
do not fix; everything in the foreground, one compile at a time, small models.
Harnesses A–AL (486 decks, 32 Verilog-A modules) live in the session scratchpad
`h6/`, one report per harness.

**Ground.** The earlier ngspice + OSDI hunts covered the integration seams
([2026-09-04](2026-09-04_ngspice-osdi-integration.md),
[2026-09-10](2026-09-10_ngspice-osdi-integration-second-hunt.md)), the less-travelled
analyses and the analysis-end events
([2026-09-21](2026-09-21_ngspice-osdi-analyses-sens-and-events.md)), the statistics
record ([2026-09-12](2026-09-12_statistics-record-and-kicad-hunt.md)) and the five
front-end options ([2026-09-25](2026-09-25_five-options-dig.md)). This hour went where
those had not: how a parameter reaches an instance (`.param`, `.func`, subcircuit
formals, `m`, `dtemp`, `temp`, `alter` in every spelling), what a device inside a
subcircuit is called (its internal node under `print`, `save`, `.ic`, `.nodeset`), the
run controls (`stop`/`resume`/`step`/`reset`/`alter` mid-run, `setcirc`), the vectors a
device publishes (operating-point variables and the branch of a voltage contribution
under `save`, `meas`, `fft`, `write`/`load`, `stop when`, `trace`), the loading of the
`.osdi` itself (`pre_osdi -va` and its cache, a truncated or textual file, a module
named like a built-in, the same module from two files), and the batch dot cards.

## Summary

| # | Finding | Kind |
|---|---|---|
| [F1](#f1--ic-and-nodeset-on-an-osdi-internal-node-inside-a-subcircuit-need-the-flattened-spelling) | `.ic` / `.nodeset` on an OSDI internal node inside a subcircuit are "non-existent node" under the spelling `x1.n1#mid` that `print`, `save`, `stop when` and `trace` all accept; only the flattened `n.x1.n1#mid` — which nothing documents and which `save all` alone reveals — is honoured | the same node has two names, and each command accepts one |
| [F2](#f2--an-alter-of-a-timer-parameter-across-stopresume-does-not-reschedule-the-timer) | an `alter` of a `@(timer(t0))` parameter after a `stop` reaches the equations on `resume` but not the pending timer: the event fires at the old `t0`, whether the new one is earlier or later | a mid-run change half applied |
| [F3](#f3--the-branch-current-of-a-voltage-contribution-cannot-be-saved-by-name) | the branch current a `V(p,n) <+` contribution creates is the vector `n1#flow(p,n)`, readable by `print`, `let`, `meas` and `wrdata`, but `save n1#flow(p,n)` registers a node called `p,n` and the analysis is then refused "no data saved" | one command's parser against the name the device chose |
| [F4](#f4--an-alter-at-a-stop-reaches-the-resumed-run-through-a-door-that-skips-the-range-check-and-only-for-some-parameters) | an `alter` at a `stop` is applied by the next analysis and not by `resume` for a built-in resistor and for an OSDI parameter folded into the setup-time expressions (`reff = r·rmod·(…)`: `r`, `m`, `dtemp` unchanged on resume), but a parameter the evaluation reads directly (`V(p,mid)/r`) does reach the resumed run — without the range check setup would have made: `alter @n1[r]=0` then `resume` dies "Timestep too small … trouble with node mid" where a fresh run says "out of bounds" | a mid-run change applied to some parameters, checked for none |
| [F5](#f5--an-operating-point-variable-of-an-osdi-device-inside-a-subcircuit-cannot-be-saved-under-its-own-name) | `save @x1.n1[vm]` is "no such device, so this vector will stay empty" and the vector has 0 points, while `print @x1.n1[vm]` reads the value, `save @n.x1.n1[vm]` records 61 points and a built-in's `@x1.r1[i]` saves under the natural name; `stop when @x1.n1[vm] > 0.3` and `meas … when @x1.n1[vm]=0.3` then find nothing | the hierarchical retry of the save does not allow for a variable that has no value yet |
| [D1](#d1--an-operating-point-variable-named-temp-draws-a-wrong-duplicate-parameter-warning) | a module whose operating-point *variable* is called `temp` draws, beside the correct "the simulator's own parameter wins" warning, a second one that the *instance parameter* `temp` "is declared more than once differing only in case" — there is no such parameter and no case difference | a diagnostic slip |
| [D2](#d2--a-stop-condition-on-an-unsaved-operating-point-variable-says-no-such-node-at-every-step) | `stop when @n1[vm] > 0.3` with the variable not in the save set prints `Error: @n1[vm]: no such node` at every accepted point and never stops, while `print @n1[vm]` reads the live value and `save @n1[vm]` makes the condition work | the wrong message, once per step |
| [D3](#d3--the-model-wildcard-alter-on-an-instance-parameter-is-silent-when-a-built-in-device-is-in-the-deck) | `alter @*[r]=2k` (the model wildcard) on an OSDI instance parameter says "no loaded model has parameter 'r', but a loaded instance does -- use the instance wildcard '@#*[r]'" in a deck of OSDI devices, and nothing at all once a built-in resistor is in the deck; either way nothing changes | a message that depends on a bystander |
| [N1](#n1-not-osdi--reset-drops-a-control-block-set-temp) | (not OSDI) `set temp=100` in the control block is honoured by the next `op`, but after a `reset` the run is back at the deck's temperature, `set temp` still set and silent; `unset temp` does not give the deck's temperature back either | an ngspice-core inconsistency, seen through `$temperature` |

Smaller notes are at the end: what `alter n1 r=[1k 2k]` does (nothing, in silence, for
built-ins too), the loaded raw file's spelling of a branch current, `trace` in batch
mode, `pre_osdi -va x.va -o y`, `i(n1)` on a voltage contribution, a batch `.meas` on
an unsaved variable, `m=0`.

## What was read and run

Harness A: `.param`/`.func`/braces/quotes in instance parameters, eleven number
spellings, subcircuit formals through one and two levels, `m`, `dtemp`, `.temp`,
`.option temp`, `set temp`, integer and string parameters, `alter`/`altermod` in every
form, `$param_given` after `alter`. B: a module named `diode` beside `.model dd diode`
on a `D` line and an `N` line, the same module from two files and the same file twice,
a missing/truncated/textual `.osdi`, unknown and duplicated parameters, duplicate and
odd instance names, model/instance name case, a model named after an instance. C:
`uic`, `.ic` on ports and internal nodes, `stop`/`resume` across an OSDI timer, `alter`
between runs, `write`/`load`/`meas`/`fft`/`wrdata` of operating-point vectors,
`remcirc`/`source`. D: two subcircuit levels, the internal node under every spelling,
`.global`, wrong node counts, `.include`, a path with spaces, wildcards. E–R: the
follow-ups and the further areas named above (`$simparam` one at a time, `$bound_step`,
`cross`/`above`, `analysis()` under every analysis, the noise contributions, a
Verilog-A inductor, voltage source and switch, `setcirc`, `.option interp`, nested and
integer `dc` sweeps, the batch dot cards, ten `ngbehavior` modes, extreme card values,
`stop when`/`trace`/`step`/`where`, `temper` in a `.param`, `alterparam` + `reset`).

## F1 — `.ic` and `.nodeset` on an OSDI internal node inside a subcircuit need the flattened spelling

**Observed.** `harnD.py` [D2], `harnE.py` [E3], `harnH.py` [H3]. A subcircuit `cell`
holding `N1 p n rcx` (an RC with the internal node `mid`), `X1 in out cell`:

| line | result |
|---|---|
| `print v(x1.n1#mid)` | 0.5, the node |
| `save v(x1.n1#mid)` | kept |
| `save all` then `display` | the node is listed as `n.x1.n1#mid` |
| `.save v(x1.n1#mid)` and `.print tran v(x1.n1#mid)` cards | both work; the `n.` spelling works there too |
| `stop when v(x1.n1#mid) > 0.3` | works |
| `.nodeset v(x1.n1#mid)=0.3` | `Warning : Nodeset on non-existent node - x1.n1#mid, ignored` |
| `.ic v(x1.n1#mid)=0.3` under `tran uic` | `IC on non-existent node`, the capacitor starts at 0 |
| `.ic v(n.x1.n1#mid)=0.3` under `tran uic` | accepted, the capacitor starts at 0.3 V (`v(x1.n1#mid)[0]` 0.9993, `v(out)[0]` 0.6993) |
| `.nodeset v(n.x1.n1#mid)=0.3` | accepted |
| `.ic v(x1.n1.mid)` / `.ic v(x1:n1#mid)` | non-existent |
| at top level, `.ic v(n1#mid)=0.5` | accepted (the 2026-09-21 hunt's F6 covered the collapsed case) |

**Where.** The flattened instance name carries the device-type letter,
`n.x1.n1`, so the internal node's real name is `n.x1.n1#mid`. [E-410](../../enhancements_doc/Enhancement-410.md)
taught the accessor path (`print`, `alter`, `show`, `save`, and by the look of it
`stop when`) to resolve the user's `x1.n1` to it; the `.ic`/`.nodeset` lookup
(`inp2*.c`/`cktic.c`, "non-existent node") was not taught.

**Expected.** The spelling `print` accepts is the one `.ic`/`.nodeset` accept, or the
warning names the spelling that would work. Nothing documents `n.x1.n1#mid`.

**Kind.** One node, two names, and the command that most needs the node takes the one
the user cannot discover.

## F2 — an `alter` of a timer parameter across `stop`/`resume` does not reschedule the timer

**Observed.** `harnM.py` [M1], `harnN.py` [N2]. A module with `@(timer(t0)) s = 1.0`
doubling its conductance, `t0=2u` on the instance line, `tran 0.1u 4u`:

| block | `i(v1)` at 1.8 µs | at 2.5 µs | at 3.9 µs |
|---|---|---|---|
| plain run | −1 mA | −2 mA | −2 mA |
| `stop when time=1u` / `resume` | −1 mA | −2 mA | −2 mA |
| `stop when time=1u` / `alter n1 t0=3u` / `resume` | | −2 mA | −2 mA |
| `stop when time=1u` / `alter n1 t0=1.5u` / `resume` | −1 mA | −2 mA | |
| `alter n1 t0=3u` between two separate `tran`s | | −1 mA | −2 mA |

The timer fires at 2 µs in every resumed run, whatever `t0` was altered to — a later
value (3 µs) does not move it, an earlier one (1.5 µs, still in the future at the stop)
does not either. The same `alter` of a resistance across the same `stop`/`resume`
does take effect (`harnM.py` [M1c]: the RC's slope changes after the resume), and a
fresh `tran` after the `alter` fires at the new time. `initial_step` fires once, not
again on `resume`; `final_step` once; the timer count is right.

**Where.** The timer is scheduled from the parameter when the run starts (the accept
hook's breakpoint of [E-698](../../enhancements_doc/Enhancement-698.md)'s family);
`alter` re-runs the instance setup, which the conductance reads, but the pending
breakpoint is not re-derived.

**Expected.** Either the altered `t0` reschedules a timer that has not fired (the LRM
schedules the event when the statement executes, and the statement executes at every
evaluation), or the `alter` says the timer keeps its schedule.

**Kind.** A mid-run change applied to the equations and not to the event queue.

## F3 — the branch current of a voltage contribution cannot be `save`d by name

**Observed.** `harnK.py` [K2], `harnN.py` [N1]. A module `V(p, n) <+ v0` (a Verilog-A
voltage source) as `N1 a 0 vsrc`:

| line | result |
|---|---|
| `print all` after `op` | `a = 2`, `n1#flow(p,n) = -2e-3` |
| `print n1#flow(p,n)`, `let x = n1#flow(p,n)`, `meas tran ib find n1#flow(p,n) at=2n`, `wrdata f n1#flow(p,n)` | all work |
| `print @n1[i]`, `@n1[i_p]`, `.probe i(n1)` (→ `n1#branch`) | work |
| `print i(n1)` | `Error: no such function as i,` |
| `save n1#flow(p,n)` then `op` | `Warning: save 'p,n': nothing of that name is in this analysis` and `Error: no data saved for D.C. Operating point analysis; analysis not run` |
| `save "n1#flow(p,n)"` (quoted) | the same |
| the card `.save n1#flow(p,n)` | `save 'p'` and `save 'n'`, nothing of that name; the analysis refused |
| `save @n1[i] v(a)` then `tran` | works: `@n1[i][2] = -2e-3` |

**Where.** The vector's name has parentheses and a comma; `save`'s argument scan
(`settrace`/`copynode`) cuts at the comma or reads `flow(...)` as a function form and
registers `p,n`. The other commands go through the expression parser, which happens to
take the name whole.

**Expected.** A name the device publishes and every other command reads is one `save`
takes; or the branch gets a plain alias (`n1#branch` is what `.probe i(n1)` makes).

**Kind.** One command's parser against the name the device chose; the analysis is then
refused for it.

## F4 — an `alter` at a stop reaches the resumed run through a door that skips the range check, and only for some parameters

**Observed.** `harnG.py` [G1], `harnV.py` [V2], `harnW.py` [W1], `harnX.py`,
`harnY.py`. Two modules: `res` computes `reff = r * rmod * (1 + tc * (T − 300.15))` and
conducts `V/reff`; `rcx` conducts `V(p,mid)/r` into an internal node with a capacitor
behind it. A built-in resistor beside them. Every block is `stop when time=1u`, a
`tran`, the change, `resume`:

| change at the stop | built-in `R1` | `res` | `rcx` |
|---|---|---|---|
| `alter … resistance=2k` / `alter n1 r=2k` | `@r1[resistance]` reads 2k, the current unchanged to the end; the next `op` uses 2k | `@n1[r]` reads 2k, `@n1[reff]` and the current unchanged; the next `op` uses 2k | `@n1[r]` reads 10k and the waveform changes at once (`v(mid)` at 3 µs 0.0459 against 0.1116) |
| `alter n1 m=3`, `alter n1 dtemp=73`, `altermod res rmod=2` | — | read back, nothing changes until the next analysis | — |
| `alter @n1[r]=0` (against `from (0:inf)`) | — | — | no message at the `alter`; the resumed run dies `Timestep too small; time = 1e-06 … trouble with node "mid"`. A fresh `tran` after the same `alter` is refused at setup, `Parameter r of 'n1' is out of bounds (value 0; range from (0:inf))!`; `alter @n1[r]=2k` before the `resume` and the run continues |

**Where.** ngspice applies an `alter` at the next analysis: setup and temperature run
then, `resume` runs neither, and a built-in device's load reads what setup computed.
An OSDI device's `alter` writes the parameter into the instance, and whether the
evaluation sees it at once depends on where the compiler put the expression: a
parameter-only expression (`reff`) is computed at setup and cached, a parameter read
inside the evaluation (`/r`) is read live. The range check is setup's too.

**Expected.** One rule, the simulator's: an `alter` at a stop is applied by the next
analysis, or by `resume` after re-running setup (so that the range is checked and
every parameter, cached or live, moves together) — either, but the same for every
module and every parameter. As it stands the outcome is a property of the module's
source.

**Kind.** A mid-run change applied to some parameters and checked for none.

## F5 — an operating-point variable of an OSDI device inside a subcircuit cannot be saved under its own name

**Observed.** `harnAH.py` [AH2], `harnAI.py` [AI1]. `X1 in mid cell` with `N1 p n rcx`
and a built-in `R1 p n 1meg` inside `cell`:

| line | result |
|---|---|
| `print @x1.n1[vm]` after `op` | 0.5, the variable |
| `save @x1.n1[vm]` / `tran` | `Warning: save '@x1.n1[vm]': no such device, so this vector will stay empty.`; `length(@x1.n1[vm])` is not available |
| `save @x1.n1[q]` | the same |
| `save @n.x1.n1[vm]` / `tran` | 61 points (with E-600's "has no value yet" line, as for any hand-written opvar save) |
| `save @x1.r1[i]` / `tran` (the built-in beside it) | 61 points, `@x1.r1[i][5]` 5.0e-7 |
| `save all @x1.n1[vm]` / `stop when @x1.n1[vm] > 0.3` / `tran … uic` | no stop, no message, the run to the end |
| `meas tran t3 when @x1.n1[vm]=0.3` on the same save | `'@x1.n1[vm]' holds 0 point(s) but the analysis produced 111` |

**Where.** `outitf.c`, Pass 2 of `beginPlot`: [E-418](../../enhancements_doc/Enhancement-418.md)
resolves a hierarchical `@x1.n1[…]` by retrying `INPaName` with the flattened
`n.x1.n1` and keeps the rewrite only when that call returns `OK`. For an
operating-point variable before any analysis the ask fails — the case
[E-507](../../enhancements_doc/Enhancement-507.md) taught the *first* call to treat as
"the name resolves, the value is not there yet" — so the retry is discarded, the first
call's `E_NODEV` stands, "no such device" is printed and the name is never resolved per
point. A built-in's `[i]` is askable at save time, so its retry succeeds.

**Expected.** The retry judged as the first call is: `E_NODEV`/`E_BADPARM` mean the name
is wrong, anything else means it resolved; the vector then records per point under
the spelling `print` accepts.

**Kind.** The same node-name split as F1, for the device's variables: `print` takes
`x1.n1`, `save` needs `n.x1.n1`, and the hierarchy is where models live.

## D1 — an operating-point variable named `temp` draws a wrong "duplicate parameter" warning

**Observed.** `harnG.py` [G6]. A module with `(* desc="…" *) real temp;` (a variable,
not a parameter). The compiler warns rightly (`L035: operating-point variable 'temp' has
the name of ngspice's own instance parameter 'temp', which wins the lookup`), and at
load time ngspice prints two lines:

```
Warning: clash: the operating-point variable 'temp' has the same name as the simulator's own instance parameter 'temp', which wins the lookup -- …
Warning: clash: instance parameter 'temp' is declared more than once differing only in case; SPICE cannot tell the names apart, so only one of them ca…
```

The second is wrong twice: the module declares no instance parameter `temp`, and there
is no case difference. `show n1` then lists two rows named `temp` (27, the simulator's;
44, the variable's), and `@n1[temp]` reads 27 as the first warning says.

**Where.** The case-fold duplicate check over the merged parameter and opvar tables
(`osdisetup.c`/`osdiinit.c`, the E-535-era name registration) counts the simulator's
`temp` and the module's opvar `temp` as two declarations of one instance parameter.

**Expected.** One warning, the first; the duplicate check limited to the module's own
declarations.

**Kind.** A diagnostic slip that accuses the model of something it did not write.

## D2 — a stop condition on an unsaved operating-point variable says "no such node" at every step

**Observed.** `harnQ.py` [Q1]:

| block | result |
|---|---|
| `save all @n1[vm]` / `stop when @n1[vm] > 0.3` / `tran … uic` | stops after 25 points, `3 : condition met` |
| `save all` / `stop when @n1[vm] > 0.3` / `tran … uic` | `Error: @n1[vm]: no such node`, once per accepted point, the run to the end |
| `stop when v(n1#mid) > 0.3` | stops |

`print @n1[vm]` reads the live value of an unsaved variable (a scalar); the stop
condition's evaluator does not, and calls the variable a node.

**Where.** `breakp2.c`, the `stop when` evaluation reads the vector by name from the
plot; an operating-point variable is a per-point vector only when saved
([E-418](../../enhancements_doc/Enhancement-418.md)).

**Expected.** The condition reads the live value as `print` does, or one message that
says "`@n1[vm]` is an operating-point variable; `save @n1[vm]` to watch it" — once.

**Kind.** The wrong message, repeated.

## D3 — the model wildcard `alter` on an instance parameter is silent when a built-in device is in the deck

**Observed.** `harnAA.py` [AA1], `harnAB.py`, `harnAC.py`. Two OSDI instances
`N1`/`N2` (`r=1k` each), `alter @*[r]=2k`, `op`:

| deck | what `alter @*[r]=2k` says | `@n1[r]` after |
|---|---|---|
| `N1`, `N3` (no built-in) | `Warning: no loaded model has parameter 'r', but a loaded instance does -- use the instance wildcard '@#*[r]'.` | 1k |
| `N1`, `N2`, and a built-in `R9 a 0 1k` | nothing | 1k |
| `alter @#*[r]=2k`, either deck | — | 2k on every OSDI instance, the current halves |
| `alter @*[resistance]=2k` with `R9` | the same warning, for `@#*[resistance]` | `@r9[resistance]` 1k |
| `alter @n?[r]=2k` | `Error: no such device or model name n?` | 1k |
| `altermod res r=2k` (an instance parameter through the model) | "2000 is now the default of model res -- 1 instance follows it, 1 keeps its own value" | as it says |

`@*[p]` is the model wildcard, `@#*[p]` the instance one (`sweep` takes both, and
names which it took). The `alter` warning that steers a user from one to the other
is printed only when no built-in device is loaded; with `R9` in the deck the same
line changes nothing and says nothing.

**Where.** The model-wildcard `alter` looks for a loaded model with the parameter;
the built-in resistor's model type answers for `r` (its instance parameter
`resistance` has the alias `r`), so "no loaded model has parameter 'r'" is not
reached, no model actually takes the value, and the OSDI instances keep theirs.

**Expected.** The warning printed whenever the wildcard set nothing, whatever else is
in the deck.

**Kind.** A message that depends on a bystander device.

## N1 (not OSDI) — `reset` drops a control-block `set temp`

**Observed.** `harnE.py` [E1]. `N1 a 0 res r=1k tc=1e-3` (a `$temperature`
coefficient) and a built-in `R9` beside it:

| block | the run reports | `@n1[reff]` |
|---|---|---|
| `op` / `set temp=100` / `op` | `TEMP = 27` then `TEMP = 100` | 1000 then 1073 |
| `op` / `set temp=100` / `reset` / `op` / `op` | `TEMP = 27` three times | 1000 throughout |
| `.option temp=60` in the deck, then `set temp=100` / `reset` / `op` | `TEMP = 60` | 1033 |
| `set temp=100` before the first `op` | `TEMP = 100` | 1073 |
| `set temp=40` / `op` / `unset temp` / `op` | `TEMP = 40` twice | 1013 twice |

`.temp 60` beats `.option temp=50` whichever comes first, and `set temp` beats both;
`unset temp` does not give the deck's temperature back. The variable is still set after
the `reset` (nothing unsets it); the rebuilt circuit
takes its temperature from the deck and never consults it again, while the un-reset
circuit consults it at every run. Not an OSDI matter — the built-in resistor's
temperature follows the same `TEMP =` line — but `$temperature` makes it visible in a
model's own numbers.

**Where.** `inp.c`/`runcoms.c`: the circuit's temperature is read from the `temp`
variable when an analysis starts on the first circuit and from the deck's options on a
`reset` (`inp_dodeck`'s option pass), where a `temp` variable set later is not looked
at.

**Expected.** `set temp` means the same thing before and after `reset`, or `reset` says
it put the deck's temperature back.

**Kind.** An ngspice-core inconsistency.

## What held

- **Parameter plumbing** (harness A): `.param`, `{}` and `'…'` expressions, `.func`,
  every SPICE number spelling (`1k`, `1K`, `1meg`, `1MEG`, `0.001meg`, `1e3ohm`; `1,000`
  refused), subcircuit formals through one and two levels with defaults and overrides,
  `alter @x1.x1.n1[g]` and `alter x1.x1.n1 g=`, `altermod` through the hierarchy, `m`
  (2, 0.5, `alter n1 m=3`; a negative `m` warned and ignored), `dtemp`, `.temp`,
  `.option temp`, `set temp` before a run, `alter @n1[dtemp]`, integer parameters
  (2.7 rounded with a warning, 100 refused against `[1:64]` with the range named),
  `$param_given` after `alter` (1), a model parameter on the instance line refused with
  "it is a model parameter of this device -- set it on the .model card", `alter` of a
  model parameter through the instance refused with the `altermod` form, a parameter
  set twice on a line or a card warned, `alter` with an expression (`2k*2`, `{2k*2}`),
  a `set` variable and a `$&` vector.
- **Loading** (harness B, H): a missing, truncated and textual `.osdi` each say why
  ("segment extends beyond end of file", "not valid mach-o") and the model card's
  error names the cure; the same module from two files keeps the first and says so;
  the same file twice is skipped with the `-f` hint; `pre_osdi -va` compiles into
  `./osdi/`, reuses the cache, recompiles a changed source, reports a broken one with
  the compiler's own error and a missing source by name; a module named `diode` beside
  `.model dd diode is=…` makes the built-in on a `D` line (warned, "created as
  ngspice's built-in Diode") and the Verilog-A one on an `N` line (said), and a
  parameter the module lacks is "unrecognized — ignored"; instance names `N[1]`,
  `N#1`, node names `a-b`, `1e3`; a model named after an instance (`n1`) works, one
  named after the source `v1` loses `@v1[g]` to the source.
- **Transient control** (harness C, M, N, Q): `uic`, `.ic` on a port and on a
  top-level internal node, `.nodeset` on it, `stop`/`resume` with the timer, the
  `initial_step`/`final_step`/timer counts across a resume (1, 1, and the right number),
  `alter` of a conductance across a resume, `alter` between runs with and without
  `reset`, `remcirc`/`source`, two circuits under `setcirc` (numbered newest first,
  `alter` reaching the right one), `step` after a stop (+2, +1, then the rest, as for a
  built-in), `stop when` on a saved variable and on an internal node, `where` after a
  failed op.
- **Vectors** (harness C, K, L, M, O): a saved operating-point variable through
  `write`/`load` (binary and ascii), `meas` (`find`, `max`, `avg`, `pp`), `let`, `fft`,
  `wrdata`, `.option interp` (100 points for every vector, the variable included),
  `.print tran`, `.four`, `.print ac`, a `.save` card; the batch `.probe @n1[vm]`
  refused with the `.save` cure; `dc temp` and `dc v1` sweeps recording a saved
  variable per point; the internal node and the branch vector through a raw-file
  round trip (`v(n1#mid)`, `i(n2#flow(p,n))`; the latter reachable by `let`, see the
  notes).
- **Contributions and events** (harness F, J): a Verilog-A inductor under `op`, `ac`
  (45° at 1/(2πL/R)), `tran`, `uic`, `rs`, a current-source drive; a Verilog-A voltage
  source in series with a source, its `sens` (`n1_v0 = 1`), two of them in parallel and
  one across a source refused as singular; a switch branch changing contribution kind
  under `op`, `tran` (`ton` 1.0005 µs) and `dc`; `analysis("dc"/"ac"/"noise")` under
  `op`, `ac`, `noise`, `dc`; the thermal contribution `onoise_n1_thermal` beside the
  built-in's; `$simparam("gmin")` following `.option gmin`, `"iteration"`,
  `"sourceScaleFactor"`, `"tnom"`, `"simulatorVersion"` (46), a default for an unknown
  name, and a fatal without one; `$bound_step` (207, 59 and 2004 points for 10 ns,
  100 ns and 1 ns); `cross` and `above` at the right voltages.
- **Sweeps** (harness G, M): `dc @n1[r]` into its range boundary keeps the points before
  and abandons with a message naming the `alter` equivalence; nested sweeps over two
  instances' parameters; an integer parameter as the sweep variable, a fractional step
  refused; a `.param` or an instance expression with `temper` feeding an OSDI
  parameter follows `.temp`, `set temp` and every point of a `dc temp` sweep (harness
  R, S: `r={1k*(1+1e-3*(temper-27))}` reads 1050 at 77 °C, as the built-in resistor
  that ngspice rewrites into a B source does); `alterparam` + `reset` reaches an OSDI
  instance and model parameter; the parameter and the temperature put back after a
  sweep.
- **Local model cards** (harness T): a `.model` inside a subcircuit becomes `x1:res`,
  `altermod x1:res` reaches it, two subcircuits with the same local model name and a
  global card of that name beside them stay apart (2k, 4k, 3k).
- **Temperature and sweeps again** (harness Z): `dtemp=10` and `alter @n1[dtemp]=10`
  keep their offset at every point of a `dc temp` sweep (1100, 1600, 2100 Ω for
  `tc=1e-2`); a source outside and a parameter inside the nested `dc`, and the other
  way round, read consistently; an `op` after a `tran` reads the operating point
  again.
- **Compatibility** (harness L): ten `ngbehavior` modes leave an OSDI line, its
  parameters, `m`, a bracketed node and a `.param` alone.
- **Extreme values** (harness P): `1e400` refused as "overflows to infinity", `inf` and
  `nan` refused by numparam, `0x10` read as 0 and refused by the range, `1e-320` accepted
  and the op fails to converge (no message about the value).

## Smaller notes (not pursued)

- `alter n1 r=[1k 2k]` — a list for a scalar real parameter — changes nothing and says
  nothing; the built-in `alter r1 resistance=[1k 2k]` is the same, so this is
  ngspice's `alter` and not the OSDI interface.
- After `write`/`load`, the branch of a voltage contribution is the vector
  `i(n2#flow(p,n))`: `let b = i(n2#flow(p,n))` reads it, `print i(n2#flow(p,n))[5]`
  says "no such function as i", `print n2#flow(p,n)[5]` "not available".
- `trace` prints nothing in batch mode, for a built-in node as for an OSDI variable, and
  does not say so (`iplot` does: "not available during batch simulation, ignored").
- `pre_osdi -va cva.va -o out.osdi`: the `-o` and `out.osdi` are read as two more files
  to load ("Error opening osdi lib "-o"").
- `i(n1)` on a device whose branch is a voltage contribution says "no such function as
  i"; the current is `@n1[i]`, `@n1[i_p]`, `n1#flow(p,n)` or `.probe i(n1)`.
- A batch `.meas tran vend find @n1[vm] at=2u` with no `.save` card fails with
  `'@n1[vm]' holds 1 point(s) but the analysis produced 68` — right, and without the
  cure (`.save @n1[vm]`) that the `.probe` refusal gives.
- `m=0` on an OSDI instance (as on a built-in resistor) removes the device in silence;
  `m=-2` is warned and ignored.
- A `save` added at a stop does not reach the running plot ("vector mid is not
  available" after the `resume`); a `write` at a stop writes the points so far and the
  run continues; a `set temp` at a stop changes nothing until the next analysis, for
  a built-in and an OSDI device alike.
- `0.0` and `vss` are ordinary node names, not ground (`0`, `gnd`, `GND` are); a
  device between `a` and `0.0` floats in silence — ngspice's own.
- A Verilog-A voltage source (`V(p,n) <+ v0`) cannot be the input source of `tf` or
  `noise`: "Transfer function source n1 not of proper type", "Noise input source n1
  is not of proper type". The analyses want a built-in `V`/`I` instance; an
  `ac_stim("ac", mag)` in the same module does drive `ac` (2 V at the source, 1 V at
  the divider, a series one with `mag=0` passing the built-in stimulus through).
- `reset` and then `resume`: nothing happens and nothing is said; the plot keeps the
  points to the stop.
- Instance, node and model names of 300 characters work; `alter n1 r = $&k * 1k`
  inside a `while` and `alter n1 r = $rv` inside a `foreach` work.
- `.probe i(x1.n1)` on a device inside a subcircuit — an OSDI device or the built-in
  `R1` beside it — is "Could not find the instance line for x1.n1, .probe i(x1.n1)
  will be ignored": the probe wants a top-level instance line; `.probe alli` gives
  the subcircuit's port current `x1#branch` instead. ngspice's own, for every device.
- A binned model's parameter is read by the bin's name (`@br.1[rsh]`); `@br[rsh]`
  is "no such device or model name br" and `@n1[rsh]` "no such parameter" — `show n1`
  names the bin.
- `.option scale` is not applied to an OSDI instance parameter, by
  [E-394](../../enhancements_doc/Enhancement-394.md)'s design (a model reads
  `$simparam("scale")` and scales itself, as BSIM does): `l=1` under `scale=1e-6`
  computes with 1 and reads back 1, where the built-in MOS reads back 1e-6. The bin
  selection, though, compares the *scaled* `l` and `w` with the bins
  ([E-600](../../enhancements_doc/Enhancement-600.md)): a model that does not read the
  simparam gets the bin of 1 µm and the equations of 1 m. Consistent for a model that
  follows the policy, silent for one that does not.
- A repeated node on an OSDI instance — both terminals of a conductance or of an RC on
  one node, both on ground, a three-terminal switch with two terminals shared — is
  stamped without complaint and contributes what the physics says (nothing, or the
  switch's leakage). A Verilog-A inductor or voltage source with both terminals on one
  node is a singular matrix, "check node n1#flow(p,n)", as the built-in inductor is
  ("check node l1#branch"); the built-in voltage source, though, is refused at parse
  time — `Fatal error: instance v2 is a shorted VSRC` — where the Verilog-A one goes
  through gmin and source stepping and fails without a word about the short.
- `pre_osdi` takes a relative path, `~/…`, `$HOME/…`, an absolute path and a `./lib/../`
  spelling; it does not search `sourcepath` (a bare `plumb.osdi` with `set sourcepath
  = ( lib )` is "couldn't be loaded", and the model card then falls through to the
  built-in resistor's type error, since this module shares the built-in's name).
  `.lib file section` cards hold OSDI model cards as any other; a missing section is
  ngspice's fatal exit.
- `$temperature` in a parameter default is refused at compile time with the LRM 3.4
  clause and the cure (`analog initial`), which is right.
- Binned model cards (`lmin`/`lmax`/`wmin`/`wmax`) select by `l`/`w` with the lower
  bound inclusive, refuse an instance outside every bin naming the bins, follow
  `altermod br.1`; a string instance or model parameter that changes the equation is
  honoured on the line, on the card (quoted; an unquoted value is numparam's error),
  under `alter`/`altermod`, and compared case-sensitively; `m=3` on a subcircuit call
  reaches the OSDI instance inside as it reaches a built-in.
- `$&v(in,out)` in an `echo` splits at the comma ("&v(in: no such variable") on every
  binary — ngspice's `$&` takes a name, not an accessor with two nodes.
- `.print op @n1[vm]` prints the variable; `.print ac @n1[vm]` prints its operating-point
  value at each frequency.

## Coverage, honestly

Not touched: XSPICE code models beside an OSDI device (the build has XSPICE, but the
uninstalled binary loads no code-model library and every `A` line is `MIF-ERROR`), the
shared library, `montecarlo`/`corners`/`sweep` (their own suites and hunts), noise
totals, `pz`/`tf`/`sp`/`disto` (the 2026-09-21 hunt), string parameters (the 2026-09-05
hunt), file I/O from a model, interrupts. Every value here was read on the Sparse
solver; the suites that would pin a fix run both.
