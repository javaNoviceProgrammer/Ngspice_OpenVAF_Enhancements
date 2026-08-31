# lrmexpr — expressions & math vs. the LRM (Enhancement-518)

An LRM-2023 conformance audit of clauses **4.1–4.4** found two bugs, three
deviations, and a latent undefined-behavior hazard. This suite pins the fixes:

- **Same-node branch access is an error** (4.4, Table 4-16): `V(a,a)` and
  `I(a,a)` are located errors ("the operands of an expression shall be unique
  to define a valid branch") — `V(a,a)` used to compile silently and read 0.
  A hierarchy-**flattened** diode-connected instantiation stays legal, and a
  *named* degenerate branch declaration keeps its warning.
- **`%` by a deck-supplied zero** (4.2.4): aborts with an `OSDI(fatal)`
  naming the operator and the clause (was a silent NaN plus a generic
  convergence failure). A genuinely runtime zero divisor evaluates to the
  defined 0 instead of LLVM UB that SIGFPEs on x86 — and `INT_MIN/-1` wraps.
- **Shift distances** (4.2.11): the distance is unsigned with no upper bound,
  so `1<<32` is legal and equals 0 — now a warning plus the LRM value, with
  the compile-time and runtime paths agreeing (`-8>>>34` gives the sign
  fill). `<<<`/`>>>` stay as a **flagged extension** (each use warns).
- **Case (in)equality** (4.2.6): `===`/`!==` lex and evaluate as 2-state
  `==`/`!=` (they died with a parse error that never named the operator).

Run `python3 verify_lrmexpr.py` — 22 checks, both solvers.
