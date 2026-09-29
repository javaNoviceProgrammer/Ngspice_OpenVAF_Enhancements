# progressbar_examples — the "Reference value" progress line (Enhancements 129, 184, 761)

```
python3 verify_progressbar.py
```

25 checks, one solver (a front-end output feature: the bar bytes do not depend on the
linear solver). 23 of 25 on the E-760 binary.

Sections [1]–[5] are Enhancement-129 and Enhancement-184: each of tran, ac, dc and noise
draws `[====    ] NN%` after the reference value, the percentage matches the analytic
sweep fraction, the fill is proportional, the sequence is monotone and ends at 100 %, and
an operating point draws no bar.

Section [6] is Enhancement-761: the output path used to query the free memory (a Mach
`host_statistics` call and a port trap on macOS), read `clock()` (a `getrusage` system
call) for this line's quarter-second throttle, and look `no_mem_check` up by name on
every accepted point — about a microsecond a point, 48 % of a 600 000-point transient,
compiled or built in. The memory check now runs only when the output vectors are about
to grow, the variable is re-read when the variable lists change, and the throttle reads
the wall clock through `seconds()`. The checks: a 1.2 M-point built-in RC transient
spends under 3× the timed phases (load, factor, solve, trunc) outside them and under
1.5 µs per accepted point (the E-760 binary: 4.6× and 1.8 µs), and the progress line is
drawn between 2 and 12 times over the run.
