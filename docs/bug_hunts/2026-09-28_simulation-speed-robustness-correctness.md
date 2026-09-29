# Bug hunt — simulation speed, robustness and correctness of the core with compiled models

**When:** 2026-09-28, 19:08–19:25 of probing (the hour's budget included the write-up).
**Tree:** E-757 (`fb5a3948`), both solvers. **Harness:** `sp/run.py` and the `p*.va` /
`_*.cir` probes in the session scratchpad (`57176c0c`, `scratchpad/sp/`). Every number
below was measured; a probe whose deck was wrong is listed as such under *Coverage*.

**Method.** Compiled models of the basic analog operators (a resistor, a capacitor, an
inductor, an exponential diode with `limexp`, a noisy resistor, an integrator, a Laplace
filter, a switch with and without `@(cross)`/`$bound_step`/`$discontinuity`, a nonlinear
and a time-varying capacitor, a piecewise-linear and a hysteretic diode) were run beside
their built-in twins and against closed-form answers in `op`, `dc`, `ac`, `noise` and
`tran`, with `rusage all` for the iteration, timepoint and time split; the CMC BSIM4
(`bsim4va`) against `level=54`; a `sample` profile of a 1.2-million-iteration run.

| # | Finding | Severity |
|---|---|---|
| [F1](#f1--every-newton-iteration-with-a-compiled-model-calls-getcwd) | *(fixed in [E-758](../../enhancements_doc/Enhancement-758.md): the cwd is cached and re-read after `cd`; 0.63 µs per iteration, the PRBS run 0.28 s)* every Newton iteration with a compiled model calls `getcwd()` — 12 µs of the 14.4 s of a 1.2 M-iteration run were spent there (89 %); a 10 Gb/s PRBS through a compiled RC takes 3.07 s where the built-in RC takes 0.14 s; caching it (scratch experiment) gives 0.29 s | **high** — speed, every deck with a compiled model |
| [F2](#f2--cross-does-not-control-the-timestep) | *(fixed in [E-759](../../enhancements_doc/Enhancement-759.md): the event lands the step on the interpolated crossing; 0.04 ns at a 100 ns step, 0.001 ns with `time_tol = 1p`, exact counts under the 500 MHz drive)* `@(cross(...))` does not control the timestep: the crossing is resolved only to the step grid (11–20 ns error at a 100 ns step, the same as a plain `if` and as the built-in switch), the `time_tol` argument is ignored; `$discontinuity(0)` in the event body brings the error to 1.2 ns, `$bound_step` to 0.1 ns at 30× the points | **medium** — LRM 5.10.3, timing accuracy of every event-driven model |
| [O1](#observations) | *(fixed in [E-760](../../enhancements_doc/Enhancement-760.md): the repeat-ring walk, the three option lookups, the version parse and the runtime's file walk are hoisted; 0.11 µs per iteration, 1.3× built in)* the compiled load path's remaining fixed cost after F1 is ~1 µs per iteration (built-in: 0.06 µs); per instance ~14–20 ns against 9 ns built in | observation |
| [F3](#f3--the-output-path-queries-free-memory-and-the-clock-on-every-accepted-point) | `OUTpData` calls `getAvailableMemorySize()` (a Mach `host_statistics` and a port trap on macOS), `clock()` (a `getrusage`) and `cp_getvar("no_mem_check")` on every accepted point: about 1 µs per point, 48 % of a 600 000-point transient, compiled or built in | **medium** — every transient with many points, any device set |
| [O2](#observations) | BSIM4: compiled 1.00 µs per device-iteration against 0.54 built in, and 39 % more Newton iterations per transient timepoint, independent of the simulator-side limiter (which halves the operating point's) | observation (options hunt F3/F4) |
| [O3](#observations) | a bare `exp()` diode without `$limit` needs gmin stepping and 2178 iterations at the operating point where `$limit(..., "pnjlim")` needs 8 and the built-in 6; `limexp` needs 42 at 2 V through 1 Ω | observation, model-side |
| [O4](#observations) | the compiled capacitor's truncation-error step costs 2.4× the built-in's (47 ns against 20 ns per state per timepoint) | observation |

## F1 — every Newton iteration with a compiled model calls `getcwd()`

**Observed.** A 300-stage compiled RC ladder loads 7.7× slower than the built-in
one for identical iteration and timepoint counts (0.323 s against 0.042 s over 8112
iterations). Scaling the ladder shows the cost is not per instance:

| devices | built-in load per device-iteration | compiled |
|---|---|---|
| 200 | 8.5 ns | 131.8 ns |
| 600 | 9.4 ns | 58.3 ns |
| 2000 | 9.5 ns | 31.4 ns |

A fit gives ~20 ns per compiled instance plus a **fixed ~12 µs per Newton iteration**,
confirmed directly: one compiled resistor, 12.08 µs per iteration; 100 of them, 13.6 µs;
100 instances over 100 model cards, 13.7 µs; one built-in resistor, 0.06 µs.

A `sample` profile of a single-instance transient (1 215 614 iterations, 14.42 s of
analysis of which 12.81 s load) puts 2303 of 3394 samples under `__open_nocancel`, with
`stat`, `fstat`, `fcntl` and `close` behind it, all on one path:

```
OSDIload -> get_simparams -> __private_getcwd -> __getcwd -> open$NOCANCEL
```

`get_simparams()` (`osdi/osdiload.c`) fills the `$simparam$str` table on every load
call and its `"cwd"` entry is "refreshed per query" through `osdi_cwd()`, which calls
`getcwd()`; on macOS that opens and stats the directory chain. The cost is paid
whether or not any model ever asks for `cwd`.

**Measured impact.** The 10 Gb/s PRBS7 stream of E-752 through a compiled 50 Ω/0.4 pF
channel, 3000 bits: 3.07 s wall (2.86 s load, 138 122 iterations) against 0.14 s for the
built-in RC, identical timepoints (69 062). The 500 MHz switching run: 1.06 s against
0.10 s. Every small circuit with any compiled model is dominated by this cost; a
large one hides it behind per-instance work.

**Scratch experiment.** Caching the string once (a two-line change to `osdi_cwd()`,
reverted after the measurement): one instance 1.08 µs per iteration, 100 instances
2.46 µs; the PRBS run 0.29 s (load 0.107 s). The remaining ~1 µs is the per-iteration
hooks (`osdi_note_iteration`'s display/io begin, the two `cp_getvar` string lookups for
`noosdilim`/`osdilim_verbose`, the simparam array fill), see O1.

**Fix.** Cache the working directory and refresh it only when it can change: `com_chdir`
(the `cd` command) invalidates, `osdi_cwd()` recomputes on the next query. Nothing else in
ngspice changes the process directory. The same pass can hoist the two `cp_getvar` calls
to once per analysis.

*Fixed in [E-758](../../enhancements_doc/Enhancement-758.md).* `osdi_cwd()` caches the string and the `cd` command marks it
stale through `OSDIcwdChanged()`; one instance now loads in 0.63 µs per iteration, a
hundred in 2.04 µs, the PRBS run takes 0.28 s and the 500 MHz switching run 0.15 s. The
`cp_getvar` lookups and the iteration hooks are left as they are (O1).

## F2 — `@(cross)` does not control the timestep

**Observed.** A compiled switch driven by a 0→1 V ramp over 1 µs (threshold 0.5 V,
crossing at exactly 500 ns) with `@(cross(V(c) - vth, 0))` in its analog block, measured
by the output's own 0.5 V crossing:

| model | tstep 10 n: rise error | tstep 100 n: rise / fall error | timepoints |
|---|---|---|---|
| `@(cross(..., 0))` | 2.2 ns | 11.2 / 20.0 ns | 62 |
| `@(cross(..., 0, 1p))` (time_tol) | — | 11.2 / 20.0 ns | 62 |
| plain `if (V(c) > vth)`, no event | 2.2 ns | 11.2 / 20.0 ns | 62 |
| built-in `sw` model | 2.2 ns | 11.2 / 20.0 ns | 62 |
| `@(cross(...)) $discontinuity(0);` | 0.01 ns | 1.2 / 2.5 ns | 71 (3 rejected) |
| `$bound_step(1n)` | 0.1 ns | 0.1 / 0.0 ns | 2007 |

The cross event changes nothing about the step sequence: the same point count, no
rejected point, the same crossing error as a model with no event at all, and the
`time_tol` argument is ignored. LRM 5.10.3: the simulator shall place a timepoint at the
crossing, within `time_tol` when given. In the event-heavy run (500 MHz switching, 2 µs)
every crossing costs one rejected point (4002 of 41 008) because the step after the
crossing fails and is cut, instead of the crossing being landed on.

**Where.** `osdi/osditrunc.c` acts on `$discontinuity` (E-55's edge-triggered retry at
delta/8 and E-24's no-growth sentinel) and on `$bound_step`; nothing in it or in
`osdiaccept.c` reads a cross event. `osdiaccept.c` already computes crossing times by
linear interpolation for `last_crossing()`.

**Fix.** When a cross event fires at a converged-but-not-accepted point (its expression
changed sign since the last accepted point), request the step that lands on the
interpolated crossing (the `last_crossing` interpolation, applied before acceptance)
rather than the blind delta/8 cut, retrying until the point is within `time_tol` (default:
the step's own tolerance, as E-55 uses), and let `$discontinuity` inside the event keep
its meaning. The `$discontinuity(0)` row shows the retry machinery alone already gets
within 1.2 ns at a 100 ns step; interpolation should reach the tolerance in one retry.

*Fixed in [E-759](../../enhancements_doc/Enhancement-759.md).* Not quite as sketched: the
event, not `osditrunc.c`, locates the crossing (it keeps the sample at the last accepted
point, which ngspice now identifies through the `$osdi$point` count) and asks for the
landing through the bound-step slot; `OSDItrunc` makes the landing the attempt's step
and forces the rejection, and `dctran` accepts the landing once converged. One retry for
a linear crossing (the switch closes 0.04 ns late at a 100 ns step, 0.001 ns with
`time_tol = 1p`), a second for a curved one (a sine at a 60 ns step: 0.2 ns, then
0.04 ns). The 500 MHz run counts 1000/1000/2000 exactly for the same work (39 005
points, 4000 rejected, 88 008 iterations against 41 008, 4002, 84 016). A
`$discontinuity(0)` in the body no longer redoes the approach: E-55's eighth is the step
after the landing. The plain `if` and the built-in `sw` are unchanged.

## F3 — the output path queries free memory and the clock on every accepted point

**Observed.** The profile taken for O1 put 48 % of the one-instance `prof` transient
(600 000 accepted points) under `CKTdump → OUTpData`, in three calls made once per
accepted point, whatever the devices: `getAvailableMemorySize()`, which on macOS is a
Mach `host_statistics` plus a `mach_host_self` port trap (about 1000 of 3047 samples);
`clock()`, a `getrusage` system call, in the progress throttle (about 380 samples); and
`cp_getvar("no_mem_check")`, a variable lookup by name (about 45 samples). About 1 µs
per point. The built-in run has the same share: its 1.20 s transient is half output
bookkeeping, and the 300-stage RC ladder and the PRBS runs of F1 carry it too.

**Where.** `frontend/outitf.c`: `OUTpD_memory()` estimates the memory the next vector
growth needs and compares it with the free memory on every point, although
`AddRealValueToVector` grows a vector only when `v_length` reaches `v_alloc_length`
(`vlength2delta`: a chunk sized from the point count, so a few times per run); the
progress-print throttle reads the clock to decide whether a quarter second has passed,
which costs more than the print it throttles at this point rate.

**Fix.** Query the free memory only when a vector is about to grow (the chunk boundary
`OUTpD_memory` already computes from), cache `no_mem_check` behind E-760's variable
state stamp, and throttle the clock read itself (every 256 points, or by the point count
against the last draw). Expected: about half the transient time of a small circuit at a
fine step, compiled or built in.

## Observations

**O1 — the fixed per-iteration cost after F1.** 1.08 µs for one instance against
0.06 µs built in: `osdi_note_iteration()` (display and io iteration-begin hooks, the
severity context refresh), two `cp_getvar` lookups by name on every load call, the
simparam array fill. Hoistable to once per analysis in the F1 pass.

*Fixed in [E-760](../../enhancements_doc/Enhancement-760.md).* A `sample` profile after
E-758 (0.63 µs per iteration on the same deck) put the cost elsewhere than guessed: the
repeated-message summary walked its 64-slot ring and freed two NULL pointers per slot on
every iteration (about 60 % of the load samples), three `cp_getvar` lookups by name
(`noosdilim`, `osdilim_verbose`, `scale`; about 25 %), `strtod(PACKAGE_VERSION)`, and the
compiled runtime's file hook walking 64 empty slots. A live-slot count, a variable state
stamp (the options re-read only when a `set`, `unset`, circuit or plot changes), a static
version and an early return in the hook: 0.11 µs per iteration, 1.3× the built-in
resistor; the `prof` transient 1.32 s against 2.12 s (built in 1.20 s), the PRBS run
0.155 s, the 500 MHz switching run 0.073 s.

**O2 — BSIM4.** A 100-stage common-source chain, 1 ns steps over 1 µs: compiled 1.00 µs
per device-iteration, built-in `level=54` 0.54 µs; timepoints identical (1008), Newton
iterations 2803 against 2014 (2.8 against 2.0 per point); the answers agree to 1.2 %
(`v(o3)` 0.02673 against 0.02641, the two model versions differ). With
`option noosdilim` the transient iterations are unchanged (2803) while the operating point
takes 216 instead of 92, so the extra transient iterations are not the limiter's; they are
the model's own (the options hunt's F3/F4).

**O3 — limiting is the model's job, and it matters.** At the operating point of
2 V through 1 Ω: the built-in diode (pnjlim) converges in 6 iterations, a compiled model
using `$limit(V, "pnjlim", ...)` in 8, the `limexp` diode in 42, and a bare `exp()`
only through gmin stepping in 2178. In the transient that follows, all three take the
same 3008 points and within 10 % the same iterations. Models written with `exp()` and no
`$limit` are the exposure; the simulator-side limiter (E-543) recognises MOSFET/BJT
terminal names only.

**O4 — truncation-error time.** 1000 compiled capacitors: 0.0957 s of `Transient trunc
time` over 2033 points against 0.0410 s built in — 47 ns against 20 ns per state per
point. About 10 % of the transient time of a capacitive circuit.

**O5 — integration methods on a Q = 3162 tank** (series RLC, 200 points per cycle, 100
cycles): trapezoidal keeps the envelope at 0.90633 against the exact 0.90574 (+0.065 %),
Gear at 0.90194 (−0.42 %, numerical damping). Both as expected; noted for anyone reading
a decay off a Gear run.

**O6 — an absurd capacitance.** `c=1e300` fails with "Timestep too small; initial
timepoint: cause unrecorded" on both device kinds (c/dt overflows). `c=1e30` and
`r=1e-300`/`1e300` are handled exactly; the built-in resistor clamps `1e-300` to 1e-12
with a warning, the compiled one does not clamp and gets the right 1e-303 V.

## What held

- The compiled resistor, capacitor, inductor and noisy resistor match the built-ins and
  the closed forms to the printed digits: the RC step at τ and 3τ, |I| of C and L at
  1 MHz, the thermal noise of 1 kΩ ∥ 1 MΩ (4.06934e-9 against 4.069338e-9 V/√Hz), the
  exponential diode at 27 °C and 100 °C (`limexp` against `xti=0 eg=0`), `.ic` with `uic`
  through a compiled capacitor (0.816061 against 0.816060 at 1 µs).
- `idt` and `laplace_nd` in AC (six digits over 1 kHz–100 MHz) and in the time domain
  (the lowpass step at 1/ω₀ 0.63212; the integrator's mean after 1000 cycles 1.59142e-7
  against 1.591549e-7, no drift); a time-varying capacitance `ddt(c(t)·V)` ±3.14161e-3
  against ±3.141593e-3; the compiled LC tank's amplitude and 19th zero equal to the
  built-in's; a nonlinear capacitor's net charge per cycle at 1e-5 of a half-cycle's
  charge, trapezoidal and Gear, no growth over 10 cycles.
- KLU and Sparse agree on every probe, the 1e-9/1e15 Ω divider and the 2 µs switching
  run included; a 60-diode series ladder at 30 V converges directly on both, 4–5
  iterations, compiled and built-in; `.dc` over 301 points takes 2.0 (built-in) and 2.4
  (compiled) iterations per point; the piecewise-linear and the hysteretic diode converge
  in 3–4 iterations at the knee.
- 10 000 compiled resistors: the same 0.05 s wall as 10 000 built-in ones, +3.8 MB;
  memory over 1.2 M iterations is the stored waveforms (25 MB), no growth beyond them;
  `montecarlo` 100 samples takes the fast path on both kinds; an AC sweep of a 1000-stage
  ladder over 1001 points costs the same on both (0.067 s).
- Coarse-step accuracy (tstep = τ/2) is identical for the compiled and the built-in
  capacitor; the step sequences are identical in every paired run (the same `tp` and
  `rej`).

## Coverage, honestly

Three probes were wrong the first time and are recorded corrected: an inductor left
open (the "tank" did not decay), a `.model` card's `r1=1M` (SPICE's milli, not the
model's mega), and a memoryless diode chain used as a tolerance probe (no state, so
`reltol` could change nothing); a fourth mistook the DC operating point's charging of a
capacitor for a wrong answer. Not probed: noise of compiled models beyond the resistor,
`sens`/`pz`/`sp` with compiled models (their own suites), `.option` extremes (`gmin`,
`abstol` against fA currents), OpenMP (parked), the shared library, transient noise, and
the per-iteration cost on Linux (whether `getcwd` is as expensive there — it is a syscall
either way). F1's fix was measured in a scratch build and reverted; nothing is folded.
