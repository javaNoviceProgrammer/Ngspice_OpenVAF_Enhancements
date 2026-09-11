# nupafail_examples — Enhancement-604

`w=nan` or a trailing `w=` on an instance line reached numparam as the brace
expression `{nan}` / `{}`, could not be evaluated, and every numparam error
ended the process ("ERROR: fatal error in ngspice, exit(1)") — the interactive
session included — where `w=1e400` on the same line is refused at the line
level. A failure on a device, model or dot card is now attached to the card and
the deck reader refuses the line ("Error on line N or its substitute", the
author's text, numparam's reason, the parser's message); a failure on a `.param`,
`.func` or subcircuit-call line refuses the deck, as an unknown subcircuit does.
The error text is printed in full, numparam's line numbers are labelled the
right way round, and a `.model` card with such a failure is an error, not a
"Model issue" warning.

Run: `python3 verify_nupafail.py` (13 checks per solver, both solvers).
