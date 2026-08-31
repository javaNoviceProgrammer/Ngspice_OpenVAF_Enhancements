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
- The 4-arg `transition` amplitude approximation (E-512's documented
  contract) is re-pinned so any change to it is caught here.

Run `python3 verify_lrmfilters.py` — 14 checks, both solvers.
