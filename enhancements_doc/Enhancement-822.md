# Enhancement-822: a Verilog-A message raised in a setup pass names the sweep point being applied, or says "during setup", and a setup `$fatal` prints once

**Scope:** F6 of the
[ngspice + OSDI hunt of 2026-10-08](../docs/bug_hunts/2026-10-08_ngspice-osdi-hierarchy-sweeps-events-and-outputs.md),
with the temperature-sweep, after-analysis and duplicate cases found while fixing it.

ngspice:
- `osdi/osdicallbacks.c`:
  - `osdi_severity_when` labels a message raised outside a Newton iteration from the sweep
    phase (Enhancement-820), not from the last analysis's mode.
  - A setup pass holds its `$fatal` like its other messages (Enhancement-660).
- `osdi/osdisetup.c`: setup and the temperature pass publish the circuit to the label.
- `spicelib/analysis/dctrcurv.c`: `DCTpointAhead` publishes a point in `CKTtime` before the
  point is applied.

`examples/sweepstate_examples/` (section [3], six checks). **ngspice only.**

**Suites:** [`sweepstate_examples`](../examples/sweepstate_examples/) 18 of 18 per solver (5 of
the 6 checks in [3] fail on the E-819 binaries; the sixth is a solution-dependent warning,
which was right). The full sweep, 543 of 543.

## What was wrong

Code that depends only on parameters and the temperature is compiled into the device's setup.
It runs in ngspice's setup and temperature passes, before any Newton iteration
(Enhancement-660). A severity task there took its place, LRM 9.7.3's "(at …)", from `CKTmode`
and `CKTtime`. Those still described whichever analysis ran last:

| | the device's line said |
|---|---|
| `dc @fpm[g] 1m 4m 1m`, `$fatal` at 3m | `(at sweep value 0.002)`, while the error line said 0.003 |
| `dc temp 0 100 50`, a `$warning` above 310 K | `hot 50 (at sweep value 0)`, `hot 100 (at sweep value 50)` |
| an `op` after a `dc` | `(at sweep value 0)`, twice |
| `altermod` after a `tran`, then `op` | `(at t = 2e-09)`, then `(at t = 0)` twice |
| an `op` with the fatal value on the card | the line twice, with no place at all |

- **A sweep point.** It is applied by the device's temperature pass, before the point's value
  reaches `CKTtime`. Enhancement-673 published it before the solve; the pass runs earlier
  still. So the label named the previous point.
- **Outside a sweep.** The reset before an analysis, `altermod` and `alter` belong to no solve.
  They read the last analysis's mode.
- **Twice.** The setup pass and the temperature pass both run the code. Enhancement-660 held
  the setup pass's messages, except `$fatal`. Its own limits list the duplicate.

## The change

- **The label.** A message raised while deferral is not engaged comes from a setup pass.
  - Inside a running dc sweep, it gets "(at sweep value X)", where X is the point being
    applied.
  - Anywhere else, it gets "(during setup)".
  - A message raised in a Newton iteration keeps its label, and an `analog initial` block
    keeps "(during initialization)".
- **The point.** The sweep publishes the point it is about to apply in `CKTtime`. That is
  level 0's value, or level 0's start when an outer level moves. This happens for a
  temperature, an instance or model parameter, a cross-parameter, and a counted level.
- **Once.** The setup pass holds its `$fatal` too:
  - the temperature pass raises it again, with the values the analysis runs with;
  - a failed setup releases it;
  - so does the first iteration, if no temperature pass comes.

  The abort comes from the evaluation's return flag, not from the message.

## The checks

`sweepstate_examples` [3]:
- `dc @fpm[g] 1m 4m 1m`: `g too big 0.003 (at sweep value 0.003)` (was 0.002).
- `dc temp 0 100 50`: `hot 50 (at sweep value 50)`, `hot 100 (at sweep value 100)` (were 0 and
  50).
- A solution-dependent `$warning` in a dc: `high 2 (at sweep value 2)` (control).
- `op` with g = 3m on the card: the `$fatal` once, `(during setup)` (was twice, with no place).
- `altermod fpm g=3m` after a `tran`, then `op`: `(during setup)` at each (were `(at t = 2e-09)`
  and twice `(at t = 0)`).
- The same after a finished `dc`: `(during setup)` at each (were `(at sweep value 1)` and twice
  `(at sweep value 0)`).
