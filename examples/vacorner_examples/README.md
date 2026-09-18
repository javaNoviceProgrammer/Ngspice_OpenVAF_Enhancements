# vacorner_examples — Enhancement-654

Process corners declared on Verilog-A parameters and selected in the
netlist. `(* corner="ss=115, ff=-10%, sf=+3sigma" *)` names a parameter's
position at each corner — an absolute value with an optional scale factor,
a percentage of the nominal, or a multiple of the declared `std`/`std_rel`
(through the transform a draw uses) — with entries separated by commas
and/or whitespace and names folded to lower case. The compiler exports the
entries through a new OSDI side table; ngspice's `.option corner=<name>`
(or `set corner=<name>` between runs) writes every cornered parameter's
value on each run, the first one included. A cornered parameter does not
draw under `.option osdimc`; a name no loaded model declares refuses the
run; `tt`, `nom` and `unset corner` return to the nominal.

Run: `python3 verify_vacorner.py` (18 checks per solver, both solvers).
