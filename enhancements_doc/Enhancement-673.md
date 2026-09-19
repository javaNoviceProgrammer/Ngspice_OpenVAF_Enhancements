# Enhancement-673: a `$fatal` in a `dc` sweep names the point being solved, once

**Scope:** F7 of the
[bug hunt of 2026-09-19](../docs/bug_hunts/2026-09-19_openvaf-r-operators-folding-and-delays.md).
ngspice: `src/spicelib/analysis/dctrcurv.c` (`DCTsweepTime`; the swept value
published before the solve; the abort on a raised `$fatal`).
`examples/lrmvoice_examples/` (`lrmvoice_fatal.va` and three checks, 31).
Handbook [§2.11](../docs/handbook/02-verilog-a-language.md) row. **ngspice
only.**

**Suites:** [`lrmvoice_examples`](../examples/lrmvoice_examples/) 31 of 31
per solver, both solvers (2 of the 3 new checks fail on the E-670 binaries;
the model compiles on both); full sweep 531 of 531.

## What was wrong

```verilog
if (V(p, n) > 0.25) $fatal(1, "FATAL over %g", V(p, n));
```

under `.dc v1 0 1 0.5`:

| task | was |
|---|---|
| `$fatal` | `OSDI(fatal) n1: FATAL over 0.5 (at sweep value 0)` — printed twice |
| `$error`, `$warning`, `$info` | `over 0.5 (at sweep value 0.5)`, once |

Two things, both in `dctrcurv.c`. The swept value of level 0 was published
into `CKTtime` — what the LRM 9.7.3 label `(at sweep value …)` reads
(`osdi_severity_when`) — only *after* a point converged, for the output
vector. `$error`, `$warning` and `$info` are deferred to the accepted point
([E-660](Enhancement-660.md)'s rule) and flushed after that publish, so they
named the right point; `$fatal` is never deferred ("terminates the
simulation without checking whether the iteration would be rejected",
9.7.3), so it read the previous point's value. And the direct Newton solve
the sweep tries first returned `E_PANIC` with `CKTvaFatalRaised` set, which
the sweep took for a non-convergence: it went on to `CKTop`'s ladder, whose
first rung evaluated every device again, so the model re-raised the `$fatal`
and the line printed a second time. `CKTop` itself stops on the flag
([E-378](Enhancement-378.md)); the sweep's own path did not.

## What changed

**The point is published before the solve, and a raised `$fatal` ends the
sweep.** The six-way assignment (a voltage, current or resistance source, a
`.param`, an `x`-parameter or the temperature) is `DCTsweepTime`, called
before the solve as well as after it, so a message raised during the solve
names the point being solved. When the direct solve returns `E_PANIC` with
`CKTvaFatalRaised`, the sweep prints its own abort line and returns instead
of re-solving the point through the ladder:

```
OSDI(fatal) n1: FATAL over 0.5 (at sweep value 0.5)

Error: a Verilog-A device raised $fatal at sweep value 0.5; aborting.
       This is not a convergence failure -- see the OSDI(fatal) message above for the cause.
```

No model reads the earlier publish: `$abstime` is 0 outside a transient
([E-434](Enhancement-434.md)), and the output vector records the same value
it did.

## Verification

| check | result |
|---|---|
| `$fatal` at V = 0.5 under `.dc v1 0 1 0.5` | `FATAL over 0.5 (at sweep value 0.5)`, one line (was `(at sweep value 0)`, two lines) |
| the sweep's abort line | `raised $fatal at sweep value 0.5; aborting`, "not a convergence failure" |
| `$error` at the same point (the suite's existing sweep check) | `(at sweep value 0.5)`, once, unchanged |
| the transient `(at t = …)` and `.ac` `(at the operating point)` labels | unchanged |
| the E-670 binaries on the suite | 2 of the 3 new checks fail (the model compiles on both) |
| full sweep | 531 of 531 |

## What this does not do

- A `$fatal` whose arguments are solution-independent is hoisted into the
  model's setup code and prints in both the setup and the temperature pass
  ([E-660](Enhancement-660.md)'s rule, unchanged); that doubling is a
  different mechanism and is recorded in the hunt's smaller notes.
- The operating-point and transient labels were right and are untouched;
  `.dc temp` and a `.dc` over a `.param` take the same `DCTsweepTime` path.
