# 4 · Limitations and gotchas

An honest map of the edges: what is out of scope by design, what carries
fallback semantics, the deliberate design decisions, and the traps that
cost real debugging time in this project. Everything here is *documented
behavior* — most entries are pinned by a verify script so they can't
regress silently into something different.

## 4.1 Scope: Verilog-A, not full AMS

The project targets **Verilog-A** — the analog-only subset defined in Annex
C of the Verilog-AMS LRM. Features that exist only in full Verilog-AMS are
out of scope, most notably:

- **digital/mixed-signal constructs** — `reg`/`wire` logic, `always`/
  `initial` (digital) blocks, delays/event control on digital signals,
  connect modules and auto-insertion;
- **`` `default_discipline ``** — the directive is AMS-only. (Implicit nets
  *are* Verilog-A, and work: an undeclared net takes its discipline from
  the connected port — [E-41](../../enhancements_doc/Enhancement-41.md).)
- **discrete-domain disciplines** — `domain discrete` combined with natures
  is rejected with a proper error per LRM 3.6.2.2.
- **vector branches** (LRM 3.12: `branch (a,b) br;` over whole vector
  nets) — rejected with a located diagnostic; declare per-bit branches
  (`branch (a[i],b[i]) bri;`) instead. Likewise **out-of-module
  discipline declarations** (`electrical top.other.net;`, LRM 3.10),
  which have no meaning in a single-module OSDI compile.

When in doubt whether a construct is Verilog-A or AMS-only, Annex C of the
LRM (in [`docs/`](..)) is the authority the compiler follows.

## 4.2 Features with fallback semantics

These compile and behave predictably, but the OSDI/ngspice target has no
underlying mechanism for them, so they return their LRM-specified
"mechanism unavailable" values ([E-12](../../enhancements_doc/Enhancement-12.md)):

| Function | Behavior |
|---|---|
| `$simprobe` | the supplied default |
| `$analog_node_alias` / `$analog_port_alias` | `0` (no runtime hierarchical aliasing) |

## 4.3 Compile time vs. simulation time

The single most useful mental model for this toolchain:

- **Structure binds at compile time.** Hierarchy, `generate` blocks,
  genvars, `defparam`, paramsets, bus widths — all resolved by the
  elaboration pass. Consequently a `generate` condition or bound on a
  module **parameter** is an intentional, explained error: parameters
  arrive from model cards at simulation time, after structure is frozen
  ([E-67](../../enhancements_doc/Enhancement-67.md)).
- **Behavior binds at simulation time.** Loop trip counts, `if` arms, and
  expressions may depend on parameters (and the solution) freely — a
  model-card override genuinely changes how many times a `for` loop runs
  ([E-70](../../enhancements_doc/Enhancement-70.md)).
- **Untyped parameters take their default's type at compile time.**
  `parameter untyped = 1;` compiles as an *integer* parameter, so a
  netlist override of `2.5` is rounded to that frozen type. LRM 3.4.1
  says the type follows the *final overridden value*, but a compiled
  OSDI descriptor declares exactly one type per parameter, so
  override-dependent typing cannot exist here. Write `parameter real`
  when real overrides are expected; ngspice warns when an override is
  rounded this way.
- **A constant argument the LRM forbids is refused at compile time**, and
  only a constant one: `sqrt(-4.0)`, a `slew` rate of the wrong sign, a
  `noise_table` with an odd number of entries are errors naming the builtin,
  the value and the domain — `sqrt: the argument is -4, which is outside
  the domain of sqrt (values >= 0)`, caret label `invalid argument for
  sqrt` — while the same value from a model card is a run-time matter
  ([E-396](../../enhancements_doc/Enhancement-396.md),
  [E-509](../../enhancements_doc/Enhancement-509.md); the label read
  "invalid the argument for sqrt" until
  [E-721](../../enhancements_doc/Enhancement-721.md)). A constant the LRM
  gives a defined meaning draws a warning instead, whose label does not call
  it invalid: `the delay given to absdelay`.

## 4.4 Documented design decisions

- **`limexp()` is stateless** ([E-13](../../enhancements_doc/Enhancement-13.md)):
  `exp(x)` below the overflow cutoff at `ln(1e30)` ≈ 69.08, tangent-continued
  above it (`1e30·(1 + x − ln 1e30)`). Below the cutoff it is exactly `exp` in
  every analysis; **above it the converged value is the linearisation, not
  `exp`** — a junction forced deep past the cutoff (e.g. an ideal diode at a
  hard 5 V, x ≈ 193) converges quietly to the tangent value, tens of decades
  below the true exponential. No silicon operates there, and the LRM's
  "apparent behavior identical to exp" is traded for convergence exactly as
  every production simulator trades it — but the trade is real, so it is
  written down here. A stateful, previous-iterate limiting version was built
  and reverted: correct converged values under limiting require SPICE's
  limiting-RHS correction, which applies to circuit unknowns, not to
  `limexp`'s derived argument. Use `$limit` for genuine iteration limiting.
- **Random draws don't advance a seed** ([E-10](../../enhancements_doc/Enhancement-10.md)):
  each `$random`/`$dist_*` call site is a deterministic function of (seed,
  call site). An advancing seed would return different values on every
  Newton iteration and destroy convergence. Sequences within one evaluation
  are therefore not available; per-instance/per-call-site independence is.
  An unseeded `$random`/`$arandom` is seeded per analysis and per instance
  since [E-832](../../enhancements_doc/Enhancement-832.md), from `setseed`, and
  holds still within an analysis for the same reason.
- **`.disto` works for OSDI devices, via numerical differencing**
  ([E-359](../../enhancements_doc/Enhancement-359.md)): the Volterra kernel needs 2nd- and
  3rd-order derivative tensors. Rather than have the compiler emit them — an
  approach that was built, measured and *abandoned* because it cost 20–49x
  compile time, 30 MB objects and a 3.3–3.9x runtime penalty on every OTHER
  analysis — ngspice differences the analytic Jacobian numerically at the
  operating point. Compile time, object size, runtime and the OSDI ABI are all
  back at baseline. The tensors used *by `.disto` only* are therefore accurate
  to ~5e-9 rather than exact; **every other analysis still uses the compiler's
  exact derivatives**, unchanged. Supersedes the older behaviour where OSDI
  devices were skipped with a warning ([E-62](../../enhancements_doc/Enhancement-62.md)).
  Since [E-739](../../enhancements_doc/Enhancement-739.md) the differencing
  also covers the reactive Jacobian, so the nonlinearity of a device's charges
  — a diode's diffusion charge, a varactor — enters the kernels; before it
  only the resistive part did, and a pure charge nonlinearity reported no
  distortion at all.
- **The built-in dialect on a compiled device is named, not just refused**
  ([E-740](../../enhancements_doc/Enhancement-740.md)): `ic=` and a bare
  `off` on the instance line, `level=` on the model card, a model owning `m`
  given `m=` (the multiplier is `_mfactor=`), a compiled model under another
  device letter, and `.option bypass` each get a message that says what the
  keyword is and the route that exists; none of them does anything on a
  compiled device.
- **`@(final_step)` fires only on success**: a failed or interrupted
  analysis never fires it — "final" means the converged end of the run
  ([E-53](../../enhancements_doc/Enhancement-53.md)).

- **Transient noise activates automatically** ([E-364](../../enhancements_doc/Enhancement-364.md)):
  Verilog-A `white_noise`/`flicker_noise` are injected into `.tran` when — and
  only when — the circuit already contains a `trnoise` source, whose noise
  timestep is adopted so every generator shares one grid. A deck without one is
  unaffected. `noise_table` sources are **not** injected (a tabulated spectrum
  needs frequency shaping, not a scalar amplitude); they warn once and remain
  fully accounted for in `.noise`.

## 4.5 ngspice control-language traps

Pinned during this project's own verification work — they will bite anyone
scripting ngspice:

- **The first line of a deck is the title**, not a statement. A netlist
  line placed first is silently swallowed.
- **A deck is folded to lower case as it is read**, and the fold reaches the
  text a control script hands to a command — a `set` value, a plot title —
  except for a few exempt commands (`echo`, `shell`, `load`, …); the same pass
  drops the spaces around an `=` inside a quoted string. Since E-553 a
  **raw string**, `r"…"` or `r'…'`, is copied through as written, and an
  **f-string**, `f"… {expr:.3f} …"`, is evaluated at the command
  ([§3.10](03-ngspice-workflows.md#310-raw-strings-and-f-strings-in-control-scripts)).
  `pyplot` now keeps the case of its `title`/`xlabel`/`ylabel` tokens the way
  `plot` and `gnuplot` always did.
- **`wrdata` mispairs control-created vectors** (it attaches the current
  plot's scale, which for a control-made vector is length 1). Export such
  vectors by parsing `print` output, or `wrdata` only plot-native vectors
  ([E-66](../../enhancements_doc/Enhancement-66.md)).
- **`print` of an imported/foreign plot omits the scale column** — print
  `frequency[0]`-style expressions separately
  ([E-72](../../enhancements_doc/Enhancement-72.md)).
- **`sunif(0)` is uniform on [−1, 1]**, not [0, 1]; and every textual
  occurrence of a random-valued `{param}` draws independently — matched
  devices need the `alter` idiom ([E-66](../../enhancements_doc/Enhancement-66.md)).
- **Control scripts continue past aborted analyses** — detect completion
  from data, not from `echo` markers after the analysis command
  ([E-56](../../enhancements_doc/Enhancement-56.md)).
- **`sp lin 2 f1 f2` yields one point** (a stock ngspice quirk; `lin 3`
  and up behave; [E-63](../../enhancements_doc/Enhancement-63.md)).
- **A recompiled `.osdi` does not reload in-session** — `pre_osdi` on an
  already-loaded path notes it and keeps the existing registration;
  restart ngspice to pick up a recompiled file
  ([E-81](../../enhancements_doc/Enhancement-81.md)).
- **Module names that collide with ngspice built-in device types**
  (`cccs`, `vccs`, `vcvs`, …) are skipped with a warning — the built-in
  keeps the name, so pick another module name to actually use the model
  (this used to be a hard crash;
  [E-76](../../enhancements_doc/Enhancement-76.md)).

## 4.6 Assorted edges

- **A non-terminating analog loop is a compile-time error**
  ([E-375](../../enhancements_doc/Enhancement-375.md)): `while (1)`, or the far more ordinary
  case of forgetting the loop increment, is rejected with `loop condition is
  always true` or `loop condition can never change`. There is no correct object
  code for such a model — it can never finish one evaluation — so a diagnostic
  was the only right answer. It is worth knowing what it replaced: this used to
  crash `openvaf-r`, and after the E-363 CFG repair it stopped crashing and
  started *emitting* — the `.osdi` loaded cleanly and then hung the simulator on
  the first device evaluation with no diagnostic at all, which is worse than the
  crash. [E-389](../../enhancements_doc/Enhancement-389.md) closed the gap that
  mattered most in practice: a control variable that is *written but never
  changes* (`for (k = 0; k < 10; k = k + 0)`, or a plain `k = k`) used to
  satisfy the check and hang the simulator, and is now rejected too. The check
  remains conservative — it can still miss a loop whose variables genuinely
  change but never toward the exit, notably nested loops sharing an index — so
  it is still worth confirming that your loop variables actually advance. A loop
  that terminates only by integer wrap (`k = k - 1`) is *not* rejected: it does
  finish, after about 2³¹ iterations.

- **`break`/`continue`/`return` are the VAMS-2023 jump statements** and
  work as of [E-520](../../enhancements_doc/Enhancement-520.md); `disable
  <block>;` remains the named-block early exit
  ([E-9](../../enhancements_doc/Enhancement-9.md)). One restriction carried
  over: neither `disable` nor `break` is accepted as the **only** way out of
  a loop whose condition never changes — `while (1) … disable blk;` is
  rejected by the termination check above
  ([E-375](../../enhancements_doc/Enhancement-375.md)).
- **Analog operators can't sit in loops or solution-dependent
  conditionals** (LRM 4.5.1) — hoist them or unroll with `generate`; the
  diagnostics say which ([E-70](../../enhancements_doc/Enhancement-70.md)).
- **Recursion in analog functions is illegal** — direct and mutual forms
  are clean errors naming the cycle ([E-59](../../enhancements_doc/Enhancement-59.md)).
- **Analog function arguments accept all three declaration forms**
  ([E-389](../../enhancements_doc/Enhancement-389.md)): the classic separated
  style `input x; real x;`, the combined declaration `input real x;`, and the
  ANSI header `analog function real f(input real x);` — in which a later
  argument may restate neither direction nor type (`f(input real x, y)` gives
  `y` both of `x`'s). **Array** arguments use the separated form, in either
  the LRM's own spelling (4.7.1 Example 3: `inout [0:1]a; real a[0:1];` — the
  range on the direction line is accepted, with the dimensions taken from the
  mandatory data-type declaration) or the plain `output w; real w[0:3];`.
  The combined and ANSI positions still take no array dimensions.
- **String opvars** display via `show` but can't become vectors (ngspice
  vectors are numeric) — `print @n1[strvar]` fails with a clear message
  ([E-69](../../enhancements_doc/Enhancement-69.md)).
- **`sin` is a reserved word** in Verilog-A — don't name a net `sin`
  ([E-36](../../enhancements_doc/Enhancement-36.md)).
- **OSDI ABI pairing**: this ngspice requires OSDI ≥ 0.7; `.osdi` files
  from older compilers must be recompiled, and this compiler's output
  won't load into stock ngspice ([E-54](../../enhancements_doc/Enhancement-54.md)).
- **Parameter default ranges**: a parameter's default is exempt from its
  own `from` range (the CMC "disabled feature" idiom) — but every
  user-given value is fully validated. Don't rely on an out-of-range
  *given* value sneaking through ([E-56](../../enhancements_doc/Enhancement-56.md)).
- **Corpus models that "fail" by design**: some industry models reject
  default configurations on purpose (HiSIM's `$port_connected` guards,
  VBIC floating internal nodes at `RCX=0` — use `.option rshunt`, FBH-HBT
  needing `fb>0`). The triage lives in
  [E-56](../../enhancements_doc/Enhancement-56.md).
- **An omitted OSDI terminal** dangles rather than grounding
  ([E-402](../../enhancements_doc/Enhancement-402.md)): an instance line shorter
  than the port list leaves the model reading `$port_connected() = 0` there and
  gives the terminal a private node, `n1#c`. Since
  [E-719](../../enhancements_doc/Enhancement-719.md) the `.option dcpath` walk
  holds that node with its installed gmin in every mode and names it as an
  unconnected terminal — three iterations where it went "singular matrix" down
  the ladder. `.option silentports`
  ([E-481](../../enhancements_doc/Enhancement-481.md)) installs the hold without
  a word; `.option silentports=ground`
  ([E-482](../../enhancements_doc/Enhancement-482.md)) grounds the terminal
  instead. The native `nport` device declares 512 terminals as a maximum and
  is exempt since [E-746](../../enhancements_doc/Enhancement-746.md): an
  `N1 p1 p2 0 mm` line names nothing, and a line with too few nodes gets the
  device's own message with both counts.
