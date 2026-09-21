# ngspice + OSDI bug hunt — the less-travelled analyses (`sens`, `pz`, `tf`, `disto`, `sp`), the instance interface and the analysis-end events

**Date:** 2026-09-21, one hour (07:10–08:10; the probes ran until 07:50, the write-up
interleaved from 07:28 on), at head `38ad1df9` (after E-671…E-680, the 2026-09-19 hunt's fixes).
**Binaries:** the repo's `OpenVAF-master-20260610/target/opt/openvaf-r` and
`ngspice-46/build/src/ngspice`, both built the evening before from the E-680 tree.
**Method:** ~80 decks and 18 small Verilog-A modules written for the hour, run through a
throw-away harness in the scratchpad (`hunt/h.py`, `p1.py … p56.py`), each OSDI result
checked against the built-in device that does the same thing in the same deck (resistor,
capacitor, inductor, diode, VCCS) or against the LRM text. Nothing was fixed; this is the
list. The ground chosen was what the two earlier ngspice+OSDI hunts (2026-09-04,
2026-09-10) said they had not reached: the small-signal analyses beyond `ac` and `noise`
(`tf`, `sens` in DC and AC, `pz`, `disto`, `sp`), a thermal port under every analysis,
the `m` multiplier under every analysis and against the LRM 6.3.6 rules, KLU against
Sparse on each of them, the instance interface (`alter`, `altermod`, `alterparam`,
`reset`, `remcirc`, `show`, `showmod`, `listing`, `.probe`, `savecurrents`, the
simulator-owned `m`/`temp`/`dtemp`/`dt` parameters, `.model`-card defaults), internal
nodes in `.ic`/`.nodeset`/`.save`/raw files/subcircuits, repeated analyses in one session
(delay history, event counters, `analysis()` and `final_step` per analysis).

## Summary

| # | finding | kind |
|---|---|---|
| [F1](#f1--a-sens-writes-every-parameter-it-perturbed-back-as-given-the-temperature-dependence-the-temperature-and-the-resistors-ac-value-are-frozen-afterwards) | after any `sens`, every instance parameter the sweep perturbed is written back **given**: a built-in resistor gets `tce=0` given and loses its `tc1`/`tc2` temperature dependence for the rest of the session (1.0 V at 60 °C where a fresh deck gives 1.33 V, even after `alter r2 temp=60`), an OSDI instance gets `temp` given and is pinned to the temperature of the moment (`set temp=80`, `.option temp`, `dc temp` no longer reach it; `alter n1 dtemp=10` is refused with "Instance temperature specified, dtemp ignored"); after an AC `sens` the resistor's `ac` alias is given and `alter r1 r=2k` followed by `ac` still reports the 1 kΩ response (0.4995 where 0.3327 is right, `op` is right); a second AC `sens` reports every resistor's sensitivity as −0; and an OSDI module's `$param_given(w)` turns true for a `w` the netlist never set, so a "derive from geometry if given" rule fires and a 1 kΩ device reads 2 kΩ; `reset` clears it all | wrong result, silent |
| [F2](#f2--final_step-never-fires-under-pz-tf-sens-disto-and-sp) | `@(final_step)` never fires in a `pz`, `tf`, `sens`, `disto` or `sp` analysis (the five analyses that do not call the OSDI final step); under `ac` and `noise` it fires but its variable assignments are discarded by design (E-412's snapshot), so a counter written there reads 0 afterwards | conformance |
| [F3](#f3--analysisac-is-0-at-the-operating-point-of-sp-pz-disto-tf-and-an-ac-sens) | at the operating point of an `sp`, `pz`, `disto`, `tf` or AC `sens` analysis the model reads `analysis("ac")` = 0 and `analysis("dc")` = 1, while the operating point of a plain `ac` reads `analysis("ac")` = 1 (E-53's owning-analysis rule); `@(initial_step("ac"))` does not fire under `sp` | conformance |
| [F4](#f4--the-lrms-badres-double-scaling-of-mfactor-compiles-with-no-diagnostic) | the LRM's own `badres` (`I(a,b) <+ V(a,b)/r * $mfactor`, LRM 6.3.6: "the simulator shall issue a warning … will generate an error") compiles silently; under `m=2` the current is scaled four times, under `m=3` nine | compiler diagnostic gap |
| [F5](#f5--the-simulator-owned-instance-parameters-on-a-model-card) | on a `.model` card `m=2` is refused with a warning that points to `_mfactor`, while `_mfactor=2`, `temp=60`, `dtemp=10` and `dt=10` are all honoured silently as instance defaults; `showmod` lists `_mfactor` but not `temp`/`dtemp`; `altermod mres m=3` is accepted and applied | inconsistency |
| [F6](#f6--a-nodeset-on-a-collapsed-internal-node-says-the-module-has-no-such-node) | `.nodeset v(n1#ai)=0.5` on an internal node the model collapsed (`rs=0`) is dropped with "n1 has no internal node 'ai'" — the node exists, it is collapsed; `.save v(n1#ai)` says "nothing of that name", and a save list that empties this way stops the analysis ("no data saved … analysis not run") | diagnostic |
| [F7](#f7--under-tran-uic-the-models-analysisic-branch-runs-once-and-its-contribution-is-never-solved) | under `tran … uic` an OSDI model that applies its initial condition the LRM way — `if (analysis("ic")) V(p,n) <+ ic;` — runs that branch exactly once at t = 0 (the strobe fires, `V(p,n)` reads 0) but the contribution is never solved: the node starts at 0 V and charges from there (3e-5 at the first point) where the built-in capacitor's `ic=0.5` starts at 0.5; without `uic` the same model starts at 0.5; a `.ic v(a)=0.5` on the node is the only way in | conformance gap |
| [F8](#f8--an-internal-node-cannot-be-the-output-of-sens-pz-tf-or-noise) | `sens v(n1#mid)`, `pz in 0 n1#mid 0 vol pz`, `tf v(n1#mid) vin` and `noise v(n1#mid) vin …` are all refused with "no such node: n1#mid" and the analysis is aborted, while `print v(n1#mid)`, `.save`, `.ic`, `.nodeset`, `meas` and the raw file all accept the node; the analysis cards resolve their node arguments before the device setup that creates the internal nodes | gap |
| [F9](#f9--probe-in3-on-a-four-terminal-osdi-device-saves-every-terminal-current-under-one-name) | `.probe i(n3)` on a four-terminal OSDI device inserts four zero-volt sources (`vcurr_n3:nn:1_0` … `:4_0`) and saves their currents as four vectors that all carry the name `n3:nn#branch` (1e-3, −1e-3, 0, 0), so a script reads only the first; a two-terminal device gets one `n1#branch` and a built-in resistor `r1#branch` | wrong output naming |
| [N1](#n1-not-osdi--a-netlist-node-spelled-instnode-merges-silently-with-the-devices-internal-node) | a netlist node spelled `n1#mid` merges silently with instance `n1`'s internal node `mid` (5 V forced onto it, 11.5 mA drawn); the built-in BJT's `q1#base` merges the same way (`vx#branch` = −1.2e35 A), no warning either way | ngspice namespace, silent |
| [N2](#n2-not-osdi--sens-over-a-current-source-prints-get-error-lines) | a `sens` in a deck with current sources prints `GET ERROR: Isource:I:i1 -> param r (27)` and `… td (28)` twice per source per sweep — the sweep asks the source for parameters it cannot return | diagnostic noise |

Dropped after checking: the double scaling itself in F4 (LRM 6.3.6 says the automatic
scaling cannot be disabled, so `badres` *is* scaled twice by the letter of the standard —
the defect is the missing diagnostic); the OSDI diode's `.tf` and `.disto` values differing
from the built-in diode's at the 1e-4 level (the physical-constant sets differ by 3e-5 in
kT/q); the one-point `noise … lin 1` producing no integrated-totals plot (built-in devices
do the same; there is nothing to integrate); the `.ic` without `uic` on an internal node
jumping at the first point (the forcing is released, the capacitor's voltage persists —
textbook SPICE); two OSDI inductors in parallel being a singular matrix at DC (ill-posed
for any solver, and ngspice's own inductors do the same).

## What was read and run

LRM sections read for the probes: 4.6.1 (`analysis()` and Table 4-22), 5.10.2
(`initial_step`/`final_step`: "the last time step of the analysis", any analysis), 6.3.6
(`$mfactor`: the four automatic-scaling rules, "shall issue a warning", the `badres` and
`parares` examples), 9.18 (the hierarchical system parameters). ngspice sources read:
`osdi/osdiload.c` (`get_simparams`, the analysis-name mapping at lines 583–598,
`OSDIfinalStep` at 1536 with the E-412 snapshot and the E-677 bias-point evaluation),
`osdi/osdiinit.c` (the device function table: no `DEVsens`, no `DEVfindBranch`; `.sens`
is finite-difference through `DEVparam`/`DEVtemperature`), `spicelib/analysis/cktsens.c`
(`sens_setp`, `sens_load`, `sens_temp`, the E-440 model save/restore), `span.c` (`MODESP`),
`pzan.c`, `tfanal.c`, and which analyses call `OSDIfinalStep` (`acan.c`, `dcop.c`,
`dctran.c`, `dctrcurv.c`, `noisean.c` — and no other).

Probe families: p1/p1t `.tf`, `.sens`, `.pz` on OSDI R, C, VCCS, diode and a two-port with
an internal node, each beside its built-in; p2 noise under `m=2` against two parallel
instances and a half-value resistor; p3 `.disto` diode against diode; p4 `.sp` two-port
against the same network in built-ins; p6 `.tf` of the VCCS, `.ic`/`.nodeset`/`.save`/`uic`
on `n1#mid`; p7/p15 `dc temp`, `.temp`, `set temp`, `option temp`, `tnom`, instance `temp`
and `dtemp`, `alter` of both; p8 every `alter`/`altermod` spelling, out-of-range values,
unknown names, `reset`; p9/p14 `$mfactor` read under `m`, `$param_given` after `alter`;
p10/p12 an `altermod` that changes node collapse, on KLU and Sparse; p11/p13 raw-file
write/load with internal-node, branch and subcircuit names; p16 delay history across
repeated `tran`, `alter`, `reset`; p17 array and string parameters through cards and
`alter`; p18 `listing`, `.option node`, `.probe`; p19 `m` through a subcircuit, brace and
quote expressions; p25 the gmin a model reads through gmin stepping; p28 OSDI `ddt`
against the built-in capacitor under trap, Gear 1, 2 and 4; p30 op→ac→tran→noise→tran→op
on a nonlinear circuit; p32 `remcirc`, re-`source`, `osdi -f`; p35 duplicated parameters
on a line and a card; p36 instance prefixes that collide with built-in letters,
`savecurrents`, `alterparam`+`reset`; p37 `.ic`/`.nodeset`/`.save` on collapsed and
nonexistent internal nodes; p40 the LRM 6.3.6 rules (flow probe divided by `m`,
potential-branch noise divided by `m`, a potential-contribution inductor under `m`); p41
an electrothermal module under op, ac, pz, noise, tran, sens, tf and sp; p42
`analysis()` and `initial_step` under every analysis; p43 the simulator-owned vectors
under a temperature sweep and `ac`; p44 name collisions and odd instance names; p45/p45b
the simulator-owned parameters on `.model` cards; p46 the sensitivity thread (twelve
decks); p48 KLU against Sparse on op, ac, pz, noise, disto, tf, sens and sp; p49 event
counters per analysis; p51 current vectors under `m`; p52 noise names through a
subcircuit with `m`; p55 `sens` naming of OSDI model parameters, `tran` after `sens`,
`alter` of a model parameter; p56–p61 temperature and temperature dependence after `sens`
(OSDI and built-in resistors and diodes, `.option temp`, `dc temp`, `alter dtemp`, an explicit
`tce=0`); p62 `m` under disto, pz, tf, sp; p63 the `analysis("ic")` initial condition with
and without `uic`; p64 `show all`/`showmod all`; p65 the current vectors under `ac`; p66/p67 current-type
outputs and inputs, intermodulation, differential noise; p68/p70 `$param_given` after `sens`
(instance- and model-scope); p73 `option` changes between runs; p79 an internal node as the
output of `sens`/`pz`/`tf`/`noise`; p84/p85/p89 `.probe` on a four-terminal device, on a BJT and on the electrothermal device;
p86 `noise` after `sens`; p88 card defaults after `sens`; p97–p99 `.osdi` paths with spaces and
relative paths; p100 `sens` under KLU on the collapse model, `dtemp` after `sens`.

## F1 — a `sens` writes every parameter it perturbed back as given; the temperature dependence, the temperature and the resistor's `ac` value are frozen afterwards

ngspice's `.sens` is finite-difference: for each instance parameter it reads the value,
writes a perturbed one through `DEVparam`, re-runs the temperature update and the solve,
and then writes the original back through the same `DEVparam` ("Put the parameter back,
exactly as the normal path does", `cktsens.c` ~830, `sens_setp`). A `DEVparam` write is
what marks a parameter *given*. So after the sweep every parameter it touched — whether
the netlist ever set it or not — is given, at whatever the read-back returned. Which
parameter that breaks depends on the device. Four consequences, each measured on an OSDI
resistor with `tc1=0.01` beside a built-in resistor with the same `tc1`, 1 mA each:

**The built-in resistor loses its temperature dependence.** The sweep perturbs `tce` (it
prints an `r2_tce` sensitivity) and writes 0 back as given; ngspice's resistor uses the
exponential form `1.01^(tce·ΔT)` whenever `tce` is given, so the factor is 1 at every
temperature from then on:

```
.option temp=60
op                          v(a) = 1.33   v(b) = 1.33        (both at 60 °C)
sens v(b)
op                          v(a) = 1.33   v(b) = 1.0         <- r2 at 27 °C
print @r2[temp] @r2[tc1]    60            0.01               (nothing looks changed)
show r2                     resistance 1000 ... conductance 0.001
alter r2 temp=60 ; op       v(b) = 1.0                       (temperature cannot bring it back)
reset ; op                  v(b) = 1.33
r2 b 0 1k tc1=0.01 tce=0    v(b) = 1.0 at 60 °C in a fresh deck   (the same rule, written out)
```

`restemp.c` line 116: `if (here->REStceGiven || model->REStceGiven)` selects the exponential
form; the sweep's write-back of `tce` is what sets that flag.

**The OSDI instance is pinned to the temperature of the moment.** The sweep perturbs the
instance `temp` and writes its effective value back as given — the instance-temperature
override that beats `.option temp`/`set temp` ("Instance temperature specified, dtemp
ignored" is the same mechanism, and it is printed three times during the sweep for the
built-in resistor while `dtemp` is perturbed after `temp` became given):

```
(27 °C deck)  sens v(a) ; sens v(b) ; set temp=60 ; op    v(a) = 1.0    v(b) = 1.0    (fresh: 1.33, 1.33)
              dc temp 0 40 40 after a sens                  v(a) = 1.0, 1.0  (fresh: 0.73, 1.13)
              alter n1 dtemp=10 after a sens                "n1: Instance temperature specified, dtemp ignored"
(60 °C deck)  sens v(b) ; set temp=80 ; op                  v(a) = 1.33   (fresh: 1.53)
diodes:       sens ; set temp=60 ; op   built-in d1 0.6294 (fresh 0.5718), OSDI n2 0.6294 (fresh 0.6932)
dtemp=20 on both lines:  op 1.2, 1.2 ; sens ; op 1.0, 1.0 ; alter n1 dtemp=40 -> "Instance temperature specified, dtemp ignored"
```

The `dtemp` line shows what the write-back pins the OSDI instance to: the circuit
temperature without the instance's own `dtemp` offset (27 °C, not 47), so a `dtemp` the
netlist did set is lost as well. Every device with a `temp` instance parameter is pinned this way — the built-in diode as
much as the OSDI one. The OSDI parameter path has its own `temp_given` flag and takes it
the same way; the module's own parameters are not affected (`n3_r` stays right below — an OSDI parameter
has no "given-changes-the-formula" alias like `tce` or `ac`).

**The noise analysis moves with it.** `noise v(a) vin` on a 1 kΩ `tc1=0.01` resistor at
`.option temp=60`: `onoise_total` 1.0248e-7 before a `sens`, 9.591e-8 after it (the resistor
is now the 27 °C one), 1.0248e-7 again after `reset` (p86).

**An OSDI model's `$param_given` rules flip.** The write-back marks the module's own
instance parameters given as well, so a compact model's "if the geometry was given, derive
the value; else use the explicit one" rule takes the other branch for the rest of the
session:

```verilog
reff = $param_given(w) ? rsh * (w / 1u) * 2.0 : r;    // w never set on the line; r=1k
```

```
op                  v(a) = 1.0        ($param_given(w) = 0, reff = r)
sens v(a)
op                  v(a) = 2.0        <- $param_given(w) = 1 now, reff = rsh*w/1u*2
reset ; op          v(a) = 1.0
```

(p68a/p68b; the `@n1[wg]` opvar reads 0, 1, 1, 0 across the same sequence, and an `alter`
of another parameter does not clear it.) That is the form of F1 that reaches a real
compact model — BSIM- and PSP-style geometry rules are exactly this shape. Model-scope
parameters are safe: the same rule on a model-scope `w` reads `wg` = 0 after a DC and an
AC `sens` (p70), because E-440 copies the model struct back byte for byte after each
perturbation; the instance struct and its given flags get no such copy.

**The built-in resistor's AC value.** An AC `sens` also perturbs the resistor's `ac`
parameter (`r1_ac` appears in the output) and writes back what the ask returned — for an
unset `ac`, the DC resistance. From then on `RESacResist` is given and the AC load uses it
instead of `r`:

```
ac lin 1 10meg 10meg ; print v(a)            0.4995,-0.0157     (r1 = 1k)
sens v(a) ac lin 1 10meg 10meg               r1 = -2.50e-4       (right)
show r1                                      ac 1000             (now given)
alter r1 r=2k ; ac ... ; print v(a)          0.4995,-0.0157     <- still the 1k response
op ; print v(a)                              0.3333              (DC follows r)
reset ; alter r1 r=2k ; ac ... ; print v(a)  0.3327,-0.0139     (correct)
```

**A second AC `sens`.** The same freeze makes the resistor's sensitivity vanish: in a deck
with R, C, L and an OSDI resistor, the second `sens v(b) ac` in a session prints
`r1 = -0, r2 = -0` while `c1`, `l1` and `n3_r` are unchanged and right; a third is the
same; `reset` between them restores the values; an `op` between them does not; two DC
`sens` in a row are fine for `r` (the DC sweep does not touch `ac`), and a built-in-only
deck shows the same (p46f), so this is ngspice core.

What this means: any deck that runs a `sens` and then anything else — a temperature
sweep, an `alter` followed by `ac`, a second sensitivity, or simply the next `op` in a
deck with `.option temp` — silently gets a different circuit for those parameters, and
`show`/`@r2[temp]`/`@r2[tc1]` all print the original values. `cktsens.c` already has the
E-440 save/restore for *model* parameters (a byte copy put back after each perturbation,
which fixed the same disease for `altermod`-visible values); the instance side needs the
same byte-level restore (instance struct and, for OSDI, its given-flag block), or the
write-back must not set the given flags.

## F2 — `final_step` never fires under `pz`, `tf`, `sens`, `disto` and `sp`

A module with `@(initial_step) $strobe("INIT")` and `@(final_step) begin cf = cf + 1;
$strobe("FINAL cf=%d", cf); end`, `cf` an opvar:

| analysis | strobes | `@n1[cf]` afterwards |
|---|---|---|
| `op`, `dc`, `tran` | INIT, FINAL cf=1 | 1 |
| `ac`, `noise` | INIT, FINAL cf=1 | **0** |
| `pz`, `tf`, `disto`, `sp` | INIT only | 0 |
| `sens v(a)` (DC) | INIT ×9 (one per perturbation) | 0 |

`OSDIfinalStep` is called from `acan.c`, `dcop.c`, `dctran.c`, `dctrcurv.c` and
`noisean.c` and nowhere else; `pzan.c`, `tfanal.c`, `cktsens.c`, `disto.c` and `span.c`
end without it, so LRM 5.10.2's "the last time step of the analysis" event does not exist
for those five. The `ac`/`noise` row is different: the event fires (E-677 evaluates it at
the captured bias point) but E-412's snapshot deliberately restores the instance
afterwards so the small-signal solution never leaks into it — the strobe is real, the
assignment is discarded. That is a documented design choice, recorded here because a
model that counts or files something in `final_step` sees 0 where the strobe said 1. The
`sens` row also shows `initial_step` firing once per perturbation, with the instance
re-set-up each time (the counter restarts at 1): a model with a side effect in
`initial_step` (a file header, a `$fopen`) performs it nine times per two-terminal device.

## F3 — `analysis("ac")` is 0 at the operating point of `sp`, `pz`, `disto`, `tf` and an AC `sens`

Opvars `a_ac = analysis("ac")`, `a_dc = analysis("dc")`, `a_static`, `a_noise`, read after
each analysis (the last evaluation is the analysis's operating point, since none of these
re-evaluate the analog block during the frequency sweep):

| analysis | ac | dc | static | noise |
|---|---|---|---|---|
| `op`, `dc` | 0 | 1 | 1 | 0 |
| `ac` | **1** | 0 | 1 | 0 |
| `noise` | 0 | 0 | 1 | 1 |
| `pz`, `tf`, `disto`, `sens … ac`, `sp` | **0** | **1** | 1 | 0 |

E-53 made the operating point of an `ac` job report `analysis("ac")` = 1 ("it reports the
owning analysis", `osdiload.c` line ~660), and the LRM's Table 4-22 agrees for AC. The
mapping (`osdiload.c` 583–598) keys on `MODEAC`/`MODEACNOISE` only; `span.c` runs its
operating point under `MODEDCOP | MODEINITSMSIG` and its sweep under its own `MODESP`,
`pzan.c`/`tfanal.c`/`disto.c` likewise never set `MODEAC`. So a model that branches on
`analysis("ac")` — to choose a small-signal capacitance formulation, to enable an
`ac_stim`-style source, or in an `@(initial_step("ac"))` block — takes its DC branch under
the four other small-signal analyses. `sp` is the one that matters most: it is an AC sweep
with ports, and the LRM has no separate name for it.

## F4 — the LRM's `badres` double scaling of `$mfactor` compiles with no diagnostic

```verilog
module mfres(p, n); ...
  (* desc="mfactor seen" *) real mf;
  analog begin
    mf = $mfactor;
    I(p, n) <+ mf * V(p, n) / r;      // the LRM's badres, LRM 6.3.6: "// ERROR"
  end
```

compiles with `Finished building` and no warning. On ngspice with a 1 mA source into
`r=1k`: `m=2` → 0.25 V (four times the conductance: the explicit `mf` = 2 and the automatic
flow scaling), `m=3` → 2000/9 V. The double scaling is what LRM 6.3.6 prescribes (the
automatic scaling cannot be disabled), and the flows under `m` were otherwise right in
every probe (flow probe divided by `m`, potential-branch noise power divided by `m`, a
potential-contribution inductor halved, noise power on flow branches doubled — p40). The
gap is the diagnostic: "The simulator shall issue a warning if it detects a misuse of the
$mfactor in a manner that would result in double-scaling … The simulator will generate an
error for this module." The compiler already tracks `$mfactor` reads (`_mfactor` is a
hidden parameter, `hir_lower/src/state.rs`); a flow contribution whose value depends on it
multiplicatively is detectable at lower time. The `parares` form (`$mfactor` only in a
condition) must stay silent.

## F5 — the simulator-owned instance parameters on a `.model` card

`.model` cards accept instance-parameter defaults (E-xxx's "instance defaults on this card"
in `showmod`). For the five parameters ngspice itself owns:

| on the card | effect | `showmod` |
|---|---|---|
| `m=2` | refused: "`m` on a .model card is ignored; … write it on the instance line (or as `_mfactor` on the model card)" | — |
| `_mfactor=2` | honoured (0.5 V) | listed |
| `temp=60` | honoured silently (1.33 V on the `tc1` model) | **not listed** |
| `dtemp=10`, `dt=10` | honoured silently (1.10 V) | **not listed** |
| `altermod mt temp=60`, `altermod mt dtemp=10` | accepted as instance defaults ("'temp' is an instance parameter; 60 is now the default of model mt") | **listed** (`temp 60`, `dtemp 10`) |
| `_mfactor=2` on the card and `m=3` on the instance | the instance value wins (0.333 V, the same as `m=3` alone) | — |
| `altermod mres m=3` | accepted: "'m' is an instance parameter; 3 is now the default of model mres" → 0.333 V | — |

So `m` is the one spelling the card refuses while the command form accepts it, and the
temperature defaults a card sets are the ones `showmod` hides — the same defaults set by
`altermod` are listed, so the card path is the one that skips the bookkeeping. A user who reads the `m`
warning and writes `_mfactor` gets a default `showmod` shows; one who writes `temp=` gets
one it does not.

## F6 — a `.nodeset` on a collapsed internal node says the module has no such node

`colres` has an internal node `ai` collapsed to `a` when `rs=0` (its default):

```
.nodeset v(n1#ai)=0.5      Warning : Nodeset on non-existent node - n1#ai, ignored
                              (n1 has no internal node 'ai')
.ic v(n1#zz)=0.5           Warning : IC on non-existent node - n1#zz, ignored
                              (n1 has no internal node 'zz')          <- right
.save v(n1#ai) v(n1#zz)    Warning: save 'n1#ai': nothing of that name is in this analysis
                           Error: no data saved for D.C. Operating point analysis; analysis not run
```

The `zz` line is right; the `ai` line gives the wrong reason — the module declares `ai`,
the model collapsed it, and the value could be applied to the node it collapsed into (or
the message could say "collapsed into 'a' by the model"). The third line is a consequence
worth its own note: when every entry of a `.save` list is dropped this way, the analysis
does not run at all, with "no data saved" as the only explanation.

## F7 — under `tran uic` the model's `analysis("ic")` branch runs once and its contribution is never solved

```verilog
if (analysis("ic")) begin nic = nic + 1; $strobe("ICEVAL nic=%d V=%g t=%g", nic, V(p, n), $abstime); V(p, n) <+ ic; end
else I(p, n) <+ ddt(c * V(p, n));
```

with `ic=0.5`, `c=1n`, driven through 1 kΩ from 1 V, beside a built-in `c2 … ic=0.5`:

| run | strobes | `v(a)` first points | built-in `v(b)` |
|---|---|---|---|
| `tran 0.1u 1u uic` | `ICEVAL nic=1 V=0 t=0` (once) | 3.0e-5, 6.0e-5, … 0.181 at 0.2 µs (charging from 0) | 0.5005, … 0.59 at 0.2 µs (from 0.5) |
| `tran 0.1u 1u` (no `uic`) | the op's evaluations | 0.5 at t = 0, then charging from 0.5 | 1.0 (SPICE ignores `ic=` without `uic`) |
| `uic` + `.ic v(a)=0.5` | `ICEVAL nic=1 V=0.5 t=0` | 0.50002, … (from 0.5) | — |

Without `uic` the LRM path works: the transient's operating point runs with
`analysis("ic")` true (p42a: `ic=1` under `tran`), the model's potential contribution
forces 0.5 V, and the transient starts from it. With `uic` SPICE skips the operating point:
ngspice evaluates the devices once under `MODEUIC | MODEINITTRAN` so that the built-in
capacitor and inductor can *write their initial state directly* (`CAPinitCond` into the
state vector), and then integrates. The OSDI loader reports `analysis("ic")` = 1 for that
one evaluation — the model takes its ic branch — but a Verilog-A model has no way to write
the state vector; its `V(p,n) <+ ic` is a stamp that this phase never solves, so the
capacitor's history starts at V = 0 and the `ic` parameter is dead under `uic`. The
built-in `ic=` works because it bypasses the equations. What a model author would expect,
by LRM 4.6.1 ("ic: the initial-condition analysis that precedes a transient"), is that the
ic-phase contributions are solved once, `uic` or not; the fix belongs in the transient's
uic path (one Newton solve of the ic-phase system before the first step, or a documented
rule that OSDI initial conditions need `.ic`).

## F8 — an internal node cannot be the output of `sens`, `pz`, `tf` or `noise`

```
sens v(n1#mid)                       Error: no such node: n1#mid   in   .sens v(n1#mid)   sens simulation(s) aborted
pz in 0 n1#mid 0 vol pz              Error: no such node: n1#mid   pz simulation(s) aborted
tf v(n1#mid) vin                     Error: no such node: n1#mid   tf simulation(s) aborted
noise v(n1#mid) vin lin 2 1k 2k      Error: no such node: n1#mid   noise simulation(s) aborted
print v(n1#mid) ; .save v(n1#mid) ; .ic v(n1#mid)=0.9 ; meas tran x FIND v(n1#mid) AT=2u     all work (p6, p11)
```

The four analyses resolve their node arguments when the card is parsed, against the
netlist's node table, before the device setup that creates `n1#mid`; the commands that work
resolve names later (at save time or against the finished plot). Built-in internal nodes
have the same limit (`sens v(q1#base)` on a BJT with `rb`, p85). An OSDI compact model's
interesting nodes are often internal (the intrinsic drain of a MOSFET, the junction
temperature of an electrothermal device), so a `noise` or `tf` referred to one has to go
through an external copy of the node.

## F9 — `.probe i(n3)` on a four-terminal OSDI device saves every terminal current under one name

```
n3 0 d a 0 mvccs gm=2m
.probe i(n3)
op ; print all
    n3:nn#branch = 1.000000e-03
    n3:nn#branch = -1.00000e-03
    n3:nn#branch = 0.000000e+00
    n3:nn#branch = 0.000000e+00
    r1#branch = 5.000000e-04
listing:  n3 probe_int_0_n3_1 probe_int_d_n3_2 probe_int_a_n3_3 probe_int_0_n3_4 mvccs gm=2m
          vcurr_n3:nn:4_0 0 probe_int_0_n3_4 0
          vcurr_n3:nn:3_a a probe_int_a_n3_3 0   ...
```

The inserted sources are distinct (`vcurr_n3:nn:1_0` … `:4_0`) but the saved vectors are
all `n3:nn#branch`: the probe code's terminal label for an OSDI device is the fixed `nn`
instead of the terminal's name (`p`, `n`, `cp`, `cn` — the descriptor has them, and the
"terminals not connected" warning already prints them). Four vectors with one name are
indistinguishable to `print`, `meas` and `wrdata`. The three-terminal electrothermal
device gets three `n1:nn#branch` (−4.94e-3, 4.94e-3, −2.50e-2 — the last is the thermal
flow, the power, so the zero-volt source in the thermal branch measures correctly; p89).
A two-terminal OSDI device (p18) gets the plain `n1#branch`, which is fine, and a BJT's
probe is per terminal (`q1:b#branch`, `q1:c#branch`, `q1:e#branch`, p85). The
workaround exists already: `.option savecurrents` gives the same currents as per-terminal
opvars named after the terminals (`@n3[i_p]`, `@n3[i_n]`, `@n3[i_cp]`, `@n3[i_cn]`, p91),
which is where the probe's labels should come from.

## N1 (not OSDI) — a netlist node spelled `inst#node` merges silently with the device's internal node

```
n1 in out mint r1=1k r2=1k c=1n      (internal node n1#mid)
vx n1#mid 0 dc 5
rx n1#mid 0 1k
op:  v(out) = 2.5   v(n1#mid) = 5   i(vx) = -11.5 mA
```

The 5 V source is connected to the model's internal node: `out` sits at 2.5 V (the divider
from the forced 5 V), the source delivers the internal current. The built-in BJT with
`rb=100` and a netlist node `q1#base` does the same, with `vx#branch = -1.2e35`. ngspice
binds internal nodes by name through `CKTmkVolt`, so the `#` namespace is not reserved and
nothing warns. Rare in practice; recorded because the failure is silent and the OSDI
naming convention (`inst#node`) is the same one a user would type to probe the node.

## N2 (not OSDI) — `sens` over a current source prints `GET ERROR` lines

```
GET ERROR: Isource:I:i2 -> param r (27)
GET ERROR: Isource:I:i2 -> param td (28)
```

twice per current source per `sens` (24 lines for two sources and two sweeps). The
sensitivity walk asks every instance parameter through `DEVask`; the current source's `r`
and `td` (the PWL repeat and delay) are write-only there and the ask reports an error the
sweep prints and ignores. Harmless, but it fills the log of any `sens` run.

## What held

Everything below was measured on this tree and matched the built-in device or the
theory, both solvers unless noted:

- `.tf` (gain, input and output impedance), `.sens` DC (values equal to the built-in's
  finite differences), `.pz` (poles and zeros of an RC and an RL network, with and
  without an internal node), `.disto` (HD3 of the diode), `.sp` (S and Y of a two-port),
  `.noise` (thermal and flicker under `m=2` against two parallel instances, rms sums
  equal), all on OSDI devices beside built-ins (p1, p1t, p3, p4, p9b, p46a, p46d).
- The LRM 6.3.6 rules under `m`: flow probe divided by `m` (`V(p,n) <+ I(p,n)*r` reads
  0.5 V under `m=2`), potential-branch noise power divided by `m`, a
  potential-contribution inductor under `m=2` equal to two in parallel and to a built-in
  of half value, `$param_given` after `alter`, `$mfactor` read equal to `m` (p14, p40).
- The electrothermal module (thermal port, `Pwr`/`Temp`) under op, ac, pz, noise, tran,
  sens, tf and sp, including the thermal pole at 1/(rt·ct) (p41).
- `m=2` equal to two parallel instances under `disto` (HD3), `pz`, `tf` and `sp`, as it
  already was under op, ac and noise (p62, p9b, p2a).
- `.tf` with a current output (`tf i(vm) vin`) and with a current-source input
  (`tf v(c) iin`), `sens i(vm)`, `pz … cur`, `disto` with `f2overf1` (intermodulation),
  `noise v(c,d)` across an OSDI two-port referred to a current source — each equal to the
  built-in path beside it (p66, p67).
- A `.model` card's instance defaults survive a `sens`: an instance whose `m` comes from
  the card's `_mfactor=2` still follows a later `altermod mt2 _mfactor=4` ("1 instance
  follows it, 0 keep their own value"), so the F1 write-back does not mark `_mfactor`
  given on the OSDI side; `temp` and the module's own parameters are the ones it marks (p88).
- `option gmin=… reltol=… abstol=… tnom=…` and `set tnom=…` between runs reach the
  `$simparam` values a model reads (p73).
- `pre_osdi "dir with space/my model.osdi"` and the single-quoted form both load; a
  relative `pre_osdi basics.osdi` resolves next to the deck when ngspice runs from another
  directory (p97, p98); the non-hoisted `osdi basics.osdi` resolves the same way and
  `osdi -f` reloads it (p99).
- `sens` under `.option klu` on the collapse-changing model: the collapsing parameter
  gets the existing warning ("changes the model's node collapse when perturbed … reported
  as 0") and its sensitivity is right once `altermod` opens the node (p100a).
- `show all`/`showmod all` with `: r`/`: is` filters list OSDI and built-in devices side
  by side (p64).
- KLU equal to Sparse on op, ac, pz, noise, disto, tf and sp of the same OSDI deck, and
  on a loop that toggles node collapse through `altermod` (p12, p48).
- OSDI `ddt` against the built-in capacitor under trap, Gear 1, 2 and 4: max difference
  5.6e-16 (p28).
- Temperature: `dc temp`, `.temp`, `set temp`, `option temp`, instance `temp`, `dtemp`,
  `alter` of both, "Instance temperature specified, dtemp ignored" — identical to the
  built-in resistor (p7, p15); the gmin a model reads is the option value throughout
  gmin stepping (p25).
- The instance interface: every `alter`/`altermod` spelling, `reset`, `alterparam` +
  `reset`, `remcirc` + re-`source` ("already loaded; skipping"), `osdi -f` refusing the
  stale circuit until `reset`, an `alter` of a model parameter refused with the
  `altermod` spelling, duplicated parameters warned on both lines and cards, `listing`,
  `.probe i(n1)`, `savecurrents` (`@n1[i]`, `@n1[i_p]`, `@n1[i_n]`), `m` through a
  subcircuit, brace and quote expressions on OSDI lines (p8, p18, p19, p32, p35, p36, p55).
- Internal nodes: `.ic` with `uic`, `.nodeset`, `.save`, raw write/load (`v(n1#mid)` and
  `n1#mid` both readable after `load`), `meas` on them, hierarchical `v(x1.n1#mid)` and
  `@x1.n1[r1]`, instance names `n#1` and `n.2` (p6, p11, p13, p44b, p44c).
- XSPICE `adc_bridge`/`dac_bridge` around OSDI resistors and a capacitor (code models
  loaded through a `.spiceinit`, since the harness has no spinit): the bridged pulse
  arrives and the OSDI RC charges from it (p5c).
- Delay history: a second `tran`, one after `alter td=`, one after `reset` — each starts
  clean (p16c). The op→ac→tran→noise→tran→op chain on a nonlinear circuit: every
  operating point equal (p30). `tran` after `sens`: equal to a fresh op (p55).

## Smaller notes (not pursued)

- `alter n1 r=-1` is stored (`show n1` prints −1) and refused only at the next analysis
  ("out of bounds … OSDI setup_instance", the analysis aborted); `print v(a)` then shows
  the previous plot's value without a note. The netlist form is refused at the same
  point. The built-in diode with `area=-1` has no check at all (NaN operating point).
- An `op` plot with a `.save` list takes the first saved vector as its `[default scale]`,
  and the raw-file writer leaves that one vector's name unwrapped (`n1#mid` beside
  `v(out)`, `out` beside `v(in)` in a built-in-only deck); after `load` the names differ
  from the `tran` plot's (`v(n1#mid)`). Generic ngspice.
- `show n#1` finds nothing for an instance named `n#1` although the instance runs.
- The whole-array spelling `w=[1 1 1]` on an instance line and `k=[1 1]` on a card are
  still refused ("unknown parameter (w)", "unrecognized parameter (k) … ([1)"); the
  per-element form works (2026-09-04 hunt F3, downgraded there).
- `analysis()` opvars and the simulator-owned vectors (`@n1[temp]`, `@n1[m]`, `@n1[i]`)
  printed after a sweep without a `.save` are the current scalar, one point long — the
  harness lesson of the previous hunt, unchanged.
- A `sens` to a parameter whose *given-ness* changes the model's formula is the branch
  jump divided by the perturbation, not a derivative: `n1:w = 5.0e11` for the model-scope
  `$param_given(w)` rule above (p70). Inherent to finite differences; worth a warning
  when the perturbed parameter was not given.
- Under `ac`, `.save @n1[i]` on an OSDI device produces a complex vector that holds the
  operating-point current at every frequency (5e-4, j0 at 100 kHz and 1 MHz alike); a
  built-in resistor's `@r1[i]` is "not available" in an `ac` plot and a capacitor's
  `@c1[i]` likewise. Neither is the AC current; the OSDI one looks like one.
- The `_mfactor` parameter appears beside `m` in `show` (both 2 under `m=2`) and as
  `n1__mfactor` (double underscore) in `sens` output.
- `r1 a 0 mres r=1k` (a built-in prefix on an OSDI model) is a hard error, "model type
  mismatch" then "incorrect model type for resistor"; the message does not say what
  `mres` is.

## Coverage, honestly

One hour, ~80 decks, all foreground, on the E-680 binaries. Not reached: `.pss`/harmonic
balance and the quasi-periodic family (their own suites exist), the F1 write-back traced through `sens_setp` into each device's `DEVparam` (the `tce`
and `temp` explanations rest on the measurements, on `restemp.c`'s rule and on `reset`
clearing them), and the F1 write-back's full parameter list (`tce`, `temp`, `dtemp`, `ac` and the module's
own parameters were traced; `_mfactor` was shown not to be affected). F1 is the one finding here that
silently changes an answer in an ordinary flow (`sens`, then anything), and it earned the
twelve decks it took.
