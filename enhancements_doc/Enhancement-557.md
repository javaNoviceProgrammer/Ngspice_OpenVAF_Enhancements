# Enhancement-557: `pyplot_status` on every `pyplot`, a colliding `-expr` name refused, a bin count below 2 said

**Scope:** F6, F7 and F8 of the
[bug hunt of 2026-09-05](../docs/bug_hunts/2026-09-05_strings-mcexpr-and-osdimc-distributions.md):
`src/frontend/com_pyplot.c`, `src/frontend/plotting/pyplot.c`,
`src/frontend/com_sweep.c`. **ngspice only; the compiler is unchanged.**

**Suites:** [`pyplot_examples`](../examples/pyplot_examples/) 49 → 53,
[`mcrecord_examples`](../examples/mcrecord_examples/) 13 → 14, both solvers;
the twelve neighbouring pyplot and Monte Carlo suites pass; full sweep 459 of
459 ([`paramgiven_examples`](../examples/paramgiven_examples/) now takes its
pre-E-555 compiler from the repository's history, since the CI republishes
`bin/` after every push). The pyplot reference
([§13.1](../docs/internals/ngspice_internals/ngspice_pyplot.md), the settings
table, the decimate row), the
[statistics guide](../docs/internals/ngspice_internals/ngspice_statistics.md) §6.1.

## What was wrong

* **F6.** E-547 promised that every `pyplot` publishes `pyplot_status`, and
  five paths did not — a refusal before the backend ran (a usage error,
  plotit's own *X values must be > 0 for log scale*), a table or script that
  could not be opened (a read-only file, a missing directory), and a
  successful `-export` — so the deck's `if $pyplot_status ne 0` died with
  *no such variable* on exactly the failures it was written to catch.
* **F7.** `montecarlo` refused two `-expr` of one name and let one take the
  record plot's own — `sample`, its scale, or a result such as
  `montecarlo_n` — which then shadowed the record: `print sample` read 1..N
  and the values were unreachable.
* **F8.** `set pyplot_decimate=1`, `0` or `-5` silently turned decimation off
  where `abc` was told it was neither off, auto nor a bin count.

## What changed

* `com_pyplot` assumes a failure at entry (`pyplot_status` = 1) and every path
  that succeeds says so: the launch path with Python's exit status, the export
  path with 0. A refusal, an unopenable table or script, a usage error leave 1.
* A `-expr` name the record plot owns is refused with the reason: *`-expr` name
  'sample' is the record plot's own vector (its scale `sample`, or a result
  such as montecarlo_n); choose another name.*
* A `pyplot_decimate` count below 2 gets the same warning as a non-number and
  decimation stays automatic.

## Verification

| check | result |
|---|---|
| `pyplot -export exp2 v(in)` | `pyplot_status` = 0, the table written |
| `pyplot bad v(in) xlog xlimit 0 1m` | *X values must be > 0 for log scale*, status 1 |
| `pyplot nodir/x v(in)`, an export onto a read-only file | status 1 |
| `set pyplot_decimate=1` | *is not a bin count (2 or more), off or auto; decimating automatically*, the plot rendered |
| `-expr sample=…`, `-expr montecarlo_n=…` | refused, nothing recorded, the script goes on |
| `pyplot_examples`, `mcrecord_examples`; full sweep | 53 / 53, 14 / 14; 459 of 459 |
