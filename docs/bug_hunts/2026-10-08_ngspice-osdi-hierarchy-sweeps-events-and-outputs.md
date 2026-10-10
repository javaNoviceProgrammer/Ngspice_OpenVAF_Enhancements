# Bug hunt — ngspice + OSDI: subcircuit copies, sweeps, events, outputs and loading

**When:** 2026-10-08, 13:20–14:20 (a one-hour hunt; the write-up is inside the hour).
**Binaries:** the repo's `ngspice-46/build/src/ngspice` (built 2026-10-04 08:17, the E-789 ngspice
tree; ngspice has not changed since) and `OpenVAF-master-20260610/target/opt/openvaf-r`
(2026-10-04 12:59, E-795). Tree at `1383b5e4`.

**Method:** about 240 probe decks, one compile or simulation at a time under a 12 GB RSS cap,
through throwaway harnesses in the session scratchpad (`h2/*.py`, `h2/*.cir`, driven by
`probe.py`); the last third also ran under macOS Guard Malloc (`libgmalloc`), which turns a
heap overrun into a fault at the overrunning access. Each probe checks against one of:
- a closed-form value;
- the built-in device doing the same thing;
- the same quantity reached a second way (a source sweep against a parameter sweep, `print`
  against `.save`, a top-level card against a subcircuit copy);
