# Enhancement-524: the transition and laplace filter defaults, squared with the LRM

**Scope:** Accellera VAMS-2023 clauses 4.5.8–4.5.15 (the filter
operators), from the full LRM conformance audit: two `transition`
default rules the implementation skipped, and the laplace
constant-argument deviation made audible.

**Suite:** [`examples/lrmfilters_examples/`](../examples/lrmfilters_examples/)
— 14 checks, both solvers. The `defaulttransition`, `transedge`,
`lrmops`, `laplace`, `complexpole`, `arraycast` and `zi`-family suites
all still pass.

## An explicit zero rise time skipped `default_transition (compiler)

LRM 4.5.8: "If neither rise_time nor fall_time are specified **or are
equal to zero (0.0)**, the rise and fall time default to the value
defined by `` `default_transition ``." The lowering clamped
non-positive times to zero *before* consulting the directive, so
`transition(s, 0.0, 0.0)` under `` `default_transition 1u `` stepped
instantaneously — the explicit-zero spelling and the omitted-argument
spelling behaved differently, which is precisely what the clause rules
out. When a directive value is present, each edge time now selects at
runtime: the written time if positive, the directive value otherwise.
Pinned mid-ramp: 0.5 at 1.5 µs into a 1 µs ramp.

## A bare transition() passed through unfiltered (compiler)

With no rise/fall times *and* no directive, `transition(x)` — and the
delay-only `transition(x, td)` — lowered to the bare input: no filter
at all, so a discontinuous driver stayed discontinuous and nothing
resembling 4.5.8's "the transition ... to happen in one timestep"
smoothing existed. Both forms now route through the rate-limited track
machinery with an unbounded requested rate, which the finite-gain clamp
turns into a negligible ~1 ns ramp: DC is an exact pass-through
(pinned to the femtoampere), a transient settles to its target within
a few nanoseconds, and the operator finally *is* a filter — it
smooths, delays and drives like the LRM's operator, just with a
negligible time constant.

## Dynamic laplace coefficients now say they track (compiler)

LRM 4.5.14 with Table 4-20 classes the zero/pole/coefficient vectors
as *constant* arguments: a dynamic expression there takes its value at
the start of the analysis and "any further change ... shall be
ignored". This implementation re-evaluates the vectors every iteration
— a solution-dependent coefficient makes the filter time-varying, a
genuinely useful extension but a silent LRM deviation. A recursive
operating-point-dependence walk (potential/flow/temperature/vt/abstime)
over the vectors now draws one warning per statement naming the filter
("a coefficient depends on the solution and will TRACK"); parameter-
built coefficients stay silent, and none of the thirteen big CMC
models triggers it. The tracking behavior itself is untouched — and
with the coefficient held constant, the suite verifies the filter is
the matching fixed lowpass at its corner.

## The documented approximations, re-pinned

The compliance doc's §4.3 was rewritten around three ⚠️ blocks — the
4-arg `transition` amplitude/AC-corner approximation (E-512's
contract, pinned here at its measured 1.0996 value so a change is
caught), the `zi_*` continuous bilinear realization with tau/t0
ignored, and the laplace tracking above — plus the corrected
"Table 4-20 honoured exactly" claim in E-514's write-up.
