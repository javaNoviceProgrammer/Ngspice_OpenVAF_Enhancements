# Cross-model self-heating sweep (Enhancement-167)

[Enhancement-166](../../enhancements_doc/Enhancement-166.md) validated **one**
production compact model's self-heating (HICUM/L2). This is the breadth
follow-up — like [E-160](../../examples/cmcsweep_examples/) was to
[E-159](../../examples/compactmodels_examples/) — driving the **same**
electro-thermal analogy through **every** bundled CMC model that exposes a
self-heating thermal terminal, across four different device classes:

| Model | Device class | flag | rth parameter |
|---|---|---|---|
| **HICUM/L2** | SiGe HBT | `flsh=1` | `rth` (direct, K/W) |
| **ASMHEMT** | GaN HEMT | `shmod=1` | `rth0` (direct, K/W) |
| **BSIMBULK** | bulk MOSFET | `SHMOD=1` | `RTH0` (per width → `rth_eff = RTH0/W`) |
| **BSIMCMG** | FinFET | `SHMOD=1` | `RTH0` (geometry-normalized) |

Each model carries an internal thermal branch of the form
`Pwr(thermal) <+ Temp(thermal)/rth − Pdiss`, so wiring the model's thermal
terminal to a circuit node lets us read the junction temperature rise directly
and check the electro-thermal analogy **`V(tnode) = Pdiss · rth_eff`**.

`V(tnode)/Pdiss` is a genuine **thermal resistance**, and the sweep confirms it is:

- **zero** when the model's self-heating flag is off;
- a **bias-independent constant** (a real thermal resistance, not an artifact of
  the operating point);
- **linearly controlled** by the model's thermal-resistance parameter (doubling
  the parameter doubles the thermal resistance);
- and — for the three models whose parameter is a direct or per-width thermal
  resistance — **exactly equal** to `rth` / `rth0` / `RTH0·W⁻¹` to machine
  precision. (The FinFET's `RTH0` is geometry-normalized, so only the constant +
  linear-control properties are asserted for it.)

## Files

- **`verify_cmcselfheat.py`** — the validation. For each of the four models, under
  **both** the Sparse and KLU solvers:
  - `[off]` self-heating flag off → `V(tnode) = 0`;
  - `[analogy]` on, two operating points → `V(tnode)/Pdiss` is a bias-independent
    constant equal to the expected `rth_eff` (exact for the three direct/per-width
    models);
  - `[control]` doubling the rth parameter doubles `V(tnode)/Pdiss`.
- **`make_cmcselfheat_fig.py`** → **`cmcselfheat.png`** — two panels: (A) the
  universal `ΔT = P·rth` across all four device classes on one log-log plot,
  spanning five decades of dissipated power; (B) each model's `V(tnode)/Pdiss`
  tracking its rth parameter with slope 1 (linear control).
- **`cmcselfheat_demo.cir`** — one deck that instantiates all four devices and
  prints `V(tnode)/Pdiss` for each, showing the same analogy across four device
  classes in a single `.op`.

## Running

```sh
python3 verify_cmcselfheat.py        # validation (both solvers)
python3 make_cmcselfheat_fig.py      # figure

# standalone demo (compile the four models first, then run):
openvaf-r ../../OpenVAF-master-20260610/integration_tests/HICUML2/hicuml2.va  -o hicuml2.osdi
openvaf-r ../../OpenVAF-master-20260610/integration_tests/ASMHEMT/asmhemt.va  -o asmhemt.osdi
openvaf-r ../../OpenVAF-master-20260610/integration_tests/BSIMBULK/bsimbulk.va -o bsimbulk.osdi
openvaf-r ../../OpenVAF-master-20260610/integration_tests/BSIMCMG/bsimcmg.va  -o bsimcmg.osdi
ngspice -b cmcselfheat_demo.cir
```

## Notes

- The MOSFETs are voltage-biased and the HBT is **current-biased** — a fixed base
  current gives the bipolar a stable operating point (a fixed-`Vbe` bipolar with
  self-heating runs away; see E-166).
- A `1e12`-ohm **thermal-probe** resistor from each thermal node to ground keeps
  that node non-singular under **KLU** when self-heating is off (some models leave
  the thermal node unconstrained in that case). It is negligible when self-heating
  is on — the model's own `1/rth` thermal conductance (≥ ~1e-5 S here) swamps the
  1e-12 S probe, so the `V(tnode)=Pdiss·rth` ratio is unaffected to < 1e-7.
- **Scope.** BSIM-SOI also exposes a thermal terminal, but in SOI the dissipated
  power includes body/parasitic-BJT and impact-ionization currents, so
  `Pdiss ≠ Id·Vds` and validating its analogy needs the model's *internal*
  dissipated power rather than the terminal product — a natural follow-up. Models
  whose thermal node is *internal* (MVSG-CMC, HiSIM-SOTB) self-heat correctly but
  don't expose `V(tnode)` for a direct read.