- **An output stage written as a current into ground** — `I(out) <+ (V(out) -
  y)/rout`, the usual way to give a block a finite output resistance — was
  named "no DC path from node 'out'" and gmin-held whenever nothing else on
  `out` conducted (a capacitor, nothing, the next stage's probed input), since
  ground is no node of the device and the conductance shows only as a
  diagonal. Since [E-743](../../enhancements_doc/Enhancement-743.md) the
  `.option dcpath` walk reads a resistive diagonal with nothing else in the
  node's column as the conductance to ground it is; the potential form
  `V(out) <+ y` was always a path and still is. A controlled current with no
  dependence on the node's own voltage is still a current source, and held.
- **A module's internal node reached only through `ddt()`** (`n1#mid` between
  two capacitive contributions) went "singular matrix" down every homotopy,
  277 iterations to a transient operating point, because the walk took its
  `#` name for a built-in device's internal node. Since
  [E-833](../../enhancements_doc/Enhancement-833.md) the walk checks an OSDI
  module's internal nodes: such a node gets the dc-path gmin at once, as its
  built-in twin does, and a transient releases it.
- **An OSDI internal row's name and kind** came from the wrong node of the
  model once anything below it collapsed (`V(p, a1) <+ 0`): the midpoint of a
  divider was the vector `n1#a1`, a branch current was a voltage node tested
  against `vntol`, and "singular matrix: check node n1#si" named BSIM-BULK's
  source node for what was its thermal branch. Since
  [E-836](../../enhancements_doc/Enhancement-836.md) each row carries the name,
  kind and nodeset of the node it stands for.
