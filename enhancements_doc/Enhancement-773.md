# Enhancement-773: a suite that runs away with the machine's memory is stopped and reported, with the deck its simulator was running and a sample of what it was writing — the linux-arm CI runner was shut down three runs in a row when three suites' scripts each grew by ~70 MB/s, and the sweep, its log and every other platform's view of it went with the machine

**Scope:** `examples/run_regression.py` only (`run_one`, `_group_procs`,
`_memory_report`, `MEM_CAP_MB`, the serial set). No simulator or compiler change.

**Suites:** the full sweep, 536 of 536, through the new runner.

## What was wrong

The linux-arm job of every CI run with the sweep stopped at the same point, two and a half
minutes in, with exit code 137 and "The runner has received a shutdown signal"; nothing in
its log said why. E-772 added a memory log to the Linux sweep, and the third run's shows
it: three suite scripts -- `verify_analogloop.py`, `verify_arraynodeprint.py`,
`verify_autocorner.py`, running side by side -- grew by about 70 MB a second each, the
machine's 16 GB went from 14.4 GB available to 250 MB in a minute, and the runner died.
The scripts hold their children's output in memory (`capture_output`), so a script grows
like that when the ngspice or openvaf-r it runs writes without end. The same suites pass on
linux-intel and on both macOS runners; an ngspice built here with `-funsigned-char`
(aarch64 Linux's `char`) passes analogloop, so the cause is not that, and it is not known
yet.

A runaway suite is a failure of that suite. It must not take the sweep with it.

## What changed

On Linux the sweep runs each suite in its own session and, once a second, sums the
resident memory of its process group from /proc. Past `MEM_CAP_MB` (4096; `NG_SUITE_MEM_MB`
sets it) the group is stopped, the suite is reported as `MEMORY`, and the sweep goes on.
Before stopping it, the report writes to `_failures/<suite>.log`: each process's memory,
working directory and command line, the deck every ngspice in the group was running (copied
to `_failures/<suite>.deck-<pid>`), and up to 16 kB of what each was writing, read from its
own output pipe -- what the next linux-arm run needs to show what runs away. A fault in the
watchdog only turns it off for that suite. Output and errors of a suite are now one stream,
in the order written. macOS and Windows have no /proc and run as before.

`plotname`'s per-point flatness ratio measured 1.74 against its 1.6 on the 3-core macOS
runner beside two other suites (the growth it guards against was 2.8); it joins the suites
that run alone after the parallel batch.

## Checks

On macOS, with `_group_procs` replaced by a stub reporting a 5 GB group, `run_one` stops the
suite within a second, reports `MEMORY (>4096 MB)` and writes the report with the group's
processes; the real sweep runs as before.

## Limits

- Why the three suites' children write without end on linux-arm is still open; the next run
  of that job should name the deck and show the output.
