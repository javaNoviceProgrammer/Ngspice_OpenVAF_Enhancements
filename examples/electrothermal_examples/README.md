# Electro-thermal / self-heating validation (Enhancement-166)

Enhancements 159–165 validated a **production compact model** across DC, coverage,
small-signal, large-signal and noise — always with the device treated as
**isothermal**. This example exercises the one remaining path: a model's own
internal **self-heating** node, which OSDI stamps as an extra (thermal) terminal
whose "voltage" is the junction temperature rise and whose "current" is the
dissipated power.

The device is **HICUM/L2** (a SiGe HBT), compiled in place from the OpenVAF
integration-test source. Its electro-thermal network is gated by the model flag
`flsh`, with parameters `rth` (thermal resistance, K/W) and `cth` (thermal
capacitance, J/K). The model contains an internal thermal branch

```
I(br_sht) <+ V(tnode)/rth - Pdiss
```

so the thermal node obeys the textbook **electro-thermal analogy**:

| electrical | ↔ | thermal |
|---|---|---|
| voltage `V(tnode)` | ↔ | temperature rise ΔT [K] |
| current into node | ↔ | dissipated power P [W] |
| resistor `rth` | ↔ | thermal resistance [K/W] |
| capacitor `cth` | ↔ | thermal capacitance [J/K] |

giving `V(tnode) = P·rth` at DC and a single-pole thermal transient with
`τ = rth·cth`.

By wiring the model's thermal terminal to an ordinary circuit node we can read
ΔT directly and check it against these laws.

## Files

- **`verify_electrothermal.py`** — the validation (6 checks, run under **both** the
  Sparse and KLU solvers):
  1. self-heating **off** (`flsh=0`) → `V(tnode)=0` (isothermal baseline);
  2. **static** analogy `V(tnode) = P·rth` to machine precision, over a decade of
     dissipated power and for two thermal resistances;
  3. **feedback** — at fixed collector current, self-heating lowers `Vbe` by a
     consistent, physical temperature coefficient (≈ −1.5 mV/K), more so for
     larger `rth`;
  4. **dynamic** — after a power step the thermal node rises as a single pole,
     reaching 63.2 % of its final change at one `τ = rth·cth`;
  5. `τ` scales with `cth` (double `cth` → double `τ`);
  6. **runaway** — under a fixed `Vbe`, self-heating is positive feedback: the
     self-heated collector current runs far above the isothermal current at high
     bias.
- **`make_electrothermal_fig.py`** → **`electrothermal.png`** — three panels:
  (A) `ΔT = P·rth` on the nose for two `rth`; (B) a Gummel plot showing the
  self-heating runaway; (C) the thermal transient for two time constants.
- **`electrothermal_demo.cir`** — a minimal hand-runnable deck: it prints the
  isothermal baseline, then enables self-heating and shows `V(tnode) = P·rth` and
  the `Vbe` drop.

## Running

```sh
# validation (both solvers)
python3 verify_electrothermal.py

# figure
python3 make_electrothermal_fig.py

# standalone demo
openvaf-r ../../OpenVAF-master-20260610/integration_tests/HICUML2/hicuml2.va -o hicuml2.osdi
ngspice -b electrothermal_demo.cir
```

## Why a stable operating point matters

A bipolar transistor driven by a **fixed base–emitter voltage** is
thermally unstable once self-heating is on: more current heats the junction,
which lowers the turn-on voltage, which raises the current — positive feedback
that runs away (Panel B; check 6). Real bias networks avoid this with a current
source or emitter degeneration. So the quantitative checks here **current-bias**
the device (fixing the base current), which gives a stable operating point and a
well-posed `V(tnode) = P·rth`.

## Notes

- The OSDI HICUM device has five terminals — `(collector, base, emitter,
  substrate, thermal)`. Tie the thermal terminal to `0` for a pure isothermal
  reference (no thermal branch), or to a live node to observe self-heating.
- With `flsh=1` the cold-start self-heated operating point can be hard for
  Newton; the demo (and figure) start isothermal and enable self-heating with
  `altermod`, warm-starting the harder solve — a good habit for self-heated decks.
- Everything here is validated with the **default Sparse 1.3** solver and again
  under **KLU** (`.option klu`); both agree.
