# seedexpr_examples — Enhancement-642

A literal or computed seed for the analog random functions. LRM Syntax
9-8/9-9 let the seed of `$arandom` and of the `$dist_*`/`$rdist_*` family be
an integer variable, an integer parameter or `[sign] decimal_number` — the
LRM's own §6.4.1 example seeds with literals — but the compiler admitted only
the first two: `$rdist_normal(7, 0, 1)` was "expected integer variable
reference or integer parameter ref but found integer literal", and so was the
IHP corner modules' `seed + 3`. Under the E-10 design a draw is a pure
function of the seed's value and the call site, so any integer expression
serves; `seed + i` inside a loop is a fresh draw per iteration, which lint
L019 `rng_in_loop` now recognises (a seed the loop changes is not reported).
`$random` keeps Verilog's variable-only seed; a real seed is refused.

Run: `python3 verify_seedexpr.py` (7 checks per solver, both solvers).
