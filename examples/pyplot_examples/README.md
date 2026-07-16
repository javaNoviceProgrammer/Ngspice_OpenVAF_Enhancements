# pyplot_examples — the `pyplot` command (matplotlib backend) (Enhancement-94)

A new ngspice command, `pyplot`, plots simulated vectors with **matplotlib** —
a Python counterpart to `gnuplot`. Same syntax: `pyplot <file> <expr...>`. With
`set pyplot_terminal=png` it renders headless (Agg) to `<file>.png`;
`set pyplot_python=<interp>` picks the interpreter (default `python3`).

`rcload.va` (a 1 kΩ OSDI conductance) is simulated; the verify runs a transient
`pyplot rc v(out) v(in)` and an AC `pyplot acmag db(v(out))`, then confirms the
generated matplotlib scripts render valid PNGs. Requires matplotlib installed.

**Enhancement-208 — `pyplot -eye`:** `pyplot [name] -eye <expr> -ui <T>` runs the
[`eye`](../eye_examples) analysis and renders the folded eye directly as a
persistence-style 2-D-histogram eye diagram (annotated with eye height / width /
jitter), honouring the same `pyplot_*` settings — the classic eye diagram in one
line. The verify drives a pseudo-random NRZ bit stream through a bandwidth-limiting
RC channel and checks the eye PNG renders.

Run: `python3 verify_pyplot.py` (17 checks, both solvers).
