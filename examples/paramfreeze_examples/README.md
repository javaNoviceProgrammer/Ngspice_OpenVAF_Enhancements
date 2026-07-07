# paramfreeze_examples — freezing structural (width) parameters (Enhancement-92)

Closes a safety gap in Enhancement-91: a parameter that shapes a declaration
width is *structural* (the OSDI descriptor has one fixed node/array count), so
it is frozen to a `localparam` at its declaration. A netlist override can no
longer desync the frozen structure from behavioural code.

`paramfreeze.va` — `wsum` sizes an array `w[0:N-1]` *and* bounds a runtime loop
by `N`; before E-92, `.model ... N=8` left `w` sized at the default while the
loop ran to 8 (a silent out-of-bounds, garbage result). Now `N` is frozen: the
override is ignored and the model keeps its default. `mp` shows a
multi-parameter declaration split so only the width name (`bits`) freezes while
`gain` stays overridable. Run: `python3 verify_paramfreeze.py` (4 checks).
