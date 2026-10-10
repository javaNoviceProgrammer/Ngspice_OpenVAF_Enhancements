# noisegain_examples — Enhancement-850

[E-850](../../enhancements_doc/Enhancement-850.md): F6 of the
[second robustness and correctness campaign of 2026-10-10](../../docs/bug_hunts/2026-10-10_ngspice-openvaf-r-second-robustness-campaign.md).

The noise analysis refers each device's noise to the input by dividing by the gain squared from
the input source to the output. It floored that at 1e-20, a gain of 1e-10, and said nothing. A
real circuit reaches it: 1 fF into 1 kΩ has a gain of 6.3e-12 at 1 Hz. `inoise_spectrum` came
out 40.7 V/√Hz there, where `onoise`/|gain| is 648.

The floor now stands only for a zero: 1e-200 on the gain squared. A frequency that reaches it is
reported once per analysis, naming the source. `pnoise` and the swept `qpnoise` share the floor
and the report.

The checks:
- **[1]** 1 fF into 1 kΩ: `inoise`/`onoise` = 1/|H| at 1, 50.5 and 100 Hz.
- **[2]** No note for that gain, which is real.
- **[3]** An output the input does not reach: the note names `v1` and counts 5 of 5 frequencies.
- **[4]** (control) An RC low-pass: `inoise`/`onoise` = 1/|H| at 21 points, and no note.

Run: `python3 verify_noisegain.py` (4 checks per solver). On the E-844 binaries [1] and [3]
fail.
