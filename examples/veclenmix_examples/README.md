# veclenmix_examples — Enhancement-285

A vector's own length need not equal its plot SCALE's length -- any synthetic vector
(`let y = vector(8)` on a 66-point transient plot) carries the plot's scale -- and a
COMPLEX vector has `v_realdata == NULL` (the dvec union holds `v_compdata`). Four
output paths assumed otherwise:

- `plotit.c` passed `v->v_realdata` with the SCALE's length to `ft_interpolate()`,
  which indexes the data by that length (reading past a shorter vector), and passed
  NULL outright for a complex vector -- a hard SEGV (`asciiplot sqrt(-1*vector(10))`);
- `agraf.c` used the X-scale-bounded `lower`/`upper` indices to index each VECTOR;
- `gnuplot.c` (`wrdata`) bounded its loop by `scale->v_length` but indexed
  `v->v_realdata[i]`;
- `com_measure2.c` read `d->v_realdata[i]` on the tran/dc path with no NULL check
  (its ac/sp branches already had one) -- twice, in measure_at and measure_deriv_at.

Fix: clamp each index to the vector it addresses, skip the transient resampling when a
vector is not real, and take the real part for a complex measure input. Ordinary plot
and wrdata output are byte-identical to before.

## Verify

```
python3 verify_veclenmix.py
```

Seven checks: short / long / complex vectors through asciiplot, wrdata of a short
vector, a measure over a complex vector -- all clean; ordinary asciiplot and meas
unchanged.
