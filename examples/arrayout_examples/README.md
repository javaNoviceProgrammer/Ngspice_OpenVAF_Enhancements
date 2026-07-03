# arrayout_examples — array output/inout function arguments (Enhancement-20)

Demonstrates **`output`** and **`inout`** array arguments to `analog function`s,
using **version11's own** `openvaf-r` and `ngspice-46`. This completes
Enhancement-18's array-argument support, which was input-only (a whole array
could be passed *in* but a function couldn't write one back).

`arrayout_demo.va`:

- **`make_taps`** fills a 4-tap geometric array `1, ratio, ratio², ratio³` via an
  **output** array argument;
- **`normalize`** scales that array in place (so the elements sum to 1) via an
  **inout** array argument.

The gain is the sum of the normalized taps, which is `1` by construction for any
`ratio`, so `V(out) = V(in)` — but **only if both writebacks reach the caller's
array**. A broken output write leaves the taps zero; a broken inout write leaves
them unnormalized; either way the gain would be wrong.

## Run

```
python3 verify_arrayout.py
```

Expected:

```
 ratio  V(out) (=gain, V(in)=1)   expected  result
   0.3              1.000000000        1.0  PASS
   0.5              1.000000000        1.0  PASS
   0.8              1.000000000        1.0  PASS
   1.0              1.000000000        1.0  PASS
   1.5              1.000000000        1.0  PASS
ALL PASS
```

## Notes

- A whole array passed to an `output`/`inout` array argument must be a writable
  array **variable** (the callee's element variables are copied back into it after
  the function body runs). `input` array arguments (Enhancement-18) pass by value.
- Combines with everything else: the functions here use array locals, dynamic
  indexing, and `for` loops over the array arguments.
