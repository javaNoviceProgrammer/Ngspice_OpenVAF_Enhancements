# Enhancement-703: the `E` extrapolation error of `$table_model` is judged on the accepted solution — it fired on the zero initial guess of every operating point, so a table whose domain excludes 0 could never start under `E`, and a point above the table was reported as below it

**Scope:** F2 of the
[bug hunt of 2026-09-21 on the filters, tables and noise sources](../docs/bug_hunts/2026-09-21_openvaf-r-filters-tables-and-noise.md).
**Both tools change.** openvaf: `hir_lower/src/ctx.rs` (`runtime_fatal_deferred`),
`hir_lower/src/expr.rs` (the two `E` branches of `apply_end_extrap_at`),
`hir_lower/src/callbacks.rs` (`RetFlag::AbortDeferred`), `hir_lower/src/fmt.rs`
(`DisplayKind::FatalDeferred`), `osdi/src/compilation_unit.rs` (the flag and the
level mapped), `osdi/stdlib.c` (`set_ret_flag_fatal_deferred`),
`osdi/header/osdi_0_4.h`, `osdi/src/metadata/osdi_0_4.rs` and
`openvaf/tests/load/osdi_0_4.rs` (`EVAL_RET_FLAG_FATAL_DEFERRED`,
`LOG_FLAG_DEFER`). ngspice: `src/osdi/osdi.h` (the two bits),
`src/osdi/osdicallbacks.c` (a flagged fatal-level message waits for the accepted
iteration), `src/osdi/osdiload.c` (`OSDI_REQ_FATAL` in `OSDIpendingRequests`,
`OSDIdeferredFatal`), `src/osdi/osdisetup.c` (raised during setup it is a
rejection), `src/include/ngspice/osdiitf.h`,
`src/spicelib/analysis/{dcop,dctran,dctrcurv,acan,noisean,tfanal}.c` (the check
at each accepted-point boundary, before the point is output).
`examples/langguard_examples/` (section [5], six checks, 125 per solver). The
compliance document and the handbook row, the hunt page.

**Suites:** [`langguard_examples`](../examples/langguard_examples/) 125 of 125 per
solver, both solvers (121 of 125 on the E-702 binaries: an `op` inside the table,
an `op` above it judged at the accepted point with the right side named, a `dc`
sweep and a transient that leave the table part-way);
[`lrmvoice_examples`](../examples/lrmvoice_examples/) (the deferral machinery),
`domainwarn`, `reportguard`, `silentloss`, `altermulti`, `ctrlnode`, `lrmexpr`,
`hunt13slips`, `simparamdiag` and `fmtdiag` (every suite that pins a fatal
message) unchanged; `tablesrc` 57 of 57, `lrmfilters` 26 of 26, `nullarg` 39 of
39; the compiler workspace tests green apart from the three pre-existing
sourcegen drift failures (219 passed), no build warnings; full sweep 532 of 532,
run alone.

## What was wrong

A one-dimensional table over `x ∈ [1, 4]` under `"1E"`, evaluated at
`V(in) = 2.5` from a voltage source:

```
OSDI(fatal) n1: $table_model: the evaluation point is below the table and the control
string requests an error there ('E', LRM 9.21.2); it is 0 (at the operating point)
Error: a Verilog-A device raised $fatal during the operating point; aborting.
```

The same deck with `.nodeset v(in)=2.5` ran and printed 2.5. The first Newton
iteration of an operating point starts with every node at zero, so the device
was evaluated at `x = 0` once before the source's equation had been solved; the
`E` check fired on that iterate and raised the abort flag. A table whose domain
excludes zero — a temperature table over 250–400 K, an I-V table over 1–6 V, a
normalised bias from 0.5 up — could never start under `E`, whatever the solution
was; a `dc` sweep aborted at its first point; a transient aborted in its
operating point. And a source at 6 V, above the table, drew the same "below the
table … it is 0", since the first iterate was reached before the solution.

LRM 9.21.2: "an extrapolation error is reported if the $table_model function is
requested to evaluate a point beyond the interpolation region" — the point the
simulator asks the model about is the solution, not the iterates on the way to
it. Every other run-time check of this family compares a converged quantity:
`$error` and `$warning` defer to the accepted iteration
([E-541](Enhancement-541.md)), the deck-domain warnings of
[E-651](Enhancement-651.md) likewise, and the abort-at-once `runtime_fatal` was
reserved ([E-504](Enhancement-504.md), [E-506](Enhancement-506.md)) for
constants — a sampling period, a leading coefficient — that no iteration can
change. The extrapolation check was the one solution-dependent user of it.

