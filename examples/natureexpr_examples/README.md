# natureexpr_examples — a nature or discipline attribute value is a constant expression (Enhancement-649)

Twenty checks per solver, run under both KLU and Sparse by `_setup.check_both_solvers`.

LRM A.1.6: `nature_attribute_expression ::= constant_expression | nature_identifier |
nature_access_identifier`. openvaf-r folded an attribute value with a folder that sees one
literal and an optional sign, so `abstol = 1e-3*1e-3` was refused as "not a real constant"
and the nature was left with no abstol at all, while a user-defined attribute spelled the
same way reached the `.osdi` tables with no value, in silence.

Accepted, with the folded value stamped on the node by ngspice's convergence test (E-539)
and equal to what the model reads back from `p.potential.abstol`: `1e-3*1e-3`, `(1e-6)`,
`1e-6/1000`, `2.0**-20`, `-(-1e-6)`, a `` `define `` in arithmetic, `1e-6+0.0` (which E-422
had pinned as refused), a real remainder, a discipline's `potential.abstol = 1e-3*1e-3`
override, and a literal as before. Folded and then refused by value, with the LRM's operand
rules: `1/1000000` and `10**-6` are the integer 0, `-7.5 % 2` is -1.5, `1.0/0.0` is inf and
`0.0/0.0` is NaN. Still not a constant, now with a help line naming what folds: a string, a
name, a function call. A `[msb:lsb]` bound shares the folder (E-405) and takes `**` and
`<<<`.

```bash
python3 examples/natureexpr_examples/verify_natureexpr.py
```
