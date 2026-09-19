# Enhancement-671: a delay survives the transient operating point — `absdelay` and a delayed `transition` keep their delay after ngspice's Transient-op fallback

**Scope:** F1 of the
[bug hunt of 2026-09-19](../docs/bug_hunts/2026-09-19_openvaf-r-operators-folding-and-delays.md).
ngspice: `src/osdi/osdiload.c` (`absdelay_ensure_timepoints` and its two
callers, `absdelay_stamp_tran` and `last_crossing_stamp`).
`examples/tranopdelay_examples/` (new, 11 checks per solver). Handbook
[§2](../docs/handbook/02-verilog-a-language.md), the `absdelay` row.
**ngspice only** — the compiler and the `.osdi` ABI are untouched.

**Suites:** [`tranopdelay_examples`](../examples/tranopdelay_examples/) 11 of
11 per solver, both solvers (5 of the 11 fail on the E-670 binaries);
`absdelay` (KLU against Sparse, dc/ac/tran), `defaulttransition`,
`hunt17diag` unchanged; full sweep 531 of 531.

## What was wrong

When plain Newton, gmin stepping and source stepping all fail, `CKTop`
reaches its last rung: `OPtran` in `optran.c`, a short transient with the
sources frozen at their t = 0 values (`Note: Transient op started`, 1 µs in
10 ns steps by default; enabled at circuit load). Every circuit whose
operating point came through that rung then simulated its OSDI delays as if
they were not there, for the whole transient that followed:

| model | plain Newton | after the Transient op |
|---|---|---|
| `del = absdelay(V(a,b), 1u)` on a step at 1 µs | 0 until 2 µs, 1 after | **0 throughout** |
| `I(a,b) <+ absdelay(V(a,b), 1u)/1e3` | the delayed current | **the input, undelayed** |
| `transition(x, 0.5u, 1u)` (lowered as `slew(absdelay(x, 0.5u), …)`) | the ramp from 1.5 to 2.5 µs | **0 throughout** |
| `idt(absdelay(V(a,b), 1u), 0)` | the integral of the delayed pulse | **0 throughout** |
| `absdelay` with `maxdelay`, nested, with a parameter delay, of a `slew`, under a `slew` | right | **0 throughout** |
| `slew`, `laplace_nd`, `zi_nd`, `idtmod`, `last_crossing`, `cross`/`timer` counters | right | right |

What forced the rung did not matter: an ideal inductor across the source, an
`idt` without an initial condition in the same module or in **another
instance**, a `laplace` integrator — or an `idt` of a delayed signal, which
is singular at the operating point on its own even with an initial
condition. Gmin stepping alone (`.option noopiter`) and source stepping alone
(`gminsteps=0`) kept the delay; `uic` skips the operating point and kept it;
`method=gear` changed nothing. Nothing was said.

The cause is the shared accepted-timepoint list. [E-1](Enhancement-1.md)'s
delay is a synthetic-node DAE whose output row ngspice stamps from a
per-instance waveform history indexed by `CKTtimePoints`/`CKTtimeIndex`, the
list `dctran.c` keeps for LTRA lines: `absdelay_ensure_timepoints` allocates
it when it is NULL, `OSDIaccept` writes the converged value at each accepted
index, and `absdelay_lookup` binary-searches it for t − td. `dctran.c` resets
that list (`CKTtimeIndex = -1`, the array freed) **before** it calls `CKTop`.
`OPtran` frees it again at its start, raises `MODETRAN | MODEINITTRAN` and
runs its own transient — during which the OSDI stamp allocates the list, and
`OSDIaccept` fills about a hundred points with the fallback's own times and
the frozen operating point — and returns without resetting either. The real
transient's first Newton solve (`MODEINITTRAN`) then found a non-NULL list
with the index at the fallback's last point; `absdelay_ensure_timepoints`
only started over when the list was NULL or the index negative, so it kept
it, re-seeded `hist[0]` and left the index where it was. `dctran.c`'s
`nextTime` appended the real times **after** the fallback's: a non-monotonic
timeline whose first microsecond was the operating point. The binary search
over it returned the operating-point value (a delayed variable read 0) or,
once t − td passed the fallback's horizon, whatever point the search fell on
(a delayed contribution passed its input through). An `idt` of a delayed
signal integrated the 0.

