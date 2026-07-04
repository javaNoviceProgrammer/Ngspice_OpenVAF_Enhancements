# arraycase_examples — array `case` + array-literal function args (Enhancement-33)

Demonstrates **element-wise array `case` statements** and **array literals as
function arguments**, using **the committed** `openvaf-r` and `ngspice-46`.

## What was broken

Retiring the compiler's last `todo!()` stubs uncovered four related defects:

- `case` over an array **crashed the compiler** (`not yet implemented` panic) even
  though type inference accepted it;
- an **integer**-array discriminant additionally hit `invalid int operation feq`
  (whole-array variables were typed `real` regardless of element type);
- an array **literal** passed as a whole-array function input compiled but silently
  bound nothing — `sum2('{1.0, 2.0})` returned **0** instead of 3;
- an array literal passed to an array **output** argument was silently accepted and
  the writeback skipped (scalars were always properly rejected).

## The fix

`case` on arrays compares **element-wise** (an arm matches iff all elements are
equal), for literals and whole-array variables, real and integer. Function inputs
accept array literals via the same shared element-lowering helper
(`lower_array_elems`); whole-array variables now carry their true element type;
array output args require a caller variable. Pure front-end change. See
`../Enhancement-33.md`.

```verilog
case (st)                    // st is integer st[0:1]
  '{0, 0}: g = 1e-3;
  '{1, 0}: g = 2e-3;
  '{1, 1}: g = 3e-3;
  default: g = 9e-3;
endcase
scale = sum2('{0.25, 0.75}); // array literal argument -> 1.0 (was silently 0)
```

## Run

```
python3 verify_arraycase.py
```

Checks (ALL PASS): compiles (used to panic); the integer-array `case` selects all
three regions in a DC sweep (proving the literal argument reads 1.0, not 0); a
real-array `case` matches; an array literal to an array output argument is
rejected with a proper type error.
