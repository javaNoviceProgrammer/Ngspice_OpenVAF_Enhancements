# Enhancement-777: the sweep traces what the simulator printed for every suite that failed, and the suites stop assuming POSIX — `nm`, a pseudo-terminal, deleting a file still open, a C harness that calls `dlopen`, an emptied PATH that hides the linker — on the Windows and macOS Intel CI jobs

**Scope:** examples only. `examples/_setup.py` (`NG_TRACE_DIR`, `_install_trace`;
`exported_symbols`, `_pe_exports`; three Windows entries in `PLATFORM_EXCLUDE`),
`examples/run_regression.py` (`NG_TRACE_FAILED`), `.github/workflows/build-binaries.yml`
(both sweep steps trace their failures; `examples/_trace/` uploaded with the logs), and the
suites constguard, osdidist, osdimc, paramgiven, savemc, writemc, cornerscmd, limguard,
multimod, lrmdisc, numguard and winlink. The simulator and compiler fixes from the same CI
run are [E-775](Enhancement-775.md) and [E-776](Enhancement-776.md).

**Suites:** the full sweep on macOS, 536 of 536.

## The trace

A suite reports which check failed; on a CI machine nobody can see what ngspice printed.
With `NG_TRACE_DIR=<dir>`, `_setup.py` wraps `subprocess.run` so that every ngspice and
openvaf-r run a suite makes is recorded in `<dir>/<suite>.log`: the command, its
directory, the deck it was given, the exit status and the tail of its output; with
`NG_TRACE_LLDB=1` on macOS, a run killed by a signal is run again under lldb and its
backtrace kept. `NG_TRACE_FAILED=1` makes `run_regression.py` re-run each failed suite once,
alone, with the trace on (at most 30). Both CI sweep steps set it and upload
`examples/_trace/` with the regression logs -- the next Windows and macOS Intel runs bring
the output of every run behind a failure. A trace fault never fails a suite.

## The suites

- `exported_symbols(path)`: `nm` on POSIX; on Windows, which has no `nm`, the DLL's export
  table read from the file in Python (`_pe_exports`). osdidist [2], osdimc [3][4][45] and
  paramgiven [1][16] read "no such file" there. Checked on a DLL cross-linked here with
  lld-link: its 20 exports, the OSDI tables and both I/O hooks among them.
- constguard [29]: the Windows runtime prints 0/0 as `-nan(ind)`.
- savemc [4], writemc [6], cornerscmd: the workbook was opened with `zipfile.ZipFile` and
  never closed, and Windows does not delete a file a process holds: the suites' clean-up
  failed with `PermissionError`.
- limguard: a directory a still-held file kept is reused (`exist_ok`).
- multimod [15] hides the linker by emptying PATH; MSVC's link.exe is found through the
  Visual Studio installation, not PATH, so on Windows the check stands aside.
- lrmdisc [16]: the dump harness calls `dlopen` (`<dlfcn.h>`); it stands aside on Windows.
- numguard: MinGW's `sin` and `cos` reduce a large argument in x87 precision -- 1e-9 off at
  1e12, a wrong value at 1e20 (−0.747 for −0.646) -- while Python and a compiled Verilog-A
  model use the Microsoft runtime's. From 1e10 up the Windows values are reported, not
  asserted.
- winlink [4]: an x86_64-pc-windows object references `_fltused`, the x64 C runtime's
  floating-point marker (an arm64 one does not); it is a runtime symbol like the others.
- `PLATFORM_EXCLUDE` on Windows: helpcmd, syntaxhl and vafcolor drive ngspice or the
  compiler through a POSIX pseudo-terminal (`pty`, `termios`), which Windows lacks.

## Limits

- numguard's large-argument trig on Windows is MinGW's libm and is held, not fixed.
- The causes behind the rest of the Windows list and the macOS Intel crashes are for the
  traces to show.
