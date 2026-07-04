# defaulttransition_examples — `default_transition (Enhancement-47)

Demonstrates the **`` `default_transition``** compiler directive — the default
rise/fall time for `transition()` filters that omit those arguments — using the committed
`openvaf-r` and `ngspice-46`.

## What was broken

- `` `default_transition 1u`` was a **hard error** ("macro
  '`default_transition' has not been declared") — the preprocessor treated it
  as an undeclared user macro, unlike `` `default_discipline`` which it
  deliberately captures. Now the directive is recognized, its value parsed
  (SI suffixes and `_` separators included) and recorded (last directive wins,
  file-level granularity), exposed through the `CompilationDB`, and used by
  `transition()` lowering for the no-args and delay-only forms; explicit
  rise/fall arguments always win, and without a directive the default stays 0
  (instantaneous), per the LRM.
- **Pre-existing crash**: the TRANSITION signature table was one argument
  short per entry — a 3-argument `transition(s, td, trise)` crashed the
  compiler (`args[3]` out of bounds), 4-argument calls only worked by accident
  through the tol signature, and the true 5-argument tol form didn't resolve.
- **Pre-existing DC singularity**: the slew/transition tracking loop's clamp
  has a zero derivative when saturated, so the operating point was singular
  (garbage transient without `uic`) whenever the input started a full swing
  away from the filter state. In DC the filter is now the LRM's static
  identity (`y = x`), selected via the integration-enable parameter.

## Run

```
python3 verify_defaulttransition.py
```

Checks (ALL PASS): bare `transition(s)` under `` `default_transition 1u``
ramps over exactly 1 µs (half-cross at 0.5 µs) with a clean DC operating point
(no `uic`, no singular matrix); the delay-only form delays 0.2 µs then ramps
with the default; explicit rise times win over the directive; all five
arities compile and run (including the previously-crashing 3-argument and the
previously-unresolvable 5-argument forms, weighted sum 0.875 exact); without
the directive the bare form stays instantaneous; and a directive inside a
false `` `ifdef`` is correctly ignored.
