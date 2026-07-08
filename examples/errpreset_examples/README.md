# errpreset_examples — coordinated accuracy presets (Enhancement-110)

A SPICE-class simulator exposes ~8 interacting accuracy/robustness knobs
(`reltol`, `abstol`, `vntol`, `chgtol`, `trtol`, gmin/source steps, `itl1`).
Tuning them by hand is error-prone. Commercial tools (e.g. Spectre's
`errpreset`) instead offer **one** knob that selects a coordinated, validated
combination. Enhancement-110 adds the same to ngspice:

```
.option errpreset=conservative   ; accurate / robust, slower
.option errpreset=moderate       ; ngspice's historical defaults (backward compatible)
.option errpreset=liberal        ; fast, looser accuracy
```

Each preset sets one consistent group of options. `moderate` reproduces the
existing defaults exactly, so adding the feature changes nothing unless you ask
for it. **Explicit `.option`s always win over the preset, regardless of the
order they appear** (e.g. `errpreset=liberal reltol=1e-4` keeps the tight
`reltol`), so you can start from a preset and fine-tune one value.

| preset | reltol | abstol | vntol | chgtol | trtol | gmin/src steps | itl1 |
|---|---|---|---|---|---|---|---|
| conservative | 1e-4 | 1e-13 | 1e-7 | 1e-15 | 1 | 10 / 10 | 200 |
| moderate | 1e-3 | 1e-12 | 1e-6 | 1e-14 | 7 | 1 / 1 | 100 |
| liberal | 1e-2 | 1e-10 | 1e-4 | 1e-12 | 20 | 1 / 1 | 100 |

## What's here

- `errpreset_demo.cir` — a 2-stage RC network driven by a fast pulse; run it
  directly (`ngspice -b errpreset_demo.cir`) and switch the `errpreset=` line to
  see the accepted time-point count (and thus edge resolution) change.
- `verify_errpreset.py` — the checks.

## Verify

```
python3 verify_errpreset.py
```

Runs the same adaptive-stepping transient under each preset and checks (9/9):
the time-point count orders **conservative > moderate ≥ liberal** (tighter
tolerances → finer stepping); `moderate` equals the no-errpreset default
(backward compatibility); an explicit `reltol` overrides the preset **and gives
the same result in either `.options` order**; a preset can be loosened by an
explicit value; and an unknown preset warns and is ignored. errpreset is a
simulator-side feature, so no Verilog-A model is involved. See
[`../../enhancements_doc/Enhancement-110.md`](../../enhancements_doc/Enhancement-110.md).