## What changed

**The timeline starts over at the transient's first Newton solve.**
`absdelay_ensure_timepoints(ckt, init_tran)` takes `MODEINITTRAN`; when it is
set the index goes to 0 and `CKTtimePoints[0]` to the current time (0)
whatever the list holds, not only when the list is NULL or the index
negative. `absdelay_stamp_tran` passes `true` (its only call is under
`is_init_tran`); `last_crossing_stamp`, which shares the list, passes its own
`is_init_tran`. Both re-raises of `MODEINITTRAN` in `dctran.c` are under
`firsttime`, i.e. still at t = 0, so the reset is always at the origin of the
transient being started; the fallback's own `MODEINITTRAN` resets its own
list the same way. The history rows are re-seeded from the converged
operating point as before, `OSDIaccept` overwrites index 1 onward, and the
stale entries beyond the index are never read.

Under the fallback every delay form now reads as under plain Newton: the
delayed step at 2 µs, the delayed current from 2 µs, the ramp from 1.5 to
2.5 µs, the integral of the delayed pulse, `maxdelay`, nested and parameter
delays, and the fallback forced from another instance. `last_crossing`
under the fallback still reads the negative sentinel before the edge and the
crossing time after it. Plain Newton, gmin stepping, source stepping and
`uic` are unchanged.

## Verification

| check | result |
|---|---|
| the delay-only model alone (plain Newton) | 0 at 1.5 µs, 1 at 2.5 and 4 µs — the reference, no fallback |
| the same with `l1 a 0 1m` across the source | `Transient op started … finished`; 0 at 1.5 µs, 1 at 2.5 and 4 µs (was 0, 0, 0) |
| `last_crossing` in that run | −1 at 0.5 µs, 1.0005 µs at 4 µs |
| `I(a,b) <+ V/1k + absdelay(V, 1u)/1k`, fallback forced by a second instance | −1 mA at 1.5 µs, −2 mA at 2.5 and 4 µs (was −1 mA throughout) |
| `transition(x, 0.5u, 1u)` under the fallback | 0.002 at 1.5 µs, 0.46 at 2 µs, 1.000 at 3 µs (was 0, 0, 0) |
| `idt(absdelay(V, 1u), 0)` on a 2 µs pulse | forces the fallback by itself; 0 at 1.5 µs, 2.02e-6 V·s at 4 µs (was 0, 0) |
| the fallback forced by an `idt(1.0)` in a second instance | the first instance's delay intact |
| `.tran … uic` | no fallback, the delayed step at 2 µs as before |
| the hunt's bisect decks (`maxdelay`, nested, parameter delay, `absdelay(slew())`, `slew(absdelay())`, `method=gear`, `maxord=1`) | all right under the fallback |
| the E-670 binaries on the suite | 5 of the 11 checks fail per solver (the two references, `uic`, `last_crossing` and the "fallback forced" observations pass there) |
| full sweep | 531 of 531 |

## What this does not do

- `OPtran` itself still leaves its timeline behind (`CKTtimePoints`
  allocated, `CKTtimeIndex` at its last point); the OSDI side no longer
  depends on that. An LTRA line after the same fallback reads the same stale
  list — stock ngspice's, and untouched here.
- The `last_crossing` cache is re-armed by `OSDItemp` before the operating
  point, not at `MODEINITTRAN`. A crossing observed during the fallback's own
  transient would persist into the real one; none can occur with the sources
  frozen at a converged point, and the suite's check reads the sentinel.
- A node joined only by delayed elements (the hunt's F8) diverges as before:
  that is the circuit's conditioning, not the timeline.
- The fallback's own dynamics are unchanged: an `idt` without an initial
  condition still needs the rung, and still starts the transient from the
  state the rung found.
