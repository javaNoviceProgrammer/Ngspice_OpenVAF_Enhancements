# derivcx_examples — Enhancement-277

The COMPLEX branch of `cx_deriv` (`src/maths/cmaths/cmath4.c`) had several index bugs
its (correct) real branch did not -- each an out-of-bounds access on the last block and
a numerical error:

- the data window `c_indata[j + i + base]` was offset by `degree` from the fit's scale
  window `scale + i - degree + base` (misaligned fit + read past the end);
- the real-part output loop used `j <= i + degree/2` vs the `i - degree/2` used by the
  imag loop and the whole real branch;
- the tail indexed `scale[j + base]` / `c_outdata[j + base]` where the real branch uses
  `j` (its FIXME notes `j + base` crashed).

Fix: align the complex branch to the real branch. Every overflow is gone AND the complex
derivative is now numerically correct.

## Verify

```
python3 verify_derivcx.py
```

Three checks: `deriv((0.5,time))` runs clean; `deriv(t + 2t*i)` == (1, 2i) (correct);
a real `deriv(2t)` still == 2.
