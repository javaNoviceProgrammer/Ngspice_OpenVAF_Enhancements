# Enhancement-784: a Verilog-A file the model reopens stays binary on Windows, and the last Windows suites stop assuming one platform's arithmetic and one path separator

**Scope:** OpenVAF: `openvaf/osdi/stdlib.c` (`osdi_byte_mode`, used by every `fopen` and
`freopen` of `osdi_fopen`). Examples: hbconv [3], savemc [17], vafice, and the failure detail of
analyses' AC-sensitivity check and autobusopt's spelling checks. From the first complete Windows
sweep since E-778 (CI run 37091735340: 522 of 529; macOS Intel 532 of 532).

**Suites:** the full sweep on macOS, 536 of 536; fileio, lrmfuncs, stringio, display, lrmio,
lrmsysio, fgetc, ungetc and scanbody under both solvers.

## The reopened file (fileio, lrmfuncs)

E-776 and E-778 made `$fopen` open its file in binary mode on Windows, whose C runtime otherwise
writes every `"\n"` as `"\r\n"`. fileio's `$ftell` still read 171 for the 160 bytes the model
wrote. `osdi_fopen` has four ways to open: the multichannel `fopen`, the descriptor `fopen` --
the two that were fixed -- and two `freopen`s for a stream the model closed and opens again,
which passed the requested mode through unchanged. The Windows bitcode showed it: binary mode on
both `fopen` calls (the constants `"ab"`/`"wb"` on one, a `strchr(mode, 'b')` check on the other),
none on either `freopen`.

fileio's `$fopen` and `$fdisplay`s depend on parameters only, so the compiler runs them in the
instance setup, and ngspice runs instance setup twice (setup, then temperature). A probe build
printed the path each open took for fileio's deck: `fopen` fresh, then the unmanaged re-run's
`freopen` -- so the file the run left behind came from the text-mode reopen. Every open now goes
through one helper, `osdi_byte_mode`, which appends the `b` on Windows and returns the mode as it
is elsewhere; the Windows bitcode carries the check before all four opens, the macOS bitcode none.

## The suites

- **hbconv [3]** (E-779) said a "genuine failure" must not be papered over by E-483's stall
  test. On Windows the deck gives a full harmonic table, and since E-779 the check accepted a
  clean convergence but not an *accepted stall*. The property it guards is the rule -- a stall is
  accepted only after the residual came down at least 1e6 times -- so the check now asserts that,
  whichever way a platform's arithmetic falls: a failure is reported as one and stalls far above
  [1]'s floor, a clean convergence needs nothing, and an accepted stall must show its 1e6x
  reduction. Its detail always quotes qpss's convergence line.
- **savemc [17]** compared ngspice's note, which joins with `/`, with a path `os.path.join` built
  with `\`; both are compared with `/`, as E-779 did for [5] and [15].
- **vafice**: "a read-only TMPDIR" cannot be made on Windows -- the temporary directory comes from
  `TMP` and `TEMP`, and the drive's root is writable -- so the check stands aside there, as it does
  for root on Linux.
- **analyses** (AC sensitivity, Sparse) and **autobusopt** (`.option autobus=yes`, top level, on
  Sparse) each failed once in the Windows sweep and passed when re-run alone. Neither said what it
  had read; both now quote the value, or what ngspice printed.

## Limits

- The Windows branches run on the Windows CI job only; the probe build ran on macOS, where text
  and binary mode write the same bytes.
- What made analyses and autobusopt fail once is not known; the next failure will say what
  ngspice printed.
