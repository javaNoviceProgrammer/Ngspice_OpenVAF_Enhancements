# Enhancement-775: ngspice on Windows — a compile started from ngspice failed in cmd.exe's quote stripping, pyplot ran a `python3` that was not the user's Python and wrote beside a path whose backslashes the plot command ate, and a loaded model's DLL could be neither recompiled nor replaced

**Scope:** the Windows CI sweep (run 37033263653: 490 of 532; 42 failing suites). ngspice,
Windows branches only: `frontend/com_dl.c` and `frontend/com_presnp.c` (the compile
command), `frontend/plotting/pyplot.c` (`PYPLOT_DEFAULT_PYTHON`), `frontend/com_pyplot.c`
(the output path), `spicelib/devices/dev.c` (`load_osdi`, `osdi_sweep_stale_copies`).
The suites made portable in the same run are [E-777](Enhancement-777.md); the OSDI
runtime's file mode is [E-776](Enhancement-776.md).

**Suites:** the full sweep on macOS, 536 of 536 (these branches are compiled
for Windows only; the Windows CI run is their first test).

## What was wrong

**1. Every compile ngspice started failed.** `pre_osdi -va`, the `.option osdicache`
rebuild and `pre_snp` run openvaf-r through `system("\"<openvaf-r>\" \"<src>\" -o
\"<out>\"")`. On Windows `system()` hands the line to `cmd.exe /c`, which strips the first
and the last quote of a line that starts with a quote and holds more than two -- the program
path lost its quotes and cmd answered that it is not a command, exit 1: vacompile [1],
optknown, presnp. The line is now wrapped in one extra pair of quotes, which is what cmd
strips -- the form pyplot's own launch has used since E-547.

**2. pyplot's default interpreter was another Python.** `pyplot_python` defaults to
`python3`. On Windows a Python is `python` -- the python.org installer and a virtual
environment provide `python.exe` -- and `python3` is another installation or the Microsoft
Store's stub: on the CI runner one without numpy (`ModuleNotFoundError`), and pyplot,
pyplotcontour, pyplotexport, pyplothist, pyplotpanel and mcrecord's render all failed. The
default is `python` on Windows, `python3` elsewhere.

**3. pyplot's output path lost its backslashes.** pyplot writes its script, data and image
beside the circuit file (E-183), building the path from the deck's directory with the
platform separator; the name then passes through the plot command's argument handling,
where a backslash is an escape, and `C:\Users\...` became `C: sers\...` (mcrecord's own
message shows it). On Windows the directory is written with `/`, which Windows accepts.

**4. A loaded model locked its file.** Windows locks a loaded DLL against writes, so a
model ngspice had loaded could not be recompiled (openvaf-r: permission denied) or replaced
(`copy` refused) while the session ran, and E-229's edit, recompile, `pre_osdi -f` loop could
not start (osdireload). On Windows every load is now of a staged copy in TMPDIR (E-229's
reload copy, E-770's per-process name); the copy is what is locked. A copy cannot be
removed while it is loaded, so each session first removes the copies earlier sessions left
(one a running ngspice still holds refuses and stays).

## Limits

- The Windows branches are compiled only by the Windows CI job; this commit is their first
  build and run there.
- What else fails on Windows -- every model using `transition`, `slew` or events produced
  no transient there, and the compile cache, `hb`, low-rank and `laplace_nd` cases --
  is not understood yet; E-777's trace of the failed suites is what the next run brings.
