# Enhancement-897: the built-in HICUM's lateral spreading and substrate transistor carry their currents — the substrate current was 6.3 times low at the default flcomp

**Scope:** found while digging into F2 of the
[analyses correctness campaign of 2026-10-16](../docs/bug_hunts/2026-10-16_ngspice-openvaf-r-analyses-correctness-campaign.md)
([E-896](Enhancement-896.md)). These two are not derivatives: they changed currents, so the
operating point was wrong too. The reference is the corpus's own Verilog-A HICUM L2.4.0
(`hicumL2V2p4p0.va`), the version the built-in model ports.

ngspice:
- `spicelib/devices/hicum2/hicumL2.cpp`: `HICQFC` takes `HICQFF`'s `FFdVc` and `FFdVc_ditf`.
- `spicelib/devices/hicum2/hicumL2temp.cpp`: `itss_t`'s derivative goes to `.dpart`.

**ngspice only.**

**Suites:**
- [`hicum2_examples`](../examples/hicum2_examples/): checks [7] and [8]. 16 of 16 per solver;
  on the E-895 binaries 15 of 16 fail.
- The full sweep: 592 of 592.

## What was wrong

**Lateral current spreading with vcbar.** `HICQFC`, the collector charge with 2D/3D current
spreading (`latb`, `latl`), weighs its charges by exp((FFdVc − vcbar)/VT). In the Verilog-A
source `HICQFC` is a macro expanded inside `HICQFF`, so `FFdVc` is the voltage drop `HICQFF`
has just computed. In the C++ port `HICQFC` is a separate lambda that declared its own `FFdVc`
and `FFdVc_ditf`, which a default dual number sets to zero. With `latb`, `latl` and `vcbar`
given, the collector current at high current was 0.65 % above the Verilog-A model's (0.86 % at
`flcomp=2.4`). Lateral spreading alone, or `vcbar` alone, agreed to 2.5e-5, the offset the base
card has.

**The substrate transistor.** In the temperature update for `flcomp` < 2.3, the default:

```
here->HICUMitss_t.rpart = a.rpart();
here->HICUMitss_t.rpart = a.dpart();
```

The second line put the temperature derivative of `itss_t` where its value belongs. That is
about 0.16 times the value at 300 K, and `.dpart` was left unset. A saturated stage's substrate
current was 2.68e-7 A against the Verilog-A model's 1.70e-6 A. Its temperature derivative was
missing too, which put a self-heating stage's `ac` 9.8e-3 off the dc derivative. With
`flcomp=2.4` the other branch was right.

## The change

- `HICQFC(T, Ix, I_CK, FFT_pcS, FFdVc, FFdVc_ditf, ...)`, called from `HICQFF` with its own
  `FFdVc` and `FFdVc_ditf`.
- `here->HICUMitss_t.dpart = a.dpart();`

## The checks

`hicum2_examples`:
- **[7]** `latb`, `latl` and `vcbar` at high current: the collector current within 1e-4 of
  the Verilog-A model. E-895: 6.5e-3.
- **[8]** The substrate transistor in saturation, `flcomp` at its default: its current within
  1e-3 of the Verilog-A model. E-895: 6.3 times low.

150 random cards, built-in against Verilog-A, with E-896 to E-899 together:
- E-895: 130 of 150 solve, and 7 of those have a node more than 0.1 mV off.
- Now: 149 solve, none more than 30 µV off. The collector current is within 5e-5 everywhere,
  the offset the base card has. Substrate currents above 1 nA are within 2.6e-4.
