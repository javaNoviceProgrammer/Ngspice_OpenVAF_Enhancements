# Design — multithreaded device evaluation without OpenMP

**Date:** 2026-09-26 · **Status: design proposal with a measured profile;
nothing in the code changed.** Builds
on the measured pass [2026-09-04_openmp-build.md](2026-09-04_openmp-build.md)
(the OpenMP build, parked) and on the solver scoping note
[parallel_solver_scope.md](../internals/ngspice_internals/parallel_solver_scope.md).
The question asked was: *if the OpenMP build is unsafe for compiled models,
how would a multithreading feature be built from scratch so that it works on
every platform?* This page is the answer, recorded so the work can be picked
up whole.

**The short form: threads are not incompatible with OSDI; ngspice's OpenMP
branch is.** The 2026-09-04 pass established by reading that the compiled
`eval` is safe to run concurrently, and by measuring that the three things
that broke were all in the simulator's loop around it. The design below is a
small thread pool owned by ngspice (pthreads or Win32, no new dependency)
driving the one shape that is known to work — *evaluate in parallel over an
instance array, stamp serially in instance order* — for the OSDI devices
first and the eight built-ins that already have that shape second. Its
defining property is that the numbers are bit-identical to the serial build
at every thread count, which makes the whole regression sweep the oracle.

**What it is worth, measured** (the section *What it buys* below): on a
10 000-device chain two thirds of the run is the compiled `eval`, the
serial stamping loop is a fifth and KLU is a few per cent, for the VA BSIM4
and for PSP103 alike. Phase 1 therefore gives about 2.4× at 8 threads and
2.7× at 16 on the whole run, with a ceiling of 3×; parallel stamping, the
later phase, lifts that to 4.4× and 5.7×. A single-thread KLU run is not the
thing being waited on in this regime: it is 3.5–10 % of the time.

---

## What the OpenMP pass established

Everything here is measured or read in
[2026-09-04_openmp-build.md](2026-09-04_openmp-build.md); it is summarised so
this page stands alone.

| finding there | what it was | what it means for a new design |
|---|---|---|
| F1 | the `USE_OMP` branch of `OSDIload` never calls the E-543 limiter; the limiter patches up to four entries of the *shared* previous solution around one instance's `eval`, a race against every other task | the limiter needs a per-thread view of the previous solution |
| F2 | `$warning`/`$display`/`$write`/`$monitor` from inside `eval` append to file-scope buffers in `osdicallbacks.c` with no synchronisation; 2 000 printing instances lost messages and crashed | every static reachable from `eval` must become per-thread state merged afterwards |
| F3 | one `omp task` per instance, spawned from a linked-list walk on one thread: the 5 000-stage OSDI chain went 12.0 → 8.5 → 20.0 → 37.3 s at 1/2/8/16 threads while built-in BSIM4 went 2.09 → 1.37 → 0.77 → 0.71 s | partition an instance *array* into static chunks; never a task per instance |
| N1 | `--enable-openmp` needs Homebrew clang and libomp; Apple's clang rejects `-fopenmp`; the XSPICE code-model link rule drops LDFLAGS | OpenMP is the wrong portability layer |

And what that pass read as safe, which is the foundation:

* `eval()` writes only its instance data and the per-instance
  `OsdiExtraInstData`;
* `$random` / `$rdist_*` are pure hashes of `(seed, salt)` in the compiled
  code, no runtime state;
* the `$simparam` and plusargs tables are built once by `get_simparams()`
  before any instance is evaluated;
* the `$limit` callbacks (`osdi_pnjlim`, `osdi_fetlim`, `osdi_limitlog`) are
  pure functions;
* the initial-step latch, the crossing history and the `EVAL_RET_FLAG_LIM`
  flag are stored per instance;
* the handle passed to `eval` is a stack object of the caller
  ([`osdiload.c:870`](../../ngspice-46/src/osdi/osdiload.c)).

Where the time goes decides what to parallelise. On a 5 000-stage OSDI BSIM4
chain 94 % of the run is evaluating and stamping and the factorisation is
1 %; on a 180 k-instance resistor mesh it is the other way round (57 % in
`klu_kernel` + `klu_refactor`, `eval` near 0 %). This page is about the
first regime; the split of that 94 % between the evaluation and the stamping,
which decides the gain, is measured in *What it buys*. The second regime is
the solver track and is scoped separately.