- **A self-heating model with the heating off** ties its thermal terminal to
  ground itself (`Temp(t) <+ 0`, a 0 V branch). A second such short on the
  same net (two instances sharing it) is dropped since
  [E-837](../../enhancements_doc/Enhancement-837.md), and a voltage source on
  the net (`vt t 0 0`) is named in a warning, since two ideal sources in parallel
  stay singular. Leave the terminal open, or connect it to `0`.
- **A model's internal node written only in an untaken branch** (HiSIM-SOI's
  `db` and `sb` in its 4-terminal mode) has entries in the pattern and none with
  a value, so the dc-path walk cannot see it and no factorization survives it.
  Since [E-838](../../enhancements_doc/Enhancement-838.md) such a row is found at
  the reorder, held with the dc-path conductance and named.
- **A refused analysis command, then `reset`** (`op`, then `sens v(nosuch)` or
  `ac dec 0 1 1`, then `reset`) read a freed job: the command had deleted the
  previous task before refusing its card, and the circuit still pointed into it.
  Silent normally, SIGSEGV under Guard Malloc. Fixed in
  [E-840](../../enhancements_doc/Enhancement-840.md).
- **Two `.sens` cards in one deck**, or an `.sp` after a `.sens`: the second
  analysis ran on devices `sens` had left bound to its freed scratch matrix and
  failed with "singular matrix" on a plain divider. Fixed in
  [E-841](../../enhancements_doc/Enhancement-841.md). `envelope` after a device
  refused at setup copied from a NULL vector; fixed in
  [E-842](../../enhancements_doc/Enhancement-842.md).
