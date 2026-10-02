# Enhancement-779: a quoted Windows path keeps its backslashes in a deck's commands, a Windows crash is traced with its stack, and the second round of suites made portable — the interpreter, the compiler copy, the temporary directory and the separators each assumed POSIX

**Scope:** ngspice: `frontend/parser/lexical.c` (a backslash inside quotes on Windows).
Examples: `examples/_setup.py` (the trace re-runs a Windows crash under cdb), and the suites
pyplot, reusecache, vafice, hbconv, savemc, optpath, fgetc, ungetc, scanbody and lrmio.
From the Windows CI sweep after E-775..777 (run 37047779037: 504 of 529), read through
E-777's traces.

**Suites:** the full sweep on macOS, 536 of 536.

## The lexer

A deck's command line drops a backslash and keeps the character after it. Outside quotes
upstream already makes an exception on Windows, where the backslash is the path separator
(`DIR_TERM`); inside quotes it did not, so `pre_osdi "C:\Users\...\dir with space\va
res.osdi"` -- the quotes being there for the space -- reached the loader as
`C:Users...dir with spaceva res.osdi` (osdireload's quoted-path case). Inside quotes the
backslash is now kept on Windows as well.

## The trace

A process that dies on Windows exits with an NTSTATUS code (0xC0000005, an access
violation). The trace now runs such a run again under cdb, which GitHub's Windows images
ship with the Windows SDK, and keeps the faulting stack and the module list. Every model
with `transition`, `slew`, an absdelay or a crossing event crashes ngspice at once on
Windows (transedge, evtedge, rtdomain, opargs, defaulttransition, lrmops, portconnected,
domainwarn): the tables they carry are exported (checked on a cross-linked DLL) and their
layout is plain `uint32_t`, so the next run's stack is what is needed.

## The suites

- pyplot E-547c/d/f/g on Windows: the failing interpreter is a `.bat` that exits 3; a missing
  interpreter is status 1 (or 9009) from cmd.exe, not a shell's 127; the interpreter with
  an option is `python -B`; the interpreter path with a space is a `.bat` running the
  suite's own Python; paths go into the deck with '/'.
- reusecache: the compiler copies are `ovf.exe` and `openvaf-r.exe` on Windows (Windows runs
  only a file with an executable extension), and the PATH case compares with separators
  normalised.
- vafice: a missing temporary directory is set in TMP and TEMP as well as TMPDIR (Windows
  reads the former).
- hbconv [3]: on Windows the "genuine failure" deck converges -- a full table, no stall
  caveat -- so there is nothing to paper over; a stall reported as a result still fails.
- savemc [5][15]: paths compared with separators normalised (ngspice joins with '/');
  [16] removes a directory holding an open file with `shell rm -r`, which Windows does not
  allow and cmd.exe does not have, so it stands aside there.
- optpath: the unwritable-directory checks stand aside on Windows, where the drive's root
  is writable, as they do under root.
- fgetc, ungetc, scanbody, lrmio write their input files with `\n` line ends: the model
  reads bytes (E-776), and Python's text mode on Windows writes `\r\n`.

## Limits

- The crash of the transition / slew / event models on Windows is not fixed here; the cdb
  stack is what the next run brings.
