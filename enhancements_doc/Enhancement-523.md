# Enhancement-523: the core analog operators absdelay, ddx and idtmod, squared with the LRM

**Scope:** Accellera VAMS-2023 clauses 4.5.5–4.5.7 (the time-derivative /
integral / delay operator family), from the full LRM conformance audit:
one refused-but-legal `ddx` form, one absdelay deviation promoted to the
LRM behavior, and one silently singular `idtmod` default.

**Suite:** [`examples/lrmcoreops_examples/`](../examples/lrmcoreops_examples/)
— 18 checks, both solvers. The existing `absdelay`, `ddx`, `idtmod`,
`idtassert` and `opargs` suites all still pass.

## absdelay froze nothing: a time-varying td tracked (compiler + ngspice)

LRM 4.5.7 splits `absdelay` in two: with maxdelay present, td may vary
and is bounded by maxdelay; *without* it, "the value of the delay
argument td when the module instance is initialized shall be used" — a
frozen delay. The implementation had one path: td re-evaluated every
step, so `absdelay(V(in), 1m + 1m*V(ctl))` with `V(ctl)` stepping at
t = 4 ms drifted its delay mid-transient (the audit measured the output
answering to td = 2 ms where the LRM requires the initial 1 ms).

The fix spans the OSDI boundary. The compiler's absdelay info structs
grew a fourth field — a flags word with `OSDI_ABSDELAY_TD_FROZEN` set
for the two-argument form — and ngspice's per-instance data latches td
at the first transient evaluation (`MODEINITTRAN`), clamping a negative
initial value to 0. Every later evaluation of a frozen entry reads the
latched value; maxdelay entries keep the tracking semantics 4.5.7
prescribes for them, including the td > maxdelay substitution. Pinned:
the frozen case reads the input 4.99 ms back (tracking gave 3.99), DC
passes through exactly, and the AC phase is −2πf·td to four digits.

## ddx refused the unnamed-branch flow (compiler)

LRM 4.5.6 with Table 4-16 lets `ddx` differentiate with respect to "the
flow through a branch" — and `I(n1,n2)` *is* the flow of the unnamed
branch between n1 and n2, exactly as `I(br)` is for a named one. The
inference table only accepted the named spelling and errored with
"declare a named branch" for the form the LRM itself writes. The
`(flow, NATURE_ACCESS_NODES)` signature now maps to the same `DDX_FLOW`
lowering, which already handled every shape the probe lowers to: the
forward orientation (`ddx(I(a,b)², I(a,b)) = 2I` exactly), the reversed
orientation (negated), and a flow that is not a system unknown — a
current-defined branch — where the derivative is exactly 0. No lint:
unlike the potential-difference extension next to it, this form is
inside the LRM surface.

## idtmod without ic left the matrix singular (compiler)

LRM 4.5.5: idtmod's initial condition "defaults to 0", and the ic
"shall force the DC solution". `idtmod(x)` lowered with *no* DC
constraint at all — the integrator state was an unconstrained unknown,
the operating point a singular matrix that ngspice regularized to an
arbitrary value. The no-ic signature now routes through the same
`IdtKind::Ic` path as `idtmod(x, 0)`, with the ic operand defaulting to
zero: the DC output pins to 0 exactly and the solve is clean — the
suite greps the singular-matrix warning away.

## Kept, and documented

Two audited deviations stay by design and are recorded in the
compliance doc: the `idt` assert-reset settles to its ic through a
short first-order decay rather than instantaneously, and the
abstol/nature tolerance arguments of `ddt`/`idt`/`idtmod` are validated
and then discarded (tolerances are the solver's). A negative constant
td remains a targeted compile error.
