# Enhancement-516: display and file I/O, deferred to the accepted iteration

**Scope:** Accellera VAMS-2023 clauses 9.4 (display tasks) and 9.5 (file I/O).
Five bugs, two missing features, and one long-standing silent no-op — fixed
with one coordinated mechanism spanning the compiler, its OSDI runtime, and
ngspice.

**Suite:** [`examples/lrmsysio_examples/`](../examples/lrmsysio_examples/) — 19
checks, both solvers. The pre-existing `display`, `fileio` and `scanfmt`
suites also pass, and two of them caught real regressions during development
(see "What the suites caught").

## The headline: every display fired on every Newton iteration

LRM 9.4.6 is one sentence: "All the display tasks, except $debug, shall not
display output unless an iteration has been accepted." LRM 9.5.9 is its file
twin: "If a file is being written to during an iterative solve, then the file
write operations shall not be performed unless the iteration is accepted"
(only `$fdebug` exempt), plus a read-pointer reset for rejected iterations.

Neither held. A single `.op` of a diode printed **fifteen** `$strobe` lines
walking through the unconverged Newton iterates (`v=0.0, 0.8, 0.774, ...`),
and an un-gated `$fdisplay` wrote five lines to its file — the first holding
`v=0`, a solution the circuit never settled at. `$monitor` had no change
detection at all (9.4.1: printed only "if a variable or expression in the
argument list changes value compared with the last accepted step") — 120
lines over a transient whose watched value changed once.

### The mechanism

Display output already funnels through one function — ngspice's `osdi_log` —
so the display buffer lives there. File writes stay inside each `.osdi`'s
runtime, which buffers them and exports two lifecycle hooks
(`osdi_io_iter_begin` / `osdi_io_flush`) that ngspice resolves with `dlsym`
at load time — an old `.osdi` without them simply writes through as before,
and an old ngspice never calls them.

The lifecycle: `OSDIload` announces each new Newton iteration and drops the
superseded iteration's buffered output. Detecting "new iteration" is the
subtle part — `STATnumIter` is only bulk-updated when `NIiter` returns, so it
cannot tell the iterations of one solve apart; but `NIiter` swaps
`CKTrhs`/`CKTrhsOld` once per iteration, so the composite (circuit, RHS
pointer, time, mode, iteration total) differs between any two adjacent
iterations. The accepted point's output is flushed from `OSDIaccept`
(transient points), `OSDIfinalStep` (analysis ends — dcop/acan/noise/dctran
already call it), and a new per-point flush in the `.dc` sweep (each sweep
point is its own accepted operating point per Table 4-22).

**Event-gated statements print immediately.** `@(initial_step) $strobe(...)`
fires on the event's own iteration — usually not the accepted one — so
deferring it would *drop* it. The compiler knows the gating: statements
lowered inside an event control carry a new `LOG_FLAG_IMMEDIATE` bit (and
`$fdebug`/severity tasks keep their immediate paths). The events suite still
shows every `initial_step`/`final_step`/`cross` message exactly once.

`$monitor` lowers with its own level (`LOG_LVL_MONITOR`); at flush, the k-th
monitor message of the point is compared with the k-th of the previously
flushed point and skipped when the text is unchanged. One documented
deviation: a `$abstime` argument in the text defeats the comparison.

## %r printed garbage for every value

Three compounding defects (LRM 9.4.3, Table 9-23): `fmt_char_idx` picked the
scale with the **natural** log, truncated toward zero, and never applied the
table offset; and the codegen handed snprintf's `%c` the GEP **pointer** into
the scale-character table rather than the character. `$strobe("%r", 1e3)`
printed `0.000000` followed by a garbage byte. Now: `1e3 → 1.000000k`,
`1e-9 → 1.000000n`, `0.036 → 36.000000m`, `2.2e4 → 22.000000k`, with
0/NaN/inf pinned to the unit scale.

## The file lifecycle: append, dedup, deferred close, exact re-runs

* **9.5.1.1** — "content written from the following analyses shall be
  appended": a per-process registry of written file names turns a `"w"`
  reopen into an append. Two `op` runs leave two `RUN` lines; it used to
  truncate and keep only the last.
* **The open-write-close idiom wrote nothing.** Parameter-only `$fopen`/
  `$fclose` are hoisted into instance initialization (a documented split),
  so the descriptor was closed before eval's first deferred write. An
  instance-setup `$fclose` now *defers* — the stream stays open, the close
  executes at the first accepted flush — and a managed-phase `$fclose`
  becomes a pending marker that a superseded iteration simply drops.
  Same-name `$fopen` returns the existing descriptor, so per-evaluation
  reopens cannot exhaust the table.
* **ngspice runs instance initialization more than once** (setup +
  temperature). A re-run used to overlay its writes onto the previous run's
  final position — `$rewind`/`$fseek` files came out as
  `XY234**0123456789`. An unmanaged reopen of a closed-requested file now
  `freopen`s with the caller's mode, so a re-run reproduces the first run
  byte for byte: `XY234**789`.
* **Read replay (9.5.9)**: at each iteration start, streams opened readable
  rewind to their accepted baseline; the baseline advances only at flush. A
  write-only stream never rewinds — rewinding one would make later writes
  overwrite accepted output.
* **Pre-opened descriptors (9.5.1)**: `32'h8000_0000/1/2` reach
  stdin/stdout/stderr, with the per-target symbol names baked into the
  per-triple stdlib bitcode (`__stdinp` on macOS, `__acrt_iob_func` on
  Windows). Full one-hot multichannel descriptors remain documented-missing.

## Null display arguments

`$strobe("a",,"b")` was a compile-time type error ("found _[0:0] value").
The parser already records the empty slot as an empty array (the LRM's own
null-argument form for the Laplace filters); inference now types it `Void`
for the display family, and the lowering renders exactly one space — LRM
9.4.1 / IEEE 1364 17.1.1.2.

## What the suites caught (kept, because the mechanism matters)

Two development-time designs were reverted by the repo's own suites:

* Making `$fopen`/file-ops operating-point-dependent (to un-hoist them)
  tainted everything touching a descriptor and broke `fileio`'s
  parameter-table report. The hoisting is legitimate; the *close timing* was
  the bug — hence the deferred-close design above.
* Unifying the per-codegen-unit stdlib state by giving every `osdi_*`
  function weak-ODR linkage broke `%o`/`%b` scanning: LLVM's per-unit
  *specialized clones* (`osdi_scanf_begin.specialized.N`) kept writing their
  own unit's scan cursor while the surviving weak function read another's.
  The state itself — descriptor tables, pending writes, scan cursor — is now
  `__attribute__((weak))` so exactly one instance survives linking, and the
  functions stay internal per unit. `scanfmt` bisected this to the compiler
  with the committed binaries in three runs.

## Remaining, documented

Constant-argument display statements still execute at instance
initialization (the hoisting note in `sim_back/src/context.rs` — moving them
needs their operands moved too); `$fmonitor` has no change detection;
`$finish(n)` verbosity is accepted and ignored; full MCD semantics are
missing.

## Files

Compiler: `hir_lower/src/{callbacks,ctx,expr,fmt,stmt}.rs`,
`hir_ty/src/inference.rs`, `osdi/stdlib.c`, `osdi/src/compilation_unit.rs`,
`osdi/header/osdi_0_4.h`, `osdi/src/metadata/osdi_0_4.rs`, MIR snapshots.
ngspice: `src/osdi/{osdicallbacks,osdiload,osdiaccept,osdiregistry}.c`,
`src/osdi/osdidefs.h`, `src/include/ngspice/osdiitf.h`,
`src/spicelib/analysis/dctrcurv.c`. New suite: `examples/lrmsysio_examples/`.
