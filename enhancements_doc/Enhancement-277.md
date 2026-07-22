# Enhancement-277 — ngspice: `deriv()` of a complex vector — fix a heap overflow and a wrong result

The expression-layer fuzz flagged `src/maths/cmaths/cmath4.c:314` on
`deriv((0.5,time))` (a complex input). Investigation showed the **complex** branch of
`cx_deriv` had several index bugs that its **real** branch did not — the real branch
is correct, so it served as the reference.

## The bug

`cx_deriv` computes a derivative by fitting a degree-`d` polynomial over a sliding
window. The complex branch diverged from the real branch in three places, each an
out-of-bounds access on the last block **and** a numerical error:

1. **Data window misaligned.** It read `c_indata[j + i + base]` while fitting against
   the scale window `scale + i - degree + base` — offset by `degree`. So it both fit
   mismatched *(x, y)* pairs and read `degree` points past the end of the input
   (AddressSanitizer heap-buffer-overflow READ). The real branch reads
   `indata + i - degree + base`.
2. **Output loop over-ran.** The real-part output loop used `j <= i + degree/2`,
   where the imaginary-part loop and the entire real branch use `j <= i - degree/2`,
   overrunning `scale[]` / `c_outdata[]`.
3. **Tail loop over-ran.** The tail indexed `scale[j + base]` / `c_outdata[j + base]`;
   the real branch's tail uses `j` (its own FIXME comment notes `j + base` crashed),
   so a grouped (`base > 0`) complex derivative overran both arrays.

## Fix

`src/maths/cmaths/cmath4.c`: align the complex branch to the real branch — read
`c_indata[j + i - degree + base]`, bound the real-part output loop with
`i - degree/2`, and index the tail with `j`. This removes every overflow **and**
makes the complex derivative numerically correct.

## Verification

`examples/derivcx_examples/verify_derivcx.py` (3 checks): `deriv((0.5,time))` runs
with no overflow; `deriv(t + 2t·i)` now returns `(1, 2i)` — the correct derivative,
mid-vector; and a real `deriv(2t)` still returns `2`. A focused `deriv` stress over
complex / real / grouped inputs is clean under ASan.

## Scope

One source file (`src/maths/cmaths/cmath4.c`), complex branch only. Real derivatives
are unchanged; complex derivatives are now both memory-safe and correct.
