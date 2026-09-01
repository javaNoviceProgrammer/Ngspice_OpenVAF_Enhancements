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
variables:

```spice
.dc @n1[r] 500 1500 100            ; sweep an OSDI instance parameter
.dc @n1[r] 500 1500 500 vin 0 2 1  ; nested with a source sweep
.dc temp -40 125 5                  ; temperature sweep; $temperature
                                    ; tracks each point (°C in the deck,
                                    ; K inside the model)
```

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
| `.disto` | **Not supported for OSDI devices** — the distortion kernel needs Taylor coefficients beyond first derivatives, which the OSDI ABI cannot provide. ngspice prints a prominent warning naming each affected device (it used to report silent zeros) |
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
param id)`, so a deck re-runs bit-identically; `alter` recenters a
parameter's nominal; dropping the option restores nominals on the next run;
`.option osdimc_verbose` prints every draw. A draw that violates the
parameter's `from` range fails that run with the device's own range error,
exactly as the same `alter` would — size the sigmas accordingly.

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
