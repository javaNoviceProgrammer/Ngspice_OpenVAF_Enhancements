# diagslips_examples — eleven diagnostic slips from the 2026-09-16 hunt (Enhancement-650)

Thirty-two checks per solver, run under both KLU and Sparse by `_setup.check_both_solvers`.

Each item is a message that blamed the wrong thing, said nothing, or said "encountered
unexpected token!" for an input that deserved its own sentence. Now: a contribution across
two disciplines (`Pwr(p,n) <+ 1.0` with `electrical p; thermal2 n;`) names the incompatible
disciplines instead of "expected nature access such as V(foo)"; `` `endif ``/`` `else ``
with no `` `ifdef ``, a `\` continuation followed by white space (counted) and a NUL byte
each get their own sentence; `` `line `` is warned about (it moves `` `__LINE__ `` only,
diagnostics keep the physical position); an unknown lint name in `openvaf_allow` on a
declaration, a module or a statement is refused, with a "did you mean" for a near miss;
`from {1, 2.5}` on an integer parameter is refused (no integer equals 2.5) and
`exclude {2.5}` warns; `.5` gets LRM 2.6.2's sentence like `5.`; `"\777"` is refused (an
octal escape names one 8-bit character) and `\q`/`\x41` are warned about while still kept
verbatim (E-48's contract); `%m` inside an inlined child prints the hierarchical instance
name (`na1.l1.l2`, `na1.l1.arr[0]`); a bad `-D` argument is refused on the command line
by shape, and a value that fails to parse names the argument it came from; a file that
includes itself is named at the include, not blamed on `disciplines.vams` 64 levels down;
`` `define G() `` says the formal list is empty; and "attriubte" is spelt right.

```bash
python3 examples/diagslips_examples/verify_diagslips.py
```
