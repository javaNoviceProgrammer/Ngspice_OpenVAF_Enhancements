# Enhancement-850: the input-referred noise divides by the gain the circuit has — the gain squared was floored at 1e-20 without a word, and inoise came out 16 times low through 1 fF at 1 Hz

**Scope:** F6 of the
[second robustness and correctness campaign of 2026-10-10](../docs/bug_hunts/2026-10-10_ngspice-openvaf-r-second-robustness-campaign.md).

ngspice:
- `include/ngspice/noisedef.h`: `N_MINGAIN` is 1e-200; `Ndata` counts the frequencies that
  reach it; prototypes for `NgainSqInv` and `NlowGainNote`.
- `spicelib/analysis/noisean.c`: the two helpers; `NOISEan` uses them.
- `spicelib/analysis/dcpss.c`: `pnoise` and the swept `qpnoise` count and report the same way.

`examples/noisegain_examples/` (new). **ngspice only.**

**Suites:**
- [`noisegain_examples`](../examples/noisegain_examples/): 4 of 4 per solver. On the E-844
  binaries checks [1] and [3] fail; [2] and [4] pass.
- The 16 noise suites pass unchanged.
- The full sweep: 557 of 557.

## What was wrong

```spice
v1 in 0 dc 0 ac 1
c1 in out 1f
r1 out 0 1k
.control
noise v(out) v1 lin 3 1 100
```

At 1 Hz the gain is 2π·1·1e-15·1e3 = 6.3e-12. `inoise_spectrum` was 40.7 V/√Hz, where
`onoise`/|gain| is 648. The analysis refers each device's noise to the input by multiplying by
`GainSqInv`, which `noisean.c` computed as `1/MAX(gain², N_MINGAIN)` with `N_MINGAIN` = 1e-20.
Any gain below 1e-10 was taken as 1e-10, and nothing said so.

A gain that small is real: an output coupled to the input only through a small capacitor, at low
frequency. 3 of the campaign's Family E's 300 networks reached it. `dcpss.c` divided by the same
floor in `pnoise` and `qpnoise`.

## The change

The floor is 1e-200 on the gain squared, a gain of 1e-100. It still keeps an output that the
input cannot reach from dividing by zero, but no real gain reaches it.

`NgainSqInv` returns the inverse and counts each frequency where the gain squared is below the
floor, or not a number. After the sweep, `NlowGainNote` reports them once:

```
Warning: noise: the gain from v1 to the output is zero at 5 of 5 frequencies, the first 1 Hz;
the input-referred noise there divides by a floor of 1e-100 on the gain and means nothing
```

The input-referred noise of such a frequency was a plausible-looking number. It is now plainly
not one: 4e91 V/√Hz in the example of check [3].

`inoise_total` integrates each frequency interval with the gain at its upper end, as upstream
does. The lowest frequency's gain does not enter it, so the total of the example above is
unchanged.

## The checks

`noisegain_examples`:
- **[1]** 1 fF into 1 kΩ: `inoise`/`onoise` = 1/|H| at 1, 50.5 and 100 Hz.
- **[2]** No note for that gain, which is real.
- **[3]** An output the input does not reach: the note names `v1` and counts 5 of 5
  frequencies.
- **[4]** (control) An RC low-pass: `inoise`/`onoise` = 1/|H| at 21 points, and no note.
