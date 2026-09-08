# openvaf-r events, noise, functions and the alter commands — a one-hour hunt

**Date:** 2026-09-07, 20:17–21:10 (the document was written alongside the last batches) · **Commit under test:** `41f38492` ·
**Compiler:** locally built `OpenVAF-master-20260610/target/opt/openvaf-r`
(OpenVAF-Reloaded 23.6.0, build of 2026-09-07 15:49) · **Simulator:** locally built
`ngspice-46/build/src/ngspice` (build of 2026-09-07 18:28, after Enhancement-585) ·
**Method:** black-box. Small Verilog-A modules were written for every suspicion,
compiled, loaded with `pre_osdi`, and their operating-point variables, small-signal
responses (`ac` with a 1 V source), noise spectra (`noise` with the input source
behind a noiseless series resistor) or transient event counts were compared with
hand-computed LRM answers. One finding (F1) needed a look at ngspice's `device.c`. No
fixes were applied; every deck is inline so a run can be repeated. Foreground only.

The earlier hunts (2026-09-04 compiler, 2026-09-05 strings, 2026-09-07 language
semantics) had covered arithmetic, automatic differentiation, the analog operators in
transient, placement rules, the preprocessor, parameters and environment, branches
and contributions. This hour went to the **event system** (`cross`, `above`, `timer`,
`initial_step`, `final_step`, `or`-combined events), **user-defined analog functions**
(output and inout arguments, integer returns, local arrays, differentiation through
them), **`case` and the loop forms**, **vector ports and hierarchy**, **noise sources**
(white, flicker, table, in flow and potential contributions, operating-point-dependent
power, `m` scaling), **the analog operators in ac**, **`ddx` corners**, **`$simparam`**,
**temperature sources**, **operating-point variable types**, **run-time integer
semantics**, **node-collapse chains toggled per instance and by `alter`**, **run-time
switch branches**, the **system tasks** (`$warning`, `$error`, `$fatal`, `$finish`,
`$bound_step`, `$discontinuity`, `$strobe` frequency), model-card and netlist edge
cases, and the `alter`/`altermod` commands as the way a script reaches a model.

**Result: eight defects confirmed with plain decks — none a wrong-answer bug in an
ordinary model; the two that matter are a script command that silently drops
parameters (F1) and a parameter-name collision that silently changes what an instance
line means (F6) — plus a group of diagnostic slips and some two dozen observations.** The list
of what came out exactly right is in "Coverage, honestly", and it is most of the hour.

