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

## 3.3 Parameter access, `alter`, and sweeps

Parameters are readable and writable from the control language:

```spice
print @n1[r]          ; read (instance param, (* type="instance" *))
alter @n1[r] = 2k     ; change + re-run setup on the next analysis
altermod @mm[r] = 2k  ; same for a model-card parameter
```

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

**Automatic MC from the model's own statistics — `.option osdimc`.** A
Verilog-A parameter can *declare* its variability with attributes, and the
simulator then handles the whole loop
([`examples/osdimc_examples/`](../../examples/osdimc_examples/)):

```verilog
(* std=25.0 *)                  parameter real r  = 1000.0 from (0:inf);
(* dist="uniform", std=2e-4 *)  parameter real g  = 1e-3;   // std = half-width
(* std_rel=0.05 *)              parameter real k  = 2.0;    // σ = 5 % of nominal
(* type="instance", std=10.0 *) parameter real dr = 0.0;    // per-device mismatch
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

Each run writes nominal + draw through the ordinary parameter setter — no
`reset`, no netlist re-expansion, no `gauss()` expressions in the deck. The
**first run after sourcing is the nominal baseline** (defaults of unset
parameters are only knowable after one setup pass); draws begin with the
second run. A **model** parameter is one draw per model card per trial
(process — instances sharing the card move in lockstep), an **instance**
parameter (`(* type="instance" *)`) draws independently per instance
(mismatch). Draws are pure functions of `(mcseed, trial, owner name,
param id)`, so a deck re-runs bit-identically; `alter`/`altermod` recenter a
parameter's nominal (machine writes — `.dc` parameter sweeps, the `sweep`
command's points and restores, sensitivity perturbations — deliberately do
not); dropping the option restores nominals on the next run;
`.option osdimc_verbose` prints every draw. A draw that violates the
parameter's `from` range fails that run with the device's own range error,
exactly as the same `alter` would — size the sigmas accordingly.

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
`.param` draws. **Ctrl-C** now stops a loop command at its next iteration
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
when nothing had been re-sampled). **`-lhs` says so** when it cannot reach
model-declared variability: it stratifies the netlist's own `.param` draws
only. And every sampling command now **excludes samples that did not solve
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
widening the scope back to everything:

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