- **A deck that `source`s itself**, or two that source each other, recursed
  until the stack overflowed. Since
  [E-843](../../enhancements_doc/Enhancement-843.md) `source` stops at 50
  levels, as `.include` does. The prompt a failed `source` drops to under
  `set interactive` now ends at the end of its input and runs each command
  typed there once.
- **A parameter without a type that reads itself** (`parameter p = p;`), or a
  later parameter that reads it back, panicked openvaf-r. Since
  [E-844](../../enhancements_doc/Enhancement-844.md) it is reported as the
  typed spelling always was.
- **The first transient step** was accepted without a truncation check, at a
  fixed fraction of the run: at `reltol=1e-7` a sine into a 1 ns RC was 32 %
  off at its first point, and a linear L–C network could collapse with
  "Timestep too small" right after it. Since
  [E-846](../../enhancements_doc/Enhancement-846.md) it is checked when the
  start is smooth, and a run usually begins with a shorter step. Where a ramp
  drives a capacitor directly at t = 0, the first step is still SPICE's, since a
  shorter one leaves trap ringing in modes no step resolves. An inductor's error
  floor is `vntol` since [E-847](../../enhancements_doc/Enhancement-847.md).
- **A `.meas` window that opens after the first sample** lost its first point.
  AVG, INTEG and RMS with `from=` dropped the first sample in the window: 3e-4
  low on a triangle, up to 4.8 % on a sampled sine. Fixed in
  [E-848](../../enhancements_doc/Enhancement-848.md). WHEN, FIND..WHEN and TRIG
  with `td=` or `from=` lost a crossing between the window's first two samples,
  and with several crossings reported the next. Fixed in
  [E-849](../../enhancements_doc/Enhancement-849.md). A crossing between t = 0
  and the first step is still not counted (E-418).
