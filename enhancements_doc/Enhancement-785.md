# Enhancement-785: a suite that fails once keeps the simulator output of its last runs, and lrmfuncs writes its input file as bytes

**Scope:** examples only. `examples/_setup.py` (`_install_ring`, `NG_RING_DIR`),
`examples/run_regression.py` (a ring directory per sweep, attached to a failing suite's log),
`examples/lrmfuncs_examples/verify_lrmfuncs.py` (input files written with `\n`). From CI run
37095422733: Windows 526 of 529, every other platform green.

**Suites:** the full sweep on macOS, 536 of 536 in 378 s (381 s before); lrmfuncs both solvers; a
forced failure (below).

## Failures that do not repeat

Four Windows suites have each failed once, in two sweeps: analyses (AC sensitivity) and
autobusopt (`autobus=yes` at the top level) in run 37091735340, opargs (`ac_stim v(c) missing`)
and reuseloops ([14], nothing read) in 37095422733. Every one failed on its first pass (Sparse)
and passed on the second (KLU), and every one passed when E-777's trace re-ran it alone -- so the
trace, which is written by that re-run, never holds the failing run, and the suite's own log says
only that a value was missing.

With `NG_RING_DIR` set, which `run_regression.py` now does for every suite, each process a suite
starts keeps its last 12 ngspice and openvaf-r runs in memory -- arguments, directory, exit
status, time, and the tail of what each printed -- and writes them to
`<dir>/<suite>-<pid>.log` when it exits, labelled with its solver pass. The sweep appends them to
`_failures/<suite>.log` when the suite failed and deletes them either way. Nothing is written
while the suite runs, and a suite that passes leaves nothing behind.

Checked by pointing `NGSPICE_BIN` at a stand-in that prints its arguments and exits 0: opargs
failed on both passes, and its failure log ends with two rings, `(sparse)` and `(klu)`, each with
its runs' command lines and output. The sweep's time did not change.

## lrmfuncs

lrmfuncs' `$ftell(fd)` case reads `"hello world\n42 3.5\n"` from a file the suite writes; Python
wrote it with `\r\n` on Windows, and the model, which reads bytes since E-776, found `$ftell` two
bytes further on. The suite's extra files are written with `\n`, as fgetc, ungetc, scanbody and
lrmio do since E-779.

## Limits

- The ring holds what a run printed, not why the machine behaved that way; it is there so the
  next one-off failure on Windows names the run that went wrong.
