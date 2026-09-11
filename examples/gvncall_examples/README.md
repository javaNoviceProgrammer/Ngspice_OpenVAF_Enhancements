# gvncall_examples — Enhancement-596

Global value numbering compared a call expression with itself: the `Opcode::Call`
arm of `GVNExpression::eq` read both payloads from `self`, so two side-effect-free
calls that met in the same hash-table probe were declared equal whatever the callee
and the arguments, and the later call was replaced by the earlier one's value. A
model reading `$simparam("gmin")` and nine `$simparam(name, -1)` got gmin back for
the tenth. The suite reads ten simparams, twelve string compares and eight `ddx()`
partials back through ngspice and checks each is its own value, and that the object
carries every name literal.

Run: `python3 verify_gvncall.py` (7 checks per solver, both solvers).