- **The input-referred noise** took any gain below 1e-10 as 1e-10: through
  1 fF into 1 kOhm at 1 Hz, `inoise` was 16 times low.
  Since [E-850](../../enhancements_doc/Enhancement-850.md) it divides by the
  real gain, and a gain of zero is reported.
- **The `meas` command's result** kept 7 digits, and so did a vector it
  substituted after `at=` or `val=`. Since
  [E-851](../../enhancements_doc/Enhancement-851.md) both keep all 17, as a
  `.meas` card's result does.
- **A `uic` transient** began at its first step: nothing solved t = 0. Since
  [E-852](../../enhancements_doc/Enhancement-852.md) the t = 0 point is solved
  and written, with each capacitor at its initial voltage. Where a source makes
  a capacitor jump, its currents are those just after the jump, without the
  impulse.
- **`maxord` above 2** does nothing unless `dynorder` or `ordfix` is set: the
  default order control takes Gear to order 2 at most. Since
  [E-853](../../enhancements_doc/Enhancement-853.md) a note says so. Trap's
  order is 2 at most whatever the options: `dynorder` and `ordfix` took it to 3
  on stale coefficients, and `ordfix=3` could hang.
- **A Verilog-A device that loads a NaN or an infinity**, such as `ln(V(x))` at
  Newton's zero start, failed the analysis with "cause unrecorded". Since
  [E-854](../../enhancements_doc/Enhancement-854.md) the failure names the
  instance, and a warning gives the value and the terminal voltages.
- **AVG and INTEG** integrated by different rules, so AVG and
  INTEG/(to−from) differed by up to 2e-3. Since
  [E-855](../../enhancements_doc/Enhancement-855.md) AVG uses INTEG's rule.
- **`.pz` lost complex roots** on 4 of 252 random networks: the search gave up
  at its iteration limit ("Pole-zero iteration limit reached") and the plot held
  the roots found so far. Since [E-856](../../enhancements_doc/Enhancement-856.md)
  a found root is divided out analytically and a pair on the jω axis is
  declared, and those networks give every root. Where the warning remains, the
  search has wandered past its last root, and every set seen with it was
  complete.
- **A sign after an operator in a `.param`**: `{2*-p}` was refused and stopped
  the netlist, `{2*--2}` was −4, and `{2*-3^2}` was 18. Since
  [E-857](../../enhancements_doc/Enhancement-857.md) a sign after an operator
  takes the power chain after it, as in a B-source: −6, 4 and −18. A deck that
  relied on the old values changes. `let` takes a unary plus.
- **`mil` in a `.param`** was milli: `{1mil}` was 1e-3 where `1mil` on an
  element is 25.4e-6. Since [E-858](../../enhancements_doc/Enhancement-858.md)
  it is 25.4e-6 everywhere, and a `.param` value reaches the element with all
  17 digits (`{0.1+0.2}` was 0.3). A deck that wrote `mil` meaning milli
  changes by a factor of 39.
- **A scale factor after an exponent** was dropped by `let`, `print` and
  `plot`: `let x = 1.5e2u` was 150. Since
  [E-859](../../enhancements_doc/Enhancement-859.md) it is 1.5e-4, as on an
  element line.
- **ac on inductive networks at low frequency** could lose up to 6 digits to
  threshold pivoting (`pivrel` 1e-3). Since
  [E-860](../../enhancements_doc/Enhancement-860.md) each ac solve checks its
  residual and refines where it must. A point solved well keeps its bits; the
  check costs up to a quarter more time on circuits whose devices load almost
  nothing.
- **`sens` to a resistance** was low by exactly 1e-6, a one-sided difference
  of a 1/R stamp. Since [E-861](../../enhancements_doc/Enhancement-861.md) the
  difference is central where the parameter is not zero, accurate to about
  1e-10.
- **`$vt` and `` `P_K*T/`P_Q ``** differed by 1.05e-6 inside one model: `$vt`
  took the 2019 SI constants while `constants.vams` defaults to NIST 1998.
  Since [E-862](../../enhancements_doc/Enhancement-862.md) `$vt` uses the
  model's own `P_K` and `P_Q`. ngspice's built-in devices use CODATA 2014, so
  a Verilog-A model on the default header still sits about 1.4e-6 from a
  built-in device's kT/q; a model can define `P_K` and `P_Q` as ngspice's to
  match it exactly.
