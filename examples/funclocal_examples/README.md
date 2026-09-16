# funclocal_examples — an analog function's local variables start every call afresh (Enhancement-646)

Twelve checks per solver, run under both KLU and Sparse by `_setup.check_both_solvers`.

A function body is inlined at its call site, so its locals were module variables and a
read before the call's own write reached the value left by the previous call or the
previous Newton iteration: `integer n; n = n + 1; cnt = n;` counted every evaluation
(1074 at one operating point, reached through gmin stepping), a declared initializer
applied once, a named block's local the same. The return variable (LRM 4.7.2.1) and
the output arguments (4.7.2.2) were already fresh per call.

The checks: the counter local is 1 at the operating point without gmin stepping and at
every point of a transient; two calls in one evaluation each start at zero; a declared
initializer (`integer n = 5;`) applies at every call; a string local is the empty
string; a named block's local is zero; a local array starts at zeros and accumulates
within the call; a return array's unwritten elements are zero on the next call; a
local inside a `$limit` limiting function; two instances; and a local written before
it is read is unchanged.

```bash
python3 examples/funclocal_examples/verify_funclocal.py
```
