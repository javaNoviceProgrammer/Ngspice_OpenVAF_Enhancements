# paramarrayarg_examples — a parameter array as an array argument, and a paramset binding an array parameter (Enhancement-645)

Twenty-three checks per solver, run under both KLU and Sparse by `_setup.check_both_solvers`.

**Functions.** `parameter real c[0:2]` fed to `input [0:2] a; real a[0:2];` (LRM 4.7.1
Example 3's shape) binds the formal and the call sums the array; a card value for one
element (`c[1]=20`) reaches the call; a 2-D parameter array binds a 2-D formal; an
integer parameter array binds an integer formal; the Jacobian flows through the
argument (`ddx` of a polynomial in the array is `c0 + 2 c1 V`). A variable or parameter
array of the wrong size is refused as "array argument has 4 elements but the
function's formal declares 3" (the old message blamed a missing bit-select); an
`output` or `inout` formal fed a parameter array is refused as "output argument bound
to parameter array 'c', which cannot be written", once.

**Paramsets.** `.c = '{10.0, 20.0, 30.0};` binds every element to its leaf; a bound
element is no longer settable from the card (warned, value kept); a literal of the
wrong length, or a scalar, is refused with the element counts; an element outside the
declared range is refused by its element name (`'c[1]' the value 50`); the paramset's
own parameters may appear in the leaves, from the card and from the instance line
(the E-644 route, `alter`); a 2-D array binds row-major; the E-563 fold (an
out-of-module reference beside the array) keeps the binding; a `localparam` array is
refused as not a parameter, once; an unknown name beside a bound array is still
reported.

```bash
python3 examples/paramarrayarg_examples/verify_paramarrayarg.py
```
