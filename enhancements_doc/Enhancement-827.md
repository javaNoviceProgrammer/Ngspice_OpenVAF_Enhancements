# Enhancement-827: a failed Verilog-A compile says whether the compiler could not run or the source has an error

**Scope:** F11 of the
[ngspice + OSDI hunt of 2026-10-08](../docs/bug_hunts/2026-10-08_ngspice-osdi-hierarchy-sweeps-events-and-outputs.md),
with `pre_snp` found while fixing it.

ngspice:
- `frontend/com_presnp.c`:
  - `osdi_report_compile_failure`, shared by `pre_osdi -va` and `pre_snp`;
  - `osdi_resolve_on_path`, Enhancement-574's PATH lookup moved here from `com_dl.c` and
    exported.
- `frontend/com_dl.c`: `va_compile` reports through it.
- `include/ngspice/osdiitf.h`: both declarations.

`examples/rebinfinal_examples/` (section [2], five checks). **ngspice only.**

**Suites:** [`rebinfinal_examples`](../examples/rebinfinal_examples/) 15 of 15 per solver (all
5 checks in [2] fail on the E-825 binaries).
[`vacompile_examples`](../examples/vacompile_examples/) checks [22] and [23] pinned the old
report of a source error, the advice included, and now pin the new one. The full sweep, 545 of
545.

## What was wrong

```
error: 'nosuch' was not found in the current scope
...
pre_osdi: openvaf-r failed (exit 65) compiling ./sub/bad.va.
  Set the compiler with `set openvaf=/path/to/openvaf-r`, the OPENVAF
  environment variable, or put openvaf-r in $SPICE_LIB_DIR or PATH.
```

The compiler was found and ran; the source has an error. Every failure got the advice on
where to put the compiler, including this one. `pre_snp` printed the same advice. It also
printed `system()`'s raw wait status: "exit 32512" for a compiler that was not there, where
Enhancement-510 had decoded the status for `pre_osdi` alone.

## The change

One report serves both commands. It decodes the wait status, then reports one of four cases:
- **The compiler could not be run:**
  - a path that names no file;
  - a bare name not on PATH;
  - the shell's 127, or cmd's 9009;
  - a file that is not executable (126).

  It says why and gives the advice.
- **The compiler stopped on an internal error (exit 101, a Rust panic):** that is said, with a
  pointer to its message.
- **The compiler ran and refused the source:** its exit code and a pointer to its own messages
  above, without the advice.
- **The compiler was killed by a signal:** the signal is named.

```
pre_osdi: …/openvaf-r could not compile …/bad.va (exit 65); its messages above
  say why.
pre_osdi: could not run the compiler /opt/x/openvaf-r (no such file).
pre_osdi: could not run the compiler openvaf-r-x (not on PATH).
pre_osdi: could not run the compiler ./noexec (not executable).
```

Each "could not run" line is followed by the advice.

## The checks

`rebinfinal_examples` [2]:
- A source error: "could not compile … (exit 65); its messages above say why", with no advice
  (the compiler's own error is above it).
- A compiler named by a path that does not exist: "(no such file)" and the advice.
- A bare name not on PATH: "(not on PATH)" and the advice.
- A compiler file that is not executable: "(not executable)" and the advice. This check is
  skipped on Windows.
- `pre_snp` with a compiler that does not exist: the same report (was "exit 32512").