- **`let x = tan(0)`** failed "argument out of range". Since
  [E-863](../../enhancements_doc/Enhancement-863.md) it is 0.
- **Complex `%` with a real divisor** (`let a = v(1) % 2` after an ac) was
  refused. Since [E-864](../../enhancements_doc/Enhancement-864.md) each part
  is taken modulo the divisor.
- **Power chains** associate left to right in all three of ngspice's parsers
  since [E-865](../../enhancements_doc/Enhancement-865.md): 2^3^2 is 64 (`let`
  gave 512). Unary minus binds *below* `^`: −2^2 is −4 in a `.param`, a
  B-source and `let`, whatever the manual's precedence table (§2.11.5) says.
  Verilog-A differs here: there −2**2 is 4.
- **`write` on a pz plot** named the roots `v(zero(1))` and wrote a lone pole
  twice, the second time as `v(all)`; `print all` printed `all = …`. Since
  [E-866](../../enhancements_doc/Enhancement-866.md) the roots keep their
  names.
- **A high-gain loop through a 0 V source, under Sparse** lost about the gain
  times the rounding of a double: a follower built from a VCVS of gain 1e12,
  with an ammeter in its feedback, was 1.8e-5 off at the operating point and
  2.4e-4 through a transient. **A dc sweep of a resistance** kept the pivot
  order of its first point, and an ammeter beside the swept load read up to
  0.5 % wrong. KLU, which scales its rows, was exact on both. Since
  [E-867](../../enhancements_doc/Enhancement-867.md) the op, dc and transient
  solve checks its residual and refines where it must, as ac does since E-860.
  A solve that was good keeps its bits; the check costs up to a fifth more
  time on circuits whose devices load almost nothing. Since
  [E-868](../../enhancements_doc/Enhancement-868.md) that includes a small
  current beside currents thirteen decades larger: a 6e-8 A sensor next to a
  4e5 A inductor was 1.5e-3 off.
- **A linear amplifier of gain 1e12** went through gmin stepping, 126
  iterations instead of 3: the false-convergence guard read the gain times the
  rounding of its 1e-12 V control voltage as a KCL violation. Since
  [E-869](../../enhancements_doc/Enhancement-869.md) the guard allows what x's
  rounding makes of a row, and gains up to 1e15 converge in plain Newton.
- **`sens … ac` to an inductor coupled by a `K`** held the mutual inductance
  at its nominal value. M = k√(L1L2) should follow L1, as it does under
  `alter`; on a transformer the sensitivity was a quarter of the true one,
  with the sign of its imaginary part flipped. Since
  [E-870](../../enhancements_doc/Enhancement-870.md) the couplings move with
  the inductance.
- **`.option pivrel=1` with `pivtol` set** made Sparse report pivots of 1e+12
  as "below pivtol". Since [E-871](../../enhancements_doc/Enhancement-871.md)
  only a pivot at or below `pivtol` is reported.
- **A `dc temp` sweep of coupled inductors** wrote into freed memory at every
  point after the first, and a coupling that went wrong at a later
  temperature was never reported. Since
  [E-872](../../enhancements_doc/Enhancement-872.md) the coupled-inductor check
  is rebuilt at each point, and reports each system once.
- **`dynorder` with `maxord` above 3** could make a stable network explode
  without a word: 9e22 V on a node that peaks at 0.919 V at `maxord=6`. The
  truncation estimate at order k ≥ 3 was (k+1)!/3! too small, so the high orders
  looked cheap. Since [E-873](../../enhancements_doc/Enhancement-873.md) every
  order is measured alike. Orders 1 and 2 are unchanged; `sdirk`'s order-3
  estimate is four times larger, as it should be.
- **`trbdf2` and `sdirk`** needed ten times the points per decade of `reltol`
  at the default `maxord`: 580 045 points for an RC at 1e-6 where trap needed
  512. Since [E-874](../../enhancements_doc/Enhancement-874.md) their stages no
  longer overwrite the history, and `maxord` is pinned to their order (2 and 3),
  with a note when it is given otherwise.
- **A PULSE voltage source** could skip the end of a rise it had landed at the
  start of, when floating-point rounding put the rise at the end of the period
  before; a repeating PWL could skip a knot the same way. Since
  [E-875](../../enhancements_doc/Enhancement-875.md) every corner is landed.
- **`dynorder` with `trbdf2` or `sdirk`** froze the step at its first size,
  and a run could take millions of points or never end: each staged method
  has one order, and `dynorder` re-decided it every step. Since
  [E-876](../../enhancements_doc/Enhancement-876.md) `dynorder` leaves them
  alone and says it has no effect.
- **A PULSE current source with edges shorter than `minbreak`** stopped
  scheduling its edges after the first period, and the run stepped over them:
  3 % off where the same pulse from a voltage source was 0.03 %. Since
  [E-877](../../enhancements_doc/Enhancement-877.md) both sources place their
  points alike.
