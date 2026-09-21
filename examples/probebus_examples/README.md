# probebus_examples — Enhancement-628

`.probe alli` -- the card KiCad's simulator adds to every run -- on a Verilog-A
bus device. The pass counted the node tokens of `N2 /mid /out vares` (two 4-bit
bus ports in autobus shorthand), took the device for a two-terminal one and
spliced its measuring source into the second token; autobus then expanded the
invented base into four bits the source never touched, the bits floated, and
every output read 0 V (F11 of the 2026-09-12 hunt). A subcircuit call whose
formal is a bus base inside failed the same way through the X line.

OSDI lines and subcircuit calls are now probed in a second pass, run once
`pre_osdi` has registered the modules and `.option autobus` is resolved: a
shorthand line is written out against its model's ports, in the deck's
spelling, and every terminal gets its own source (`n2:n_3_#branch`); an X line
keeps its base token and gets one source per bit the formal stands for inside,
found through nested calls (`x1:out_3_#branch`). A two-terminal scalar device
or a two-formal plain subcircuit keeps `<inst>#branch`.

`va_res.va` is the example5 model (two `[0:3]` bus ports).

Run: `python3 verify_probebus.py` (11 checks per solver, both solvers).

Enhancement-691 (F9 of the 2026-09-21 hunt) adds five checks: the explicit `i(<inst>)`,
`i(<inst>,<k>)` and `i(<inst>,<terminal>)` probes on an OSDI instance ran during the deck
read, before the module was registered, so every terminal was labelled `nn` -- a
four-terminal device got four vectors that all read `n3:nn#branch`, and `i(n3,p)` was refused
as "Node p is not available". They now go through the same second pass as `alli` and carry
the model's terminal names (`n3:p#branch`, `n3:cp#branch`, `n2:n_1_#branch` on a written-out
bus line); a two-terminal device keeps `<inst>#branch`.
