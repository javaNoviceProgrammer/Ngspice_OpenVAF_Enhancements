# transopts_examples — Enhancement-881, Enhancement-882, Enhancement-883

[E-881](../../enhancements_doc/Enhancement-881.md), [E-882](../../enhancements_doc/Enhancement-882.md)
and [E-883](../../enhancements_doc/Enhancement-883.md): D1, D2 and D3 of the
[transient stress campaign of 2026-10-12](../../docs/bug_hunts/2026-10-12_transient-sparse-klu-stress-campaign.md).

Transient options took values that have no reading, without a word:
- **`xmu`** outside [0, 0.5] gave wrong answers;
- **`ordfix`:** −1 was taken as off, and 7 and up were cut to the order ceiling;
- **`reltol`** of 1 and more was taken;
- **an unknown `method`** printed only "unsupported integration method".

They are now refused, capped with a warning, or reported with the value and what runs instead.

The checks, on an RC with an inductor whose answer at 4 µs is 3.757e-7:
- **[1]** (E-881) `xmu=-1` and `xmu=2` are refused, and the run is the default run.
- **[2]** (E-881, control) `xmu=0` and `xmu=0.3` are taken, and move the answer.
- **[3]** (E-882) `ordfix=-1` is refused; `ordfix=7` and `ordfix=1e9` warn that 6 is used.
- **[4]** (E-882) `reltol=1` and `reltol=10` are refused, and the run is the default run.
- **[5]** (E-882) Gear with `ordfix=4` at the default `maxord=2` says the order is pinned at 2; at
  `maxord=4` it says nothing.
- **[6]** (E-883) `method=trbdf` names the value and says trap is kept; after
  `option method=gear`, `method=foo` says gear is kept.
- **[7]** (control) `reltol=0` is refused as "must be greater than zero", as before.

Run: `python3 verify_transopts.py` (7 checks per solver). On the E-875 binaries [1] and [3] to [6]
fail.
