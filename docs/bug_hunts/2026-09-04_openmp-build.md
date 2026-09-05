# Bug hunt — the OpenMP build, measured and parked

**Date:** 2026-09-04 · **Commit under test:** `f926e877` · **Binaries:** a
second build of the same sources under `~/software-builds/version12/`,
`ngspice-46/build-omp` configured `--enable-openmp --enable-klu` with
Homebrew clang 18.1.8 and libomp 23.1.0, measured against the serial
`ngspice-46/build` (Apple clang, `--disable-openmp`). **Status: parked** —
nothing in the repository was changed; the build directory exists only under
version12.

The question was what ngspice and the compiled models would gain from
`--enable-openmp`. The earlier integration hunt had a code-reading finding
(its F5: the deferred-message buffers are unsynchronised under OpenMP) that
could not be reproduced without libomp; this pass installs it, builds, and
measures. Every number below is one run of the binary named, on a 24-core
machine (16 performance, 8 efficiency cores).

**Result: the OpenMP build is what ngspice intends for its built-in devices
and unsafe for compiled ones.** Built-in BSIM4 scales 2.7× at 8 threads. An
OSDI deck loses Enhancement-543's limiter (297 iterations with gmin stepping
where the serial build takes 9), crashes on any model that prints during
`eval`, and gets *slower* with every thread beyond two. Three findings, one
build note, and the design that would fix them, recorded so the work can be
picked up whole.

