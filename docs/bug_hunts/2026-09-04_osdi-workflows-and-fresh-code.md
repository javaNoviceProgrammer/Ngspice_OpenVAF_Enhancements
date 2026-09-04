# Bug hunt — OSDI workflows and the code Enhancement-543 just added

**Date:** 2026-09-04 · **Commit under test:** `649747c6` (Enhancement-543) ·
**Binaries:** locally built `ngspice-46/build/src/ngspice` and `~/bin/openvaf`
(OpenVAF-master-20260610). **Duration:** 18:27–19:14, foreground only, nothing
fixed; the document was written during the last quarter of it.

Two targets. First, the code that landed an hour earlier: the simulator-side
MOSFET/BJT step limiter (`osdiload.c`), its recognizer (`osdiregistry.c`),
the KLU refactor-collapse check, the display coalescing ring, and the Monte
Carlo walk mode and seed notes. Second, the everyday OSDI workflows the
previous hunts had not touched: `optimize`, `alter`/`altermod` in every
spelling, `.nodeset`/`.ic` steering, `show`/`showmod`, `pre_osdi` paths,
`m`, `sens`, series-resistance and gate-resistance model configurations,
bistable cells. Method as before: every probe has a built-in twin or a
closed-form answer, and every number below comes from a run of the binary
above.

**Result: one finding that turns the new default on its head for a standard
model configuration, one wrong-state result that predates it, one state loss
in the sampling commands, two coverage gaps, and a tail of diagnostics.** The limiter that made
a 100-stage chain converge in 8 iterations makes the same chain with BSIM4's
series resistances switched on take 356 where the un-limited path takes 30,
and with the gate resistance on as well the operating point fails outright.
Separately, and independent of the limiter, a BSIM4 OSDI SRAM cell steered
by `.nodeset v(q)=0` settles in the opposite state from the built-in one.

