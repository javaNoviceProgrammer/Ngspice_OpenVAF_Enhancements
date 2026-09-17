# intformal_examples — a real converts into an integer function input, and a real `case` item matches an integer selector (Enhancement-647)

Nineteen checks per solver, run under both KLU and Sparse by `_setup.check_both_solvers`.

LRM 4.7.3 assigns a call's actual to the formal and 4.2.1.1 rounds a real assigned to
an integer; openvaf-r did that for assignments, `repeat` counts, integer returns and
array elements, yet an integer input formal given a real was a type error, and LRM
5.8.3's `case` refused a real item under an integer selector while it accepted an
integer item under a real one.

The checks: real literals into an integer input formal round as the LRM says (2.7,
−2.5, 0.5, 1.5 → 3, −3, 1, 2); a real variable and a node expression convert; an
integer into a real formal is unchanged; mixed formals in one call; an integer or
boolean selector with a real item is compared as real (2.0 matches 2, 2.5 does not,
an integer item beside it still matches, a real parameter item matches); a real
selector with an integer item, `casez` masks and an array `case` are unchanged. Still
refused, by the same messages as before: a real seed for `$rdist_normal`, a real shift
distance, an integer output formal bound to a real variable, a string into an integer
formal, a string selector with a real item.

```bash
python3 examples/intformal_examples/verify_intformal.py
```
