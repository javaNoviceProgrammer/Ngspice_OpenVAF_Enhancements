# domainwarn_examples — a deck-fixed argument that is projected onto its domain is named (Enhancement-651)

Twenty checks per solver, run under both KLU and Sparse by `_setup.check_both_solvers`.

E-504/505/506 project an unusable argument onto its domain at run time: a negative or NaN
noise power becomes 0 (the source contributes nothing), a negative standard deviation
becomes the mean, a reversed uniform range becomes its start, a NaN flicker exponent makes
the source inert. The LRM mandates no error for these, so the projections stay, but each was
silent when the bad value came from the model card, while the same value written as a
literal is refused at compile time and the exponential family with a bad deck mean is a
`$fatal` (E-527).

The checks: `white_noise(pw)` with a deck `pw = -1e-18`, and `white_noise(z/z)` with
`z = 0`, keep the source inert (the output spectrum stays at the series resistor's thermal
floor) and print a deferred `OSDI(warn)` line naming `white_noise`, the number (or `nan`)
and "the source contributes nothing"; a zero or a usable power says nothing;
`flicker_noise` is named for its power and for a `0/0` exponent; `$rdist_normal` and
`$dist_normal` with a deck `sg = -1` return the mean and are named, a zero or a usable
sigma says nothing; `$rdist_uniform`/`$dist_uniform` with `lo = 1, hi = 0`, equal bounds,
or a literal beside a deck bound return the start and name both numbers; a run-time sigma
(`V(p,n) - 2`) is projected in silence as before; `$rdist_exponential` keeps its fatal; a
literal negative sigma is still refused at compile time; a 5-point transient prints the
warning a handful of times, not per iteration.

```bash
python3 examples/domainwarn_examples/verify_domainwarn.py
```
