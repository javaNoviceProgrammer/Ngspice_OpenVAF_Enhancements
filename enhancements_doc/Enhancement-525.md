# Enhancement-525: hierarchy, audited against the LRM

**Scope:** Accellera VAMS-2023 clause 6, from the full LRM conformance
audit — five silent hierarchy bugs: defparam dropped by generate,
ignored `#(.$mfactor(n))`-family child overrides, `$param_given` blind
to hierarchy overrides, scalar-onto-vector-port replication, and mixed
parameter-override lists.

**Suite:** [`examples/lrmhier_examples/`](../examples/lrmhier_examples/)
— 22 checks, both solvers. `instantiation`-family, `generate`,
`defparam`, `hiername`, `paramset`, `businst`-family and the full
436-suite sweep all pass (one stale pin updated: `vafinstcheck` now
expects the honored −7 A, not the silently ignored −1 A).

## defparam vanished wherever generate existed (compiler)

LRM 6.3.1 allows defparam anywhere in the module, generate blocks
included. Two independent holes ate them: the generate-block *parser*
had no `defparam` arm, and its parse error was then swallowed because
elaboration re-renders the region from the syntax tree (the same
failure shape E-390 fixed for `analog` blocks); and the module-level
generate rewrite rebuilt the item region from the typed item list —
which defparam is deliberately not part of, being consumed later by the
E-58 machinery — so module-scope defparams *beside* a generate vanished
in the splice. The parser gained `defparam` (plus `branch` and
`aliasparam`) arms, the rewrite now splices by byte range so everything
it does not explicitly rewrite survives verbatim, and generate blocks
render defparams with genvars folded and the per-iteration instance
rename applied. Pinned: per-iteration targets inside `generate for`
(2m·1 + 2m·2 = 6 mA), `generate if`, module scope beside a generate,
and precedence over `#(...)` two levels down.

## `#(.$mfactor(4))` compiled clean and did nothing (compiler)

LRM 6.3.6: hierarchical system parameters "may be overridden using ...
module instance parameter value assignment by name". The paramset path
worked and `defparam u1.$mfactor` at least errored — but the instance
spelling parsed into an ERROR node (whose diagnostic only existed on
the pre-elaboration tree) and was dropped. The parser now wraps the
SYSFUN in a proper NAME node, and the flattening applies the full LRM
multiplicity transform to the inlined child as single-token text holes:
reads compose (`$mfactor` multiplicatively with the netlist instance
value, `$xposition`-family additively), every flow contribution's RHS
scales by m, every flow probe divides by m (the per-copy read-back),
and every noise call divides by √m — so contributed-current noise
power scales ×m and contributed-voltage noise power ÷m, both the
parallel-combination results. Overrides compose down the hierarchy
(×2 under ×4 is ×8) and with the netlist `m=`; `ddx`/`$limit` probe
references are exempt from the division. Pinned numerically on every
axis, including the √4 noise-amplitude ratio; duplicate and unknown
`.$` overrides are targeted errors.

## $param_given answered "not given" for VA-given values (compiler)

LRM 6.3.5/9.19: a parameter overridden by an instance `#(...)` value or
a defparam *is* given. Compile-time flattening bakes the override in as
the parameter's new default, so OSDI reported false and every
"did the user set this?" guard took the default branch. The flattening
now records the final flattened name of every parameter it binds, and a
post-pass rewrites `$param_given(<flat>)` for exactly those to a true
literal — netlist `.model` overrides of the flattened names keep their
native OSDI given-flag path untouched.

## A scalar net drove every bit of a vector port (compiler)

LRM 6.5.7.1: "The sizes of the ports and net need to match." A scalar
actual on a 2-bit port compiled and was replicated onto both bits — a
best-effort broadcast fallback. It is now a compile error citing the
clause and naming both modules; matching-width buses, part-selects and
`{...}` concatenations connect exactly as before (width-1 ports still
take scalars).

## Mixed ordered + named parameter overrides half-applied (compiler)

Syntax 6-2 makes the `#(...)` list all-ordered or all-named. The mixed
form bound only the named half and silently dropped the positional
values (the port-connection equivalent was already an E-395 error).
Now the same error, for parameters.

## Disclosure

The compliance doc's §6 was rewritten: the five fixes above, the two
⚠️ transform limits (indirect contributions and via-variable noise
inside a scaled child keep their unscaled form), the remaining
refused-with-diagnostics gaps (multi-construct generate regions,
descending genvar loops, generate-block hierarchical refs,
`macromodule`, paramset overloading/output variables, child *port* net
access), and the two accepted extensions (out-of-scope named-block
variable writes; the undiagnosed 6.3.6 double-scaling misuse).
