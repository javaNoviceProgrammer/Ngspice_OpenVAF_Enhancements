# hypotzero_examples — `hypot` and `atan2` have a finite derivative at the origin

The 2026-09-07 compiler hunt's F1
([write-up](../../docs/bug_hunts/2026-09-07_openvaf-r-language-semantics.md)), fixed by
Enhancement-580. Run `python3 verify_hypotzero.py`; 15 checks per solver, 11 of them
passing against the shipped compiler.

`hypot(x, y)` was differentiated as `(x·x' + y·y') / hypot(x, y)`, which is 0/0 at the
origin, and `atan2(y, x)` as `(x'·y − y'·x) / (x² + y²)`, which is 0·∞ there. V = 0 is
ngspice's DC initial guess, so any contribution taking `hypot` or `atan2` of node
quantities failed every operating-point method on its first Newton iteration — while
`abs`, `sqrt` and `pow` at zero had been guarded for a long time (Enhancement-261's
`sqrt(x + 1e-18)`). The two caches are now `hypot(hypot(x, y), 1e-18)` and
`1/(x² + y² + 1e-36)`: finite at the origin (the derivative there is 0, the value of the
smooth |x|), and below the ULP for any radius above 1e-9 and 1e-10 respectively.

| check | what it pins |
|---|---|
| [1] the origin | `hypot(V, 0)`, `hypot(Va, Vb)`, `atan2(Vb, Va)` and their sum, each as a current contribution, solve at V = 0 with a zero small-signal conductance |
| [2] away from the origin | at (0.3, 0.4), d hypot/dx = x/h = 0.6 and d atan2(y,x)/dx = −y/(x²+y²) = −1.6, their sum −1.0; hypot(V, 0) has slope 1 at 0.5; at a radius of 1e-6 the slope is still x/h to 1e-12, so the regularisation is invisible there |
| [3] the neighbours | `abs(V)` at 0 has slope 1, `sqrt(V·V)` slope 0, `sqrt(V)` the E-261 large finite slope; transients of `hypot(Va, Vb)` and of the sum sweep Va through the origin |

A constant zero argument never showed the atan2 half: `atan2(V, 0.0)` folds the
constant away before the chain rule runs, which is why the hunt's probe with a
literal 0 passed while two node voltages fail.
