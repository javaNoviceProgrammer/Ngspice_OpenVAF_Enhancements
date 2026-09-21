# lrmfilters — filter operators vs. the LRM (Enhancement-524)

An LRM-2023 conformance audit of clauses **4.5.8–4.5.15** found the
`transition` defaults ignoring the LRM's own rules and a silent
deviation in the laplace filters. This suite pins the fixes:

- **Explicit zero honors `` `default_transition ``** (4.5.8): "if
  neither rise_time nor fall_time are specified *or are equal to zero*,
  the rise and fall time default to the value defined by
  `` `default_transition ``" — `transition(s, 0.0, 0.0)` under a 1u
  directive used to step instantaneously; it now ramps over 1u
  (mid-ramp 0.5 at 1.5u, done by 2.1u).
- **Bare `transition(x)` with no directive filters** (4.5.8): it used
  to pass its input through completely unfiltered. It now applies a
  negligible-but-nonzero ramp: DC is an exact pass-through and a
  transient settles to target within nanoseconds; the delay-only
  `transition(x, td)` form routes the same way.
- **Dynamic laplace coefficients are audible** (4.5.14, Table 4-20):
  the coefficient vectors are constant-class arguments the LRM freezes
  at analysis start; this implementation re-evaluates them, so a
  solution-dependent coefficient TRACKS — that deviation now draws a
  warning naming the filter, while parameter-built coefficients stay
  silent. With the coefficient held constant the filter is verified as
  the matching fixed lowpass (|H| = 0.7071 at the corner).
- The 4-arg `transition` ramp takes `rise_time` whatever the swing
  (4.5.8): a 0 → 2 step is at 1.0 half way through its 1 µs and at 2.0
  after it. Until [E-698](../../enhancements_doc/Enhancement-698.md) the
  operator ran at the fixed rate `1/rise_time` (1.0996 at 2.1 µs), an
  approximation this suite pinned as the shipped contract.

- **A z-filter root at the origin is the factor `z`** (4.5.12): "if a
  root (a pole or zero) is zero, then the term associated with it is
  implemented as z, rather than (1 − z⁻¹ r)". Since
  [E-699](../../enhancements_doc/Enhancement-699.md) a `zi_zp`/`zi_zd`/`zi_np`
  pole at the origin is the one-period delay and a zero the one-period
  advance the clause makes them (phase −0.49 / +0.49 rad at ωT = 0.5,
  the `zi_nd` spelling's values); the root expansion used to build the
  term 1, so `zi_zp(x, , '{0, 0}, T)` was a wire. On the unit circle only
  the phase shows the missing factor, which is what the checks read.

Run `python3 verify_lrmfilters.py` — 22 checks, both solvers.
