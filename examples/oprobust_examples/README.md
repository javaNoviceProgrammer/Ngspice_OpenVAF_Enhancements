# oprobust_examples — Enhancement-568: operating-point robustness

`verify_oprobust.py` pins, under **both** linear solvers (KLU and Sparse 1.3),
the four operating-point defects found by the 2026-09-06 OP torture battery:

| | before | now |
|---|---|---|
| R1 VCVS gain 1e6 in unity feedback | 4 Newton iterations, then declined by the false-convergence guard: 127 gmin iterations under KLU, Sparse tripping from gain 1e8 | plain Newton, 4 iterations, up to gain 1e9 |
| R2 `E … TABLE` Schmitt trigger | 38 000 iterations across gmin, source stepping and optran, then failure | plain Newton, 16 iterations |
| R3 `.nodeset v(out)=100` on a 3 V diode clamp | 2160 (Sparse) / 1400 (KLU) iterations, six "singular matrix" reports under KLU only, NaN in the abandoned solves | 229 iterations, both solvers alike, no report |
| R4 two behavioural voltage sources in a ring | 37 673 iterations, then "could not be simulated" | 53 iterations through the new last-resort damped-Newton rung |
| R5 source stepping's exit (Enhancement-734) | left `CKTdiagGmin` at gmin: a 1e11 Ω divider read 0.476 V through the transient after it, a 1e14 Ω node beside an inductor across a source 990 V, an unsolvable source loop "succeeded" under Sparse with 1/gmin amperes | the transient and the dc sweep after a forced source stepping read 0.5 V, the 1e14 Ω node 1e5 V, the loop is refused on both solvers |

Run it:

```
python3 verify_oprobust.py
```

Decks that must **not** change are pinned beside them: a TABLE op-amp in
negative feedback, a seven-point table in a loop, the Schmitt's transient
switching thresholds, a BJT flip-flop whose `.nodeset` picks the state, and the
tanh bistable pair that plain Newton solves in three iterations.
