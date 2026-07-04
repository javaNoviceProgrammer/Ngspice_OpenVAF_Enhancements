# varinit_examples — variable initializers, completed (Enhancement-43)

Demonstrates **declaration initializers** (`real x = 2.5;`) — evaluated once at
the start of the simulation, LRM semantics — using the committed
`openvaf-r` and `ngspice-46`.

## What was broken

Scalar initializers (including parameter-dependent constant expressions and
strings) already worked, with correct init-once semantics for event-updated
state. Three defects remained:

1. **Array declaration initializers were rejected** — `real x[0:2] =
   '{1.0, 2.0, 4.0};` failed with "expected real value but found real[0:3]
   value", repeated once per element (each expanded element variable checked
   the *whole* aggregate against its scalar type).
2. **An analog-function argument without a type declaration crashed the
   compiler** — `input v;` with no `real v;` line yielded `Type::Err`, which
   hit `unreachable!("unknown cast found Real -> Err")` at the first cast.
3. **A wrong-arity initializer crashed the compiler** — `real x[0:2] =
   '{1.0, 2.0};` (and the array-*parameter* equivalent) lowered the missing
   leaves as `Expr::Missing` and died with "invalid HIR: Missing".

E-43 wires array-variable initializers through the same split-literal
machinery as array parameters (each element carries its flat row-major
`array_index` and picks its leaf), defaults untyped function arguments to
`real` (matching the untyped return type), and adds a named arity diagnostic
covering variables *and* parameters.

## Run

```
python3 verify_varinit.py
```

Checks (ALL PASS, exact): scalar/param-dependent/string inits, `y = 2*p+1`
tracking a `p` override; init-once counter starting at 10 and counting
crossings; 1-D real + integer, 2-D, 3-D arrays and parameter-dependent leaves
(66 + 4·s) tracking an `s` override; an array element initialized to 100 and
event-updated from there; function-local scalar + array initializers with an
untyped argument (used to ICE); and four wrong-arity forms rejected with
`array initializer for 'x' has N elements but the array has M` instead of a
crash.
