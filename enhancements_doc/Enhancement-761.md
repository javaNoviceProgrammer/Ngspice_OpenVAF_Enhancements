# Enhancement-761: the output path no longer queries the free memory and the clock on every accepted point — a Mach memory query, a `getrusage` and a variable lookup by name cost about a microsecond a point, half of a 600 000-point transient whatever its devices; the memory check now runs only when the output vectors are about to grow, the variable is cached, and the progress line's throttle reads a cheap wall clock

**Scope:** F3 of the 2026-09-28 speed, robustness and correctness hunt, found in the
profile taken for O1 (E-760). ngspice only: `frontend/outitf.c` (`OUTpD_memory()` checks
the free memory only when the run's output vectors are at a chunk boundary and about to
grow, and reads `no_mem_check` behind E-760's variable state stamp; `outp_ref_due()`
replaces the five `clock()` throttles of the "Reference value" line with one wall-clock
read through `seconds()`). Nothing observable changes: the out-of-memory check still runs
before every allocation the vectors make, `set no_mem_check` still disables it, and the
progress line keeps its quarter-second cadence.

**Suites:** `progressbar` 25 of 25 (23 of 25 on the E-760 binary: the new section [6]),
`loopbar` 21 of 21 (its sweep's inner transient runs 1.2 M points now, four times as
many, so a point still spans the two refreshes check [5] needs on a build this fast),
`lifecycle`, `rawfstring`, `rawfuzz`, `rawparam`, `rawtrip`, `savecur`, `savecuroff`,
`saveforms`, `savemiss`, `multisave`, `autosave`, `plotname`, `plotorder`, `benchmark`,
`abstolperf`, `savenoise` and `savekw` unchanged; the full sweep 534 of 534.

## What was wrong

The profile of the one-instance transient used for O1 put 48 % of its samples under
`CKTdump → OUTpData`, the path that appends each accepted point to the output vectors.
Three calls ran there on every point:

| call | samples of 3047 | what it is on macOS |
|---|---|---|
| `getAvailableMemorySize()` | about 1000 | a Mach `host_statistics` query plus a `mach_host_self` port trap |
| `clock()` | about 380 | a `getrusage` system call, read to decide whether a quarter second had passed |
| `cp_getvar("no_mem_check")` | about 45 | a lookup by name: a `cp_usrvar` probe and four list walks |

About a microsecond per accepted point. The built-in run had the same share: its 1.20 s
transient was half output bookkeeping, and the PRBS and switching runs of F1 and F2
carried it too. Large circuits hide it behind their device work, exactly as F1's `getcwd`
was hidden.

`OUTpD_memory()` estimates the memory the next vector growth needs and refuses to
continue when it exceeds the free memory. But `AddRealValueToVector` grows a vector only
when its length reaches its allocation, by a chunk `vlength2delta` sizes from the point
count: a few times per run. The check was answering a question that only arose at those
points. The throttle's clock read cost more than the print it throttled: at this point
rate the line is redrawn four times a second and the clock was read six hundred thousand
times.

## What changed

- **The memory check runs at chunk boundaries.** `outp_vectors_about_to_grow()` looks at
  the first data vector of the run (every vector of a run has the same length, one value
  per point) and the check runs only when `v_length` has reached `v_alloc_length`. The
  first point (both zero) checks as before, and every growth checks before the chunk is
  claimed. `no_mem_check` is re-read when the variable state stamp of E-760 moves.
- **The throttle reads the wall clock.** `outp_ref_due()` compares `seconds()` (a
  `clock_gettime` served from the commpage, some 30 ns) against the last print and
  replaces the five `clock()` sites: the two rawfile paths, the in-memory path, and the
  two interpolation paths. Wall time is the right clock for a display cadence anyway; the
  CPU clock it used stood still while the process waited. `startclock` stays for the
  `ngdebug` speedcheck vector.

## Measured

| deck | E-760 | now |
|---|---|---|
| one built-in resistor and capacitor, 607 808 points | 1.20 s (rest outside the timed phases 1.0 s) | 0.54 s (0.34 s) |
| the same with a compiled resistor | 1.32 s | 0.65 s |
| the E-752 10 Gb/s PRBS through a compiled 50 Ω / 0.4 pF, 69 062 points | 0.156 s | 0.087 s |
| the F2 hunt's 500 MHz switching run, 30 005 points | 0.074 s | 0.042 s |
| the F1 hunt's 300-stage RC ladder, 2033 points | 0.069 s built in, 0.134 s compiled | unchanged |
| progressbar [6], 1.2 M points: time outside load, factor, solve and trunc | 2.19 s, 1.80 µs per point (4.6× the timed phases) | 0.34 s, 0.28 µs (1.7×) |

The output path fell from 48 % of the samples to 3 %. The profile after shows the next
item down: ngspice's own statistics timers, six `seconds()` reads per Newton iteration in
`CKTload` and `NIiter`, a third of what is left of this trivial circuit's transient (about
80 ns an iteration, noted as O7 on the hunt page; invisible for any real circuit).

## Checks

`progressbar` section [6]: a 1.2 M-point built-in RC transient spends under 3× the timed
phases outside them and under 1.5 µs per accepted point, and the progress line is drawn
between 2 and 12 times over the run (a frame per point would be a million).

## Limits

- The memory check reads the first data vector's allocation; a run whose vectors grow at
  different points (none does: every vector takes one value per point) would check at
  the first one's boundaries only.
- On Linux the free-memory query reads `/proc/meminfo` (an `fopen`, a `read`, a
  `strstr`), which is at least as expensive as the Mach query, so the saving is of the
  same order there; on Windows `GlobalMemoryStatusEx` is cheaper and the saving smaller.
- The clock read is now wall time: a run that is suspended prints its next line as soon
  as it resumes rather than a quarter second of CPU later.