- **A transient whose Newton iteration ran away once** could end in "Timestep
  too small" however small the step: the retry started from the runaway
  iteration. Since [E-878](../../enhancements_doc/Enhancement-878.md) a retry
  starts where the step started.
- **`loadstate` with `maxord` above 2** refused the checkpoint as "does not
  match this circuit", naming two counts that matched. Since
  [E-879](../../enhancements_doc/Enhancement-879.md) it restores, and a real
  mismatch names the order.
- **A resumed transient** (`resume`, or `loadstate`) re-derived `minbreak`
  5e6 times larger than the run had it, and stepped over short edges the run
  had landed on. Since [E-880](../../enhancements_doc/Enhancement-880.md) it
  keeps the run's spacing. `stop when time > t` still lands the run on t, so a
  continuation follows a run with the same stop.
- **Transient options with no reading** were taken without a word: `xmu`
  outside [0, 0.5] (wrong answers), `ordfix=-1` or above 6, `reltol` of 1 or
  more, and an unknown `method`, which ran trap after a generic message. Since
  [E-881](../../enhancements_doc/Enhancement-881.md),
  [E-882](../../enhancements_doc/Enhancement-882.md) and
  [E-883](../../enhancements_doc/Enhancement-883.md) they are refused, capped
  with a warning, or named with what runs instead.
- **Built-in switches (`sw`, `csw`)** turned over on the step grid: a crossing
  was accepted where a step happened to end (11 ns late at a 100 ns step), and
  at tight tolerance the step crept up on it until "Timestep too small" (a
  charge pump with `vh=0` at `reltol=1e-6`). Since
  [E-884](../../enhancements_doc/Enhancement-884.md) a switch lands on its
  crossing and the step after it starts at order 1, which also stops trap
  ringing at switch edges. The step after a landing crosses a picosecond-scale
  transient in one backward-Euler step; tighten the tolerance, not `tmax`, to
  resolve it.
- **Trap on a high-Q tank** at the default tolerance keeps each step's error
  within `reltol` but lets the phase drift: a 274 MHz tank with Q ≈ 130,
  ringing for the whole run at 11 points a period, ended 71 % off, and
  `reltol=1e-7` gave 0.57 %. For an oscillator or a long ring, tighten
  `reltol` (or set `trtol=1`) and check the result against a tighter run.
- **`xmu` below 0.5** is a first-order method; since
  [E-885](../../enhancements_doc/Enhancement-885.md) the step control says so,
  and `xmu=0` costs what backward Euler costs.
- **`newtrunc`** needs a build configured with `--enable-predictor`; here it,
  and its tolerances `ltereltol`, `lteabstol` and `ltetrtol`, have no effect,
  and say so ([E-886](../../enhancements_doc/Enhancement-886.md)).
- **An `option` given while a run is paused** reaches the resumed run only if
  it is read at every step (the tolerances, `itl4`, `gmin`, the Newton aids);
  the method, `maxord`, `ordfix`, `dynorder`, the temperatures and the solver
  keep the run's values until the next analysis
  ([E-887](../../enhancements_doc/Enhancement-887.md)). Before, a run started by
  `run` took them all, and crashed on a new `maxord` or solver.
- **`ordfix`** has no truncation control at all: every converged step is
  accepted, at `tmax`. Gear or Adams pinned at 3 or above is not A-stable, and
  a stiff circuit diverges; since
  [E-888](../../enhancements_doc/Enhancement-888.md) the run says so and stops
  when a node passes 1e15 V. Use `ordfix` to measure an integrator, not to
  simulate.
- **Newton's convergence** is two tests: no unknown moved more than `reltol`
  of itself plus `vntol` (or `abstol`), and no device current moves more than
  `reltol` of itself plus `abstol` over the last step. Until
  [E-889](../../enhancements_doc/Enhancement-889.md) the second never decided
  anything, and a Verilog-A device had none: a diode across a resistor between
  two 100 V nodes was accepted 0.68 V forward, where the node test allows
  0.1 V a step. The node test is still relative to the node's own voltage, and
  linear elements have no device test. The same pair between two 1 kV nodes
  converges with 1.67 mV across it, inside 1e-3 of 1 kV. A current into a
  low-impedance node is resolved only to `vntol` over its resistance: 1.25 nA
  into 65 Ω is 82 nV, under `vntol`. For a circuit that lives at a high common
  mode, or a node that must carry nanoamps, lower `reltol` or `vntol`.
- **The device tests cost iterations** where they find work: a BSIM4 ring
  oscillator takes 14 % more Newton iterations since
  [E-889](../../enhancements_doc/Enhancement-889.md), and 500 random diode, BJT
  and MOSFET networks 1 % more.