## Why OpenMP is the wrong portability layer

* **macOS.** Apple's `/usr/bin/clang` does not accept `-fopenmp`. The OpenMP
  build needs Homebrew's `llvm@18` and `libomp`, a second toolchain for the
  one platform this project is developed on.
* **Windows.** MSVC's default `/openmp` is the OpenMP 2.0 dialect, which has
  no `task` construct — the very construct the current OSDI branch is built
  on. MinGW has it through libgomp, MSVC only with `/openmp:llvm`.
* **The build.** The XSPICE code models are linked from CFLAGS without
  LDFLAGS, so `-fopenmp` implies `-lomp` with no search path (N1 above).
* **Debuggability.** A pthread pool built with the platform compiler runs
  under ThreadSanitizer as-is. Homebrew's libomp is not instrumented, and
  the OpenMP build could only *crash* on F2 where a TSan build would name the
  race.
* **Control.** With our own pool the partition, the chunk size, the
  per-worker storage and the merge order are all ours to fix, and the
  behaviour is the same under every compiler.

The tree already carries the portability shim this needs:
[`alloc.c`](../../ngspice-46/src/misc/alloc.c) and
[`dvec.c`](../../ngspice-46/src/frontend/dvec.c) switch between
`pthread_mutex_t` and `CRITICAL_SECTION` on the same `#ifdef`, and
`sharedspice.c` runs its background thread the same way.

## The design

### 1. A pool owned by ngspice

One new file, roughly 300 lines, `src/misc/ngthread.c` with its header, on
the pthread/Win32 split above. No new dependency, no configure switch beyond
`--disable-threads` for a build that wants the serial code only.

```c
typedef struct ng_pool ng_pool;
typedef void (*ng_region_fn)(int worker, size_t begin, size_t end, void *ctx);

ng_pool *ng_pool_create(int nworkers);          /* nworkers includes the caller */
void     ng_pool_run(ng_pool *p, size_t nitems, size_t min_chunk,
                     ng_region_fn fn, void *ctx);
int      ng_pool_workers(const ng_pool *p);
void     ng_pool_destroy(ng_pool *p);
```

* Workers are created once, at `CKTsetup`, from the `num_threads` variable
  that [`cktsetup.c:671`](../../ngspice-46/src/spicelib/analysis/cktsetup.c)
  already reads for OpenMP, and destroyed with the circuit.
* Workers park on a condition variable, but spin for a few tens of
  microseconds first: a load pass is a few milliseconds and must not pay a
  kernel wake-up per region.
* The calling thread is worker 0 and takes the first chunk.
* `ng_pool_run` partitions `[0, nitems)` into `nworkers` contiguous chunks in
  index order (static schedule). A region with fewer than `min_chunk` items
  per worker runs on the caller with no hand-off at all, so a model with a
  handful of instances costs nothing.
* The join is a mutex/condvar handshake, which is the happens-before edge
  that makes the workers' writes to instance data visible to the serial
  stamping loop. No atomics are needed in the model path.

### 2. Instance arrays

OSDI setup builds a pointer array per model, exactly as
[`b4set.c:2698`](../../ngspice-46/src/spicelib/devices/bsim4/b4set.c) builds
`BSIM4InstanceArray`, and frees it with the model. The linked list stays for
everything else. Instances of one module cost about the same, so the static
schedule is the right one; if a module ever mixes cheap and dear instances
(bypass, or a `$simparam`-gated branch), a chunk-of-64 dynamic schedule on an
atomic counter is a ten-line change inside the pool.

### 3. Evaluate in parallel, stamp serially, in instance order

This is the shape of the eight built-in devices with OpenMP code
(`b3ld.c`, `b3v32ld.c`, `b4ld.c`, `b4v5ld.c`, `b4v6ld.c`, `b4v7ld.c`,
`b4soild.c`, `hsm2ld.c`): a `parallel for` over the instance array that
evaluates, then a serial `LoadRhsMat` that stamps. It is the reason the
results are bit-identical to the serial build: the only floating-point
*sums* in a load pass are the stamps into the shared matrix and right-hand
side, and their order does not change.

The region body per instance, replacing the `omp task` in
[`osdiload.c:1820`](../../ngspice-46/src/osdi/osdiload.c):

