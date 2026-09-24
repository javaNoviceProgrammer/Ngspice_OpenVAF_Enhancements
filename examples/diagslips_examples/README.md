# diagslips_examples — eleven diagnostic slips from the 2026-09-16 hunt (Enhancement-650)

Forty-six checks per solver — thirty-two from Enhancement-650 and fourteen from [Enhancement-708](../../enhancements_doc/Enhancement-708.md) (below) — run under both KLU and Sparse by `_setup.check_both_solvers`.

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

## Enhancement-708 — four more slips, from the robustness campaign of 2026-09-23 (F10)

Checks [33]–[46], **36/46** on the E-704 binaries: a based literal wider than its size
draws L030 with its bit count and the value it reads as (`'hFFFFFFFFFF`: "40 significant
bits, more than the 32 of an `integer` … it reads as -1"; `'h1FFFFFFFF`; `8'hFFF` against
its declared size; `'d4294967296`), a 100 000-digit literal is measured and abbreviated,
`'hFFFFFFFF`, `'h0FFFFFFFF` and `8'hFF` are silent, `-A L030` silences it; `` `include ""
`` is "names no file" and not "is a directory"; `$sformat(s, "%999999999d", 1)` and a
20-digit precision are refused as above the limit of 4096 with the digits as written,
`%4096d` and `%08.3f` compile, and a `*` width of 100 000 prints a 4096-wide field at run
time; and a deck-fixed NaN and a deck-fixed infinite `laplace_nd` highest-order
coefficient are each refused as "must be a finite non-zero number, but is nan/inf" — the
NaN was called "zero", the infinity ran the filter as a silent 0.
