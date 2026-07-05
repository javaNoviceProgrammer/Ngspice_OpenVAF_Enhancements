# analyses_examples — ngspice analyses with Verilog-A (OSDI) devices (Enhancement-62)

A hands-on tour of every ngspice analysis working with OSDI-compiled
Verilog-A devices, plus the two Enhancement-62 additions: **generic
`.dc @inst[param]` sweeps** and the **`.disto` limitation warning**.

Each `.cir` deck below is standalone and commented — run any of them with

```bash
ngspice -b <deck>.cir
```

after compiling the two models (the verify/plot scripts do this
automatically):

```bash
openvaf-r analyses_blocks.va -o analyses_blocks.osdi
openvaf-r analyses_dio.va -o analyses_dio.osdi
```

## The models (`analyses_blocks.va`, `analyses_dio.va`)

| module | what it is | teaches |
|---|---|---|
| `ores` | resistor, `parameter real r` | plain (model-card) parameters |
| `ocap` | capacitor via `ddt()` | reactive elements in AC/PZ |
| `otres` | resistor with `$temperature` dependence | temp sweeps |
| `ires` | resistor with `(* type="instance" *) parameter real r` | **instance-kind** parameters |
| `odio` | exponential diode with `$limit` | nonlinear device for `.disto` |

The `(* type="instance" *)` attribute is the key to instance-level
parameter access: it is what makes `N1 a 0 mm r=2k`, `print @n1[r]`,
`alter @n1[r]`, and `.dc @n1[r]` possible. A plain `parameter` is
model-kind only (set it on the `.model` card / `altermod`).

## The decks

| deck | analysis | expected result |
|---|---|---|
| `tf.cir` | `.tf` | TF = 0.75, Z_out = 750 Ω, Z_in = 2 kΩ — exact |
| `pz.cir` | `.pz` | single pole at −1/(RC) = −1e6 rad/s — exact, identical to built-in R/C |
| `sens_dc.cir` | `.sens` | dV/dr1 = −1.875e-4, dV/dr2 = +6.25e-5 — the analytic divider derivatives |
| `sens_ac.cir` | `.sens … ac` | dV/dacmag = 0.5 − 0.5j at the pole frequency (= H there) |
| `temp_sweep.cir` | `.dc temp` | I = 1V / R(T) at every point (°C→K handled) |
| `param_sweep.cir` | **`.dc @n1[r]`** (new) | I = 1V / r at every swept value |
| `nested_sweep.cir` | **nested `.dc @n1[r] … V1 …`** (new) | family of I = V/r curves, inner level resets |
| `alter.cir` | `alter` / `altermod` | instance value beats model card; readback via `print @n1[r]` |
| `disto.cir` | `.disto` | prominent **warning** that OSDI nonlinearities are invisible to disto (was silent zeros) |

## Plots

`python3 plot_analyses.py` regenerates `plots/`:

| plot | shows |
|---|---|
| `plots/param_sweep.png` | the new `.dc @n1[r]` sweep vs analytic 1/R |
| `plots/nested_sweep.png` | the nested sweep's I = V/r curve family |
| `plots/temp_sweep.png` | `.dc temp` vs analytic 1/R(T) |
| `plots/ac_lowpass.png` | RC Bode plot with the `.pz` pole (−3 dB) and the `.sens ac` point (−45°) marked |

## What Enhancement-62 changed in ngspice

1. **`.dc @inst[param]` sweeps** (`dctrcurv.c`): the sweep code accepted
   only V/I sources, resistors, and `temp`. A new generic sweep type
   resolves `@inst[param]` through the device's own parameter tables and
   refreshes the device per point exactly like `alter` — for any device
   type, nestable, with the original value restored afterwards.
2. **`.disto` warning** (`CKTdisto.c`): distortion analysis needs
   higher-order derivatives the OSDI ABI doesn't carry, and ngspice used
   to skip OSDI devices *silently* — an OSDI diode reported exactly zero
   distortion where the identical built-in diode reported 1.8e-6. It now
   warns loudly, naming each affected device type.

Everything else in the table above already worked and is pinned by
`verify_analyses.py` (19 checks).
