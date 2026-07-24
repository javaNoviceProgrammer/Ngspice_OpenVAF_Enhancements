# `.meas AVG` window reaches `to` (Enhancement-316)

A sibling of [E-302](../../enhancements_doc/Enhancement-302.md)/303/304 found by oracle-checking
`.meas`: `AVG` must equal `INTEG/(to−from)` over the same window. `measure_minMaxAvg()`'s final
window-clip guarded the whole accumulation with `!AlmostEqualUlps(svalue, to, 100)`, so when the
first out-of-window sample fell within 100 ULPs of `to` the entire final trapezoid `[sprev, to]`
(a full timestep) was dropped — AVG ended one timestep short of `to` and disagreed with INTEG by
~1.6%. INTEG/RMS always add the final point; the fix makes AVG do the same (the guard now gates
only the interpolation). See the write-up.

## Verify

```sh
python3 verify_measavgwin.py
```

Two checks, both failing on the pre-fix binary: AVG equals INTEG/(to−from), and AVG's echoed
window reaches `to`.