- **A tight `reltol` needs a tight `vntol`.** The device tests count a step no
  larger than `vntol` (or `abstol`), or than the rounding at the circuit's
  largest voltage, as no step
  ([E-895](../../enhancements_doc/Enhancement-895.md); at `reltol=1e-9`
  E-889 asked for less than the solve resolves, and a Gummel–Poon stage's
  transient ended "Timestep too small"). At `reltol=1e-9` with the default
  `vntol` of 1 µV, a junction may still move 1 µV in the last step, 4e-5 of
  its current: set `vntol=1e-12` with it.
- **`polydegree` and `dpolydegree`** above 2 were unusable late in a long
  run: the local fit was made in the absolute time, and `deriv` at
  `dpolydegree=3` read 3e20 times the derivative after 500 ms. Since
  [E-890](../../enhancements_doc/Enhancement-890.md) the fit is local and any
  degree is accurate. `deriv` of a nested `dc` sweep still fits across each
  group boundary: take it per sweep, or ignore the point on either side of a
  restart.
- **`setseed N`** restarts every stream at the same state, however often it is
  given ([E-891](../../enhancements_doc/Enhancement-891.md)). `set rndseed=N`
  does not: setting the variable to the value it holds changes nothing.
- **The Meyer gate capacitances of MOS levels 1 to 3** (given `tox`) are
  capacitances, not charges, and do not conserve charge: a level-1 MOSFET
  whose gate, bulk and tied drain and source are driven around a closed path
  lost 67 % of the charge it moved each period, the same at every step size.
  For charge pumps, switched-capacitor circuits or anything that integrates a
  gate current over many cycles, use a charge-based model (BSIM3 or BSIM4
  `capmod` 1 to 3 conserve to 1e-6 per period under trap). Pinned in
  `nlnotes_examples` [9].
- **The built-in HICUM (`level=8`) before E-896 to E-899** was a different
  model in several places from the Verilog-A HICUM L2.4.0 it ports:
  - Its small-signal matrix was off its own currents by up to 2 % at the
    default `t0=0` (`ac`, `noise`, `pz`, `.sp`).
  - A pnp did not simulate at all.
  - At the default `flcomp`, the substrate transistor carried a sixth of its
    current.
  - A self-heating device ended ngspice at the second analysis of a small
    circuit.

  See [E-896](../../enhancements_doc/Enhancement-896.md) to
  [E-899](../../enhancements_doc/Enhancement-899.md). Results from older builds
  with any of these need re-running. Two of 200 random cards still keep a
  1e-4 gap between `ac` and the dc derivative, and the compiled
  `hicumL2V2p4p0.va` is the reference to check against.
- **MOS1 flicker noise at the default `nlev=2`** is
  KF·gm²/(f^AF·W·Leff·Cox): AF is the exponent of the FREQUENCY, not of the
  current as in the SPICE2 form, so `af=0.5` makes a 1/√f spectrum. `nlev=0`
  gives KF·Id^AF/(f·Cox·Leff²), the 1/f form. Pinned in `nlnotes_examples` [10].
- **The truncation tolerance's charge term** is `reltol` of the charge a
  capacitor HOLDS, per step: a capacitor at a DC bias may err each step by
  `reltol` of its whole charge, however small its swing. With `tmax=1m`, a
  10 mV ripple on a 1 µF capacitor biased at 1 V was taken in 35 steps over
  20 periods and missed by five times its amplitude; at 0 V bias it took 237.
  This is SPICE's definition. The default `tmax` (the `tstep` of the `tran`
  command) resolves the ripple; when you raise `tmax`, keep it a small fraction
  of the period of the smallest signal you care about. Pinned in
  `nlnotes_examples` [11].
- **"the operating point carries … A in …, past any junction a circuit
  models"** ([E-894](../../enhancements_doc/Enhancement-894.md)) names a branch
  past a megaampere: almost always a source that forward-biases a junction
  directly. Add the junction's series resistance, or the source's.
- **`compose name values 1 -2 3`** is [1, −2, 3] since
  [E-900](../../enhancements_doc/Enhancement-900.md). Before it, the values
  were one expression list, `1 -2` was 1 − 2, and the vector was [−1, 3]
  without a word. A comma did not help, since the shell turns it into a space.
  Vectors that older builds composed from unbracketed negative values need
  re-making. `print`, `plot` and the other commands that take a list still
  read `1 -2`, `1, -2` and `v(a) -v(b)` as one difference, and label it so
  (`1 -2 = -1`). To list a negative expression there, put it in parentheses:
  `print v(a) (-v(b))`.
- **`.sp`'s NF, NFmin and Rn** are the IEEE values, referred to T₀ = 290 K,
  since [E-901](../../enhancements_doc/Enhancement-901.md). Older builds
  normalised them by the circuit's temperature T, which made F − 1 and Rn T₀/T
  of their values, for any network. NF was off by up to 10·log₁₀(T/T₀), the
  bound reached where the network's own noise dominates: 0.149 dB low at
  27 °C, 1.38 dB low at 125 °C, 0.95 dB high at −40 °C. Rn was 3.4 % low at
  27 °C. Noise figures from older builds, away from 16.85 °C, need re-running;
  `Cy` was right throughout.
