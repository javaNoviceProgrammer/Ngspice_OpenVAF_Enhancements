# Enhancement-772: one random stream and one HUGE on every platform — a seed drew different Monte Carlo samples on macOS, Linux and Windows because the generator was seeded from the C library's rand(), and on Linux any expression that overflowed stopped the analysis as "out of range" because glibc no longer defines HUGE; a forced OSDI reload the system loader answers with the old object is reported; and the CI sweep's remaining environment assumptions are gone

**Scope:** the second CI run with the sweep on every platform (37005572090, the E-770/771
commit), which left linux-intel at 519 of 536, macOS Apple Silicon at 534, Windows at 474
and the linux-arm runner shut down two minutes into its sweep. ngspice:
`maths/misc/randnumb.c` (`ng_srand`, `ng_rand`), `include/ngspice/randnumb.h`, `main.c`,
`sharedspice.c`, `tclspice.c` (the start-up seed), `maths/cmaths/cmath2.c` (`rnd()`),
`include/ngspice/ngspice.h` (`HUGE`), `spicelib/devices/dev.c` (a reload that changed
nothing). Suites: osdireload, lifecycle, pyplot, optpath, vafice, progressbar, lrmkernel,
abstolperf, and `run_regression.py`'s serial set. CI: a memory log in the Linux sweep.

**Suites:** the full sweep, 536 of 536; the same sweep under Linux's conditions on
macOS (an X build, no `DISPLAY`, no terminal, a case-sensitive volume, `CI` set), 536
of 536. On macOS the E-769 binaries pass the thirteen suites these changes touch as
well: macOS's `rand()` is the stream, its `HUGE` the value, and its mapped files
behave -- every fault here is one a Mac cannot show. The same CI run confirmed
E-771 on the macOS Intel runner: 519 of 536 there (164 the run before), every model
linking.

## What was wrong

**1. A seed was three different Monte Carlo runs.** ngspice's generator (a combined
Tausworthe/LCG) takes its eight start states from the C library's `rand()` after
`srand(seed)` (`TausSeed`), so the whole stream -- every `agauss`, montecarlo sample and
trnoise draw -- followed the C library. glibc's `rand()` is a TYPE_3 additive generator,
macOS's the Park-Miller "minimal standard" one, the Windows runtime's an LCG with
`RAND_MAX` 32767: one seed, three runs. The suites' expectations were measured on macOS, so
mcyield's 30 of 40 passing was 28 on Linux and 26 on Windows, and mctrack, mcarming and
mcfastpath followed on Linux. `ng_rand()` is macOS's
`rand()` itself -- x' = 16807 x mod (2^31 - 1) by Schrage's factorisation, a zero seed
replaced by 123459876 -- in fixed-width integers so that a 32-bit `long` on Windows changes
nothing. Against the system `rand()` on macOS it matched 13 million draws over seeds from 0
to 2^32 - 1, so a seed's stream on macOS is unchanged and Linux and Windows now draw the
same one. The seeding (`TausSeed`, `checkseed`, `setseed`, the start-up seed in `main.c`,
the shared library and tclspice) and the control language's `rnd()` use it.

**2. Overflow was an error on Linux and a warning on macOS.** ngspice uses `HUGE` as the
"out of range" flag of the expression functions (`PTeval` refuses a result equal to it), as
the start of minimum searches, and for `db(0)` = 20 * -log(HUGE). macOS's `<math.h>` defines
it as `MAXFLOAT`; glibc dropped the SVID macro in 2.27, and ngspice's fallback made it
`HUGE_VAL`, infinity. So on Linux every expression that merely overflowed --
`B1 nb 0 v='1e300*1e300'` -- was refused ("Error: 1e+300, 1e+300 out of range for *") and
stopped the analysis, where macOS evaluated it to infinity and warned (E-440), and `db(0)`
was -inf where macOS gives -1774. `HUGE` is now `FLT_MAX` everywhere, macOS's value, which
every suite was measured against.

**3. A forced reload could change nothing in silence.** When the system loader answers a
reload copy with the object it already has, `load_object_file` returns an empty object for
the known handle, and `pre_osdi -f` reported "reloaded (0 devices)" with the old model still
in place. It is now an error naming the file.

The Linux reload failures of osdireload and lifecycle had another cause: both suites
overwrote the loaded `.osdi` with `cp`. Linux shares a mapped library's pages with its file,
so the running object's code changed under it, and the session lost its output (a batch
run's buffered stdout dies with the process). A compiler or linker writes a new file and
renames it over the old one; the suites now do the same (two `shell` lines -- ngspice's
lexer splits `&&` into `& &`, which had made an earlier attempt a no-op).

## The suites

- `pyplot` E-547g linked `python3` into a folder with a space; on CI that is a uv virtual
  environment's interpreter, which, started through a link outside the environment, runs
  without its matplotlib. The folder holds a script that runs the suite's own interpreter.
- `optpath` [E-452] and `vafice` expect an unwritable directory to be refused; the Linux CI
  job runs as root, for whom "/" is writable (optpath's check left a file there). Under root
  those checks say they are skipped.
- `progressbar` [6]: the time per accepted point is an absolute 1.5 us, which holds only on
  the machine it was measured on (1.76 us on the macOS runner, 2.52 us on Linux); on a CI
  runner (`CI` set) it is reported, not asserted -- the relative check beside it (time
  outside the timed phases under 3x their sum) catches the cost returning. The frame count
  is bounded by one frame per quarter second of the run, however long it took.
- `lrmkernel` [speed]: the 4x ratio to a built-in resistor held on Linux (2.7x); an absolute
  1 us cap beside it did not, and is gone.
- `abstolperf`: a scaling ratio measured beside seven other suites (2.88 against 2.8 on
  Linux) -- it runs alone now, after the parallel batch, with the bound at 3.0 (the
  quadratic it guards against measures 3.52).
- `progressbar` and `abstolperf` join `run_regression.py`'s serial set.

## CI

The Linux sweep prints, every 10 s into the job log, the available memory and the three
largest processes (read from /proc: the jammy container has no procps). The linux-arm
runner was shut down at the same point of two runs, two minutes into the sweep, and its log
did not say why; the job log survives a runner kill.

## Limits

- Not addressed here: x86-64 compile time on huge modules (a 10 000-entry instance array
  took 533 s on the Linux runner, table_model timed out) -- the selects of E-771 with
  conditions known only at run time; collapsestate's Sparse `sens`, which fails on the macOS
  Intel runner as well, so on x86-64 rather than on Linux; the linux-arm
  shutdown (the memory log should name it); the rest of Windows' list.
- `cp` over a loaded `.osdi` on Linux still rewrites the running object; replacing it by
  rename, as the compiler does, is safe.