- a stated contract (the LRM, the manual, an earlier enhancement's write-up).

The earlier ngspice + OSDI pages (2026-09-02 to 2026-09-29) set the boundary: this hunt went
where they had not:
- `.model` cards inside subcircuits and their per-instance copies;
- internal-node names inside subcircuits and Verilog-A hierarchy;
- `.dc` sweeps of temperature and of OSDI parameters;
- `$fatal`, `$finish` and `$stop` in every analysis and in the step events;
- `pss` and `hb`;
- output vectors (`savecurrents`, `saveused`, noise contributions, raw files);
- model binning;
- loading (`pre_osdi` from included files, `-va` caching, reloads, malformed objects,
  paths with spaces);
- E-543's name-based Newton limiting;
- `$random`, `setseed`;
- long names (512+ characters) through the output commands;
- the LRM's `multiplicity` attribute;
- out-of-range temperatures through `alter` and sweeps.

Nothing was fixed; this is the list.

| | Finding | Severity |
|---|---|---|
| [F1](#f1) | *(fixed in [E-817](../../enhancements_doc/Enhancement-817.md): an instance's own value is kept, the default moves)* `alterparam sub p=v` on a parameter of the `.subckt` line overrides the value every instance gave on its own line | medium |
| [F2](#f2) | *(fixed in [E-818](../../enhancements_doc/Enhancement-818.md))* `altermod gm …` with only subcircuit copies of `gm` prints a note claiming a top-level card exists and was changed | low |
| [F3](#f3) | *(fixed in [E-819](../../enhancements_doc/Enhancement-819.md); an analysis command typed first refused it too)* `.ic`, `.nodeset` and `.save @…` refuse the `x1.n1` spelling of a device or internal node inside a subcircuit that `print`, `alter`, `show` and `.save v(…)` accept | low |
| [F4](#f4) | *(fixed in [E-820](../../enhancements_doc/Enhancement-820.md): the variables carry, the final step at the last point; the initial step still re-fires per point, LRM 5.2.1)* a `.dc` sweep of temperature or of an OSDI parameter re-fires `@(initial_step)` and resets hidden state at every point, and `@(final_step)` sees the restored value, not the last point | medium |
| [F5](#f5) | *(fixed in [E-821](../../enhancements_doc/Enhancement-821.md): every abort restores)* a `.dc` sweep aborted by `$fatal` leaves the swept source or parameter at the failing value for every later analysis | medium |
| [F6](#f6) | *(fixed in [E-822](../../enhancements_doc/Enhancement-822.md); a temperature sweep lagged too, and a setup `$fatal` printed twice)* in a parameter sweep the `OSDI(fatal)` message names the previous sweep point, and in the following op it still says "at sweep value 0" | low |
| [F7](#f7) | *(fixed in [E-823](../../enhancements_doc/Enhancement-823.md): a name found beside the included file is used)* `pre_osdi` and `pre_osdi -va` inside an included library resolve relative paths against the top deck's directory, not the library's | medium |
| [F8](#f8) | *(fixed in [E-824](../../enhancements_doc/Enhancement-824.md): the lookup uses the model hash; 0.23 s at 32 000)* a `.model` inside a `.subckt` costs O(N²) in the instance count: 32 000 wrappers take 19 s with a built-in card, 2.9 s with an OSDI card, 0.19 s with the card at top level | medium (speed) |
| [F9](#f9) | *(fixed in [E-825](../../enhancements_doc/Enhancement-825.md): `$fatal` aborts and names the perturbation, `$finish`/`$stop` end with a note)* a `$fatal` raised during a `sens` perturbation is printed and ignored, and `$stop` and `$finish` are ignored without a word; `sens` completes and prints every sensitivity | medium |
| [F10](#f10) | *(fixed in [E-826](../../enhancements_doc/Enhancement-826.md): re-binned, a size no bin covers refused; built-in BSIM applied that one too)* `alter n1 l=5u` moves a binned instance out of its bin in silence: it stays on `nch.1` with `nch.2`'s size | medium |
| [F11](#f11) | *(fixed in [E-827](../../enhancements_doc/Enhancement-827.md); `pre_snp` too)* `pre_osdi -va` of a source with a compile error advises on how to *find* the compiler | low |
| [F12](#f12) | *(fixed in [E-828](../../enhancements_doc/Enhancement-828.md): once, at the end of the period)* `pss` and `hb` never fire `@(final_step)` | medium |
| [F13](#f13) | *(fixed in [E-829](../../enhancements_doc/Enhancement-829.md): the run fails, exit status 1; `$finish`/`$stop` noted)* `$fatal` (and `$finish`) inside `@(final_step)` is printed and otherwise ignored: no abort, exit status 0 | low |
| [F14](#f14) | *(fixed in [E-830](../../enhancements_doc/Enhancement-830.md): a polarity parameter `type` is also required)* E-543's BJT limiting, chosen by port names, turns a linear `c,b,e` module's op into 577 iterations and gmin stepping (3 without) | medium |
| [F15](#f15) | *(fixed in [E-831](../../enhancements_doc/Enhancement-831.md): the option stood aside, and the default set holds no `@dev[param]`)* `.option saveused` does not collect an `@dev[param]` named in a `.meas` card, so the measure fails | low |
| [F16](#f16) | `$random` and `$arandom` with no seed return the same value in every analysis and in every instance, and ignore `setseed` | medium |
| [F17](#f17) | an OSDI *internal* node with no DC path gets no dc-path gmin: every homotopy fails and the transient op answers 0.5 V where the built-in twin holds 0 | medium |
| [F18](#f18) | under `osdimc` the bins of one binned model draw independently: one device type's process shift jumps at a bin boundary | medium |
| [F19](#f19) | `.option savecurrents` in `ac` and `sp` records an OSDI device's terminal currents as the DC bias current, flat and real at every frequency | high |
| [F20](#f20) | *(fixed in [E-811](../../enhancements_doc/Enhancement-811.md): the line is sized to the name)* **crash**: `print` of a vector whose name is 512 characters or longer overruns a 512-byte heap buffer in `com_print` (intermittent SIGTRAP; deterministic under Guard Malloc) | high |
| [F21](#f21) | *(fixed in [E-812](../../enhancements_doc/Enhancement-812.md): `pvec` builds its line in a growing string)* **crash**: `display` (and `load`, which lists what it reads) of a vector whose name is about 470 characters or longer overflows a 512-byte stack buffer in `pvec` — a deterministic abort | high |
| [F22](#f22) | *(fixed in [E-813](../../enhancements_doc/Enhancement-813.md): the capture copies `SMPmatSize + 1`, the vector's length)* **memory**: with any OSDI internal node, `OSDIload` copies `CKTmaxEqNum + 1` doubles out of `CKTrhsOld` at every bias point, past the end of its allocation (a heap over-read; a fault under Guard Malloc) | high |
| [F23](#f23) | *(fixed in [E-814](../../enhancements_doc/Enhancement-814.md): the compiled model stores the scaled report)* the LRM's `multiplicity="multiply"`/`"divide"` attribute on operating-point variables is ignored: with `m=4` the reports are per device | medium |
| [F24](#f24) | *(fixed in [E-815](../../enhancements_doc/Enhancement-815.md): refused on every route, guarded in `OSDItemp` too)* `alter n1 dtemp=-400` (or `temp=-300`) says the below-absolute-zero value "is ignored", but the OSDI model receives the negative absolute temperature | medium |
| [D](#d) | seventeen smaller slips *(D1–D5 and D7–D17 fixed in [E-796](../../enhancements_doc/Enhancement-796.md)…[E-810](../../enhancements_doc/Enhancement-810.md); D6 kept as designed)* | low |

<a id="f1"></a>
## F1 — `alterparam` on a `.subckt`-line parameter overrides the instances' own values

*Fixed in [E-817](../../enhancements_doc/Enhancement-817.md). inpcom rewrites each call to
carry a value for every parameter -- its own or a copy of the default -- so `alterparam`
could not tell them apart. The rewrite now records on the X card what the instance gave
itself; `alterparam` keeps those values, moves the `.subckt` default, and names who kept
theirs. 4 mA → 13 mA.*

```spice
.subckt cell a b rr=1k
r1 a b {rr}
.ends
xa 1 0 cell rr=1k
xb 1 0 cell rr=500
xc 1 0 cell
...
alterparam cell rr=100
reset
```

After the reset every instance has 100 Ω (`listing expand`: `r.xa.r1 … 1e2`, `r.xb.r1 … 1e2`),
and i(v1) goes from 4 mA to 30 mA. Only `xc`, which took the default, should have moved. The
manual (13.5.5) documents `alterparam subname p=v` for a `.param` *inside* the subcircuit; used
on a parameter of the `.subckt` line it silently rewrites the instances' own values. It is base
ngspice: a built-in resistor reproduces it, and so does an OSDI card `.model gm gres g={gg}`
inside the subcircuit (both instances went to 10m from 1m and 3m). The documented form (a `.param inner` inside the
subcircuit, `alterparam cell inner=500`) works: 2 mA to 4 mA.

<a id="f2"></a>
## F2 — `altermod`'s copies note assumes a top-level card

*Fixed in [E-818](../../enhancements_doc/Enhancement-818.md): whether a top-level card exists
is asked, not assumed. Without one, the note says so, says nothing changed, and names a copy.*

With a card `gm` only inside a subcircuit (copies `x1:gm`, `x2:gm`, `x3:gm`) and no top-level
`gm`, `altermod gm g=7m` prints:

```
Error: no such device or model name gm
Note: 3 models are named 'gm' (the top-level card and 2 flattened subcircuit copies); only the
top-level one was changed -- use '@*:gm[...]' for all of them.
```

There is no top-level card, there are three copies, and nothing changed (i(v1) unchanged). With
one copy there is no note; with a real top-level card and two copies the note is right. E-436's
note counts every model whose leaf name matches and takes one of them for the top-level card.
`altermod *:gm g=5m` and `altermod xa:gm g=2m` work.

<a id="f3"></a>
## F3 — the `x1.n1` alias is refused by `.ic`, `.nodeset` and `.save @…`

*Fixed in [E-819](../../enhancements_doc/Enhancement-819.md): an internal node's name is taken
as the circuit spells it (`x1.n1#mid` → `n.x1.n1#mid`), for `.ic`, `.nodeset` and an analysis
command typed before the first setup -- `tf v(x1.n1#mid) v1` as the first command aborted too
-- and `.save @x1.n1[p]` keeps E-410's reconstruction whenever it finds the device.*

An OSDI device `n1` inside `x1` is `n.x1.n1`, its internal node `n.x1.n1#mid`. The shorter
`x1.n1` spelling is accepted unevenly:

| construct | `x1.n1…` | `n.x1.n1…` |
|---|---|---|
| `print v(x1.n1#mid)`, `.save v(x1.n1#mid)`, `.meas … v(x1.n1#mid)` | accepted | accepted |
| `alter @x1.n1[r]=2k`, `alter x1.n1 r=8k`, `show x1.n1` | accepted | accepted |
| `.ic v(x1.n1#mid)=1.5`, `.nodeset v(x1.n1#mid)=0.3` | **"IC on non-existent node … ignored"** | accepted |
| `.save @x1.n1[pw]` | **"no such device, so this vector will stay empty"** | accepted |

A built-in BJT's internal node inside a subcircuit (`.ic v(x1.q1#base)`) is refused the same
way. Related: a Verilog-A child's internal node is exposed only as `n1#c1__mid`. The dotted
`n1#c1.mid` is refused by `.ic` and by `print` (see D).

<a id="f4"></a>
## F4 — temperature and OSDI-parameter sweeps re-run the initial step at every point

*Fixed in [E-820](../../enhancements_doc/Enhancement-820.md). The re-fire stays: BSIM4 does
its whole temperature and parameter preprocessing in `@(initial_step)`, and LRM 5.2.1
re-executes initialisation when a sweep changes a parameter it reads. The variables now carry
from point to point (LRM 4.6.2): a later point's initial step carries a new flag, and the
compiled model initialises its variables only without it. The final step fires before the
restore. Counter 11, 12, 13; final step at 373.15 K.*

A module counting its `@(initial_step)` firings into an integer and printing in
`@(final_step)`:

| analysis | `initial_step` | counter at each | `final_step` sees |
|---|---|---|---|
| `dc v1 0 2 1`, `dc r2 1k 3k 1k`, `dc i1 0 2m 1m` | 1 | 1 | the last point (V = 2) |
| `dc temp 0 100 50` | **3** | 1, 1, 1 | **T = 27 °C** (restored), not 100 |
| `dc @n1[p] 1 3 1` (instance parameter) | **3** | 1, 1, 1 | **p = 1** (restored), not 3 |
| `dc @tm[q] 1 3 1` (model parameter) | **3** | 1, 1, 1 | **q = 1** (restored), not 3 |
| `dc v1 0 1 1 temp 0 100 100` | 2 (one per outer point) | | T = 27 °C |

Three faults:
- **The initial step re-fires per point**, with E-789's mechanism: the sweep re-runs the
  device's temperature pass at every point, and that pass clears the "first evaluation" mark.
- **Hidden state resets with it.** The counter reads 1 every time, so a model that
  accumulates across a sweep loses its state.
- **`@(final_step)` runs after the sweep has restored the temperature or parameter.** E-53
  documented the contract as "fires once and sees the last sweep point". That holds for a
  source sweep, but here it sees the restored value instead.

The final evaluation also prints the model's `$strobe` output a fourth time, at the restored
point, after a three-point sweep. Re-firing the initial step at each temperature may be what a
model caching temperature-dependent values there wants. That is a design question; the
hidden-state reset and the `final_step` value are not.

<a id="f5"></a>
## F5 — a sweep aborted by `$fatal` leaves the swept value behind

*Fixed in [E-821](../../enhancements_doc/Enhancement-821.md): every abort of the sweep
restores what it swept, as its end does. A non-converged point takes the same exit. `$stop`
still keeps its value for `resume`.*

```spice
v1 1 0 0
n1 1 0 fm          ; $fatal when V > 1.5
dc v1 0 3 1
print @v1[dc]      ; 2  (the netlist says 0)
op                 ; runs at 2 V and raises the same $fatal again
```

After `$finish` the source is restored (0); after `$fatal` it is not. A parameter sweep does
the same: `dc @fpm[g] 1m 4m 1m` aborted at 3m leaves `@fpm[g]` = 3e-3 (card 1m), and every later
analysis runs on it until `reset`. `$stop` also leaves 2, but that is a pause a `resume` may
continue, and resume works (see the clean list). A sweep aborted by plain non-convergence could
not be provoked for comparison.

<a id="f6"></a>
## F6 — the `OSDI(fatal)` location lags in a parameter sweep

*Fixed in [E-822](../../enhancements_doc/Enhancement-822.md). The message comes from the
device's setup code, run by the temperature pass that applies the point, before the point
reached `CKTtime`. The op after it read the dc's leftover mode. The sweep now publishes the
point before applying it, and a setup-pass message outside a sweep says "(during setup)". A
temperature sweep lagged the same way, and a setup `$fatal` printed twice; both are fixed.*

In the F5 parameter sweep:

```
OSDI(fatal) n1: g too big 0.003 (at sweep value 0.002)
Error: a Verilog-A device raised $fatal at sweep value 0.003; aborting.
...
OSDI(fatal) n1: g too big 0.003 (at sweep value 0)          <- the op that follows
Error: a Verilog-A device raised $fatal during the operating point; aborting.
```

The device's own line names the previous point, and in the next op still names a sweep. A
source sweep tags both lines correctly.

<a id="f7"></a>
## F7 — `pre_osdi` in an included library resolves against the top deck

*Fixed in [E-823](../../enhancements_doc/Enhancement-823.md): while the reader reads an included
file, a relative name in a `pre_osdi` or `osdi` line that names a file beside that file is
rewritten to it -- relative to the deck when beneath it, so `-va` keeps its object name, else
absolute. A `.lib` section and a nested include work the same way.*

```spice
* sub/inc.lib, beside sub/gres.osdi and sub/gres.va
.control
pre_osdi gres.osdi          ; or: pre_osdi -va gres.va
.endc
.model gm gres g=2m
```

`.include sub/inc.lib` from `top.cir` fails, from any working directory:
- `pre_osdi gres.osdi` gives `Error opening osdi lib "gres.osdi"`;
- `pre_osdi -va gres.va` gives `pre_osdi: no such Verilog-A source: ./gres.va`.

A deck's own relative `pre_osdi` resolves against the deck's directory (run from elsewhere it
works), and nested `.include`s resolve against the including file. A model library that ships
`models.lib` and `models.osdi` side by side cannot load its object by a relative path.

<a id="f8"></a>
## F8 — a `.model` inside a `.subckt` is quadratic in the instance count

*Fixed in [E-824](../../enhancements_doc/Enhancement-824.md): `INPlookMod` (and XSPICE's
`MIFgetMod`) use the hash table `INPmakeMod` already kept beside the list. 32 000 wrappers with
a built-in card inside: 0.23 s (7.9 s on the E-822 binaries), linear to 1.1 s at 128 000.*

Subcircuit expansion copies a card defined inside a subcircuit once per instance
(`x1:gm`, `x2:gm`, … — no de-duplication, even for identical parameters). Then `INPpas2`
looks each instance's model up with `INPlookMod`, a linear `strcmp` scan of the model list
(`sample` of the 32 000 built-in run: 2287 of 2295 samples in `INPlookMod` and the `strcmp` it calls). One copy per instance makes that
N × N. One `op`, wall time:

| instances | built-in R card inside | at top | OSDI card inside | at top |
|---|---|---|---|---|
| 8 000 | 1.3 s | 0.06 s | 0.25 s | 0.06 s |
| 16 000 | 4.6 s | 0.12 s | 0.79 s | 0.13 s |
| 32 000 | 19.0 s | 0.19 s | 2.9 s | 0.19 s |

The wrapper idiom (a Verilog-A device in a subcircuit that holds its card) is exactly this
shape.

<a id="f9"></a>
## F9 — `$fatal` during a `sens` perturbation is ignored

*Fixed in [E-825](../../enhancements_doc/Enhancement-825.md): the perturbation loop read none of
what the perturbed setup and load returned. Now a `$fatal` aborts with an error naming the
perturbation, `$finish` and `$stop` end the analysis with a note, and the device's line says
"(while sens perturbed n1:g to 0.001000001)".*

A model with `if (g > lim) $fatal(...)`, nominal `g` = `lim`, so the first upward
perturbation trips it:

```
OSDI(fatal) n1: g 0.001 over limit (at the operating point)
n1:g = -2.50000e+02
... every other sensitivity ...
```

The analysis is not aborted and its results are printed, while op, dc, tran, ac and noise all
abort on `$fatal`. The location tag also says "at the operating point" for a perturbation.

`$stop` and `$finish` raised the same way are ignored without any note: no pause, no early end,
and the sensitivities are printed. In op, dc and tran each of the three acts and says so.

<a id="f10"></a>
## F10 — `alter` moves a binned instance out of its bin in silence

*Fixed in [E-826](../../enhancements_doc/Enhancement-826.md): ngspice's existing re-binning on
`alter w`/`l` ran for m-devices only; it now runs for any instance on a bin, and a size no bin
covers is refused with the bins named. The m-device path applied such a size after its
"no model available" -- a built-in BSIM4 instance was left outside its bin -- and refuses it
now too.*

```spice
.model nch.1 bm g=1m lmin=0  lmax=1u  wmin=0 wmax=10u
.model nch.2 bm g=3m lmin=1u lmax=10u wmin=0 wmax=10u
n1 1 0 nch l=0.5u w=1u      ; bound to nch.1
alter n1 l=5u
op                          ; still 1 mA: nch.1's g; show n1 -> model nch.1, l 5e-06
```

The instance now runs with `nch.1`'s parameters at a size only `nch.2` covers, and nothing
says so. Binning itself works: OSDI cards bin by `lmin`/`lmax`, and an instance outside every
bin gets a clear error naming the bins. A paramset family in the same situation at least
refuses the value (D). Built-in binned models were not checked.

<a id="f11"></a>
## F11 — a compile error is answered with advice for a missing compiler

*Fixed in [E-827](../../enhancements_doc/Enhancement-827.md): one report for `pre_osdi -va` and
`pre_snp` tells a compiler that could not be run (no such file, not on PATH, not executable)
from one that ran and refused the source, and only the first gets the advice. `pre_snp` also
printed the raw wait status ("exit 32512").*

```
error: 'nosuch' was not found in the current scope
...
pre_osdi: openvaf-r failed (exit 65) compiling ./sub/bad.va.
  Set the compiler with `set openvaf=/path/to/openvaf-r`, the OPENVAF
  environment variable, or put openvaf-r in $SPICE_LIB_DIR or PATH.
```

The compiler was found and ran; the source has an error. The location advice belongs to
"compiler not found" only.

<a id="f12"></a>
## F12 — `pss` and `hb` never fire `@(final_step)`

*Fixed in [E-828](../../enhancements_doc/Enhancement-828.md): `pss` fires it at the end of the
confirmed period, `hb` at t = T on the sum of its harmonics (after dropping a bias-point
capture its own small-signal loads had retaken, which read the last sample instead).*

The counting module of F4, in the driven RC deck of `pssdriven_examples`:

| analysis | `initial_step` | `final_step` |
|---|---|---|
| `tran 1n 2u` | 1 | 1 |
| `.pss 1meg 1u b 1024 10 50 5u` + `run` | 1 | **0** |
| `hb 1meg 8` | 1 | **0** |

E-683 made every analysis fire `@(final_step)` once. A model that closes a file or reports a
tracked peak there never does under `pss` or `hb`.

<a id="f13"></a>
## F13 — `$fatal` inside `@(final_step)` is a print

*Fixed in [E-829](../../enhancements_doc/Enhancement-829.md): `OSDIfinalStep` discarded what its
evaluations returned. The flags are kept, and after the analysis returns the job asks: a
`$fatal` fails it (an error line, "simulation(s) aborted", exit status 1, the results kept), a
`$finish` or `$stop` is noted. `hb` asks too.*

`@(final_step) $fatal(0, "...")` prints `OSDI(fatal) n1: … (at the operating point)` (or
`at t = 3e-09`, or `at sweep value 1`) and nothing more: the analysis is not marked aborted,
the exit status is 0, and the script runs on. A `$fatal` anywhere else aborts and gives
exit status 1. A `$finish` inside `@(final_step)` is silent too. A `$fatal` in
`@(initial_step)` aborts properly.

<a id="f14"></a>
## F14 — E-543's limiting is applied to anything with BJT port names

*Fixed in [E-830](../../enhancements_doc/Enhancement-830.md): the BJT family now also needs a
polarity parameter `type`, which every transistor model in the corpus carries; the linear
network converges in 3 iterations. The MOSFET family, whose linear twin cost 6, is unchanged.*

E-543 recognizes a MOSFET by `d,g,s[,b]` and a BJT by `c,b,e[,s]` and applies the built-ins'
limiting to a model that calls no `$limit`. A *linear* three-terminal resistor network
`module rnet(c, b, e)`, with `vc c 0 100` and `rb b 0 1meg`:

| | op iterations | gmin stepping | answer |
|---|---|---|---|
| default | **577** | dynamic gmin stepping | v(b) = 49.975 V |
| `.option noosdilim` | 3 | none | 49.975 V (analytic 49.975) |
| the `d,g,s,b` twin | 6 | none | |

In a transient (a 0 → 100 V pulse, 2029 points either way) it costs 5669 Newton iterations
against 4059. `pnjlim` on a non-junction crawls: the answer is right, the cost is not. A large
circuit of such modules could fail to converge.

<a id="f15"></a>
## F15 — `saveused` misses an `@dev[param]` in a `.meas` card

*Fixed in [E-831](../../enhancements_doc/Enhancement-831.md). The references were collected
(E-572); the option stood aside, because the control block had no output command, and the
default save set holds no `@dev[param]`. Standing aside now saves those vectors too.*

```spice
.option saveused
.meas tran p_max max @n2[pw]     ; OSDI opvar     -> "holds 1 point(s) but the analysis produced 2018"
.meas tran i_max max @r1[i]      ; built-in, same
.meas tran mid_max max v(n1#mid) ; saved, fine
```

E-469 collects references from the `.control` block. A `.meas` card's `v(…)` reaches the
saved set, its `@dev[param]` does not.

<a id="f16"></a>
## F16 — `$random` and `$arandom` without a seed: the same number every analysis and every instance

```verilog
@(initial_step) begin r1 = $random; ... end
```

Four `op`s around `setseed 1`, `setseed 1`, `setseed 2` all print `r = 1366254664`. A
`repeat N op` loop meant to draw fresh values draws the same one every time, and ngspice's own
seed command has no effect. A seeded `$rdist_normal(s, …)` with `s` re-initialised in the
initial step repeating is expected.

It is also the same in every instance. Two instances `n1` and `n2` of one module draw identical
`$random` (1366254664) and `$arandom` (−8.80036e8) values, in an `op`, after `setseed 7`, and in a
`tran`. Per-device randomness written with the unseeded calls is therefore perfectly correlated
across devices.

<a id="f17"></a>
## F17 — a DC-floating internal node gets no dc-path gmin

```verilog
module fl(a, b); ... electrical mid;
  I(a,b)   <+ V(a,b)/1k;
  I(a,mid) <+ ddt(1p*V(a,mid));
  I(mid,b) <+ ddt(1p*V(mid,b));
```

`op` gives `singular matrix: check node n1#mid` six times, then:
- dynamic gmin, true gmin and source stepping all fail;
- the transient op finally answers `v(n1#mid)` = 0.5 V.

The built-in twin (an external node reached only through two capacitors) gets the dc-path
check's gmin at once (`no DC path from node '2' to ground; gmin installed`) and holds the node
at 0. An *external* node reached only through OSDI capacitors is handled. So the dc-path walk
does not see OSDI internal nodes. `.option rshunt=1e9` works around it; with `.option klu` in the deck the
same messages appear.

<a id="f18"></a>
## F18 — the bins of one model draw independently under `osdimc`

`nch.1` and `nch.2`, one device type at two sizes, with `(* std_rel=0.1 *) g` and the same
nominal, under `.option osdimc`:

| trial | `@nch.1[g]` | `@nch.2[g]` |
|---|---|---|
| 1 | 0.930m | 0.869m |
| 2 | 1.100m | 1.113m |

Process variation is meant to move the whole device type together. Here a transistor's shift
jumps at a bin boundary. The root is the one the
[statistics proposal](../proposals/2026-10-06_statistics-vary-block.md) records for
subcircuit copies: a model parameter's draw is keyed on the card. Its phase 0 (key on the
definition) would have to treat bins of one name as one definition.

<a id="f19"></a>
## F19 — `savecurrents` in `ac` and `sp` records the bias current for OSDI devices

```spice
v1 1 0 dc 2 ac 1
n1 1 0 rr2m        ; r1 = r2 = 1k, c = 1n from the internal node
r9 1 0 1k
.option savecurrents
ac lin 3 1k 1meg
```

| f | `@n1[i_a]` | true small-signal current (from `i(v1)` − 1 mA) |
|---|---|---|
| 1 kHz | 1.000e-3 + 0j | 0.500e-3 + 0.0016e-3j |
| 500 kHz | 1.000e-3 + 0j | 0.856e-3 + 0.226e-3j |
| 1 MHz | 1.000e-3 + 0j | 0.954e-3 + 0.145e-3j |

The complex ac vectors `@n1[i_a]`, `@n1[i_b]` and `@n1[i]` hold the DC operating-point current
(2 V / 2 kΩ) at every frequency, with dc = 0 they are all zero. They look like ac data and are
not. Built-in devices record nothing in `ac` (0-long `@r9[i]`, `@c1[i]`; see D), which is at
least not wrong. In `op`, `dc` and `tran` the same vectors are right: KCL against the source
holds to 8.7e-19 A over a transient, and `m=2` is included.

An `sp` analysis does the same: with a 50 Ω port at dc = 2 V, `@n1[i_a]` is 9.756e-4 + 0j (the bias
current, 2 V / 2.05 kΩ) at 1 kHz, 500 kHz and 1 MHz. [E-394](../../enhancements_doc/Enhancement-394.md), which introduced
these vectors, defines them from the device's own KCL stamp: the resistive residual, plus the
charge derivative in a transient. A small-signal analysis was not considered. Its value is the
phasor `(G + jωC)·v`.

*Update ([E-808](../../enhancements_doc/Enhancement-808.md)): `.options savecurrents` no longer puts these vectors into an `ac` or `sp`
plot. An explicit `.save @n1[i_a]` still records the bias current there, and a true small-signal
terminal current is still open.*

<a id="f20"></a>
## F20 — `print` of a long name overruns a heap buffer (a crash)

*Fixed in [E-811](../../enhancements_doc/Enhancement-811.md): `com_print` grows its line buffer to the name before writing it; 600- and
3000-character names print whole, under Guard Malloc too.*

```spice
v1 1 0 2
rxxxx…x 1 0 1k          ; an instance name of 512 characters or more
.control
op
print @rxxxx…x[i]
.endc
```

| name length | crashes (exit 133, SIGTRAP) |
|---|---|
| 128, 255, 256, 400, 511 | 0 of 12 each |
| 512 | 2 of 12 |
| 700 | 2 of 12 |

Under macOS Guard Malloc (`DYLD_INSERT_LIBRARIES=/usr/lib/libgmalloc.dylib`) it faults every
time, with `EXC_BAD_ACCESS` in this stack:

```
_platform_memmove <- _platform_strcpy <- com_print <- doblock <- cp_evloop <- inp_spsource <- main
```

`com_print` (`frontend/postcoms.c:212`) allocates `buf = TMALLOC(char, BSIZE_SP)` (512 bytes) and
does `strcpy(buf, basename)` with the vector's name. A name of 512 characters or more overruns
it, and the random fault is ordinary heap corruption. It is base ngspice (a built-in resistor
reproduces it, with or without `savecurrents`). It was first hit with a 1000-character OSDI
instance under `.option savecurrents`. A long Verilog-A *parameter* name gets there too:
`print @lpm[<600-character parameter>]` faults under Guard Malloc, while `showmod`, `show` and
`devhelp` print the same name safely. Generated netlists, from a flattener or a layout
extractor, reach such names.

<a id="f21"></a>
## F21 — `display` of a long name overflows a stack buffer (a deterministic crash)

*Fixed in [E-812](../../enhancements_doc/Enhancement-812.md): `pvec` builds its line in a growing string; `display`, a noise plot's
listing and `load` handle 600-character names.*

```spice
v1 nyyyy…y 0 2          ; a node name of 500 characters
r1 nyyyy…y 0 1k
.control
op
display
.endc
```

`display` exits with 133 (SIGTRAP) every time: 5 of 5 runs at 600 characters, and also at
500. 400 is fine. The stack is
`__chk_fail_overflow <- __sprintf_chk <- pvec <- com_display <- doblock <- cp_evloop`.
`pvec` (`frontend/plotting/pvec.c`) formats `"    %-20s: %s, %s, %d long"` with the vector's name
into `char buf[BSIZE_SP]` (512 bytes) with `sprintf`, and the fortified C library aborts the
overrun. A `print v(<600-character node>)` hits F20's `com_print` copy instead (SIGSEGV under
Guard Malloc). The name need not be typed by the user. A noise analysis with per-device
contributions (`noise v(2) v1 lin 1 1k 1k 1`) names a vector `onoise_<device>_thermal`, so a
480-character OSDI instance name makes `display` of the `noise1` plot abort 3 of 3 times. Without
the `display` the run completes. And `load` lists the vectors it reads through the same `pvec`, so loading a raw
file (binary or ASCII) that holds a 600-character vector name aborts too, plain run included.
Writing that file is fine.

Swept with 600-character names under Guard Malloc and found clean: `show`, `alter @…[…]=`,
`let`, `wrdata`, `.save @…[i]`, `.meas` on `v(…)`, `.ic v(…)`, `asciiplot` and `fourier`. A 700-character title is clean in
`setplot`, `print all`, `plot` and `listing`. 3000-character `$strobe`, `%s`-of-a-string-parameter and `$warning` messages
print intact under Guard Malloc.

<a id="f22"></a>
## F22 — `OSDIload` reads past the end of the right-hand side when a model has internal nodes

*Fixed in [E-813](../../enhancements_doc/Enhancement-813.md). The cause is an off-by-one, not the internal node. The solution vectors
hold `SMPmatSize + 1` doubles, which is `CKTmaxEqNum`, and the capture copied
`CKTmaxEqNum + 1`. It ran at every `op` (DCop's closing `MODEINITSMSIG` load) and at every ac or
noise bias point. It faulted whenever the vector's length filled its allocation slot, so it
depends on the parity of the unknown count, as the wider note below found.*

Found while chasing F20 under Guard Malloc. Any module with an internal node faults:

```verilog
module v_internal(a, b); inout a, b; electrical a, b; electrical mid;
  analog begin I(a,mid) <+ 1e-3*V(a,mid); I(mid,b) <+ 1e-3*V(mid,b); end
endmodule
```

`DYLD_INSERT_LIBRARIES=/usr/lib/libgmalloc.dylib ngspice -b` on a one-device `op` gives
`EXC_BAD_ACCESS` in `_platform_memmove <- OSDIload <- CKTload <- DCop`. The same module without
the internal node is clean, and so are variants with `$strobe`/`%m`, `$display` and
`(* std_rel *)`. A built-in BJT with three internal nodes (`rb`, `rc`, `re`) is clean too. So it
is OSDI-specific and keyed on internal nodes.

The faulting call is `osdi_op_solve_capture` (`osdi/osdiload.c`, E-677's capture of the bias
point for the final step), inlined at `OSDIload+436`. The disassembly loads `CKTmaxEqNum`, adds
one, and `memcpy`s that many doubles from `CKTrhsOld`. With an OSDI internal node the count
exceeds the right-hand-side vector's allocation, so every bias point reads past the end of a
heap block. Plain runs did not crash in six tries: the over-read usually lands in the
allocator's slack, and the extra values are copied into the snapshot and never used. A read
that crosses into an unmapped page would kill the run. The rhs vectors' own length
(`SMPmatSize + 1`) is the bound to copy. E-689's `uic` code in the same file already copies
`SMPmatSize(ckt->CKTmatrix) + 1` (line 1486); the E-677 capture (line 1402) and its reader's check
(line 2155) use `CKTmaxEqNum + 1`. The same module in a `tran 1n 10n uic`, which computes no bias point, runs
clean under Guard Malloc, consistent with the bias-point capture being the only site.

*Wider than first written (found while verifying the D slips):*
- *An OSDI module without internal nodes faults at the same site (`OSDIload+440`, `memmove`)
  under Guard Malloc. It does so beside built-in R, C and D, or in a subcircuit: the
  osdislips [14] decks and [12]'s noise deck.*
- *The E-795 binaries fault on the same decks.*
- *So the count exceeds the allocation whenever `CKTmaxEqNum` runs past the matrix size, not
  only through OSDI internal nodes.*

<a id="f23"></a>
## F23 — the `multiplicity` attribute on operating-point variables is ignored

*Fixed in [E-814](../../enhancements_doc/Enhancement-814.md): the compiled model stores the
report, scaled by the effective multiplicity (a subcircuit's `m`, a paramset's `.$mfactor` and a
Verilog-A child's `#(.$mfactor(...))` included), and leaves the variable the model reads alone.
Wider than written: twenty corpus families declare their operating point with the attribute,
on about 1,400 variables; "about 90" counted the attribute's text, mostly macro definitions.*

LRM 3.2.1: an output variable's `multiplicity` attribute says how its value is scaled "in any
report of operating-point values": multiplied by `$mfactor` (`"multiply"`), divided by it
(`"divide"`), or not at all (`"none"`, the default).

```verilog
(* desc="current", units="A",   multiplicity="multiply" *) real itot;   // V/1k
(* desc="reff",    units="Ohm", multiplicity="divide"   *) real reff;   // 1k
```

With `n1 1 0 mum m=4` at 2 V, `print @n1[itot] @n1[reff]` and `show n1` report 2e-3 and 1000,
the per-device values. The LRM's report is 8e-3 and 250. (The current itself, `i(v1)` =
−8 mA, is scaled right; an opvar without the attribute is correctly unscaled.) The attribute is
common in standard models: about 90 uses in the bundled corpus, in BSIM-CMG's and BSIM-IMG's
macros, HICUM L0, HiSIM-SOTB and EKV. Their operating-point reports for a device with `m > 1`
(drain current, conductances, capacitances) are off by the factor m.

<a id="f24"></a>
## F24 — a below-absolute-zero instance temperature set by `alter` reaches the model

*Fixed in [E-815](../../enhancements_doc/Enhancement-815.md). `OSDIsetup` guarded the composed
temperature and `OSDItemp`, run for every later analysis and sweep point, did not. Wider than
written:*
- *`dt=-400` on the line (the knob's other spelling) was not refused;*
- *a built-in device took the values through `alter` and `.dc`;*
- *a later ambient change (`dtemp=-290`, then `set temp=-10`) reached the model too.*
- *the `sweep` command over the same range solved its first point at -99.85 K. Once
  `alter` refused the value, that point would have been solved at the previous value and
  recorded under -400, so it is now recorded as NaN.*

*The current at -99.85 K was +0.33 mA, not -0.33 mA. The line, `alter` and `.dc` now refuse
such a value by one rule, and one guarded composition serves every OSDI route.*

A module printing `$temperature`, with a resistance of `r*(1 + 0.01*($temperature - 300.15))`:

| how | message | the model sees | i(v1) |
|---|---|---|---|
| `n1 … dtemp=-400` on the line | "puts the device at -373 C, at or below absolute zero …; ignored." | 300.15 K | −1 mA |
| `n1 … temp=-300` on the line | "… ignored, the circuit temperature is used instead." | 300.15 K | −1 mA |
| `alter n1 dtemp=-400` | "instance temperature -99.85 K is at or below absolute zero (temp=27 C, dtemp=-400); the offset is ignored" | **−99.85 K** | −0.33 mA |
| `alter n1 temp=-300` | "instance temperature -26.85 K is at or below absolute zero (**temp=27 C, dtemp=0**); the offset is ignored" | **−26.85 K** | **+0.44 mA** |

On the instance line the value is refused and the device keeps the circuit temperature. Through
`alter` the message says the same, but the OSDI device's evaluation gets the negative absolute
temperature. Here that made the resistance negative and reversed the current. The `temp=-300`
note also misreports the inputs ("temp=27 C, dtemp=0"). A sweep goes further:
`dc @n1[dtemp] -400 0 200` runs its first point at −99.85 K with no warning at all
(i = +0.33 mA). `.temp -300`, `set temp=-300` and a `dc temp` range below 0 K are refused
properly.

<a id="d"></a>
## D — smaller slips

- **D1** `altermod ipm n=3.7` on an integer model parameter rounds to 4 in silence; the same
  value on the card warns "rounded to the nearest integer". *(fixed in [E-796](../../enhancements_doc/Enhancement-796.md), which found
  more: -2.5 became -2 where the card gives -3, and 1e300 or 3e9 was stored as 2147483647 where
  the card refuses it.)*
- **D2** `.save @n1[opvar]` prints `'iop' has no value yet … it is recorded per point once an
  analysis runs` at every load: a warning on a correct deck. *(fixed in [E-797](../../enhancements_doc/Enhancement-797.md))*
- **D3** `print @t3m[mode]` of a string model parameter: `ERROR: can not handle string value of
  'mode' in vec_get`; `showmod` shows it. *(fixed in [E-798](../../enhancements_doc/Enhancement-798.md): `print` shows the text)*
- **D4** A paramset family bound to member `rs` (`l` in `[1:10)`): `altermod rsm l=20` is
  refused "out of bounds … range from [1:10)" with no word that member `rs__2` covers 20 and
  that members are chosen when the card is read. *(fixed in [E-799](../../enhancements_doc/Enhancement-799.md). The "a `reset` re-binds"
  first written here was wrong: `reset` reloads the netlist's own `l=2`; the remedy is to write
  the value in the netlist.)*
- **D5** `.temp 0 27 50`: `Could not set temperature to 0 27 50`, and the run continues at
  27 °C (base ngspice; SPICE2 ran each temperature). *(fixed in [E-800](../../enhancements_doc/Enhancement-800.md): it runs at the first
  and says how to run each; a run per temperature is left for a decision)*
- **D6** `@(timer(0, 1u))` fires at t = 0 in an `op` and at the first point of a `dc` sweep.
  The LRM bars `cross()` from dc/ac/noise and lets `above()` fire; the timer is unspecified.
  A design question. *(kept as designed: an equilibrium analysis sits at t = 0, so a timer
  starting there fires once, which is the state the transient starts from, and one starting
  later never fires; pinned in [`osdislips_examples`](../../examples/osdislips_examples/) [6])*
- **D7** `pz 1 0 1 0 pol` (the transfer type `vol`/`cur` missing) is answered `no such
  parameter on this device or parameter is missing` (base ngspice). *(fixed in [E-801](../../enhancements_doc/Enhancement-801.md))*
- **D8** A `.meas` result prints twice in a batch run with a `.control` block (after the
  analysis and again at exit), and `print` of the measure name says "not available" (base).
  *(fixed in [E-802](../../enhancements_doc/Enhancement-802.md); a deck `.tran` with `run` in the block was simulated twice as well)*
- **D9** The `osdi` command:
  - `osdi` alone answers "too few args", with no list of loaded libraries;
  - an unknown flag `-l` is read as a file name;
  - `osdi -f` with no file is silently ignored.

  *(fixed in [E-803](../../enhancements_doc/Enhancement-803.md))*
- **D10** A parameter set twice on an OSDI card: "only one value takes effect -- remove one",
  without saying which (the last ran). The instance-line twin says "the last value is used".
  *(fixed in [E-804](../../enhancements_doc/Enhancement-804.md); a repeated instance-parameter default on a card had kept its FIRST
  value, which is why E-395 named neither)*
- **D11** Too many nodes on an OSDI instance line: "too many nodes connected to instance",
  naming neither the model's terminal count nor its terminals. Too few, or a stray value, get
  good messages. *(fixed in [E-805](../../enhancements_doc/Enhancement-805.md))*
- **D12** A Verilog-A child's internal node is reachable only as the mangled `n1#c1__mid`; the
  hierarchical `n1#c1.mid` is refused by `.ic` and `print`. A noise contribution of a device in
  a subcircuit is `onoise_n.x1.n1_thermal` only (no `x1.n1` alias). *(fixed in [E-806](../../enhancements_doc/Enhancement-806.md))*
- **D13** Binned cards `nch.1`/`nch.2`: `altermod nch g=7m` is "no such device or model name
  nch", with no word about the bins, and no wildcard reaches them (`nch*`, `nch.*`,
  `@nch*[g]`; E-436's `@*:name[…]` covers subcircuit copies only). *(fixed in [E-807](../../enhancements_doc/Enhancement-807.md):
  `altermod nch` reaches every bin)*
- **D14** `.option savecurrents` in `ac` leaves built-in devices' current vectors 0 long
  (`@r9[i]`, `@c1[i]`), so `print` of them fails (base ngspice; compare F19). *(fixed in
  [E-808](../../enhancements_doc/Enhancement-808.md), with D15: savecurrents' vectors stay out of ac, sp and noise plots, and a note points
  to `.probe i(<device>)`)*
- **D15** `.option savecurrents` in a `noise` analysis puts `@n1[i_a]` and a built-in `@rs[i]`
  into the `noise1` plot as real per-frequency "currents" (bias values; base ngspice).
  *(fixed in [E-808](../../enhancements_doc/Enhancement-808.md); `noise2` carried them too)*
- **D16** After a model's `$finish` ends a `tran` at 0.503 µs,
  `.meas tran vavg avg v(1) from=0 to=1u` averages over [0, 0.503 µs] and reports
  `to= 5.028e-07`, with no word that the requested window was cut. (A `when` measure past the
  end fails with "out of interval", which is fine.) *(fixed in [E-809](../../enhancements_doc/Enhancement-809.md))*
- **D17** A saved OSDI opvar is typed *voltage* in the plot unless its unit is amperes: `units="A"`
  gives *current*, while `units="W"`, `units="Ohm"` and no `units` all give `voltage, real, 108 long`.
  *(fixed in [E-810](../../enhancements_doc/Enhancement-810.md); `units="A"` gave current only because the opvar's name began with `i`)*

## Verified clean

- **Subcircuit copies:**
  - `altermod xa:gm`, `@xb:gm[g]=`, `*:gm`;
  - `m=3` on the subcircuit instance;
  - `dc @xa:gm[g]` (and its restore);
  - `reset` after `altermod`;
  - a derived subcircuit default (`g2={2*gg}`) into an OSDI card;
  - `set corner=ss` and `.option autocorner` over the copies;
  - `aging` of a device inside a copy;
  - noise of copies (two instances = X `m=2` = instance `m=2` = built-in).
- **Internal nodes (top level):** `.ic` with and without `uic`, `.nodeset`, `.save`, `print`,
  raw `write`/`load` (binary and ASCII). The stored t = 0 point under `uic` matches the
  built-in capacitor.
- **Integer and string parameters:**
  - card rounding warns;
  - out-of-range values and out-of-set strings are refused on cards and by `alter`;
  - `dc @ipm[n]` refuses a fractional step;
  - `alter`/`altermod`/`@n1[mode]=` of strings, quoted or not.
- **Temperature:**
  - `dtemp` and `temp` on instances;
  - `.temp`, `set temp`, `alter n1 dtemp`;
  - an instance `temp=50` holds through a `dc temp` sweep;
  - `$simparam` `gmin` and `tnom` follow `.option`.
- **Opvars:**
  - per point in `tran` and `dc`, and the bias value in `ac`;
  - `.meas` on them, `stop when @n2[pw] > 1m`;
  - integer opvars.
- **Terminal currents:** `show n1` (`i_a`, `i_b`, `i`), `.option savecurrents` and `.probe i(n1)`
  in `op`, `dc` and `tran`.
- **Loading:**
  - an already-loaded file is skipped with a note;
  - `osdi -f` + `reset` picks up a recompiled object, and a run on a stale circuit is refused;
  - an empty, truncated, text or non-OSDI file, or a missing one, gets a clear error and the
    circuit still runs;
  - quoted paths with spaces work;
  - the `-va` cache recompiles after an edit of the source or of an included header, and keeps
    same-named sources in different directories apart (`da_m.osdi`, `db_m.osdi`);
  - modules named `r`, `d`, `nmos`, `sw`, `res` get the clash note and warning;
  - `devhelp` lists an OSDI device's parameters.
- **Two circuits in one session:** `setcirc`, `altermod` and `remcirc` keep their cards apart.
- **Analyses:**
  - `sp` with an OSDI load (S11 = 0.3333);
  - `tf` through an internal node (0.75, 4000 Ω, 750 Ω);
  - `pz`;
  - `cross` events at the analytic times with and without `interp`;
  - `stop when` and `.meas when`;
  - `$bound_step` against `tran`'s `tmax` (the smaller wins);
  - `above()` in dc sweeps (LRM 5.10.3.2), `cross()` never in dc;
  - LC tank OSDI vs built-in capacitor identical under trap and gear;
  - nested `dc @n1[g] … @n2[g] …` and `dc @n1[m]` sweep and restore.
- **Run control:**
  - `$finish`, `$stop`, `$fatal` in `dc` and `tran` report the point;
  - `resume` after `$stop` runs to the end with the model's state kept;
  - `$fatal` under `analysis("ac")`/`("noise")` aborts at the bias point;
  - `$fatal` in `@(initial_step)` aborts;
  - E-789's `sens` hold is released after a `sens` run.
- **Monte Carlo:** under `osdimc` a `dc temp` or parameter sweep keeps one draw for all its
  points.
- **Node collapse:** `V(a,mid) <+ 0` when `rs == 0` is re-decided after `alter n1 rs=0` and
  back.
- **Values through `alter` and `altermod`:**
  - `alter n1 m=-2` is refused with a warning, and `m=0` is noted;
  - `altermod gm g=nan`, `g=inf` and `g=1e400` are refused;
  - `alter @gm[g]=` on a model parameter points to `altermod`.
- **Temperature limits:**
  - `.option tnom=-300` is refused and `tnom=1e6` warns;
  - `.temp -300`, `set temp=-300` and a `dc temp` range below 0 K are refused (compare F24);
  - an opvar without a `multiplicity` attribute is correctly unscaled by `m`.
- **Run control in other analyses:**
  - `$stop` and `$finish` under `analysis("ac")` or `("noise")` abort that analysis at its bias
    point with a note;
  - `$finish` in some `montecarlo` samples is noted per sample, and the loop continues;
  - `$fatal` at the bias point aborts `pz`, `tf` and `disto` with the model's message;
  - `dc @n1[mode]` and `dc @sam[mmode]` (string parameters) are refused with exact messages.
- **`.save` wildcards:** `.save @n1[*]` and `.save @*[i_a]` warn that the vector will stay
  empty.
- **Instance lines:** unknown parameters (warning on a card, error on an instance line) and a
  model parameter on an instance line.
- **Late checks:**
  - a `pre_osdi` inside an unselected `.lib` section does not run;
  - `hb` stores no `savecurrents` vectors;
  - `m=2.5` on an OSDI instance and on a subcircuit instance, and nested `m` (3 × 2), multiply
    correctly;
  - `option noosdilim` set mid-session applies at the next op;
  - a `$discontinuity(0)` at a model's switching time changes the step count only slightly
    (211 against 209 points).
- **Under Guard Malloc** (`libgmalloc`), with a compiled diode without internal nodes (so F22
  does not mask anything), nothing faulted:
  - analyses: `tran`, `ac`, `noise`, `pz`, `sens`, `sp`, `disto`, `hb`, `pss`, `osdimc`, a
    corner, `savecurrents` in `ac`, `dc temp`, `dc @ndm[is]`;
  - frontend commands: `show all`, `showmod all`, `devhelp`, `listing expand`, string
    `alter`/`altermod`, `altermod @*:gm[g]=`, raw `write`/`load`, `osdi -f` + `reset`,
    `.option savemc`.
