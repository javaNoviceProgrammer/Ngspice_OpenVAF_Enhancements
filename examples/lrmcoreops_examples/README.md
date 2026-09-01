# lrmcoreops — core analog operators vs. the LRM (Enhancement-523)

An LRM-2023 conformance audit of clause **4.5** found the delay, ddx and
idtmod operators each cutting a corner. This suite pins the fixes:

- **`absdelay` freezes td** (4.5.7): with no maxdelay, "the value of the
  delay argument td when the module instance is initialized shall be
  used" — a time-varying td expression was *tracked* instead. The
  two-argument form now latches td at the first transient evaluation
  (checked as `v(o)@5.99m` = 4.99, where tracking gave 3.99), while the
  maxdelay form keeps tracking within its bound, the DC pass-through is
  exact, and the AC phase is `-2πf·td` to four digits.
- **`ddx` by the unnamed-branch flow** (4.5.6, Table 4-16): `I(n1,n2)`
  *is* the flow of the unnamed branch between n1 and n2, but the form
  was refused ("declare a named branch"). It differentiates now:
  `ddx(I², I) = 2I` exactly, the reversed orientation negates, and a
  flow that is not a system unknown gives exactly 0.
- **`idtmod` defaults its ic to 0 and forces DC** (4.5.5): `idtmod(x)`
  left the integrator unconstrained — a singular matrix regularized to
  an arbitrary value. It now pins the DC output to 0 exactly, like
  `idtmod(x, 0)`.
- A negative constant `td` stays a targeted compile error.

Run `python3 verify_lrmcoreops.py` — 18 checks, both solvers.
