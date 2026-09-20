# Enhancement-677: the final-step evaluation of an `ac` or `noise` analysis runs on the bias point — `last_crossing` read 0 and `V(a,b)` the small-signal response

**Scope:** F6 of the
[bug hunt of 2026-09-19](../docs/bug_hunts/2026-09-19_openvaf-r-operators-folding-and-delays.md).
ngspice: `src/osdi/osdiload.c` (`osdi_op_solve_capture` at the
MODEINITSMSIG load; `OSDIfinalStep` evaluates on it under AC and NOISE).
`examples/finalstep_examples/` (`fsop` and three checks, 26 per solver).
Handbook [§2.6](../docs/handbook/02-verilog-a-language.md) and
[§2.8](../docs/handbook/02-verilog-a-language.md) rows. **ngspice only.**

**Suites:** [`finalstep_examples`](../examples/finalstep_examples/) 26 of 26
per solver, both solvers (2 of the 3 new checks fail on the E-670 binaries,
the `ac` and the `noise` ones; the `op` control passes); `opvarac` 19 of 19,
`tranopdelay` 11 of 11, `reusestate` 32 of 32 unchanged; full sweep 531 of
531.

## What was wrong

```verilog
tlast = last_crossing(V(a,b) - 0.5, 0);
v = V(a,b);
@(final_step) $strobe("tlast=%g V=%g", tlast, v);
```

with a 0.2 V bias and a unit AC source on the node:

| analysis | `tlast` | `V` |
|---|---|---|
| `op` | −1 | 0.2 |
| `ac` | **0** | **1** |
| `noise` | **0** | **1** |
| `tran`, edge at 2.04 µs | 2.0375e-6 | 1 (the pulse's level at tstop) |

LRM 4.5.10: before the expression crosses zero for the first time,
`last_crossing` returns a negative value; 0 is a valid time, and a model that
tests `< 0` for "not yet" took the wrong branch under `ac` and `noise`. The
`V` column shows the cause is wider than the hunt's row: the whole event
body ran on the wrong solution. [E-53](Enhancement-53.md)'s `OSDIfinalStep`
issues one evaluation per instance at `CKTrhsOld`, and after a frequency
sweep that vector holds the **small-signal solution at the last frequency**
(its real parts): the node reads the response, 1 V for the unit source, and
a `last_crossing` synthetic node — stamped `jac[z,z] = -1` with no
small-signal stimulus — reads 0. [E-412](Enhancement-412.md) met the same
vector when the operating-point *variables* changed with frequency and
snapshotted the instance around the evaluation, so `@n1[tlast]` read −1
after the `ac` while the event body, which runs *during* that evaluation,
read 0. The analog block of a small-signal analysis is only ever evaluated at
the bias point it linearises around; the final step should see that point.

## What changed

**The bias point is kept and the final step evaluates on it.** Every `.ac`
and `.noise` job issues the MODEINITSMSIG load exactly once, on the
converged operating point, before the first frequency; the OSDI load copies
`CKTrhsOld` there (`CKTmaxEqNum + 1` entries, one buffer per circuit).
`OSDIfinalStep` under MODEAC or MODEACNOISE hands that copy to the
evaluation as `prev_solve`. E-412's instance snapshot stays: the
evaluation's results are still never loaded, and the instance is put back
afterwards.

## Verification

| check | result |
|---|---|
| the strobe after `ac dec 2 1k 10k` | `V=0.2 tl=-1` (was `V=1 tl=0`) |
| the same after `noise v(in) V1 dec 2 1k 10k` | `V=0.2 tl=-1` (was `V=1 tl=0`) |
| the same after `op` | `V=0.2 tl=-1` (unchanged) |
| a transient with an edge at 2.04 µs | `tl=2.0375e-06`, `V=1` at tstop (unchanged) |
| `@n1[tlast]` read after the `ac` | −1 (unchanged: E-412's snapshot) |
| `@(final_step("ac"))`, `@(final_step("noise"))`, `$abstime` at the final step | fire and read as before (the suite's earlier checks) |
| the E-670 binaries on the suite | the `ac` and `noise` checks fail, the `op` control passes |
| `opvarac`, `tranopdelay`, `reusestate`; full sweep | 19/19, 11/11, 32/32; 531 of 531 |

## What this does not do

- The final-step evaluation's results are still discarded under `ac` and
  `noise` (E-412): the operating-point variables keep the values the
  operating point computed.
- `$abstime` at the final step of an `ac` is 0, as before
  ([E-434](Enhancement-434.md)); a `dc` sweep's final step still sees the
  last sweep point, which is a real operating point.
- The E-6 demo in `examples/last_crossing_examples/` (decks and plots, no
  verify script) is untouched.