## What changed

**A fatal judged on the accepted solution.** `runtime_fatal_deferred` is
`runtime_fatal` with two differences. Its message is a fatal-level print carrying
a new log bit, `LOG_FLAG_DEFER`, which the simulator holds with the iteration's
other output and prints only when that iteration is accepted — the fatal level
is otherwise never deferred, because `$fatal` "terminates the simulation without
checking whether the iteration would be rejected" (LRM 9.7.3), and a `$fatal`
print reaches the simulator without the immediate tag, so the level alone could
not tell the two apart. Its flag is a new OSDI return bit,
`EVAL_RET_FLAG_FATAL_DEFERRED` (`RetFlag::AbortDeferred`): the evaluation
completes with the clamped endpoint value, the safe substitute the iterates on
the way to a solution see, and the analyses act on the flag of the instance's
LAST evaluation at the accepted-point boundary — `OSDIdeferredFatal`, which
flushes the point's held output (the device's own message), records a Verilog-A
fatal for the frontend and returns `E_PANIC` — before the point is output. The
last evaluation of a converged solve sits within the tolerance of the solution
the analysis accepts; the attempt's accumulated flags (`point_eval_flags`, the
deferred `$finish`'s source) would re-create the defect, since they keep what an
intermediate iterate raised. Both bits are additive: an older simulator ignores
the flag and continues with the substitute, and prints the message at once.

**Where the check sits.** After the operating point's converged reload and
before its output (`dcop`); right after a transient point is accepted, before it
is output (`dctran`, the same boundary as the deferred `$finish`); before a `dc`
sweep point is output, as [E-673](Enhancement-673.md)'s `$fatal` path
(`dctrcurv`); after the operating-point load that an AC or noise analysis
linearises around (`acan`, `noisean`); after the transfer function's operating
point (`tfanal`). A gmin- or source-stepping rung inside `CKTop` is not an
accepted point and is not checked — its intermediate solutions are not the
answer. Where there is no accepted iteration to wait for — an event context, an
`analog initial` block — the check is the immediate `runtime_fatal` it was; a
constant operand outside the table (a table input the model card fixes) is
still refused, its message printed at setup and the operating point's check
aborting the run. The checks on constants keep `runtime_fatal`: a sampling
period, a leading coefficient, `$simprobe` without a default.

## Verification

`langguard_examples` section [5], a run-time array table over `[1, 4]` under
`"1E"` (y = x): an `op` at 2.5 runs and gives 2.5 (it aborted on the zero
initial guess); an `op` at 6 aborts at the accepted operating point with "above
the table … it is 6" (it aborted at the first iterate with "below … it is 0");
`dc v1 1 5 1` runs the four points inside the table (1, 2, 3, 4 mA through the
source) and aborts at sweep value 5; a transient whose input pulses from 2 to 5
at 3 µs runs to 3.001 µs and aborts there, naming the time point; a constant
operand of 6 is still refused. The E-700 checks beside them are unchanged (the
`"1E"` point inside a table over `[0, 2]`, the abort above it). On the E-702
binaries the four solution-judged checks fail and the constant one passes. By
hand, the hunt's file table over `[1, 4]`: `op` at 2.5 → 2.5 (was the abort), at
6 → the abort names "above" and 6, `dc 1.5 3.5 1` runs, a transient aborts at
3.001 µs with "it is 5". Every suite that pins a fatal message (ten of them, the
`$fatal` family, `$simprobe`, the deck-domain warnings, the E-541 deferrals)
passes unchanged: the immediate route is untouched.

## What this does not do

- The verdict is the last Newton evaluation's, within tolerance of the accepted
  solution; a solution that lands on a table edge from outside by less than the
  tolerance is judged by that last iterate.
- `$fatal` written by a model keeps LRM 9.7.3's immediate semantics, and so do
  the compiler's own fatals on constants.
- An older simulator (before this release) loading a new `.osdi` continues past
  a point outside an `E` table with the clamped value, printing the message on
  every iterate that lands there; the abort needs both sides.
- The AC and noise sweeps evaluate no table beyond their operating point, which
  is where they are checked.