```c
static void osdi_eval_region(int w, size_t b, size_t e, void *ctx_)
{
    OsdiLoadCtx *ctx = ctx_;
    OsdiWorker  *wk  = &ctx->worker[w];        /* per-worker slots, see 5. */
    OsdiSimInfo  si  = *ctx->sim_info;         /* private copy */
    si.prev_solve = wk->prev_solve;            /* shadow or shared, see 4. */
    for (size_t i = b; i < e; i++) {
        GENinstance *gen = ctx->insts[i];
        void *inst = osdi_instance_data(ctx->entry, gen);
        OsdiExtraInstData *x = osdi_extra_instance_data(ctx->entry, gen);
        OsdiLimPatch lp;
        osdi_lim_apply_on(wk->prev_solve, ctx->ckt, ctx->entry, inst,
                          ctx->model, x, &lp, wk);
        if (!x->has_evaluated) si.flags |=  EVAL_FLAG_IS_INITIAL_STEP;
        eval(ctx->descr, gen, inst, x, ctx->model, &si, wk);
        if (!x->has_evaluated) { si.flags &= ~EVAL_FLAG_IS_INITIAL_STEP;
                                 x->has_evaluated = true; }
        osdi_lim_restore_on(wk->prev_solve, &lp);
    }
}
```

The serial loop that follows is the present one from
[`osdiload.c:1898`](../../ngspice-46/src/osdi/osdiload.c), untouched: `load`,
the absdelay, crossing, transition, slew, short and transient-noise stamps,
the per-instance flag accumulation and the OR-reduction of `eval_flags`.
`OSDIload` is called once per compiled module by `CKTload`, so a region is
one module's instances; the modules run one after another as today.

### 4. The limiter (E-543)

`osdi_lim_apply` at [`osdiload.c:1047`](../../ngspice-46/src/osdi/osdiload.c)
patches up to four entries of `CKTrhsOld` before one instance's `eval` and
restores them after. Under threads each worker gets its **own shadow of the
previous solution**: one vector of the node count per worker, allocated with
the pool, refreshed by one `memcpy` per worker per load pass, patched and
restored by that worker alone, and handed to `eval` as `prev_solve`. The copy
is O(nodes × workers) against O(instances × 1 µs) of evaluation, negligible
on any deck where evaluation is the cost. When `.option noosdilim` is set,
or the module has no limited branch, the shared vector is passed read-only
and nothing is copied.

The alternative, an overlay read by the compiled code, would need an ABI
change in `OsdiSimInfo` and is not worth it while the copy is free.

### 5. Thread-local state, audited once

The rule: **a callback reachable from `eval` writes only its worker's slot;
the slots are merged after the join in instance order; everything else stays
on the serial path.** Per-worker slots indexed by the worker number are
preferred to compiler thread-local storage: no portability question, and the
merge is a plain loop. The inventory, from the tree as it stands:

| state | where | today | under the pool |
|---|---|---|---|
| deferred-output queue (`pending`, `pending_len/cap`) | [`osdicallbacks.c:453`](../../ngspice-46/src/osdi/osdicallbacks.c) `osdi_log_defer` | file scope | per-worker queue, merged in instance order — message order becomes independent of the thread count, and equal to the serial build's |
| repeat-coalescing ring (`rep_ring`, `rep_next`) | `osdicallbacks.c:75` | file scope | per-worker ring; the *repeated N more times* summary is computed at the merge |
| partial-line flags (`at_line_start`) and `monitor_prev` | `osdicallbacks.c:51`, `:323` | file scope | per-worker; `$write` partial lines are joined at the merge, `$monitor`'s previous values live per instance already |
| iteration-begin latch (`osdi_note_iteration` statics) | [`osdiload.c:1285`](../../ngspice-46/src/osdi/osdiload.c) | file scope | called once, on the serial path, before the region |
| limiter report counters (`osdi_lim_nreported`, verbose statics) | `osdiload.c:974` | file scope | per-worker counters, summed after the join |
| `CKTnoncon++` | limiter and the `EVAL_RET_FLAG_LIM` path | shared counter | per-worker count reduced into `CKTnoncon` after the join; the flag path is already serial |
| `has_evaluated`, `eval_flags`, `point_eval_flags` | `OsdiExtraInstData` | per instance | unchanged |
| `$simparam`, plusargs tables | `get_simparams()` | built before the loop | unchanged |
| `OsdiNgspiceHandle` | stack of `eval()` wrapper | per call | unchanged |

