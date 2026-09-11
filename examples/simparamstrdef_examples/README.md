# simparamstrdef_examples — Enhancement-598

`$simparam$str(name, default)`, the non-fatal string form the LRM gives the same
optional default as `$simparam`, was refused at compile time although the backend
had carried the callback since Enhancement-215. It compiles now: a served name
returns its value, an unserved one (`instance`, `module`, `path`) returns the
default — a literal, a string parameter or a string variable — and the run
completes where the one-argument form is a `$fatal`. The one-argument form still
warns L025, with the note spelling the string form of the help.

Run: `python3 verify_simparamstrdef.py` (13 checks per solver, both solvers).
