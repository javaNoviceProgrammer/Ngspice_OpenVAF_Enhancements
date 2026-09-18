# 3 · Simulating with ngspice

This chapter covers the simulator side: how compiled Verilog-A devices
participate in ngspice's analyses, how to reach their parameters and
internal variables, and the statistical / RF workflows built on top.

The single best companion to this chapter is
[`examples/analyses_examples/`](../../examples/analyses_examples/) — a
tutorial folder with one standalone, commented deck per analysis, each
stating the numbers it expects, plus committed PNG plots. When a recipe
below feels terse, the corresponding deck there is the full worked example.

## 3.1 Devices, model cards, instance lines

An OSDI device instance is an `N`-letter element referencing a `.model`
card whose type name is the Verilog-A **module name**:

```spice
n1 in out mymod          ; instance (ports in declaration order)
.model mymod myres(r=1k) ; model card: module `myres`, parameter r
```

- **Model-card parameters** are the default place to set parameters.
- **Instance-line parameters** (`n1 in out mymod r=2k`) work for parameters
  the model marks `(* type="instance" *)` — plus the built-in `m=<mult>`
  device multiplicity, which correctly scales currents, charges, and noise
  (`$mfactor` in the model's own source). A **negative** `m` is warned and
  ignored on every route — `alter` included, which used to apply it
  silently, flipping the device's current and making `.noise` spectra NaN
  through the compiled `sqrt(m)` factor — while `m=0` stays the silent
  "disable this instance" idiom, exactly as for built-ins.
- `pre_osdi` loads **openvaf-reloaded objects only** (OSDI ≥ 0.7).
  Original-OpenVAF v0.3 objects are rejected with a recompile message —
  the in-repo ABI diverged, and the old acceptance path misread them
  (wrong metadata in DC, a transient segfault). See `README_OSDI.md` for
  the layer's deliberate bounds.
- Multiple instances of one model card get independent state and
  independent per-instance values of position/multiplicity parameters.
- **A netlist number is the double its text names** (E-643). A card value
  at a declared bound — `vmax=1.2` against `from [0:1.2]`, `l=0.96u`
  against `[0.96u:10u)` — is accepted: ngspice's parsers used to compute
  `mantissa × 10^exponent` and land an ulp above or below the value the
  compiler read from the same spelling (`1.2` was 1.2000000000000002), so
  the model's own range check refused it. The netlist parser, `alter`/
  `let`/`print`, and `.param` all read the same spelling to the same
  double now. One visible consequence: `0e400` is zero, not "not a
  representable number".
- **A paramset's own parameters are instance parameters** (E-644): one
  `.model rsil rsil` card per device kind, the geometry on the instance
  line — `n1 a b rsil l=0.5u w=0.5u mm_ok=0` — as any SPICE device
  library is written; the card's values are the instances' defaults. An
  overloaded family (LRM 6.4.2) is selected **per instance** from the
  card's and the instance's values together: the first instance binds the
  card to its member, and an instance that needs another member gets a
  clone of the card, `<card>.<member>` (`rsil.rsil__2`), made once and
  announced with a note; `show` names it as the instance's model.

## 3.2 Reading data out of a model

Verilog-A variables carrying a `(* desc="…" *)` attribute are
**operating-point variables**, visible wherever ngspice vectors are:

```spice
print @n1[ids]                     ; after op
.save @n1[ids] @n1[region]        ; per-point recording in tran/dc/ac
.meas tran ipk MAX @n1[ids]       ; measurements over opvar vectors
.meas tran tcross WHEN @n1[ids]=0.5m RISE=1
show n1                            ; all opvars incl. string variables
```

Real *and integer* variables record per point; a variable without `desc` is
deliberately not exposed (clean "no such parameter" error). String opvars
display via `show` but cannot become vectors (vectors are numeric).
Pinned in [`examples/opvar_examples/`](../../examples/opvar_examples/).

A model card's parameter can be saved per point as well as printed:
`.save @mm[s]` (or `save @mm[s]` in the control block) records it alongside the
node vectors, and a name the model does not have is warned about at `save`
time (E-558; before that a model-card name was refused as *no such device*
while `print @mm[s]` read it).

Two current readings of one device differ by the multiplier: the branch
unknown of a voltage contribution, the vector `n1#flow(p,n)` (typed
`current`, and a name that parses unquoted in `let`/`print` — E-634), is the
current of *one* unit, while the terminal current `@n1[i_p]` (E-394) is the
total, `m` times it; with `m=1` they agree.

## 3.3 Parameter access, `alter`, and sweeps

Parameters are readable and writable from the control language:

```spice
print @n1[r]          ; read (instance param, (* type="instance" *))
alter @n1[r] = 2k     ; change + re-run setup on the next analysis
altermod @mm[r] = 2k  ; same for a model-card parameter
```

A parameter the compiler resolves *per instance* — declared
`(* type="instance" *)`, or promoted because its default reads an instance
parameter (E-546, lint L028) — is instance-level however the card spells it:
`altermod mm l=10` is refused with a message that says so and points at the two
routes, `alter @n1[l]=10` per instance and `l=10` on the `.model` card, where it
is the instances' default; `print @mm[l]` and `dc @mm[l] …` say the same
(2026-09-05 hunt, F15; the refusal used to read *model 'mm' has no parameter l*
after a stray MOS width probe).

**`.dc` sweeps over device parameters** work for OSDI (and built-in)
devices — the sweep refreshes the device per point exactly as `alter`
would, restores the original value afterwards, and nests with other sweep
variables. Since E-534 the whole `sweep`/`altermod` parameter surface has a
dc arm — **model parameters** (`@mm[p]`, the dotted subcircuit spelling
`@x1.rmod[p]`), the **wildcards** `@*[p]` / `@#*[p]` / `@*:leaf[p]` — and
every knob kind takes the keyword scales `lin|dec|oct N start stop`
(generated exactly as the `sweep` command generates them), while the classic
triple is untouched:

```spice
.dc @n1[r] 500 1500 100            ; sweep an OSDI instance parameter
.dc @n1[r] 500 1500 500 vin 0 2 1  ; nested with a source sweep
.dc @mm[g] lin 101 1m 10m          ; a MODEL parameter, 101 exact points
.dc @*:rmod[rsh] dec 5 10 1k       ; every flattened copy of rmod, log grid
.dc temp -40 125 5                  ; temperature sweep; $temperature
                                    ; tracks each point (°C in the deck,
                                    ; K inside the model)
```

Values are written through the machine path (an `osdimc` nominal is never
recentered, E-531) and restored afterwards. Topology stays honest both ways:
an OSDI model parameter that moves a node collapse refuses the point at run
time (E-495), and a built-in parameter that *builds internal nodes at setup*
— BJT `rc`/`rb`/`re`/`rco`, diode `rs`/`tt`, MOS `rd`/`rs`/`rsh`/`nrd`/`nrs`
— is refused at resolution; both messages name the `sweep` command, which
re-runs setup per point and is the correct instrument there.

**The `sweep` command hands eligible op sweeps to `.dc`** (E-533): with the
default `-analysis op`, a single dc-sweepable knob (a source, a resistor,
`temp`, or an `@inst[param]`) and evenly spaced points, `sweep` runs one dc
analysis under the hood — a warm point-to-point continuation instead of one
cold operating point per point (measured 21.2 s → 2.16 s on a 1000-device,
9900-point sweep, bit-identical to a direct `.dc`). Since E-534, model
knobs, the wildcard families and log-spaced grids hand over too; what stays
on the loop is uneven lists, `.param` knobs, `-vs` families, live
`@dev[param]` outputs, and `temp` with OSDI devices in the deck. Every dc
refusal — a swept parameter that moves or builds topology, a rejected value,
a non-converged point — falls back to the per-point loop automatically;
`-perpoint` forces it. See
[`examples/sweepdc_examples/`](../../examples/sweepdc_examples/).

One caveat under **`.option osdimc`**: the two engines are separate run-class
commands, so each takes its *own* Monte-Carlo trial. Running a sweep twice —
once by default and once with `-perpoint` — therefore compares two different
samples, and the curves differ by however much the model's declared
variability moves them (measured ~2 % on a σ=25 resistance). Both answers are
correct for their own sample; to compare the engines themselves, turn the
option off or re-source between the two runs.

### Where a condition holds: `track`

`meas` returns one number. `track` (E-577) returns every place a condition holds, as
a plot of its own:

```spice
track v(out) -spec localmax                        ; every maximum of v(out): track1
track v(out) -spec v(out)==1.2 -edge rise          ; every rising crossing of 1.2 V
track v(a) v(b) i(v1) -spec localmax(v(a))         ; three expressions read at v(a)'s maxima
track v(b) -spec v(b)<=-1.0 -at mid                ; regions, with x_out and width
track db(v(out)) -spec db(v(out))==-3 -analysis ac1  ; a corner, interpolated in log x
print track1.time track1.value
```

The spec is a locator (`localmax`, `localmin`, `globalmax`, `globalmin`, bare or on an
expression), a crossing `lhs==rhs`, a region `lhs<rhs`, or any boolean; `-range x0 x1`,
`-which first|last|N|-N`, `-prominence p` (hysteresis against ripple), `-raw` (the sample
rather than the parabola-refined extremum) and `-output name ...` shape the result. One
expression gives `value`, several give `value1..valueN`. Zero hits prints `track failed!`
and makes no plot. The locators are also `let` functions: `let pk = localmax(v(out))`
returns the x positions. `examples/track_examples/`.

After every `track`, `$track_plot` names the plot it made and `$track_hits` holds the
hit count (E-581); a refusal or a miss leaves them empty and 0, so a per-trial loop can
reach its result without naming `trackN` by number — the number advances only on a
hit, so `track$&n` drifts as soon as one trial has none:

```spice
repeat 1000
  reset
  tran 2u 1m
  set tp = $curplot
  track v(out) -spec localmax -prominence 20m
  if $track_hits gt 0
    setplot $track_plot
    let npk[n] = $track_hits                  ; collect what the trial needs ...
    destroy $track_plot                       ; ... and free the trial's plots
  end
  destroy $tp
  let n = n + 1
end
```

The `montecarlo` command records the locators directly, without a loop: `-expr
npk=length(localmax(v(out)))` or `-expr tpk=globalmax(v(out))` is a scalar per sample
in the `montecarlo1` plot (§3.6); a vector-valued locator is recorded as a family only
when every sample has the same number of hits. And since E-582 it runs `track` itself
per sample: `montecarlo 1000 -analysis "tran 2u 1m" -track "v(out) -spec localmax
-prominence 20m"` is the loop above in one line, with the hits per sample and every
tracked vector stacked into a plot of its own, `track1` (§3.6). The loop remains the
form for a trial that does more than one analysis per draw. In every track plot a dc
sweep's scale is spelled `v_sweep` (E-584): `v-sweep` is a subtraction to `print`.

## 3.4 Analysis coverage

All core analyses treat OSDI devices as full citizens. The audited status
of everything beyond op/dc/ac/tran:

| Analysis | Status with OSDI devices |
|---|---|
| `op`, `.dc`, `.ac`, `.tran` | Fully supported; analytic Jacobians from autodiff (cross-checked against numeric derivatives on PSP103 to ~10⁻⁵ in `examples/physcheck_examples/`) |
| `.noise` | Fully supported — all four noise-source types, correlated sources, op-dependent and frequency-shaped factors ([§2.11](02-verilog-a-language.md#modeling-functions)) |
| `.tf` | Exact (transfer function, input/output impedance) |
| `.pz` | Exact for linear devices, bit-identical to built-in twins; nonlinear `.pz` failures are a stock ngspice quirk affecting built-ins identically |
| `.sens` (DC and AC) | Exact against analytic derivatives |
| `.disto` | Supported (E-352's `OSDIdisto`): a Verilog-A diode's 2nd/3rd-harmonic distortion matches an analytic ground truth (pointwise periodic solve + FFT) to <1 %, and agrees with the built-in diode twin — re-verified in the bug-hunt round |
| `.sp` (S-parameters) | Fully supported, **any port count** (1-port reflection through N-port); `donoise` (NF, noise parameters) is inherently 2-port |
| Transient noise (`TRNOISE` sources) | Propagates through OSDI devices correctly; device-*internal* noise does not enter `.tran` (same as built-ins) |
| `.pss` (experimental, needs `--enable-pss` at configure time) | OSDI devices converge like built-ins; strongly nonlinear circuits defeat the shooting method for both alike |

Details and the exact pinned numbers: [`examples/analyses_examples/`](../../examples/analyses_examples/)
and [`examples/rfanalyses_examples/`](../../examples/rfanalyses_examples/).

## 3.5 S-parameters and Touchstone files

Ports for `.sp` are voltage sources tagged with a port number and reference
impedance (`V1 in 0 DC 0 AC 1 portnum 1 z0 50`). After an `sp` run the plot holds complex
`S_i_j` (and `Y_i_j`/`Z_i_j`) vectors plus `Rbase` (published automatically
from port 1's `z0`; a manual `let Rbase = …` still overrides).

**Export** — Touchstone v1, any port count, full option surface:

```spice
wrsnp out.s2p                ; classic: # Hz S RI R 50
wrsnp out.s2p ma ghz         ; magnitude/angle, GHz frequency column
wrsnp out.s2p db             ; dB-magnitude/angle
wrsnp out.y2p y              ; Y-parameters (normalized to Rbase per spec)
wrsnp out.z2p z mhz          ; Z-parameters, MHz
```

Options (`ri|ma|db`, `s|y|z`, `hz|khz|mhz|ghz`) combine in any order; the
2-port default output is byte-identical to the classic `wrs2p`, and N ≥ 3
files use the spec's row-major layout.

**Import** — `rdsnp` reads any Touchstone v1 file (yours or a VNA's) into a
new plot with a Hz `frequency` scale and complex vectors matching the `.sp`
conventions, so **measured data diffs against simulation in one
expression**:

```spice
sp lin 100 1MEG 1G
let s21sim = S_2_1
rdsnp measured.s2p           ; port count from the extension (or: rdsnp f 3)
let err = maximum(mag(S_2_1 - {sp1}.s21sim))
```

MA/DB files convert back to real/imaginary on read, Y/Z de-normalize to
absolute values, and the imported plot's `Rbase` lets it round-trip back
out through `wrsnp`. Pinned round-trip accuracy: 4×10⁻⁸ (the file's own
6-digit precision is the limit). See
[`examples/touchstone_examples/`](../../examples/touchstone_examples/).

## 3.6 Monte Carlo

Both standard ngspice MC idioms reach OSDI parameters
([`examples/montecarlo_examples/`](../../examples/montecarlo_examples/)):

**The `reset` idiom** — a random-valued `.param` feeds a model card; each
`reset` re-throws the dice and re-runs OSDI setup:

```spice
.param rr = agauss(1k, 100, 3)     ; nominal 1k, σ = 100/3
.model mm myres(r={rr})
...
.control
let n = 0
while n < 200
  reset
  op
  ...collect...
  let n = n + 1
end
.endc
```

**The `alter` idiom** — draw in the control language and `alter` the
parameter (no re-parse, and matched devices can share one draw):

```spice
setseed 42                          ; whole ensembles bit-reproducible
let r = 1k + 33.3*sgauss(0)
alter @n1[r] = r
```

Three gotchas, pinned by the verify suite: every textual occurrence of a
random `{param}` **draws independently** (use the `alter` idiom for matched
devices); ngspice's `sunif(0)` is uniform on **[−1, 1]**, not [0, 1]; and
`wrdata` cannot export control-created vectors (parse `print` output
instead — see [§4.5](04-limitations-and-gotchas.md#45-ngspice-control-language-traps)).

**The packaged command, with or without a yield.** `montecarlo N -analysis <cmd>
-spec <metric> -max/-min …` runs N samples and reports a yield with a
confidence interval (see the [statistics guide](../internals/ngspice_internals/ngspice_statistics.md)).
Since E-552 it also serves the plainer need — run the analysis N times and keep
a value from each: `-expr [name=]<expression>` records the expression per sample
into a plot of its own, `montecarlo1`, `montecarlo2`, … (`$montecarlo_plot`),
with `sample` as its scale; a scalar becomes an N-long vector, a sweep's
waveform an N × L family that `plot` draws as N curves. No `-spec`, no yield;
a `-spec` without a limit is refused with a pointer to `-expr`. The `track`
locators are ordinary expressions here — `-expr npk=length(localmax(v(out)))`,
`-expr tpk=globalmax(v(out))` — so a peak count or a peak position per sample
needs no loop. `track` itself is a command, so it has its own flag (E-582, E-584):
`-track "<track arguments>"` (one quoted word, repeatable) runs `track <arguments>`
after every sample's analysis and records the result into a plot of its own,
`track1`, `track2`, … (`$track_plot`) — the shape of a `track` plot stacked over the
samples: `sample` as its scale, `hits` per sample (0 a miss, `nan` a sample that
never solved) and every vector of the track plot under its own name (`time` or
`frequency` or `v_sweep`, `value`, `index`, a region's `x_out` and `width`) as an
Lmax × N family whose row k is hit k of every sample, `nan` where a sample had
fewer, so a *varying* hit count is exactly what it records: `track1.time[1]` is the
second hit of every sample, `plot track1.value[0] vs r` the first peak against a
recorded parameter. `-track "... -which first"` and other one-hit forms give plain
N-long vectors. `montecarlo<n>` stays current, holding the counts and the `-expr`
vectors; `setplot $track_plot` moves to the record. And a `-spec` or `-expr` may
read the sample's track result (E-609): `track<k>.<vector>` names the k-th `-track`
of the command, for the sample being judged — `-track "v(out) -spec localmax
-prominence 20m" -spec "track1.value" -min 2` is the yield of "the peak clears
2 V"; `track1.value[0]` the first of several hits, `track1.hits` the hit count
(0 on a miss, so `-spec track1.hits -max 0` is the yield of "nothing there"), and
a metric may mix the two plots (`track1.v_sweep / maximum(v(out))`). A spec on a
track that had no hit is a violation, counted apart in the report; an `-expr` on
one is nan for that sample. The other way round, an `-expr` that does not read a
track is evaluated before the tracks and defined as a vector of the sample's
plot, so it can feed a `-track` or a `-spec`: `-expr q=v(out)*2 -track "q -spec
globalmax -output pk" -spec "track1.pk" -min 4`. A hand-written `repeat` loop with
`$track_plot`/`$track_hits` (§3.3) remains for a trial that runs several
analyses per draw.

**A record of every draw — `.option savemc`.** `.option savemc` (E-610) writes,
for every run-class command (`op`, `tran`, `run`, … — one row per run, a
failed run marked), the value in force of every parameter with statistics to
`mcparams_<date>_<time>.csv` beside the netlist: each device slot whose value
draws (`r1 in out {agauss(1k,50,1)}`, or a random `.param` used there — ngspice
inlines a random `.param` into each use, so each use is its own draw), named
`r1` or `m1:w`; a subcircuit call's own drawn value, `x1.p`; and, under
`.option osdimc`, every OSDI parameter with declared statistics, read off the
devices as `@sm[r]` / `@n1[dr]`. Every `montecarlo` sample is a row (on the
fast path a subcircuit's own value is not re-derived and its column is empty
there; the device slots it feeds are recorded). `savemc=txt` is tab-separated,
`savemc=excel` a genuine `.xlsx` (a model parameter's name in bold in the
header, an instance parameter's regular, a `writemc` column's blue — E-617,
E-619; `.option savemc_font`, `savemc_fontsize`, `savemc_model`,
`savemc_instance`, `savemc_writemc` set the font and the three styles,
`bold+navy` style), `savemc=<name>.<ext>` names the file — the
name keeps its case and its bytes, and a quoted one its spaces
(`savemc="My Runs/Draws.csv"`), since E-612; its directories are made, and a
name that cannot be opened is said, with the reason, and the rows go to the
dated default beside the netlist (E-613); a
`reset` continues the file, a different deck starts another; `.option
automc_save` (alias `osdimc_save`) records the OSDI parameters only.
[`examples/savemc_examples/`](../../examples/savemc_examples/). What the
`.control` block computes from a run goes onto the same row (E-611): `writemc
[name=]<expr> ...` after a run in a `repeat`/`reset` loop (`writemc pk tr
overshoot=pk-1`), and `montecarlo ... -writemc pk npk=track1.hits
tpk=track1.time[0]` per sample, after the tracks, specs and exprs — each a
scalar, a column added on first use, the csv's last line rewritten in place;
the value lands only on the row of the run whose plot it reads (E-624: a
trial refused at setup made no plot, and its `failed` row stays empty instead
of carrying the previous run's value). A run stopped at a breakpoint is a row
from the pause on, `paused`, and the `resume` that ends it sets `ok`/`failed`
on that same row (E-625). A `dc` that sweeps a recorded parameter itself
(`dc @rm[r] 900 1100 100`, `dc r1 …`) leaves that cell empty on its row and
says once which parameters and their levels — the device ran at each level,
not at a draw (E-626).
A `.model` card whose parameter draws (`.model rmod va_res R_ohm={agauss(1k,50,3)}`)
is a column too, `rmod:r_ohm`. From a schematic front end that loads
`libngspice` and spells every net `/name`: give `savemc` an absolute path in
the schematic's directive text, put the analysis in a `.control` block
(`montecarlo 20 -analysis op -writemc gain=v(/mid)/v(/in)` — the shared library
runs the block when the circuit is loaded), and for the host's own run write
`set controlswait` followed by the `writemc` line: those commands wait for the
run the host starts and then land on its row.
[`examples/writemc_examples/`](../../examples/writemc_examples/).

**Automatic MC from the model's own statistics — `.option osdimc`.** A
Verilog-A parameter can *declare* its variability with attributes, and the
simulator then handles the whole loop
([`examples/osdimc_examples/`](../../examples/osdimc_examples/)):

```verilog
(* std=25.0 *)                  parameter real r  = 1000.0 from (0:inf);
(* dist="uniform", std=2e-4 *)  parameter real g  = 1e-3;   // std = half-width
(* std_rel=0.05 *)              parameter real k  = 2.0;    // σ = 5 % of nominal
(* type="instance", std=10.0 *) parameter real dr = 0.0;    // per-device mismatch
(* dist="lognormal", std_rel=0.3 *) parameter real is = 1e-15 from (0:inf); // never crosses zero
(* std=25.0, trunc=2.0 *)       parameter real rs = 1000.0;  // a Gaussian confined to ±2σ
```

```spice
.option osdimc mcseed=42            ; alias: .option automc
.control
pre_osdi model.osdi
repeat 301
  op                                 ; every run-class command = one trial
  print @mm[r] @n1[dr] ...
end
.endc
```

A draw that violates the parameter's `from` range fails that trial with the
device's own range error (the range is checked in the compiled setup, with
that trial's values of every parameter it reads), and the loop commands drop
and count the trial — so a wide gauss on a `(0:inf)` parameter loses samples
at the bound. Two shapes cannot violate it (E-554): a **lognormal**
(`dist="lognormal"`, alias `lnorm`) draws `nominal·exp(s·z)`, with `std_rel`
the sigma of the logarithm (about the relative sigma for small values) and an
absolute `std` converted at the nominal; a **truncation**, `trunc=n` sigmas,
confines the Gaussian coordinate by deterministic rejection (a draw inside the
window is exactly the draw the untruncated parameter would have made), and
`dist="tgauss"` is gauss with `trunc=3`. Both inflate under `highsigma -scale`
with the matching importance weight, and take a `wcd` walk coordinate, clamped
at the truncation. Each run writes nominal + draw through the ordinary
parameter setter — no `reset`, no netlist re-expansion, no `gauss()`
expressions in the deck. The
**first run after sourcing is the nominal baseline** (defaults of unset
parameters are only knowable after one setup pass); draws begin with the
second run. A **model** parameter is one draw per model card per trial
(process — instances sharing the card move in lockstep), an **instance**
parameter (`(* type="instance" *)`) draws independently per instance
(mismatch). Draws are pure functions of `(mcseed, trial, owner name,
param id)`, so a deck re-runs bit-identically — and inside `montecarlo`,
`highsigma` and `wcd` the trial gives way to the command's `-seed` (1 by
default) and the sample number counted from its start, so a seeded loop
command replays the same draws whatever ran before it (2026-09-05 hunt,
F13); `alter`/`altermod` recenter a
parameter's nominal (machine writes — `.dc` parameter sweeps, the `sweep`
command's points and restores, sensitivity perturbations — deliberately do
not), and a statistical parameter the deck never gave, whose default reads
the written one (`leaf #(.r(rl)) c1` in a hierarchy, `parameter real rb =
rl`), is re-resolved by the next setup so its draws sit on the new value
(E-614); dropping the option restores nominals on the next run — a value
the user gave, not the default (E-614);
`.option osdimc_verbose` prints every draw. A draw that violates the
parameter's `from` range fails that run with the device's own range error,
exactly as the same `alter` would — size the sigmas accordingly.

Two rules since E-555, because a draw is a *write*, and a write marks the
parameter *given*. A parameter the model tests with `$param_given` and the
deck never gave is **not drawn**: the draw would switch the model to its
"given" branch (BSIM4 derives `toxp` from `toxe` unless `toxp` is given, and
a 0.003 % sigma on it cost 32 % of the drain current) instead of varying it,
so the simulator says so once — *`mos_va:toxp` is not given by the deck and
the model tests `$param_given(toxp)` … not drawn. Give it on the card, or
altermod it, to vary it* — and leaves the parameter alone. And a `.dc`
sweep, the `sweep` command and `unset osdimc` put the given flag back as
they found it, so a parameter the deck never gave is not given afterwards
([`examples/paramgiven_examples/`](../../examples/paramgiven_examples/)).

**Newton step limiting for compiled MOSFETs and BJTs** (F1 of the 2026-09-04
large-circuit sweep): a Verilog-A model that calls no `$limit` used to run an
un-limited Newton, so a chain of 100 BSIM4 or PSP103 inverters needed gmin
stepping for its operating point where the built-in converged in 9. The
simulator now recognizes a 3/4-terminal MOSFET (`d,g,s[,b]`) or BJT
(`c,b,e[,s]`) by its terminal names and applies the built-ins' cold-start
guess and `DEVfetlim`/`DEVlimvds`/`DEVpnjlim` limiting to it — 8 iterations
on those chains, the same operating point to 1e-16. Models that limit
themselves, carry a thermal terminal, or keep other live internal nodes are
left alone. `.option noosdilim` switches it off; `set osdilim_verbose` says,
once per model, what was decided and why
([`examples/osdilimit_examples/`](../../examples/osdilimit_examples/)).

Since E-535 the **loop commands carry a trial policy**
([`examples/mcpolicy_examples/`](../../examples/mcpolicy_examples/)): a
deterministic loop (`sweep`'s per-point path, `optimize`, `wcd`,
`loadpull`) holds **one** sample for its whole run — a swept curve is one
circuit, an optimizer's objective is deterministic — while `montecarlo` and
`highsigma` keep drawing a fresh trial per sample (their internal resets
preserve the sequence; a USER `reset` or re-source still restarts it at the
baseline). Sweeping a *statistical* parameter itself works: the machine
write wins over the draw for the duration of the command, so
`dc @n1[dr] 0 1000 500` and `sweep @n1[dr] ...` trace real curves (the
other statistical parameters stay at the held sample), and `sens` reports
correct sensitivities for statistical parameters.

E-536 completed the policy. The hold **nests**, so a loop command used as
another's `-analysis` (an `optimize` over a swept curve) is still one
sample; `optimize`'s own internal resets preserve the sequence, and
`-center` replays one trial window per candidate, so its yield objective
samples osdimc variation while staying deterministic across candidates.
`highsigma -scale` inflates the attribute-declared gauss sigmas **and
weights them** (`log λ − n²(λ²−1)/2` per dimension, beside the netlist
term), so P(fail) is estimated under the true density rather than the
inflated one — uniforms are deliberately not inflated, as for netlist
`.param` draws. Since E-544 the **user's `alter`/`altermod` writes survive
the loop commands' internal resets**: those resets are full re-sources, and
they used to put every altered value back to the deck's — a recentred
statistical nominal, a trimmed resistor, a corner's model parameter — so
`wcd`, `highsigma` and a `montecarlo` without a netlist random binding
reported the un-altered circuit. The commands the user types are journaled
(value already evaluated, one entry per target) and replayed after each
internal reset, as E-501 replays the aging doses; the optimizer's, `sweep`'s
and `temper`'s own alters are not journaled; `optimize` journals its final
optimum; a user-typed `reset` still means "the deck as written" and forgets
the journal
([`examples/mcpolicy_examples/`](../../examples/mcpolicy_examples/), checks
35–41). **Ctrl-C** now stops a loop command at its next iteration
boundary (`sweep` marks the points it never ran `nan`; `montecarlo` and
`highsigma` report over the samples that completed) and leaves no state
behind — an interrupt used to leave a sigma inflation or a held sample
armed for the rest of the session. One interrupt arriving *inside* a long
inner analysis is consumed by that analysis; press Ctrl-C again to stop the
loop.

E-537 made the sampling commands say what they are actually measuring.
**`montecarlo N` now draws N samples** in every session state — it used to
spend the first one on the nominal baseline on a freshly sourced deck, and
fold that deterministic point into the yield and its confidence interval.
**`-seed` varies the osdimc draws**, so independent replications really are
independent (it keyed only the netlist PRNG before, and every "independent"
run returned the same points — which made an estimate look perfectly stable
when nothing had been re-sampled). Since the 2026-09-05 hunt (F13) the seed
also *pins* them: E-537 had left the session-wide trial counter in the key,
so `montecarlo 3 -seed 1` run twice reproduced the netlist `agauss` values
and not the model-declared ones, and `highsigma … -seed 3` gave a different
estimate before and after a `reset`. A loop command now keys its
model-declared draws on `(-seed, sample number)`, the seed defaulting to 1
exactly as the netlist half's always has — so an unseeded run repeats itself
whole, `-seed 1` equals it, and `montecarlo_seed` regenerates the ensemble;
`.option osdimc_verbose` shows the pair as `[sample 2 of -seed 1]`. A
never-run deck on `montecarlo`'s fast path also draws on its first sample
now (the first run's new circuit pointer used to restart the count at the
nominal baseline). **`montecarlo -lhs` stratifies the model-declared draws
too** (E-623; it used to stratify the netlist's own `.param` draws only and
say so): each `(* std *)` dimension's N samples land one per stratum — a
random permutation keyed by (seed, owner, parameter), the jitter the draw's
own hash, still a pure function with no RNG state — for the gauss, uniform,
lognormal and truncated shapes alike. And every sampling command now
**excludes samples that did not solve
and reports them** rather than silently reusing the previous sample's
numbers — with `-scale` those failures cluster in the tail, so their
exclusion biases P(fail) low and the run says as much.

Two limits `highsigma` now states instead of hiding. It reports an
**effective sample size** for its importance weights, and refuses to present
P(fail) as an estimate when they have collapsed: the weight is a product over
*every* inflated dimension, so a deck with many `(* std *)` parameters —
per-instance mismatch on several devices — drives its variance up
exponentially, and the estimate can fall orders of magnitude low while
looking precise. And a weighted mean is not automatically a probability: the
estimate is clamped into `[0,1]`, with the equivalent sigma reported as `n/a`
at the boundary rather than a `0.000` that reads as P = 0.5.

E-538 supplies the remedy that guard was pointing at. **`-inflate <param>`**
(repeatable) names which statistical parameters `-scale` may inflate — a bare
name, or the usual `@owner[param]` accessor with `*` allowed as the owner —
and the importance weight then counts exactly those dimensions and no others.
Scoping the inflation to the parameters a failure actually turns on is what
keeps the weight low-dimensional enough to estimate with: on a deck where
twenty statistically-declared bystander devices had dragged a true P(fail) of
0.2967 down to 3.35e-05, `-inflate rr` recovers **0.2967**, and reproduces bit
for bit the answer from a deck that never had those devices. Without
`-inflate` every parameter still inflates, exactly as before. A spec that
matches nothing, or one that is malformed, is reported rather than silently
widening the scope back to everything. The scope reaches the netlist's own
Gaussian `.param`s too (E-622): name the `.param` (`-inflate rr`) or the slot
its draw lands in (`r1`, `r1:key`, `x1.p`, `rm:r`, as `savemc` names them), and
an unnamed netlist dimension draws at its nominal spread — the OSDI-metric-plus-
netlist-bystanders deck that collapsed to an ESS of 6 estimates with an ESS in
the hundreds once its two model parameters alone are named:

```spice
highsigma 2000 -scale 3 -inflate vth0 -inflate @nmod[u0] \
          -analysis op -metric v(out) -min 0.9
```


## 3.7 Statistical modeling inside the device

Monte Carlo can also live in the Verilog-A source itself: `$rdist_normal`
and friends give each *instance* an independent, reproducible draw (stable
across Newton iterations — see [§2.11](02-verilog-a-language.md#modeling-functions)),
which is the right tool for per-device mismatch, with the simulator-side
idioms above layered on top for lot-level variation.

**Process corners** live in the source the same way
([E-654](../../enhancements_doc/Enhancement-654.md);
[`examples/vacorner_examples/`](../../examples/vacorner_examples/)): one
`corner` attribute per parameter names its position at each corner, and
`.option corner=<name>` in the deck — or `set corner=<name>` between runs —
selects one.

```verilog
(* corner="ss=115, ff=88" *)                     parameter real rsh = 100;   // a value
(* corner="ss=+10% ff=-10%" *)                  parameter real k   = 2.0;   // of the nominal
(* std=0.02, corner="ss=+3sigma, ff=-3sigma" *)  parameter real vth = 0.45;  // of the declared sigma
```

Entries are `name=value`, separated by commas and/or whitespace; a value is a
real literal with an optional scale factor, a percentage of the nominal, or a
multiple of the declared `std`/`std_rel` (through the transform a draw uses, so a
lognormal stays in its log domain and a `trunc` clamps it); names fold to lower
case. The corner is written through the ordinary parameter setter on every run,
the first one included, so `showmod` shows it and `.option savemc` records it. A
cornered parameter does not draw under `.option osdimc` — the corner pins the
process coordinate and mismatch on the other parameters goes on, which is the
usual corner-plus-mismatch flow. A parameter that names other corners only sits
at nominal; a model type without the name runs at nominal, said once; a name no
loaded model declares refuses the run, naming the declared ones. `tt`, `nom` and
`unset corner` (without a deck option) return to the nominal; `altermod` of a
cornered parameter recentres a percentage or sigma corner. A cornered parameter
the model tests with `$param_given` and the deck never gave is left at its
nominal, said once ([E-657](../../enhancements_doc/Enhancement-657.md) — the E-555
rule for a draw: the write would flip the model to its "given" branch instead
of moving it; give it on the card, or `altermod` it, for the corner to move
it). `.lib` corner sections are untouched and compose with this.

All of them at once is the `corners` command
([E-655](../../enhancements_doc/Enhancement-655.md);
[`examples/cornerscmd_examples/`](../../examples/cornerscmd_examples/)):

```spice
corners -output v(out) gain=v(out)/v(in)           * tt, then every declared corner
corners -list ss,ff -nonominal -analysis "tran 1u 10u" -output v(out)
corners -mc 200 -analysis op -spec v(out) -max 1.2  * a montecarlo per corner
print corner v(out)                                * the corners<n> plot: index scale
echo $corners_names                                * "tt ss ff sf fs"
```

The `-analysis` may be several bare words up to the next flag, or one quoted
word in either quote style ([E-659](../../enhancements_doc/Enhancement-659.md)).
For each corner it sets the `corner` variable, runs the analysis and records
each `-output`'s last value into a `corners<n>` plot whose scale `corner` is the
corner's index, the names printed beside the values and kept in
`$corners_names`. A corner whose analysis failed is `nan`. With `-mc N` the
rest of the line is a `montecarlo` run once per corner — the corner pins the
process parameters, the mismatch draws go on — and the plot holds `yield`,
`npass`, `nsamples` and `nfailed`. A `.option savemc` file gains a `corner`
column with the first cornered row, so the rows of a corner Monte Carlo sort
by corner. The `corner` variable is put back afterwards.

A schematic's directive text holds no control script, so for it the corner
analysis is an option ([E-656](../../enhancements_doc/Enhancement-656.md);
[`examples/autocorner_examples/`](../../examples/autocorner_examples/)):

```spice
.option autocorner          * every run at tt and then at every declared corner
.tran 1u 1m
```

With it set, every run-class command — `op`, `tran`, `ac`, the batch-mode
`run`, the shared library's — runs at the nominal and then at every corner the
loaded models declare. The per-corner plots are kept, named with their corner
(`Transient Analysis (corner ss)`), so batch `.print` cards print each corner;
and a combined `autocorner<n>` plot is made current: the nominal's vectors
under their own names and each corner's as `<name>_<corner>` — `v(out_ss)`,
`i(v1_ff)` — resampled onto the nominal's scale, so a host that draws the
current plot's vectors against its scale shows every corner side by side.
`$autocorner_plot`, `$autocorner_plots`, `$autocorner_names` and
`$autocorner_n` describe the run. The option is inert inside a loop command
(`sweep`, `montecarlo`, `corners`, `optimize`, `wcd`, `highsigma`) and without a
declared corner, and the `corner` variable is put back afterwards.

## 3.8 XSPICE code models

Alongside the OpenVAF/OSDI device path, this ngspice is built with **XSPICE**
enabled, so it can also load ngspice's **code models** — the `A`-device library
of behavioural analog and event/digital blocks (`gain`, `summer`, `limit`,
oscillators, ADC/DAC bridges, controlled sources, transmission lines, …). Code
models are compiled `.cm` shared libraries loaded with the `codemodel` command.

The prebuilt `bin/<os>/<arch>/` bundle ships them ready to use:

```
bin/<os>/<arch>/
  ngspice, openvaf-r     the executables
  codemodels/*.cm        analog, digital, spice2poly, xtradev,
                         xtraevt, table, tlines
  scripts/spinit         loads the above relative to $SPICE_LIB_DIR
```

Point **`SPICE_LIB_DIR`** at that bundle directory; ngspice reads
`scripts/spinit` at startup, which loads every code model:

```sh
export SPICE_LIB_DIR="$PWD/bin/macos/apple-silicon"   # your platform's dir
./bin/macos/apple-silicon/ngspice -b my_deck.cir
```

The example scripts do this automatically — `_setup.py` sets `SPICE_LIB_DIR`
to the resolved bundle, so `codemodel` A-devices work with no extra setup. A
minimal use is a `gain` block (`v(out) = 2·v(in)`):

```spice
* xspice gain
Vin in 0 3
a1 in out gainblk
.model gainblk gain(gain=2.0)
Rl out 0 1k
.control
op
print v(out)
.endc
.end
```

which prints `v(out) = 6`. The loads are silent and gated on
`if $?xspice_enabled`, so a deck that uses no `A`-device (or an ngspice built
without XSPICE) is unaffected.

## 3.9 When something misbehaves

- Compile-time: `openvaf-r` diagnostics are located and specific (wrong
  construct in a condition, recursion cycles, width mismatches). `--lints`
  lists tunable lints; `-A`/`-W`/`-E` adjust their level.
- A model that rejects its configuration via `$fatal`/`$finish` *during
  setup* surfaces as "a Verilog-A device rejected its configuration during
  setup", naming the device.
- `$strobe`/`$display` output appears on ngspice's stdout — printf-exact
  formatting ([§2.11](02-verilog-a-language.md#display-and-io)) makes
  temporary debug output dependable. The **severity** tasks are routed by level:
  `$display` prints bare and `$info` as `OSDI(info)` on stdout, while `$warning`
  and `$error` print as `OSDI(warn)`/`OSDI(err)` on **stderr**, so `2>` separates
  real problems from debug chatter. Before
  [E-377](../../enhancements_doc/Enhancement-377.md) every level was labelled
  `OSDI(debug)` and went to stdout — ngspice's `LOG_LVL_MASK` was 8 where the
  level occupies the low three bits, so every severity ANDed to 0.
- For convergence work: `$limit` genuinely engages iteration limiting,
  nodesets (`electrical n = 5.0;`) seed the solver, and `$discontinuity` /
  `$bound_step` steer the transient integrator ([§2.6](02-verilog-a-language.md#26-analog-operators-filters-integrators-delays)).

## 3.10 Raw strings and f-strings in control scripts

A deck is folded to lower case as it is read, and the fold reaches the text a
control script hands to a command — `set t="ABC"` stores `abc`, a plot title
comes out in lower case — while a few commands (`echo`, `shell`, `load`, …) are
exempt; the same reading pass drops the spaces around an `=` inside a quoted
string. Two string forms, after Python's, give a script control over its own
text (E-553; [`examples/rawfstring_examples/`](../../examples/rawfstring_examples/)):

| form | meaning |
|---|---|
| `r"…"` / `r'…'` | a **raw string**: copied through the deck reader as written — case and spaces kept (also `R`) |
| `f"…"` / `f'…'` | an **f-string**: every `{expression}` in it is evaluated with the control-language evaluator when the command runs and replaced by its text; `{expr:.3f}`, `{expr:.4g}`, `{expr:e}`, `{expr:d}` format it; a scalar prints with `%g`, a vector as its elements separated by spaces, a complex value as `re,im`; `\{` and `\}` are literal braces (they do not nest: `{{1+1}}` is refused as such); `{x:d}` prints a whole number beyond a `long` exactly, `:x`/`:u` refuse a negative or too-large value, and a colon tail with no conversion letter (`{x:.3}`) is told what it is missing (2026-09-05 hunt, F12). The result is **plain text** — so `let z = f"{…}"`, `set t=f"{…}"`, `alter r1 = f"{2*rr}"`, `if f"{k*3}" = 6`, `setplot f"tran{n}"`, `wrdata f"run{i}.txt"` and a command's numeric option (`-max f"{lim}"`) all take it; a result with whitespace in it is quoted, so it stays one word and the command unquotes it (`set u=rf"{vmax:.3f} V"` stores `0.756 V`) (E-556) |
| `rf"…"` / `fr"…"` | both |

```spice
set title=r"RC Low-Pass, Corner Case"
echo f"yield {100*montecarlo_yield:.2f} %, corner {mean(fc):.4g} Hz"
pyplot fig v(out) title rf"RC low-pass, Vmax = {vecmax(v(out)):.3f} V"
foreach x f"{2*n}" f"{3*n}"
  ...
end
```

The prefix counts at the start of a token or after `=`, `(` or `,` inside one
(`set t=r"…"` has one, and so does `let z=f"{7}"`, which is what the deck reader
makes of `let z = f"{7}"`; a device called `r` or a variable called `f` does
not). An `{expression}` that resolves
to nothing, an unbalanced brace, or a format that is not one is an error naming
the string, and the command does not run — an empty substitution would be a
silent zero. `$variables` are substituted before the braces are evaluated, so
`{$&v * 2}` works. `{{ }}` is not an escape here: it belongs to the netlist's
`.for` construct ([E-474](../../enhancements_doc/Enhancement-474.md)). Interactive
input was never folded; there the prefixes are simply accepted. As a side
effect of the same work, `pyplot` keeps the case of its `title`/`xlabel`/`ylabel`
tokens the way `plot` and `gnuplot` always did. A quoted file name — the
spelling for a path with a space, and what an f-string with whitespace yields —
is unquoted by `wrdata`, `write`, `source` and `pyplot` (E-556, E-558); before
that the quotes went into the file name.

## 3.11 Ending a run from a control script: `quit` and `exit`

`quit` ends ngspice — from a `.control` block, at the prompt, in pipe mode — and
`exit` is the same command under the name most shells and interpreters use
([E-653](../../enhancements_doc/Enhancement-653.md);
[`examples/exitcmd_examples/`](../../examples/exitcmd_examples/)). Both take one
optional word: an integer becomes the process's exit status (`exit 3` lets a script
report a result to whatever launched ngspice), and `noask` skips the "Are you sure you
want to quit (yes)?" question that `set askquit` raises when a simulation is still in
progress or a plot has not been written. In the shared library either returns control
to the host instead of ending the process. A `sweep -analysis exit` is refused like
`-analysis quit`, because the analysis a sweep runs per point must leave the circuit
standing. Before E-653 `exit` was "no such command available in ngspice", and the
block went on with its next line.
