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
run; `tt`, `nom` and `unset corner` return to the nominal. A cornered
parameter the model tests with `$param_given` and the deck never gave is
left at its nominal with a note (Enhancement-657, the E-555 rule exported
for corners as `OSDI_CORNER_GATED`); given on the card, or `altermod`ed,
it moves. A cornered parameter's nominal is captured at every setup,
corner on or off, so a corner selected after a nominal run under
`.option osdimc` is applied in full on its first run (Enhancement-658).

Since [E-668](../../enhancements_doc/Enhancement-668.md) (hunt F10): a corner
that moves a parameter out of its range — its own, or the range of the
paramset member the instance was bound to at the nominal — fails the run
with a second line naming the corner, the nominal it moved the parameter
from, the member, and the sibling member that accepts the value.

Since [E-669](../../enhancements_doc/Enhancement-669.md) (hunt F14): any
number of declared corners can be selected, the loops take up to 255 beside
`tt` and say when a circuit declares more, a corner name is limited to 79
characters at compile time, and a longer name from an older object is refused
by the simulator instead of truncated (or, at 80 characters, aborting it).

Run: `python3 verify_vacorner.py` (35 checks per solver, both solvers).