| # | finding | severity |
|---|---|---|
| [F1](#f1--the-osdi-openmp-branch-carries-no-limiter) | `osdiload.c`'s `USE_OMP` branch evaluates instances in `omp task`s and never calls `osdi_lim_apply`; the 100-stage chain takes 297 iterations with gmin stepping (serial: 9), `osdilimit_examples` fails 8 of 12 | **high** — E-543's headline lost |
| [F2](#f2--the-eval-time-message-path-races-and-crashes) | the deferred-output buffers are appended from concurrent tasks without synchronisation: `$warning` from 2 000 instances at 16 threads loses up to 64 messages and crashed 1 run in 6; `$write`/`$display`/`$monitor` from 2 000 instances crashed 4 runs in 4 | **high** — crash |
| [F3](#f3--one-task-per-instance-scales-negatively) | the 5 000-stage OSDI chain's load goes 12.0 → 8.5 → 20.0 → 37.3 s at 1/2/8/16 threads while the built-in twin goes 2.09 → 1.37 → 0.77 → 0.71 s | medium — the build's purpose |
| [N1](#n1-build--the-xspice-code-model-link-rule-drops-ldflags) | `--enable-openmp` fails to link the XSPICE code models: their rule takes CFLAGS (so `-fopenmp` and its implied `-lomp`) but not LDFLAGS, so libomp's search path is missing | low — build |

---

## Where the time goes without OpenMP

Both device kinds are load-bound on a 5 000-stage inverter chain (10 000
MOSFETs, operating point, KLU), so the evaluation phase is the right thing to
parallelise:

| deck | iterations | total | matrix load | factor + solve |
|---|---:|---:|---:|---:|
| OSDI BSIM4 chain | 480 | 5.24 s | 4.91 s | 0.06 s |
| built-in level 54 twin | 356 | 2.05 s | 1.80 s | 0.05 s |

Per device-evaluation the compiled model costs about twice the built-in
(1.0 µs against 0.5 µs), and 94 % of the run is evaluating and stamping.

## What the compiled model touches, and why it is safe

Read for this pass, not measured: `eval()` writes only its instance data and
the per-instance `OsdiExtraInstData`; `$random`/`$rdist_*` are pure hashes
of `(seed, salt)` in the compiled code (no runtime state); the `$simparam`
and plusargs tables are built once by `get_simparams()` before the parallel
region; the `$limit` callbacks (`osdi_pnjlim`, `osdi_fetlim`, `osdi_limitlog`)
are pure; the initial-step latch and the crossing history are per instance;
the `EVAL_RET_FLAG_LIM` non-convergence flag is stored per instance and
aggregated in the serial stamping loop. The compiler already parallelises its
own codegen per module with a rayon pool, and OpenMP does not touch it. What
is not safe is the simulator's services around the model: F1 and F2.

## F1 — the OSDI OpenMP branch carries no limiter

Enhancement-543 put the simulator-side MOSFET/BJT limiting into the *serial*
branch of `OSDIload` ([`osdiload.c:1338`](../../ngspice-46/src/osdi/osdiload.c)):
`osdi_lim_apply` patches up to four entries of the shared `CKTrhsOld` around
one instance's `eval`, then restores them. The `USE_OMP` branch at line 1246
evaluates every instance in its own `omp task` with the shared vector and
never calls it — and could not as written, since a patch to the shared vector
is a race against every other task's read.

| 100-stage OSDI BSIM4 chain, op | iterations | stepping | max |v − serial| | run to run |
|---|---:|---|---:|---:|
| serial build | 9 | no | — | — |
| OpenMP, 1 thread | 297 | dynamic gmin | 1.0e-16 V | 0 |
| OpenMP, 8 threads | 297 | dynamic gmin | 1.0e-16 V | 0 |

The converged point is the serial one and the run is deterministic; only the
path is the un-limited one. `osdilimit_examples` under the OpenMP binary:
4 passed, 8 failed — every iteration-count and every recognizer-verdict check
(the verbose report never prints because the code never runs).

The fix is a per-thread shadow of `CKTrhsOld`: one copy per thread per load
pass (N doubles × threads, negligible beside the evaluation), each task
patching and restoring its own thread's copy and passing it as
`prev_solve`; `CKTnoncon++` in the limiter becomes `#pragma omp atomic`, the
verbose-report statics go under `omp critical`.

## F2 — the eval-time message path races, and crashes

The integration hunt's F5, reproduced. `osdicallbacks.c` keeps the deferred
output in file-scope arrays (`pending`, `pending_len/cap`, `monitor_prev`,
`at_line_start`, the coalescing ring) and `osdi_log_defer()` appends to them
from inside `eval` with no synchronisation.

2 000 instances of a module that calls `$warning` at every evaluation, two
`op`s, `set num_threads=16`, six runs:

| run | exit | summary line, first op | second op |
|---|---:|---|---|
| serial (reference) | 0 | *repeated 1995 more times* | *repeated 1995 more times* |
| 1 | **139 (SIGSEGV)** | — (1 line of output) | — |
| 2 | 0 | 1995 | 1994 |
| 3 | 0 | 1995 | 1995 |
| 4 | 0 | 1994 | **1936** |
| 5 | 0 | **1958** | **1965** |
| 6 | 0 | 1994 | 1995 |

2 000 instances of `display_kinds` (`$strobe`, `$write` partial lines,
`$display`, `$monitor`), `dc v1 0 1 0.25`, 16 threads, four runs: exit −5
(SIGTRAP), −5, −6 (SIGABRT), −5; the two that printed anything before dying
had split 9 and 10 `$write` partial lines that the serial build joins 2 000
times. At **one thread** the OpenMP binary reproduces the serial output
exactly (4 802 lines, 2 000 joined writes, 198 monitor lines), so this is the
race alone, not the branch's handling of output.

The fix is per-thread deferral buffers merged into the shared queue in
instance order at the end of the parallel region — which also makes message
order deterministic, where today it would follow task completion.

## F3 — one task per instance scales negatively

The built-in devices use a per-model instance array and `#pragma omp
parallel for` (`b4ld.c`), evaluate in parallel and stamp serially. The OSDI
branch walks the linked list from an `omp single` region and spawns one
`omp task` per instance. For a 1 µs evaluation the task creation on the one
thread is the bottleneck and the other threads contend for it:

| deck | serial | 1 thread | 2 | 8 | 16 |
|---|---:|---:|---:|---:|---:|
| built-in BSIM4, 5 000 stages, op load | 1.80 s | 2.09 s | 1.37 s | 0.77 s | 0.71 s |
| built-in BSIM4, 1 000 stages, tran load | 0.38 s | 0.40 s | — | 0.16 s | — |
| OSDI BSIM4, 5 000 stages, op load | 4.98 s (480 it.) | 12.0 s (929 it.) | 8.5 s | 20.0 s | 37.3 s |
| OSDI BSIM4, 500 stages, op load | 0.10 s (135 it.) | 0.39 s (520 it.) | 0.28 s | 0.97 s | — |
| OSDI BSIM4, 1 000 stages, tran load | 0.82 s (666 it.) | 0.85 s (1 134 it.) | — | 1.55 s | — |

The iteration counts differ because of F1; per load pass the OpenMP build's
single thread is 16 % slower on the built-in (Homebrew clang against Apple
clang, plus the parallel region's overhead) and 25 % slower on OSDI (the
task overhead on top). `OMP_WAIT_POLICY=PASSIVE` took the 8-thread OSDI load
from 20.0 to 17.2 s; `OMP_PLACES=cores OMP_PROC_BIND=close` changed nothing.

The fix is the built-in shape: an instance pointer array per model built at
setup, `parallel for` with static scheduling over it, the serial stamping
loop unchanged. With load at 94 % of the run and the stamping perhaps a
sixth of it, Amdahl puts the ceiling near 4× on 16 cores for this BSIM4, and
higher for the models whose evaluation is 5–20× dearer.

## N1 (build) — the XSPICE code-model link rule drops LDFLAGS

`configure --enable-openmp` adds `-fopenmp` to CFLAGS (AC_OPENMP). The
code models under `src/xspice/icm/*/` are linked by their own rule from
CFLAGS without LDFLAGS, so the link sees `-fopenmp` (which implies `-lomp`)
and not `-L/opt/homebrew/opt/libomp/lib`: *ld: library 'omp' not found* on
`spice2poly/spice2poly.cm`, and the build stops. `LIBRARY_PATH=/opt/homebrew/opt/libomp/lib make`
is the workaround used here. Apple's `/usr/bin/clang` does not accept
`-fopenmp` at all; the build needs Homebrew's clang (`llvm@18`).

## What was measured and holds

* Under the OpenMP binary at the default two threads, the suites osdimc,
  montecarlo, mcpolicy, display, lrmcontrib, lrmcoreops, osdiparam, osdisens
  and simctrl pass on both solvers; only osdilimit fails (F1).
* Converged operating points are the serial ones to 1e-16 V at every thread
  count tried, and bit-identical run to run, on decks that print nothing
  during `eval`.
* A minimal OpenMP program with this toolchain reports 24 threads; the
  built-in BSIM3/4/SOI/HiSIM parallel path works as upstream intends.

## Coverage, honestly

* Only BSIM4 was timed; PSP103, HiCUM and MEXTRAM under OpenMP were not run.
  Their dearer evaluation would move F3's numbers, not its sign.
* F2 was provoked with 2 000 and not 20 000 instances, and with `dc`
  rather than `tran`; the crash rate would only rise.
* The built-in devices' own `CKTnoncon++` inside their parallel region
  (upstream ngspice, `b4ld.c`) is an unsynchronised increment too; not
  measured, not ours.
* Probe decks are under the session scratchpad `hunt3/` (`omp5k.cir`,
  `omp5kb.cir`, `c100o.cir`, `race.cir`, `wrace.cir`, `s500.cir`,
  `t1k.cir`).
