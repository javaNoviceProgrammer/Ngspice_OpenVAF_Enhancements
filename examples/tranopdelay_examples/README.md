# tranopdelay_examples — Enhancement-671

The 2026-09-19 hunt's F1: after ngspice found the operating point through
its last rung, the "Transient op" (optran.c's short transient with the
sources frozen), every `absdelay` and every `transition` with a delay in
every loaded OSDI model lost its delay for the whole transient that
followed -- 0 throughout as a variable, an undelayed pass-through as a
contribution, 0 under an `idt`. The fallback left the shared
accepted-timepoint list filled with its own ~100 points and the real
transient appended after them. The timeline now starts over at the
transient's first Newton solve.

Pinned here, on the delay-only model with an ideal inductor across the
source forcing the fallback, on the contributed form, on a delayed
`transition`, on an `idt` of a delayed signal (which forces the fallback by
itself), on the fallback forced by a second instance, on `uic`, and on
`last_crossing`, which shares the timeline.

Run: `python3 verify_tranopdelay.py` (11 checks per solver, both solvers).
