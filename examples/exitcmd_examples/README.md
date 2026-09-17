# exitcmd_examples — Enhancement-653

`exit` is a second name for `quit`. It was not an ngspice command: in a
`.control` block it printed "exit: no such command available in ngspice" and
the block went on with its next line. It is now a second table entry for the
same function, in the ngspice and the nutmeg command tables, with the same
optional argument — an exit status (`exit 3`) or the word `noask` — and
`sweep -analysis exit` is refused like `-analysis quit`.

Run: `python3 verify_exitcmd.py` (10 checks per solver, both solvers).
