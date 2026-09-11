# multisave_examples — Enhancement-602

`.print dc v(a)` beside `.print tran v(a)` in a batch deck lost the transient
("no data saved for Transient analysis; analysis not run"): each card registers
a save restricted to its analysis, and the insert-time dedup kept one save per
node name whatever the restriction. A `.meas dc` beside a `.tran` did the same.
The dedup respects the restriction now, as E-594 made `ft_getSaves` do; and a
batch run evaluates the `.meas` cards of every analysis it produced, each under
the right header, where it used to evaluate the last analysis's only.

Run: `python3 verify_multisave.py` (9 checks per solver, both solvers).