| # | finding | severity |
|---|---|---|
| [F1](#f1--alter-and-altermod-silently-apply-only-the-first-namevalue-pair) | `alter n1 ga=5m gb=6m` sets `ga` and leaves `gb` alone; `altermod mm ma=3 mb=4` sets `ma` only; the same for built-in devices (`alter r1 r=2k temp=50` leaves `temp` at 27, `altermod dm is=2e-14 n=1.5` leaves `n` at 1). No message. The code has an "only a single param-value pair supported" error, but only on the `=`-less legacy path | **medium** — silent |
| [F2](#f2--transition-and-slew-carry-a-1-ns-delay-in-small-signal-analysis) | `V(o) <+ transition(V(in))` — with no arguments, with all-zero times, or with a delay — shows a phase of −0.036° at 100 kHz, −0.36° at 1 MHz, −3.6° at 10 MHz in `ac`: exactly a 1 ns delay on top of `td`. `slew` the same. `absdelay(x, 0)` is 0° | low — a phantom 1 ns |
| [F3](#f3--a-cross-event-fires-at-the-initial-step-when-the-expression-starts-exactly-at-zero) | a sine of offset 0.5 tracked with `@(cross(V-0.5, +1))` over 2.5 ms counts 3 rising crossings; there are 2 (1 ms, 2 ms). An offset of 0.5001 gives 2. The event fires at t = 0 because the expression is exactly zero there and then rises | low |
| [F4](#f4--final_step-never-fires-in-an-ac-or-noise-analysis) | `@(final_step)` fires once in `op`, `dc` and `tran`, never in `ac` or `noise` (5-point sweeps and 1-point runs alike give 0); `@(initial_step("ac"))` and `("noise")` do fire | low |
| [F5](#f5--a-port-branch-probe-on-a-bus-element-is-a-parse-error) | `I(<a[1]>)` for `inout [0:2] a` is *unexpected token '[' expected '>'*; `I(a[1], c)` and `$port_connected(a[1])` work | low |
| [F6](#f6--a-module-parameter-named-temp-or-m-silently-takes-over-ngspices-instance-parameter) | a module declaring `parameter real temp` receives `temp=100` from the instance line and `$temperature` stays at the circuit temperature; one declaring `m` receives `m=4` and `$mfactor` stays 1, so the multiplier is gone. Nothing is said. Lint L018 warns about a *module* name colliding with a SPICE model type; nothing warns about a *parameter* colliding with ngspice's reserved instance parameters `m`, `temp`, `dtemp` | low-medium |
| [F8](#f8--a-string-typed-operating-point-variable-compiles-but-cannot-be-read) | `(* desc="…" *) string o_s;` compiles and loads; `print @n1[o_s]` and `$&@n1[o_s]` give *ERROR: can not handle string value of 'o_s' in vec_get* | low |
| [F7](#f7--diagnostic-slips) | a discrete-set range error reads *range from 1 from 2 from 4*; `altermod mm mode=quad` (unquoted string) says *no such vector quad*; `$fatal`'s clean abort is followed by *doAnalyses: impossible error - can't occur*; `m=0` silently removes a device where `m<0` is warned; a negative `timer` period silently acts as a one-shot; a duplicated frequency in a `noise_table` is not diagnosed | low |

## What was read and run

Every probe lives in a scratch directory (`hunt2/*.va`, `*.cir`), compiled with
`openvaf-r X.va -o X.osdi` and run with `ngspice -b X.cir`. Where the text quotes a
number it is the number the run printed. The ngspice source read for F1 is
`src/frontend/device.c` (`com_alter_common_impl`); nothing in the compiler source was
needed.

## F1 — `alter` and `altermod` silently apply only the first name=value pair

```spice
V1 p 0 dc 1
N1 p 0 mm ga=1m gb=2m
D1 p 0 dm
.model mm ip           $ (* type="instance" *) ga, gb; model ma, mb; opvars o_ga..o_mb
.model dm d is=1e-14 n=1
.control
pre_osdi ip.osdi
altermod mm ma=3 mb=4
op
echo "ma=$&@n1[o_ma] mb=$&@n1[o_mb]"        $ ma=3 mb=1
alter n1 ga=5m gb=6m
op
echo "ga=$&@n1[o_ga] gb=$&@n1[o_gb]"        $ ga=0.005 gb=0.002
altermod dm is=2e-14 n=1.5
showmod dm : is n                           $ is 2e-14, n 1
alter r1 r=2k temp=50                       $ (a resistor deck) resistance 2000, temp 27
.endc
```

The second pair never arrives, for OSDI and built-in devices alike, with no message.
`com_alter_common_impl` splits the *first* word carrying `=` into `name`, `=`, `value`
and then `break`s out of the loop; the remaining words are treated as the tail of the
value expression, and the expression evaluator uses only the first of them. The
function's own comment says multiple pairs are not supported and there is an explicit
*Only a single param - value pair supported* error — but it sits on the legacy
`alter dev param value` path (no `=` anywhere) and never fires for `a=1 b=2`. The
built-in help says one pair, so the design is one pair per command; dropping the rest
silently is the defect. The `@dev[param] = value` form, and one pair per line, work.

## F2 — `transition` and `slew` carry a 1 ns delay in small-signal analysis

```verilog
V(o1, gnd) <+ transition(V(in, gnd));
V(o2, gnd) <+ transition(V(in, gnd), 0.0, 0.0, 0.0);
V(o3, gnd) <+ transition(V(in, gnd), 5e-6, 1e-6);
V(o4, gnd) <+ absdelay(V(in, gnd), 0.0);
V(o5, gnd) <+ slew(V(in, gnd), 1e6, -1e6);
```

```
ac lin 1 100k 100k:  ph(o1) = -0.036°   ph(o2) = -0.036°   ph(o3) = 179.964°   ph(o4) = 0°   ph(o5) = -0.036°
ac dec 1 1e5 1e8 on o2: -0.036°, -0.36°, -3.6°      (magnitude 0.9999998)
```

The phase is 360·f·1 ns at every frequency: the small-signal model of `transition`
and `slew` is a pure delay of `td` **plus one nanosecond**, regardless of the rise
and fall times. The LRM's small-signal view of both is a pass-through (unity, no
phase); a 1 ns floor is presumably the implementation's minimum delay, and it shows
even when every argument is zero or omitted. Harmless below a few MHz, visible above.

## F3 — a `cross` event fires at the initial step when the expression starts exactly at zero

```spice
V1 p 0 sin(0.5 1 1k)         $ V = 0.5 exactly at t = 0, then rising
V2 q 0 sin(0.5001 1 1k)      $ starts just above 0.5
V3 r 0 sin(0.4999 1 1k)      $ starts just below
* module: @(cross(V(p,n) - 0.5, +1)) nup = nup + 1;   with nup zeroed in initial_step
tran 1u 2.5m
```

| start | rising crossings counted | true crossings in (0, 2.5 ms] |
|---|---|---|
| exactly 0.5 | **3** | 2 (1 ms, 2 ms) |
| 0.5001 | 2 | 2 |
| 0.4999 | 3 | 3 (≈0, 1 ms, 2 ms) |

A crossing needs a previous point on the other side; at the first point there is
none. The event is generated because the expression is zero at t = 0 and positive at
the next point. `above` counts the same way. A model that counts pulses, or arms
something on the first crossing, is off by one whenever the source happens to start on
the threshold — which a `sin` with an offset equal to the threshold does.

## F4 — `final_step` never fires in an ac or noise analysis

```
op                    : initial_step 1  final_step 1
dc v1 0 1 0.25        : initial_step 1  final_step 1     (a 1-point dc sweep: 1, 1)
tran 10u 1m           : initial_step 1  final_step 1
ac dec 2 1 100        : initial_step 1  final_step 0     (initial_step("ac") = 1)
ac lin 1 1k 1k        : initial_step 1  final_step 0
noise v(p) v1 dec 2 …  : initial_step 1  final_step 0     (initial_step("noise") = 1)
```

The op point that precedes an ac or noise sweep is the analysis' first and last
analog evaluation; `initial_step` — including the qualified forms — is generated
there, `final_step` is not. A model that writes a summary or releases something in
`final_step` never does so under `ac` or `noise`. The qualified `initial_step("dc")`,
`("static")`, `("noise")`, `("ac")`, `("tran")` and `final_step("tran")`, `("dc")`
otherwise fire exactly where they should.

## F5 — a port-branch probe on a bus element is a parse error

```verilog
inout [0:1] a; electrical [0:1] a;
o = I(<a[1]>);        // error: unexpected token '['; expected '>'
```

`I(a[1], c)`, a genvar loop over `I(a[i], c) <+ ...`, and `$port_connected(a[1])` all
work, so bus ports are otherwise complete; only the `<port>` probe form does not accept
a bit-select. LRM 5.4.3 allows a port branch on any port, bus elements included.

## F6 — a module parameter named `temp` or `m` silently takes over ngspice's instance parameter

```verilog
(* type="instance" *) parameter real m = 2.0 from (0:inf);
(* type="instance" *) parameter real temp = 100.0;
parameter real dtemp = 5.0;
```

```spice
N1 p 0 mm
N2 p 0 mm m=4
op
n1: m=2  temp=100  $temperature=300.15  $mfactor=1
n2: m=4  temp=100  $mfactor=1           i(v1) = -6e-3   (= 2 mA + 4 mA: the module's m, no multiplier)
show n1:  dt 5   dtemp 5   _mfactor 1   m 2   temp 100
```

Both words are ngspice's reserved instance parameters for every device: `m` is the
multiplier, `temp` the instance temperature, `dtemp` the offset. When the module
declares them, the netlist value goes to the module's parameter and ngspice's own
meaning is lost without a word: `m=4` no longer multiplies (`$mfactor` is 1 — the
module is left to apply `m` itself, which a model that declares `m` usually does, but
nothing checks that), and `temp=100` no longer sets the device temperature
(`$temperature` stays 300.15 K). `show` even lists the module's `dtemp` under the
built-in `dtemp`/`dt` rows. The compiler warns (L018) when a *module* name collides
with a SPICE model-type keyword; a lint for parameters named `m`, `temp`, `dtemp`,
`dt` would close the same gap at the parameter level.

## F7 — diagnostic slips

- **Discrete-set range error.** `parameter integer n1 = 1 from {1, 2, 4}` given
  `n1=3` on the card: *Parameter n1 of 'mm' is out of bounds; range from 1 from 2 from
  4!* — and for a real set *range from 0.5 from 1.0 from 2.0*. The set is the right
  thing to name, the wording is not.
- **Unquoted string in `altermod`.** `altermod mm mode=quad` for a string parameter:
  *Error: no such vector quad*, and the parameter keeps its value. The quoted form
  `mode="quad"` works; the message should say the parameter is string-typed and needs
  quotes (the `alter` path already has that wording for the opposite mismatch).
- **`$fatal` aftermath.** The abort is clean — *OSDI(fatal) n1: … / Error: a Verilog-A
  device raised $fatal during the operating point; aborting. This is not a convergence
  failure* — and then *doAnalyses: impossible error - can't occur* follows it.
- **`m=0`.** An instance with `m=0` contributes nothing and the run says nothing;
  `m=-2` is warned twice (sign inversion, NaN noise). Zero is at least as likely a typo.
- **`timer(0.1m, -1m)`.** A negative period is accepted and the timer fires once.
- **`$fopen` of an unwritable path returns 0 silently**, and a `$fwrite` to that 0
  (or to a never-opened descriptor) is silently dropped. Returning 0 is the LRM; a
  warning naming the path would be cheap.
- **`$discontinuity(-1)`.** A negative order compiles without a word (the LRM's
  argument is a non-negative integer); `$discontinuity(3)` is fine.
- **`case (s) endcase`** with no items compiles (Verilog requires at least one item);
  a `default` placed first works, and a real label on an integer selector is refused.
- **`noise_table('{1.0, 4e-18, 1.0, 1e-18}, …)`.** Two entries at the same frequency
  compile; the spectrum is flat at the first entry's power. An unsorted table, on the
  other hand, is handled as if sorted (the interpolation matched the sorted answer).

## F8 — a string-typed operating-point variable compiles but cannot be read

```verilog
(* desc="a string output" *) string o_s;
analog begin o_s = "abc"; I(p,n) <+ V(p,n)/1e3; end
```

`openvaf-r` accepts it without a word and ngspice loads the module; `print @n1[o_s]`
answers *ERROR: can not handle string value of 'o_s' in vec_get … Ignoring…* and the
`$&` substitution of the same name is *no such variable*. Either the compiler should refuse a string
operating-point variable (the LRM's output variables are real or integer) or ngspice
should hand the string to `print`/`echo` as it does for string parameters.

## Status after the fixes (2026-09-08)

| # | resolution |
|---|---|
| F1 | fixed by [E-586](../../enhancements_doc/Enhancement-586.md): every pair applies, for OSDI and built-in devices; `altermulti_examples` |
| F2 | fixed by [E-587](../../enhancements_doc/Enhancement-587.md): the tracking loop's reactive residual is zeroed for the ac and noise evaluations, so `transition`/`slew` are exactly unity in small-signal; a `td` delay is still honoured |
| F3 | fixed by E-587: strict on the previous side, inclusive on the current; `above` gated at t = 0 of a transient except for its initialization event |
| F4 | **withdrawn.** `@(final_step)` does fire in `ac` and `noise` — a `$strobe` in the block prints — but E-412 snapshots the instance around that evaluation and puts it back, since `CKTrhsOld` there is a small-signal solution, so every write the block makes to a variable or an operating-point variable is rolled back by design. The probe read a counter, which is exactly what the snapshot discards |
| F5 | fixed by [E-588](../../enhancements_doc/Enhancement-588.md): `I(<a[1]>)` in expressions and branch declarations |
| F6 | fixed by E-588: lint L029 `reserved_parameter_name` |
| F7 | the discrete-set wording, the bare-word string `altermod`, the `$fatal` aftermath, the duplicated `noise_table` frequency and the empty `case` are fixed (E-586, E-588). `m=0` silently removing a device is E-426's documented "disable this instance" idiom, the same as for the built-ins; a `timer` period ≤ 0 firing once is LRM 5.10.3.3's rule (the check that refused it was removed for that reason); `$discontinuity(-1)` is the LRM's limiting-discontinuity form inside `$limit`. Those three are withdrawn |
| F8 | **withdrawn.** A string operating-point variable is the documented `opvar` design: `show <inst>` displays its text and only the vector path (`print`, `$&`) refuses it, with the very message the hunt quoted, which `opvar_examples` pins as the intended clear error |

## Smaller notes (not pursued)

- **Run-time integer division by zero is 0.** `k = 0` computed at run time, `7 / k`
  gives 0 silently while `7.0 / k` gives inf. This is 09-04's F10 (a zero-valued
  *parameter*) on the run-time path; `%` by zero is the fatal it documents.
- **Overflowing constant expressions fold to inf silently.** `parameter real big =
  1e300 * 1e300` and `1.0 / 0.0` are inf, `1e-400` is 0, with no word; the literal
  `1e400` is a compile error with a message that says expressions are the model's
  business. Consistent with that message, inconsistent with `ln(0.0)` being an error.
- **Same-named noise sources are independent.** Two `white_noise(pwr, "wn")` calls in
  one expression give √2·(one source), not 2·. This is the documented H5 design
  (`huntfix2_examples/hxcorr.va`: correlation follows the call, not the label), noted so
  the next hunt does not re-find it.
- **A single-point `noise` run makes one plot.** `noise … lin 1 1k 1k` creates
  `noise1` only; a multi-point run creates the spectrum plot and the integrated plot.
  Scripts that index `noise<2k-1>` for the k-th run get the numbering wrong.
- **A flow contribution into an `input` port compiles without a diagnostic.**
  `input a; … I(a) <+ V(y)/1e4;` — whether the LRM forbids it outright is a reading
  question; a warning would cost nothing.
- **`.save @n1[opvar]` vectors are typed `voltage`.** They record per point correctly
  in `tran` (59 points, right values); an integer opvar and a resistance opvar both
  show as `voltage`.
- **`1/V(p,n)` and `ln(V(p,n))` at the zero initial guess fail every op method** (gmin,
  source stepping, transient op) with nothing said about the inf the model produced;
  the same for `V/r` after `altermod mm r=0` on a parameter declared without a range
  (*DC solution failed*, nothing about the zero). The model is ill-posed; a note naming
  the device and the inf would save a search.
- **`transition` in ac** also reports the magnitude as 0.9999998 rather than 1.
- **A noise power that is negative at the operating point is silently 0.**
  `white_noise(1e-12 * V(in, gnd), "vdep")` with `V(in) = −2` gives an output and
  input noise spectrum of exactly 0 and no message; the compile-time check covers
  constants only (and says so). Zero is the safe value; a warning naming the source
  would save the user a puzzled hour.
- **`$strobe` prints once per accepted point**, not per iteration (78 lines for an op
  plus 77 transient points), and a `$strobe` inside `@(final_step)` prints once.
- **`repeat (2.7)`** runs three times (rounded); duplicate `case` labels are accepted
  and the first arm wins, as in Verilog.
- **State across repeated analyses:** plain module variables restart with every
  analysis (three identical `op`s report identical evaluation counts, two identical
  `tran`s likewise; an `alter` between them changes nothing), event counters and
  `$abstime` restart too, and an ordinary one-resistor model is evaluated 5 times for
  an `op` of 3 Newton iterations. A model carrying an un-initialised `idt(1.0)` is
  evaluated 279 times for the same `op` — the ill-posed integrator drives the op
  through the gmin and source-stepping fallbacks, which is where the count goes.
- **Operating-point variable names differing only in case** (`o_dt`, `o_dT`) are
  warned by ngspice, and the netlist can reach only one of them — a real help, since a
  first probe of `ddx(…, $temperature)` "found" a zero derivative that was in fact the
  other variable.
- **No lint for the four classic "unused" conditions:** an internal node declared and
  never referenced, a parameter never used, a variable read before any assignment
  (it reads 0, as the earlier hunt recorded), and a variable written and never read all
  compile without a word. The lint set is rich elsewhere (L018, L021, L025, L026); these
  would fit it.
- **`idt(1.0)` with no initial condition is 1e12 at DC, silently.** The LRM makes the
  DC value of an un-initialised integrator the one for which the input is zero; a
  constant nonzero input has no such value, and the result is 1/gmin (1e12), carried
  into the transient. The earlier hunt's `idt(1.0, 0.5)` (with an ic) and the
  singular-matrix warning of an integrator in a potential contribution are the two
  visible faces of the same rule; an operating-point variable fed by such an `idt`
  shows 1e12 with no message.
- **`$&` of a complex vector** substitutes the real part.
- **An internal node with only reactive paths is singular at the op, and `.option
  dcpath` leaves it so by design.** Two `ddt` capacitors in series through an internal
  node (flat, or as two instantiated children) give *singular matrix: check node
  n2#m* six times, the op falls through gmin and source stepping to the transient op,
  and the ac result is right (−18.85 µA for 3 nF at 1 kHz). E-575's walk takes a
  device-internal node as reached (its documented rule), so `dcpath` installs nothing
  there. Only the `m=2` instance's node is ever named, never the identical `n1#m`.
- **`inf` on a netlist line is a numparam error** (`N1 p 0 mm res=inf`: *Error in
  netlist line no. 5*), so an "infinite" value has to be spelled `1e40`; the compiler,
  for its part, allows `inf` only in ranges. Consistent with each other, easy to trip
  over.
- **An array parameter cannot be given from the netlist.** `tab=[5,4,3,2,1]` and
  `tab=5,4,3,2,1` on the `.model` card draw *unrecognized parameter (tab) - ignored*
  — the parameter exists, it is an array — and the `'{…}`/`{…}` forms are netlist
  errors. Array parameters are compile-time only; the warning could say so.
- **An escaped quote inside a string value is not supported:** `label="say \"hi\""`
  arrives as `say \`; `\t` stays a literal backslash-t; a space inside quotes is kept.
- **A parameter given twice on one line takes the last value silently**, on the
  instance line (`res=1k res=2k` → 2000) and on the card alike — SPICE's rule.
- **`res=1M` on a netlist line is 1e−3** (SPICE: M = milli), `1meg`/`1MEG` is 1e6,
  while the same `1M` inside Verilog-A is 1e6. Both are by their own rules; a model
  author moving a value from the `.va` to the card meets it.
- **An `alter` to an out-of-range value is accepted silently**; the next analysis
  aborts with the range message, and a later in-range `alter` recovers cleanly (`g=0`
  then `g=5e-3`; `mode="cubic"` then `mode="lin"`). Refusing at `alter` time would
  save the wasted analysis, since the range is known.
- **Crossing detection is evaluation-granular**, as the `ttol` warning says: with the
  maximum step forced to 1 ms on a 1 kHz sine (`tran 250u 2.5m 0 1m`) a 2-crossing
  signal counts 3 and the crossing time is reported at 2.125 ms; with any step the
  source's own breakpoints allow (1 µs to 250 µs) the counts and the time (2.000 ms)
  are exact.

## Coverage, honestly

Verified correct this hour (each with a deck, values matched by hand):

- **Events:** 200 `cross` events in one module (compiles in 0.8 s, all 200 counted
  in a 0.24 s transient), a timer-driven clock through `transition` (5 toggles,
  `$abstime` inside the timer block exactly 1.0 ms), `cross` with `+1`, `−1` and `0`
  directions (counts 3/2/5 on the sine),
  `above` in transient and in a dc sweep (LRM: `cross` is transient-only, `above` is
  not — 1 event where the sweep passes 0.5), `cross` on a flow probe `I(p,n)` (3, as
  for the voltage), a child's event counter saved per point with
  `.save @n1[a__o_nc]`, one-shot and periodic `timer` (5 firings at 0.25 + 0.5k ms), `initial_step`
  and its `"ac"`/`"tran"` qualifiers per analysis, `final_step` in op/dc/tran, a
  `cross or timer` combined event (8 = 3 + 5), the 4-argument `cross` (its `ttol` is
  warned as accepted-but-not-honoured, honestly), variables assigned in
  `initial_step` persisting through the analysis (`c` feeding `ddt(c*V)`), `$abstime`
  inside events, `$bound_step(1u)` and `(100n)` bounding a 1 ms transient to 1005 and
  10002 points, `$discontinuity(0)` harmless, `cross($abstime - 1m)` as a timer
  (fires once), and the digital-style idiom `@(cross(...)) lvl = 1.0; V(o) <+
  transition(lvl, 0, 1u, 1u)` (the ramp starts at the crossing and is half-way at
  0.5 µs), a model whose number of `ddt` states changes with a `case` on a parameter
  altered between `ac` and `tran` runs (1 nF, then 4 nF at V = 1, then none, each right).
- **Analog functions:** `output` and `inout` arguments, nested calls passing an
  output argument through two levels, an integer-returning function, a local array
  with a loop (Horner's rule), differentiation through a function and through its
  output argument (`dI/dV = 3kv² + 2v` matched by `ac`); `limexp` inside a function
  rejected as an analog operator (LRM-correct), a genvar loop bound that is a
  parameter rejected as non-constant (LRM-correct), named branches on bus elements.
- **Blocks and nets:** an `analog initial` block (Verilog-AMS 2.4) that sets a
  variable read by the main block (its value reaches `op` and `tran`, and it runs
  before `@(initial_step)`, which can override it, and `$mfactor`, `$temperature`
  and `$param_given` inside it read the instance's values), a `ground gnd;`
  declaration tied to the global ground (a one-port module conducts 1 mA to it, two
  instantiated leaves in each of two tops 4 mA, and the leaf's `analog initial`
  `$strobe` prints once per leaf per analysis); a
  contribution to the ground net, and nature access, a contribution or an event
  control inside `analog initial`, each refused with a one-line reason.
- **Control flow:** `case` on integers with multiple labels, on reals, on strings, on
  an expression label, nested `case`; `while` with a real condition, `repeat` with a
  parameter count, `for` with step 3; a flow contribution inside a signal-dependent
  `while` (10 and 6 contributions, with the right small-signal conductance); two
  `analog` blocks in one module both executed; an empty analog block; two potential
  contributions to one branch accumulating (3 V); a run-time switch branch (`V<+` when
  clamped, `I<+` otherwise: 0.15 V then 0.7 V).
- **Ports and hierarchy:** `inout [0:2]` buses with a genvar loop, `$port_connected`
  on a bus element, three levels of hierarchy with a forward reference to a module
  defined later, a string parameter passed down two levels, `$mfactor` read in the
  leaf (3 for `m=3` on the top instance), a module instantiating another with `#(.r(rt))` and positional
  `#(rs)` overrides, named port connections `.p(mid[1])`, an internal node array
  `electrical [0:2] mid` wiring a four-segment ladder (1 mA, 2 V at the middle),
  collapsing two *ports* (`V(a,b) <+ 0` between externals, then un-collapsed by
  `altermod`), `m` on the hierarchical instance (current doubled), an instance array
  `seg s[0:2] (p, n)` (three in parallel), `cross`/`timer`/`initial_step` events inside
  an instantiated child (they fire, and the child's `$strobe` prints under the parent's
  instance name), a child's operating-point variables exposed as `a__o_nc`, a parent
  reading a child's variables hierarchically (`a.nc`, `a.x`) whether or not the child
  reads them itself — one probe that read 0 turned out to be a deck whose divided
  voltage never reached the threshold, not a compiler fault —, the L018 warning for a module named
  `res` or `sw`, a contribution to a port branch rejected, two `.osdi` files defining
  one module name (the second is ignored, with a warning).
- **Noise:** `white_noise` (5e-7 V/√Hz through 500 Ω) in a flat module and inside two
  instantiated children (√2·, 4.714e-7 through 333 Ω), `flicker_noise` with exponent
  1.0 and 0.5 across four decades, `noise_table` with linear-in-power interpolation
  (9.65e-7 at 1 kHz), noise in a potential contribution, operating-point-dependent
  noise power (`pwr·V²`), `m=4` scaling (√4 in current, 200 Ω load: 4e-7) both from
  the instance line and as `_mfactor=4` on the model card, a branch carrying only a
  noise contribution (1e-6 through 1 kΩ), a `noise_table` evaluated below and above
  its span (held at the end values), thermal noise written as `4·P_K·$temperature/r`
  following `.option temp=100` (2.2698e-9 V/√Hz through 500 Ω at 373.15 K), the same
  source with a 1 nF `ddt` in parallel at 1 MHz (6.8846e-10, the reactive admittance
  in the noise transfer), shot noise `2·P_Q·|I(p,n)|` of the branch's own current
  (8.95e-9 at 1 mA), `noisy=0`
  on the series resistor, negative power and odd-length tables rejected, the `{…}` vs
  `'{…}` table form diagnosed.
- **Operator argument validation:** zero `slew` rates, a negative `transition` rise
  time, a `laplace_nd` with an identically zero denominator, an `absdelay` delay above
  its declared maximum (warned, substituted), all diagnosed by name; `transition` of a
  level set in `initial_step` starts the transient at the level with no ramp (LRM).
- **Small-signal:** `idt(x, 0.0)` (an integrator with a DC anchor) as exactly 1/s
  (1.5915e-6 at −90° at 100 kHz), `absdelay` (−36° at 100 kHz for 1 µs, 0° for 0), a `td=5u`
  transition (180°), an integrator `idt` in a potential contribution reported singular
  at the op (as it must be), collapse toggled by `altermod` between `op`, `ac` and
  `tran`, chains of three collapsible internal nodes chosen per instance (all four
  combinations right to 1e-6, total current −3.94136 mA) and re-chosen by `alter`.
- **Dynamics:** a conditional charge inside `ddt` (`ddt((V > 0.5) ? 2n·V : 1n·V)`)
  linearised as 2 nF above and 1 nF below the threshold, and a noise term in a
  potential branch leaving the ac gain at exactly 1.
- **`ddx`:** with respect to an internal node, of a product, inside a function, of a
  `ddt` (0 at dc), and with respect to `$temperature` (`ddx($vt, $temperature) = k/q`,
  `ddx(T·V, T) = V`, `ddx(T·V, V) = T`); `ddx(…, I(<p>))` rejected with a list of what
  is accepted.
- **Environment:** `$simparam` for gmin, tnom, temp, iteration, sourceScaleFactor,
  scale, simulatorVersion, gdev, abstol, reltol, vntol following `.option`, and the
  default returned for imax, imelt, shrink, timeUnit, maxStep, checkjac; an unknown name
  without a default is a lint at compile time and a `$fatal` at run time;
  `analysis("bogus")` is a lint (L021) and 0; `$temperature` from `.option temp`,
  `.temp`, `set temp`, instance `temp=`, `dtemp=` (and `temp` winning over `dtemp`,
  ngspice's rule), a `dc temp -20 80 50` sweep with `$temperature`, `$vt` and
  `$simparam("temp")` recorded per point; `$vt` at 50 °C; an `analysis("ac")`-gated
  conductance seen as 1 mS by `op` and 2 mS by `ac`, and an `analysis("noise")`-gated
  one seen as 2 mS by `ac` and 1 mS by `noise` (the noise transfer used the noise-time
  value: 5e-7, not 3.33e-7).
- **Values and types:** integer, real, array-element, ±0, inf, nan and boolean
  operating-point variables through `show` and `print`; run-time real-to-integer
  rounding (2.5→3, −2.5→−3, 0.5→1), `/` and `%` signs, `1 << 31`, multiplication
  wrap and `**` saturation (consistent with the compile-time rules of 09-04), `$rtoi`,
  saturation of 1e10, `abs(INT_MIN)`; precedence — `-2**2 = 4`, `2**3**2 = 64`,
  `1 < 2 < 3`, right-associative `?:`, `1 << 2 + 1 = 8`, `!0 + 1`, `~0 & 1`; arrays
  with negative and non-zero lower bounds including a run-time index; `aliasparam`
  through the netlist, `alter`, `alter @n1[alias]` and the model card, `$param_given`
  through the alias and after `alter` (0 before, 1 after), `alter n1 m=3` and a
  `dc @n1[m] 1 3 1` sweep of the multiplier (−0.5, −0.667, −0.75 mA),
  `altermod mm _mfactor=2` refused with a message naming the per-instance `alter`
  form, an `absdelay` delay parameter altered between two transients (2 µs then 4 µs
  edges), a `dc @n1[res]` sweep of
  an instance parameter through its alias and through its own name with an
  operating-point variable recorded per point, `$strobe` once per dc point, a string
  instance parameter with a `from {…}` set altered within and outside the set; discrete `from {…}` sets accepting members and refusing others;
  instance over model over default precedence; upper-case parameter names everywhere;
  array-initialiser length mismatches diagnosed both ways; a 300-character string
  parameter from the card and from `altermod` intact (an earlier "mismatch" was a
  miscounted literal in the probe, not a truncation), a `%` inside a string argument
  printed verbatim, `r={2*rr}` and `r='3*rr'` numparam expressions on the instance
  line, a UTF-8 string parameter (`Ω·√2`) through the card and `$strobe`, a
  120-character parameter name on the instance line, a parameter named `_under`.
- **System tasks and the netlist:** `$warning`, `$error` (run continues), `$fatal`
  (clean abort, see F7), `$finish` (op completes and is reported); a `$strobe` with
  ten arguments, with `%%`, a tab and an escaped quote; `$fopen`/`$fwrite`/`$fstrobe`/
  `$fclose` writing a file from `initial_step`; an instance with
  both terminals on one node, one terminal missing (warned, not grounded), one too many
  (error), an unknown model parameter (warned, ignored), an instance parameter that is
  model-only (error), an integer parameter given 1.5 (warned, rounded), −1 (out of
  bounds), 1e10 (refused with the saturation explained), `rr=abc` (numparam),
  `.model` `m=` (warned as instance-only), `m=0.5`; a port named like a parameter,
  `exp`/`abs`/`time` as identifiers, a string label on an integer `case`, a string
  compared with a number and a string in a real ternary all refused with typed
  messages.
