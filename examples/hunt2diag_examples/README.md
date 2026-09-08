# hunt2diag_examples — five compiler findings of the 2026-09-07 hunt (Enhancement-588)

```
python3 verify_hunt2diag.py
```

15 checks, both solvers.

| finding | before | now |
|---|---|---|
| F5 `I(<a[1]>)` | *unexpected token '[' expected '>'* | a port-branch probe on a bus element, in expressions and in `branch (<a[1]>) b;`; an out-of-range element is refused |
| F6 a parameter named `m`, `temp`, `dtemp`, `dt` | took over ngspice's reserved instance parameter silently (`m=4` no longer multiplied, `temp=100` never reached `$temperature`) | lint **L029** `reserved_parameter_name` (warn), case-insensitive |
| F7a a discrete-set range | ngspice said *range from 1 from 2 from 4* | the bounds text keeps the set: *range from {1, 2, 4}*; intervals unchanged |
| F7f `noise_table` with a frequency twice | compiled, held the first power everywhere | refused, naming the frequency; an unsorted table stays legal |
| F7h `case (s) endcase` | compiled | a syntax error at the `endcase` |