Memory allocation inside `eval` (string formatting for `$sformat`, the
message text) goes to the system allocator, which is thread-safe on every
platform this builds on; ngspice's own `tmalloc` already takes its mutex
when the shared library's background thread is compiled in.

### 6. The built-ins

The `#pragma omp parallel for` in
[`b4ld.c:81`](../../ngspice-46/src/spicelib/devices/bsim4/b4ld.c) and its
seven siblings becomes a macro over the pool, so BSIM3, BSIM4 (four
versions), BSIM-SOI and HiSIM2 scale under every compiler rather than only
under a libomp build. Their `CKTnoncon++` inside the parallel part — an
unsynchronised increment in upstream ngspice, noted in the 2026-09-04 page
and not ours — gets the same per-worker counter. `omp_set_num_threads` in
`cktsetup.c` and the `USE_OMP` gates go with it.

### 7. The solver is a separate track on the same pool

Nothing above helps a mesh, whose profile is the factorisation. The cheap
step is factoring KLU's independent BTF blocks in parallel inside the
refactor, on this pool; the real lever for a connected circuit is NICSLU as
a third SMP back end. Both are scoped in
[parallel_solver_scope.md](../internals/ngspice_internals/parallel_solver_scope.md)
and neither changes here.

### Runtime control

* `set num_threads=N` stays the switch (the name exists); an environment
  variable `NGSPICE_NUM_THREADS` for batch runs; the count printed by
  `rusage` next to the load time.
* `N = 1` must reproduce today's output byte for byte, and is the default
  for the first release; flipping the default to the core count is a
  one-line change once the sweep passes at every count.

## Phases

| phase | content | size | ships as |
|---|---|---|---|
| 1 | the pool; OSDI instance arrays; the eval region; the limiter shadow; the thread-local audit of `osdicallbacks.c` and `osdiload.c`; `num_threads` plumbing; suite checks at 1, 2 and 8 threads | ~1 000 lines of C | one enhancement |
| 2 | the eight built-ins on the pool macro; `USE_OMP` retired | mechanical | one enhancement |
| 3 | BTF blocks factored in parallel in the KLU refactor | small, topology-limited gain | one enhancement, solver side |
| later | parallel stamping by graph colouring (instances sharing a matrix entry get different colours; colours stamp in order, so the sums stay deterministic); NICSLU | the serial stamp is 18–23 % of the run (measured below), so this is the step from 2.4× to 4.4× at 8 threads | — |

## What it buys

Measured on 2026-09-26 on the serial E-738 binary (`ngspice-46/build`,
`.option klu`), so the numbers are the baseline a pool build has to beat.
The deck is a 10 000-stage NMOS common-source chain, one compiled MOSFET
and a 20 k load per stage, once with the VA BSIM4 of
`examples/benchmark_examples/bsim4va.osdi` and once with its `psp103.osdi`.
The split comes from the macOS `sample` profiler at 1 ms over the first
8 s (BSIM4) and 10 s (PSP103, which is its operating-point phase), self
time per symbol, on a 16-performance-core machine.

| deck | analysis | iterations | total | matrix load | KLU factor + solve | per device per iteration |
|---|---|---:|---:|---:|---:|---:|
| VA BSIM4 | `op` | 146 | 1.5 s | 1.29 s | 0.02 s | 0.88 µs |
| VA BSIM4 | `tran 0.5n 60n` | 3 396 | 34.0 s | 31.1 s | 0.52 s | 0.92 µs |
| PSP103 | `tran 0.5n 20n` | 14 071 | 225.5 s | 210.1 s | 3.68 s | 1.49 µs |

Where the run goes, by what the pool would and would not parallelise:

| share of the run | BSIM4, `op` | BSIM4, `tran` | PSP103 |
|---|---:|---:|---:|
| the model's `eval`, its libm calls, the `$simparam` and `$limit` callbacks — **parallel in phase 1** | 76 % | 67 % | 68 % |
| the OSDI stamping loop: `load_jacobian_*`, `load_spice_rhs_*`, the loop in `OSDIload`, the extra-data lookups, the noise stamp — serial in phase 1, parallel with colouring later | 20 % | 23 % | 18 % |
| KLU refactor and solve — serial in every phase here | 2 % | 3.5 % | 10 % |
| everything else: `CKTterr`, `NIintegrate`, `OSDItrunc`, the resistors and sources — serial | 2 % | 6 % | 4 % |

