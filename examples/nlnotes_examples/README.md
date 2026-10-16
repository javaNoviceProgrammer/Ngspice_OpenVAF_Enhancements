# nlnotes_examples — Enhancements 892 to 894, and the campaign's notes

[E-892](../../enhancements_doc/Enhancement-892.md), [E-893](../../enhancements_doc/Enhancement-893.md)
and [E-894](../../enhancements_doc/Enhancement-894.md): D1, D2 and N2 of the
[nonlinear correctness campaign of 2026-10-15](../../docs/bug_hunts/2026-10-15_ngspice-openvaf-r-nonlinear-correctness-campaign.md).
The campaign's other notes, N1, N3 and N4, are each model's or SPICE's own definition. They are
documented in the handbook and pinned here as expected behaviour.

The checks:
- **[1]** (E-892) A `.four` over the last 2 of 3 periods of a run started at one period is analysed,
  every harmonic within 2e-3 of the exact one, with no "No transient data" line.
- **[2]** (E-892) The same through the `fourier` command at `polydegree=3`.
- **[3]** (E-892) A window longer than the data is refused with the numbers, and the `.four` route
  adds nothing after the reason.
- **[4]** (E-893) A 1000-point vector in the constants plot writes 1000 rows, its index in the
  scale's column, with a note.
- **[5]** (E-893) After an `op`, with `wr_singlescale` and `wr_vecnames`, it writes 1000 rows under
  an `index` header.
- **[6]** (E-893, control) A transient's vector writes its own rows and no note.
- **[7]** (E-894) A diode an ideal source forward-biases by 4.2 V: the warning names `v4#branch` and
  its 1e45 A.
- **[8]** (E-894, control) The same diode behind 1 kΩ: no warning.
- **[9]** (N1) A level-1 MOSFET with `tox` (Meyer) driven around a closed path loses over 10 % of
  the charge it moves each period, the same at two step sizes; BSIM3 conserves to 1e-3.
- **[10]** (N3) MOS1's default flicker noise falls as f^−AF; at `nlev=0` it falls as 1/f.
- **[11]** (N4) With `tmax=1m`, a 10 mV ripple on a capacitor biased at 1 V takes under a third of
  the steps of the unbiased one; at the default `tmax` both take 2000.

Run: `python3 verify_nlnotes.py` (11 checks per solver). On the E-888 binaries [1] to [5] and [7]
fail.
