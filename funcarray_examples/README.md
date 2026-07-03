# funcarray_examples — array syntax + arrays in analog functions (Enhancement-18)

Demonstrates the two Enhancement-18 features together, using **version11's own**
`openvaf-r` and `ngspice-46`:

1. **Standard array declaration syntax** `real coeffs[0:3];` — the LRM
   *name-then-range* form, complementing the existing *range-then-name*
   `real [0:3] coeffs;`.
2. **Array support in analog functions** — an `analog function` that takes a whole
   **array argument** (`input a; real a[0:3];`) and indexes it (here with a loop
   variable, i.e. a dynamic index).

`funcarray_demo.va` is a polynomial transfer stage `V(out) = 0.5·V(in) + 0.3·V(in)²`,
evaluated inside an array-argument function `polyeval(x, a)` by Horner's rule. The
whole coefficient array is passed by name: `polyeval(V(in), coeffs)`.

## Run

```
python3 verify_funcarray.py
```

Expected:

```
DC: V(out) = poly(V(in)) via array-arg function    max err ~1e-16  PASS
AC: gain = poly-prime(bias) through the function   max err ~1e-16  PASS
```

The AC check is the important one: the small-signal gain `dV(out)/dV(in)` equals
`poly'(bias) = 0.5 + 0.6·bias`, i.e. the derivative flows through the array-argument
function into the Jacobian — array-argument functions are ordinary differentiable
code, not a black box.

## What works (and what doesn't)

Array **locals** and array **arguments** inside `analog function`s are supported,
with constant *and* dynamic indexing, in 1-D and multi-dimensional forms. Whole
arrays are passed **by name** to array-typed formals; the callee's element
variables are bound from the caller's array elements.

- Array arguments are **input** (pass-by-value of the elements); writing back to a
  whole array `output` argument is not supported.
- Both array-declaration spellings are accepted everywhere: `real x[0:n];`
  (name-then-range) and `real [0:n] x;` (range-then-name), including per-variable
  dimensions in a mixed declaration (`real g, w[0:1], k;`).
