# x11eof_examples — Enhancement 919

[E-919](../../enhancements_doc/Enhancement-919.md).

With an X display open, `ngspice -i` with piped input never ended at the end of that input. It
spun at the prompt at about 40% of a core. It needs a live display, so CI, which has none, never
saw it, and [`sourcenest_examples`](../sourcenest_examples/) [7] to [9] hung on any machine running
an X server.

Every case runs without a display. The same cases run again when an X server answers on
`$DISPLAY`, and only there do they reach the code that changed:

- **[1]** A pipe closed with nothing written: the prompt ends, exit 0.
- **[2]** A pipe closed after two commands: each runs once, exit 0.
- **[3]** A last line with no newline, from a pipe: it still runs.
- **[4]** A file as the input, its last line with no newline: every line runs.
- **[5]** A pipe left open and silent, then written to: not taken for its end.
- **[6]** A signal while waiting on an open pipe: not taken for its end.
- **[7]** A terminal, silent and sent SIGWINCH, then a command, then Ctrl-D: it ends there, exit 0.

Run: `python3 verify_x11eof.py`. POSIX only.

With a display: 14 checks, 6 of which fail on E-918 ([1] to [6], each by hanging for the suite's
30 s limit). Without one: 7 checks, all of which pass on E-918 too, and the display half reports
`SKIP`. **So this suite can only catch a regression on a machine with an X server, which CI is
not.**
