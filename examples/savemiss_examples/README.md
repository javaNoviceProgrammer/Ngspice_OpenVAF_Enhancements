# savemiss_examples — Enhancement-600

Two diagnostics from the 2026-09-10 hunt. D1: `save @n1[opvar]` before any
analysis printed two warnings for one item (the device's own, raised by the
probe `beginPlot` makes, and E-418's), and printed them for a save
`.option saveused` inferred; the device is quiet under the probe now, and an
inferred save gets none. D2: a `.model` card whose type nothing defines, or a
binned model none of whose bins covers the instance, got the bare "Unable to
find definition of model"; both say why now, with the card's line and type, or
the bins and the instance's `l` and `w`.

Run: `python3 verify_savemiss.py` (11 checks per solver, both solvers).