PSP103 costs 1.6× the BSIM4 per evaluation here, not the 5–20× an earlier
draft of this page assumed, and its split is the same. So the parallel
fraction is two thirds of the run for both, and Amdahl's law gives the
whole-run speedup:

| threads | phase 1: `eval` parallel | with parallel stamping too | BSIM4 `tran`, 34.0 s serial, phase 1 | PSP103, 225 s serial, phase 1 |
|---:|---:|---:|---:|---:|
| 2 | 1.5× | 1.8× | 22.7 s | 150 s |
| 4 | 2.0× | 2.9× | 16.9 s | 112 s |
| 8 | 2.4× | 4.4× | 14.0 s | 93 s |
| 16 | 2.7× | 5.7× | 12.6 s | 84 s |
| ceiling | 3.0× | 8.3× | 11.2 s | 75 s |

Why the model is trusted: the 2026-09-04 page measured the shape itself on
the built-in BSIM4 under `parallel for`, whose load went from 1.80 s serial
to 0.77 s at 8 threads and 0.71 s at 16 on a 5 000-stage chain. Fitting
Amdahl to those points gives a parallel fraction of 0.65 and predicts the
16-thread point within 2 %, so the profiled fraction is the right predictor
on this machine and memory bandwidth does not eat the gain at 8 or 16
threads. The pool build at one thread must match the serial binary within
noise, where the OpenMP build paid 16 %.

What the numbers say about the single-thread KLU run the question compared
against: on these decks it is not the wall. It stays single-threaded in every
phase, and it is 3.5 % of the BSIM4 transient and 10 % of the PSP103 run.
The comparison is "the same KLU, the evaluation divided by the core count,
the stamping unchanged". On the other deck class — the 180 k-instance mesh
where KLU is 57 % of the run — the pool gives roughly nothing, and only the
solver track (phase 3, then NICSLU) helps.

The probe decks and the profiles are under the session scratchpad `mt/`
(`chain_op.cir`, `chain_tr.cir`, `psp_tr.cir`, `*.sample`, `cat.awk`).

## Verification

* **Bit-identical output at every thread count.** Because the stamping
  order is unchanged, this is the target, not a hope: the full sweep runs at
  `num_threads=1` and `=8` and the outputs are byte-compared. The suites to
  run first are `osdilimit` (the limiter, F1), `display` and `lrmcontrib`
  (the message path, F2), and the Newton-phase-sensitive `warmstart`,
  `failacct` and `linesearch`.
* **Message order.** 2 000 instances calling `$warning`, `$write` partial
  lines and `$monitor` at 16 threads must print the serial build's 4 802
  lines, in its order, run after run.
* **ThreadSanitizer.** A `-fsanitize=thread` build with Apple clang, run over
  the two suites above; clean is the bar.
* **Scaling.** The two 10 000-device chains above at 1/2/4/8/16 threads,
  load time and total, against their 34.0 s and 225 s serial runs; the
  Amdahl table is the prediction to check, and a point well under it means
  the pool, not the model, is the cost.
* **Thread count 1.** The serial binary and the pool build at one thread
  must agree on every suite and every timing within noise, which also fixes
  the 16 % single-thread penalty the OpenMP build paid.

## What this does not do, and what was considered and set aside

* **A task per instance.** F3.
* **Parallel stamping into the shared value array in phase 1.** Two
  instances on one node race on the same `Ax` entry; graph colouring adds
  it later with determinism kept by colour order.
* **Threading inside the compiled library.** The compiler already links
  rayon and could emit an `eval_many` entry point that evaluates an array of
  instances on its own pool. Set aside: every model library would carry a
  pool, the simulator could not schedule across modules or interleave the
  built-ins, and the limiter-shadow problem is identical there.
* **OpenMP as the portability layer.** For the reasons in the second
  section; `--enable-openmp` is retired in phase 2.
* **Parallelism inside KLU's Gilbert–Peierls column loop.** That is the
  NICSLU project.
* **GPU.** Not for ultra-sparse circuit matrices at these sizes.

## Open questions for whoever picks this up

* Whether the `num_threads` default flips to the core count in the release
  after phase 1, or stays at 1 until phase 2.
* Whether the spin-before-park duration should be a variable; the right
  value depends on the load pass length, which depends on the deck.
* Whether Windows is built and tested (MinGW and MSVC) in the same
  enhancement or a follow-up; the shim compiles there by construction, the
  pool has to be exercised.