| # | finding | severity |
|---|---|---|
| [F1](#f1--the-limiter-across-live-internal-drainsource-nodes-makes-convergence-worse-and-can-break-it) | with `rdsmod=1` (live internal drain/source nodes) the limiter costs 5–12× the iterations of the un-limited path, pulls in gmin stepping, and with `rgatemod=1` added the DC operating point fails altogether; the verbose report presents the internal-node path as a feature | **high** — default-on, wrong direction, one configuration fails |
| [F2](#f2--a-bsim4-osdi-bistable-cell-steered-by-nodeset-lands-in-the-other-state) | `.nodeset v(q)=0` (or 0.05) on a 6T cell with OSDI BSIM4 ends in the mirrored state; the built-in twin and OSDI PSP103 honour it; a chain given its exact solution as nodeset takes 30–40 iterations against 6 | medium — wrong state, silently; not the limiter |
| [F3](#f3--altermodalter-on-a-statistical-osdimc-parameter-is-undone-by-the-sampling-commands) | after `altermod @mm[r]=1100` on a model-declared statistical parameter, `montecarlo`, `highsigma` and `wcd` all sample around the original 1000 and the operating point afterwards reads a draw | medium — confident wrong statistics |
| [F4](#f4--a-statistical-param-on-an-osdi-model-card-for-an-instance-class-parameter-yields-0-) | `.model nmv bsim4va(l={ll})` with `ll` an `agauss` param: `montecarlo` prints *model has no parameter l* once per trial and reports yield 0 %; `highsigma` and `wcd` apply the same deck correctly | medium-low — wrong number, loud but not refused |
| [F5](#f5--the-display-coalescing-ring-resets-on-every-setup-pass) | `sens` on an OSDI BSIM4 deck prints the model's `$strobe` 3 477 times with no summary; a `.dc` over a device parameter and `montecarlo` print it once per point | low — noise, E-543 F4 follow-up |
| [F6](#f6--option-osdilim_verbose-on-the-options-card-is-honoured-and-called-unknown) | `.option osdilim_verbose` works and is warned *unknown option … ignored* | low — diagnostic |
| [F7](#f7--the-verbose-report-is-keyed-by-compiled-file-not-by-model-card-and-lives-for-the-process) | one line per `.osdi` file, so the PMOS card's polarity is never reported; silent after a re-`source`; silent when `noosdilim` is set; BJT line says *threshold 0 V* | low — diagnostic |
| [F8](#f8--a-model-parameter-on-an-instance-line-is-refused-as-unknown-parameter) | `nr1 a 0 rmod r=2k` fails with *unknown parameter (r)* though `r` is a parameter the model knows, on its card | low — misleading text |
| [F9](#f9--pre_osdi-cannot-take-a-path-with-a-space) | quotes are kept literally, an escaped space splits the argument | low |
| [F10](#f10--m-1-prints-two-contradictory-warnings) | *sign-inverted* and *ignored* on the same line; acts as `m=1` | low |
| [F11](#f11--sens-vector-names-mix-two-separators) | `n1:r` beside `n1__mfactor`, `n1_dt`, `n1_temp` | cosmetic |
| [F12](#f12--hisim2-is-never-limited-its-internal-nodes-are-named-dpsp) | the recognizer knows `gp` for the gate but not `dp`/`sp`/`bp`, and HiSIM2's noise node `n` is live: a 20-stage HiSIM2 chain takes 258 iterations with gmin stepping, limiter or not | low — E-543's claim does not reach HiSIM2 |
| [F13](#f13--an-absent-terminal-is-warned-about-per-instance-then-left-floating) | BSIMBULK (`d,g,s,b,t`) written with four nodes: 40 three-line warnings name the absent `t`, then the thermal node floats and the DC operating point fails after 373 iterations and three stepping strategies without referring back; with `t` grounded, 11 iterations | low — diagnostic |

Three observations that are design limits rather than defects, and three
things that are not OSDI-specific, follow the findings.

---

## F1 — the limiter across live internal drain/source nodes makes convergence worse, and can break it

Enhancement-543's limiter recognizes a MOSFET by its terminal names and, when
the model's series resistances keep the internal drain/source/gate nodes
live, uses those nodes as the roles the built-in `b4ld.c` would use. The
suite that shipped with it tests single devices and short chains, where the
path looks fine. At the chain lengths the enhancement was written for, it
is not.

Deck family: a chain of *n* OSDI BSIM4 inverters (`bsim4.osdi` from
`VA-Models`), 5 fF per node, `vin=0`, `.model … bsim4va(type=±1 w l <mp>)`,
`op`, `rusage totiter`. `<mp>` selects the configuration. "off" is
`set noosdilim`; the built-in twin is `level=54` with the same card.

| `<mp>` | n | limiter on | limiter off | built-in |
|---|---|---|---|---|
| `rdsmod=1 rdsw=500` | 1 | 7 | 8 | — |
| | 2 | 8 | 16 | — |
| | 5 | 16 | 21 | — |
| | 10 | **153, gmin stepping** | 28 | — |
| | 20 | **356, gmin stepping** | 30 | 10 |
| `rdsmod=1 rdsw=100` | 20 | 356, stepping | 30 | 10 |
| `rdsmod=1 rdsw=10` | 20 | 356, stepping | 30 | — |
| `rgatemod=1 rshg=10` | 20 | 9 | 49 | 9 |
| `rdsmod=1 rdsw=500 rgatemod=1 rshg=10` | 20 | **DC solution failed** (38 389 iterations; *singular matrix: check nodes s13 and nn17#gi*; dynamic, true gmin and source stepping all fail) | 30 | 10 |
| `rdsmod=1 rdsw=500`, `.option klu` | 20 | 259, stepping | 47 | — |
| `rdsmod=1 rdsw=500`, `dc vdd 0 1.2 0.05` | 20 | 327, stepping | 101 | — |
| `rdsmod=1 rdsw=500` | 40 | 358, stepping | 165, stepping | — |
| `rdsmod=0` (E-543's headline case) | 40 | 9 | 71 | — |
| `rdsmod=1 rdsw=500`, `dc vin 0 1.2 0.01` | 5 | 391 | 400 | — |
| `rdsmod=1 rdsw=500`, `tran 10p 2n` | 10 | 769 | 644 | — |
| `rdsmod=1 rdsw=500`, `tran 10p 5n`, full-swing input | 20 | 1 835, stepping | 1 509 | — |

The count does not move with the resistance value (500, 100 or 10 Ω per
square all give 356), only with the nodes being live. Every run that
converges lands on the same operating point (v(s20) =
6.776492e-08 on and off; the transient waveforms agree to 5e-14 V), so the
limiter is not steering to a wrong solution — it is steering slowly, and
at 20 stages with both resistances it steers into a singular matrix at an
internal gate node. The gate-resistance-only case shows the internal-node
mechanism is not wrong per se (9 against 49): it is the drain/source pair
that goes wrong, and it goes wrong with the chain length — exactly the
regime where E-543's headline was measured with `rdsmod=0`.

`set osdilim_verbose` on the same deck says
*MOSFET limiting (DEVfetlim/DEVlimvds/DEVpnjlim), polarity +1, threshold
0.7 V, across its internal nodes* — a feature notice for the case that
hurts. `rbodymod=1` is correctly refused (*internal node 'sbulk' is live and
is not a drain/gate/source/bulk node the limiter knows*, 24 iterations either
way).

What is probably wrong (not verified — nothing was fixed): the built-in
limits `vds`/`vgs` between drain-prime and source-prime but stamps the series
resistors from the *un-patched* node voltages; the OSDI path patches
`CKTrhsOld` of the internal nodes before the whole model evaluates, so the
resistor branches, the junction diodes and the intrinsic device all see the
limited internal voltages, and their companion currents disagree with the
terminal voltages by `(patch)/rdsw` per iteration. That is consistent with
the failure being invisible at n ≤ 5 and singular with the gate node also
patched. Whatever the cause, **the default should not apply across live
internal nodes until it is shown to help there**; the `rgatemod` numbers say
a gate-only patch may be kept.

Reproduce: `hunt3/t1.cir`, `u1.cir`, `u4.cir`, `y7.cir`, `u3.cir`.

## F2 — a BSIM4 OSDI bistable cell steered by `.nodeset` lands in the other state

Not the limiter: identical with `set noosdilim`. A 6T SRAM cell (two
cross-coupled OSDI BSIM4 inverters, two access NMOS, word line and both bit
lines at 1.2 V, so the cell sits in a read condition), `op`:

| `.nodeset` | OSDI on | OSDI off | built-in `level=54` |
|---|---|---|---|
| `v(q)=0 v(qb)=1.2` | q = 1.198, qb = 0.279 — **mirrored** | mirrored | q = 0.279, qb = 1.198 |
| `v(q)=0.05 v(qb)=1.2` | mirrored | mirrored | honoured |
| `v(q)=0.1 v(qb)=1.2` | honoured | honoured | honoured |
| `v(q)=0.2`, `v(q)=0.3` | honoured | honoured | honoured |
| `v(qb)=1.2` only | honoured | honoured | honoured |
| none | 0.638 / 0.638 (metastable) | same | 0.638 / 0.638 |
| the cross-coupled pair alone, `v(q)=0 v(qb)=1.2` | honoured (q = 4.6e-8) | honoured | honoured |
| the pair with a 5 kΩ pull-up on each side, `v(q)=0 v(qb)=1.2` | **0.651 / 0.651, metastable** | metastable | q = 0.104, qb = 1.200 |
| word line at 0 V (access devices off), `v(q)=0 v(qb)=1.2` | — | honoured (q = 1.1e-7) | — |
| word line at 0.6 V, `v(q)=0 v(qb)=1.2` | — | mirrored (q = 1.200, qb = 0.061) | — |
| one access device, on `q` only, word line 1.2 V, `v(q)=0 v(qb)=1.2` | — | mirrored | — |

The same cell built from `psp103.osdi` honours `v(q)=0` (q = 0.232). So the
loss is specific to the BSIM4 OSDI model under a nodeset that pins a node at
or near 0 V while something is pulling it up — an access transistor or a
plain resistor; with the resistor the cell does not even flip, it lets go of
the nodeset and settles on the metastable point the built-in twin only
reaches with no steering at all.

The chain shows the same model taking the nodeset badly even when it is the
exact answer. 20-stage BSIM4 chain, `rdsmod=0`, `.nodeset` on every node at
its final value (odd 1.2 V, even 0 V):

| | OSDI on | OSDI off | built-in | OSDI PSP103 (on / off) |
|---|---|---|---|---|
| exact nodeset on all 20 nodes | 30 | 40 | 6 | 5 / 5 |
| `.nodeset v(s1)=1.2` only | 16 | 55 | 10 | — |
| no nodeset | 9 | 42 | 9 | 8 |

A nodeset that *is* the solution costs the OSDI BSIM4 chain three times the
iterations of no nodeset at all. `cktload.c` stamps a nodeset as a 1e10
conductance during `MODEINITJCT|MODEINITFIX`, the same for both device
kinds, so the difference is in what the model does with the clamped
voltages when the clamp is released. Not chased further.

Reproduce: `hunt3/x.cir`, `w.cir`, `y1.cir`, `z2.cir`.

## F3 — `altermod`/`alter` on a statistical osdimc parameter is undone by the sampling commands

`smcres.osdi` declares `r` as a Gaussian statistical parameter (E-535
`.option osdimc`). A plain `altermod` works, then any sampling command
silently puts the original nominal back:

```
.option osdimc mcseed=7
v1 1 0 dc 1
n1 1 0 mm
.model mm smcres
.control
pre_osdi smcres.osdi
op ; print i(v1)                       -> -1.00000e-03   (nominal 1000)
altermod @mm[r]=1100
op ; print i(v1)                       -> -8.93068e-04   (1100 with a draw: works)
montecarlo 5 -spec i(v1) -max -0.9m    -> yield 100 %, every trial "(nominal 1000)"
op ; print i(v1)                       -> -9.96583e-04   (a draw around 1000)
```

| after `altermod @mm[r]=1100` | reported | expected |
|---|---|---|
| `wcd -spec i(v1) …` (β for the 4σ threshold set for nominal 1000) | β = 4.0000 | ≈ 0.29 |
| `highsigma 300 -scale 2 -seed 3 -metric -1/i(v1) -max 1105` | P(fail) = 2.3e-05 (σ ≈ 4.1) | ≈ 0.4 (nominal 1100 is 5 Ω under the threshold) |
| `montecarlo 5` trial banners | *(nominal 1000)* | nominal 1100 |
| `alter @n1[dr]=100` then `wcd` | β = 4.0000 | shifted |

A plain OSDI model parameter (`nres` `altermod` to 3 kΩ) and a netlist
`alter r2=3k` survive the same commands; recentring in a plain `op`
sequence works. The sampling commands' internal reset (`OSDImcNewRun` /
the walk's `OSDImcWalk(NULL,0)` exit) restores the *compiled* nominal, not
the `altermod`'d one, so a designer who recentres a model-declared
statistic and then asks for yield gets the un-recentred answer with no
message.

Reproduce: `hunt3/o5.cir`, `p1h.cir`, and the earlier `z*` decks.

## F4 — a statistical `.param` on an OSDI model card, for an instance-class parameter, yields 0 %

OSDI lets an instance-class parameter (`l`, `w`) be given on the model card
as the instances' default, and the parser accepts `.model nmv bsim4va(type=1
w=1e-6 l={ll})` with `.param ll=agauss(0.1e-6, 0.01e-6, 3)`. The three
sampling commands disagree on it:

| placement of `l={ll}` | `montecarlo 20 -seed 4 -spec @nn1[l] -max 0.1e-6` | `highsigma 200 -scale 2 -seed 3` | `wcd -spec @nn1[l] -max 0.12e-6` |
|---|---|---|---|
| instance line | yield 40 % (draws above nominal fail: right) | P(fail) 0.4752 | β = 6.0000 (0.12 µ is 6σ: right) |
| model card | **yield 0 %**, and 20 × *Error: model 'nmv' has no parameter l.* | P(fail) 0.4752 | β = 6.0000 |

`montecarlo`'s in-place push (`altermod`, E-322's fast path) asks the model
for `l` as a model-class parameter, fails, and scores the trial as a
failure; the other two commands re-source and are right. The error is loud,
but the yield line underneath it is a definite 0 % and a script reading
`montecarlo_yield` sees nothing wrong. The built-in `level=54` behaves the
same way (*model 'nm' has no parameter l*), so the push path is the common
factor. Relatedly, `print @nmv[l]` after the deck loads answers *no such
parameter l* although the card accepted it.

Reproduce: `hunt3/aa1.cir`, `aa3.cir`.

## F5 — the display coalescing ring resets on every setup pass

E-543 F4 collapses a model line repeated across instances into *was
repeated N more times*. The ring is cleared at every setup pass, and every
analysis that re-runs setup starts the count again:

| analysis on an OSDI BSIM4 deck | `RECALCULATION for no K1 or K2` lines | summaries |
|---|---|---|
| `op` (two setup passes, 40 instances) | 24 | 6 |
| `sens v(d) dc` on a 2-device inverter | **3 477** | 0 |
| `sens v(s10)` on a 10-stage chain (20 devices) | **69 512** | 2 |
| `dc @nn1[w] 1u 8u 1u` (8 points) | 11 | — |
| `montecarlo 20` | 40 | — |

`sens` re-sets-up once per parameter perturbation; the ring never sees five
identical lines within one pass because each pass has two, so nothing is
ever summarized and the model's `$strobe` — which for this model also says
*FATAL Error: leff <= 0.* during the perturbations, harmlessly — floods
the log. Within a pass the coalescing works (the 20-stage `rdsmod=1` chain
prints 24 warning lines and 6 summaries for 120 messages).

## F6 — `.option osdilim_verbose` on the `.options` card is honoured and called unknown

`noosdilim` was added to `spiceif.c`'s pass-through list; `osdilim_verbose`
was not. `.option osdilim_verbose` (or `=1`) on the card sets the variable —
the report prints — and the front end says *Warning: unknown option
'osdilim_verbose' on a .options card; ignored.* `set osdilim_verbose` in
`.control` is silent and right. Every spelling of the other one works:
`.option noosdilim`, `.options noosdilim`, `.option noosdilim=1`, `set
noosdilim`, and the `option noosdilim` command all give the un-limited 42
iterations on the 20-stage chain.

## F7 — the verbose report is keyed by compiled file, not by model card, and lives for the process

`osdi_lim_reported[32]` remembers *descriptors*. Consequences, all measured:

* an inverter with `nmv` (type +1) and `pmv` (type −1) from one `bsim4.osdi`
  prints one line, *polarity +1, threshold 0.7 V*, for `nn1`; the PMOS
  card's decision is never shown;
* after `source` of a second deck in the same session the report is silent
  (one line across three `op`s and a re-source);
* with `noosdilim` set the verbose flag prints nothing, so a user asking why
  nothing is limited gets no answer;
* the BJT line reads *threshold 0 V* (`osdi_lim_vth` is MOSFET-only);
* beyond 32 distinct compiled files the report would print per instance per
  iteration (not exercised).

## F8 — a model parameter on an instance line is refused as "unknown parameter"

`nr1 a 0 rmod r=2k` (and `r={rr*2}` inside a subcircuit) with `r` a
model-class parameter of `nres.osdi` fails with *unknown parameter (r)*. The
parameter is known; it is not an instance parameter. The message should say
so and name the `.model` card.

## F9 — `pre_osdi` cannot take a path with a space

`pre_osdi "dir with space/nres.osdi"` looks for `""dir with space/nres.osdi""`
(the quotes are kept, doubled); `pre_osdi dir\ with\ space/nres.osdi` is
split into three arguments. No spelling loads the file.

## F10 — `m=-1` prints two contradictory warnings

`n1 … m=-1` warns *sign-inverted* and *ignored* on the same instance and
simulates as `m=1`. One of the two is true.

## F11 — `sens` vector names mix two separators

The OSDI sensitivity vectors are `n1:r` for the model parameter and
`n1__mfactor`, `n1_dt`, `n1_temp` for the instance ones.

## F12 — HiSIM2 is never limited: its internal nodes are named `dp`/`sp`

`hisim2.va` declares `electrical dp, gp, sp, bp, db, sb, n` (and two NQS
nodes). The recognizer's drain/source/bulk aliases are `di`/`si`/`bi`, its
gate aliases `gi`/`gp` — so the gate would be found and the drain not, and
before that the noise node `n` (not in the `noi` whitelist, not a flow
unknown) is live with default parameters:

| HiSIM2 20-stage chain | verdict | on | off |
|---|---|---|---|
| defaults | *internal node 'n' is live and is not a … node the limiter knows* | 258, stepping | 258, stepping |
| `corsrd=1 rs=50e-6 rd=50e-6` | *internal node 'dp' is live …* | 360, stepping | 360, stepping |

Given F1, the refusal is protective today; it is still the gap between
"a compiled MOSFET converges like a built-in one" and this model.

## F13 — an absent terminal is warned about per instance, then left floating

`bsimbulk.va` is `module bsimbulk(d, g, s, b, t)`. Written the way every
BSIM4 deck is written — four nodes — each instance gets a three-line
warning (*1 of the 5 terminals of model type 'bsimbulk' are not connected.
terminal 5 ('t') is absent. The model sees $port_connected() = 0 …*), 40
times for a 20-stage chain, which is right and complete. What follows is
not: the thermal node becomes an internal node nothing holds (the model
does not guard it with `$port_connected`), and the operating point fails —
373 iterations, dynamic, true gmin and source stepping all fail, *Transient
op failed, timestep too small* — without a word linking the failure to the
warning 400 lines up. With `t` grounded the same chain converges in 11.
Tying an absent terminal to ground, or naming it again in the failure, is
the missing piece; the BSIM4 deck written with three nodes (bulk absent)
gets the same warning and converges in 9, so the policy question only bites
when the absent terminal has no path.

---

## Observations — design limits, recorded so nobody rediscovers them

**O1 — polarity is read from the model card only.** A module whose `type`
is an instance parameter (`shmos3.va` here, `(*type="instance"*) parameter
integer type`) is limited as n-type whatever the instance says. It still
helped on a 10-stage PMOS/NMOS chain — 12 iterations against 165 with gmin
stepping, and `tran` 899 against 4 353 with a *timestep too small* failure
when off — because the cold-start guess and `DEVlimvds` are robust to the
sign; but that is luck, not design. A module with no `type` at all (`shmos`,
`pch` flag) is the same case: 12 against 325.

**O2 — the un-limited operating point accepted a solution 20 V outside the
rails.** The `shmos` chain with `set noosdilim` reported v(s5) = 21.2 V and
v(s10) = −20 V from a 1.2 V supply, after gmin stepping "completed". ngspice's
DC convergence test is on node-voltage change only, and an OSDI device has
no `convTest`, so a node held by 1e-12-siemens leakages can settle anywhere.
Not new and not OSDI-specific in principle, but the limiter is what stands
between a compiled model and it.

**O3 — `.ic` steers an OSDI `op` but not a built-in one.** `OP` carries
`do_ic = 1`, so `CKTic` copies `.ic` values into the solution vector before
the job; `cktload.c` stamps them only in a transient op. A built-in MOSFET
ignores the vector at `MODEINITJCT` (cold guess) and the SRAM cell with
`.ic v(q)=0 v(qb)=1.2` ends metastable (0.638 / 0.638, the no-init answer);
the OSDI cell reads the vector through `prev_solve` and ends in a state —
with the limiter off the requested one, with it on the mirrored one, because
the "guess only when all raw voltages are zero" rule sees non-zero raw
voltages and runs the `b4ld.c` block from an uninitialized history.

**O4 — the BJT branch reaches no shipped compact model.** Every BJT from
`VA-Models` is refused by the recognizer, correctly by its own rules:
HICUM/L2 and HICUM/L0 carry a fifth terminal (`tnode`); MEXTRAM keeps `b1`/`e1`
live; VBIC 1.3 (`vbic13_4t`, c,b,e,s) keeps its thermal node `dt` live even
with self-heating off, so *internal node 'dt' is live and is not a
drain/gate/source/bulk node the limiter knows* with every parameter set
tried. A 10-stage resistor-load chain of each: HICUM/L0 277 iterations with
gmin stepping, VBIC 175 with stepping, limiter on or off alike. Only the
hand-written Ebers-Moll module gets the branch: 24 against 226 with
stepping. If the BJT branch is to earn its place, it needs a thermal-node
allowance the way the MOSFET branch would need one for a thermal terminal.

## Not OSDI-specific

* `showmod` on a subcircuit-local model says *No matching instances or
  models* for built-ins too; `showmod mod : notaparam` lists every parameter
  for built-ins too.
* `stop when … ; resume` re-triggers the same stop for built-in decks.
* `montecarlo … -spec @mn1[l]` on the built-in `level=54` prints no yield
  line at all (instance-line placement, no error); not chased.

---

## What was measured and holds

* **Analyses, limiter on and off, Sparse and KLU:** `dc`, `tran` (with and
  without `uic`), `dc temp`, `tf`, `pz`, `noise`, `sens` — identical results
  to the last printed digit; transient waveforms of the `rdsmod=1` chain
  agree to 5e-14 V.
* **Newton counts Sparse vs KLU** on the 20-stage `rdsmod=0` chain: 9 / 9
  built-in, 9 / 9 OSDI on, 42 / 41 OSDI off; refactor-collapse check fired
  0 times there, on the 40-stage transient, on a stiff RC ladder, and on an
  `alter r1` loop swinging 1 Ω ↔ 1 GΩ across six operating points (values
  identical under both solvers).
* **Other MOSFET models:** EKV 2.6 (`ekv26_va`) is recognized and a 20-stage
  chain converges in 7 against 8; a chain mixing `bsim4.osdi` and
  `psp103.osdi` instances converges in 11 with one verbose line per file.
* **BSIM4's other internal-node modes:** `rgatemod=2` 12 against 35;
  `rgatemod=3` refused on the live `gm` node, 39 either way; `trnqsmod=1` and
  `acnqsmod=1` limited, 9 against 42; `tran … uic` on the `rdsmod=1 rgatemod=1`
  chain that fails its op runs identically on and off (794 iterations, same
  waveform) since the transient steps never trip the limiter.
* **More verdicts:** BSIMBULK (`d,g,s,b,t`) — *not a 3/4-terminal MOSFET's*,
  and with `t` grounded a 20-stage chain converges in 11 either way; BSIMSOI
  (7 terminals) — refused, 145 with stepping either way.
* **Recognizer verdicts:** HICUM/L2 (5 terminals) — *not a 3/4-terminal
  MOSFET's or BJT's*; BSIM4 `rbodymod=1` — refused on the live `sbulk` node;
  PSP103 `swnqs=1` — limited, 8 iterations against 256 with stepping;
  gate-resistance-only BSIM4 — 9 against 49; 5-stage `rdsmod=1` — 16
  against 21.
* **`optimize` on OSDI knobs:** `-param @nn1[w]` converges in 12 evaluations
  to the target to 7e-12; `-mparam @nmv[vth0]` runs and reports the bound
  it stopped on.
* **Bookkeeping around the limiter:** a subcircuit-wrapped chain is limited
  and named `n.x20.nn1` in the verbose line, 9 iterations; `reset` then `op`,
  `alterparam` + `reset`, and `remcirc` + `source` cycles all give 9 again with
  the same operating point; `optimize -dparam ll` on a `.param` used on the
  model card converges in 12 evaluations (the re-source path handles what
  F4's push path cannot); `.option savecurrents` produces `@nn1[i_d]`,
  `[i_g]`, `[i_s]`, `[i_b]` for an OSDI device; an internal node `nn1#di` can
  be `save`d, printed and `meas`ured in a transient.
* **Extremes, limiter on against off, 20-stage BSIM4 chain:** tolerances
  `reltol=1e-6 vntol=1e-9 abstol=1e-15` (9 against 43) and `reltol=1e-2
  vntol=1e-3` (8 against 41); `.temp -40` (9 against 43) and `125` (8 against
  69); supplies of 0.3 V (14 against 44 — the cold-start guess of vth0 + 0.1 V
  sits above the rail and is still a help), 0.6 V and 3 V (8 against 91); PMOS
  body biased separately at 1.5 V and forward at 0.9 V (9 against 47 / 35).
  Every pair agrees on the operating point to within the tolerances in force.
* **Small-signal after the slow op (F1 deck, 10 stages):** `ac` and `noise`
  results are identical to the last digit with the limiter on and off; only
  the operating point before them costs 153 iterations against 28.
* **F2 is solver-independent** (same mirrored state under `.option klu`) and
  PSP103 honours `v(q)=0.05` as well as 0.
* **History across commands:** `tran`, then `alter @nn[w]` on ten instances,
  then `tran` again gives the waveform of a fresh deck with that width to the
  last bit (the limiter's stored history is harmless); `altermod @nmv[type]=-1`
  after load is read live — the next `op` matches a fresh `type=-1` deck.
* **`alter`/`altermod` spellings:** `alter nn1 w=2u`, `alter @nn1[w] = 3*1u`,
  `altermod nmv vth0=0.6`, `altermod @nmv[vth0]=…` all take effect; plain
  model parameters survive the sampling commands.
* **Steering:** `.nodeset` values ≥ 0.1 V, a nodeset on the high side only,
  and the cross-coupled pair without access transistors are honoured by OSDI
  BSIM4; PSP103 honours 0 V; a nodeset on a nonexistent node warns and is
  ignored; internal nodes are addressable as `nn1#di` and accept a nodeset.
* **Sampling:** statistical `.param` on an instance line under `montecarlo`
  (40 % at a median threshold), and on a model card under `highsigma` and
  `wcd` (P(fail) 0.475, β = 6.0000 for a 6σ limit); the seed note and
  banners on an osdimc-only deck; `wcd` refuses `-spec` after `-metric`
  confusion with its usage line.
* **Bookkeeping:** `show nn1` lists the 31 instance parameters; `bsim4.osdi`
  from `VA-Models` exposes no operating-point variables, so `@nn1[ids]`
  being unavailable is the model, not the simulator; `pre_osdi` inside an
  `.include`; `.lib` corners; `m=4` on a subcircuit; duplicate-parameter and
  duplicate-model warnings; Ebers-Moll npn/pnp chains, diode-connected and
  gate-tied MOSFETs converge to the same point with fewer iterations under
  the limiter.

## Coverage, honestly

* F1 was found at the end of the hour; the length sweep, the `rgatemod`
  split, the KLU, `dc` and `tran` columns were measured, the mechanism was
  not — the paragraph that names it is a hypothesis.
* F2 was measured on one cell topology and one chain; the boundary at
  0.05–0.1 V was bracketed, not explained.
* The 32-descriptor cap in F7 was not exercised. VBIC, HICUM/L0, HICUM/L2
  and MEXTRAM were, and all are refused (O4), so the BJT branch has been
  measured only on the hand-written Ebers-Moll module; a Gummel-Poon VA
  module without a thermal node was not tried.
* No multi-threaded build was tested (the OSDI load loop is serial in this
  build).
* Every probe deck is under the session scratchpad `hunt3/`; the models are
  `bsim4.osdi`, `psp103.osdi`, `hicuml2.osdi` from `VA-Models`, and the
  hand-written `shmos.va`, `shmos3.va`, `ebmoll.va`, `smcres.va`, `nres.va`;
  `vbic.osdi`, `hicum0.osdi`, `ekv.osdi`, `bsimbulk.osdi`, `hisim2.osdi` and
  `bsimsoi.osdi` were compiled from `VA-Models` during the hour.
