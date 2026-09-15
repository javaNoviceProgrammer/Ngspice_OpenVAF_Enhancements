# intrange_examples — Enhancement-635

An integer parameter's real range bounds are compared as reals. `parameter
integer k from (0.5:2.5]` admits 1 and 2; the run-time check used to round the
bounds to the parameter's type first, so `(0.5:2.5]` became `(1:3]` (1 refused,
3 accepted), `(1.5:2.5)` became the empty `(2:3)` (even 2 refused), `exclude
2.5` excluded 3, and `inf` was `i32::MAX` (`from [0:inf)` refused 2147483647),
while the compile-time checks on the same range read the real bounds.

The suite pins the plain, inclusive/exclusive, `exclude`, `inf`,
parameter-referenced, instance-dependent, array and set forms, and the new
compile-time refusal of an integer range that no integer satisfies
(`from (1.5:1.9)`, `from (2:3)`).

Run: `python3 verify_intrange.py` (12 checks per solver, both solvers).
