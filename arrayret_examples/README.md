# arrayret_examples — array return values from analog functions (Enhancement-23)

Demonstrates **array return values** from `analog function`s, using **version11's
own** `openvaf-r` and `ngspice-46`. This completes the array-in-functions arc:

- **Enhancement-18** — array **arguments** (input, by value)
- **Enhancement-20** — array **output/inout** arguments (write-back)
- **Enhancement-23** — array **return values** ← this folder

## Syntax

```verilog
analog function real[0:n] f;   // return type carries array dimensions
    ...
    f[i] = ...;                // the body writes the return array's elements
endfunction
...
real c[0:n];
c = f(args);                   // the whole returned array is copied into c
```

`arrayret_demo.va` implements a cubic polynomial device `I = c0 + c1·V + c2·V² +
c3·V³` two ways:

- **`polyret`** — a function `powers(x)` **returns** the array `{1, x, x², x³}`,
  summed with the coefficients at the call site;
- **`polyret_arg`** — the returned array is fed straight into an array-**argument**
  function (E-18), composing an array return with an array argument in one
  expression.

## Run

```
python3 verify_arrayret.py
```

Expected (`ALL PASS`): for both modules and across a bias sweep, the DC current
matches the closed-form polynomial (~1e-9) and the AC conductance matches the
exact derivative `gm = c1 + 2·c2·V + 3·c3·V²` (~1e-9) — i.e. the autodiff
Jacobian flows through the array return.

## Notes / limitations

- An array-returning function call is only valid as the whole right-hand side of
  an array assignment (`c = f(...)`); it can't be used as a sub-expression.
- The destination must be a writable array **variable** of the same length as the
  return array; a length mismatch is a compile-time type error.
- The return array's element variables are function-local (written by the body,
  then copied into the caller's array), so the derivative flows through exactly
  as for array arguments (E-18) and output arguments (E-20).
