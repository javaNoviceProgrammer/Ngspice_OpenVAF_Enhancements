# Enhancement-770: what the first Linux CI sweep found in ngspice — an X build crashed before its first command whenever it ran without a display and without a terminal, `-r /dev/null` deleted /dev/null as root, two processes reloading an OSDI object in the same second shared one staged copy, `savestate` lowercased its file name, and warn_physics' "say it once" depended on where the allocator put a rebuilt circuit

**Scope:** the first regression sweep on every CI platform (run 36996142076, 2026-10-02,
added by the CI commit after E-768). ngspice only: `main.c` (the background-input
branch), `frontend/runcoms.c`, `runcoms.h`, `runcoms2.c` (`ft_drop_empty_rawfile`),
`spicelib/devices/dev.c` (`osdi_stage_reload_copy`), `frontend/inpcom.c` (the
case-keeping command list), `frontend/inp.c`, `include/ngspice/ftedefs.h` and
`frontend/spiceif.c` (`ci_serial`, `phys_seen`). Nine suites were made portable at the
same time (below). The compiler's share of the same run is
[E-771](Enhancement-771.md).

**Suites:** the full sweep, 536 of 536; the same sweep under Linux's conditions on
macOS — an X build, no `DISPLAY`, no controlling terminal, run from a case-sensitive
volume under a path with capitals — 536 of 536. On the E-769 binaries the twelve suites
these changes touch pass on this Mac but for `osdireload` beside `carddefault` (the
race): the other faults need a condition a Mac build lacks, and the reproductions below
are the old-binary evidence.

## What was wrong

The sweep had only ever run on a Mac: a build without X, from a terminal, on a
case-insensitive volume. The CI machines differ in all three ways — their builds are
`--with-x`, they have no display and no terminal, Linux's file system is
case-sensitive and the Linux job runs as root in a container — and the first sweep
there stopped at suite 152 of 536 on linux-intel, failed 15 suites on macOS Apple
Silicon and 65 on Windows. Five of the causes were in ngspice.

**1. An X build crashed in pipe mode without a display.** With no `DISPLAY`, `DevInit`
falls back to the "error" device and never opens X. But a process without a
controlling terminal — input from a pipe under CI, cron or `ssh -T` — is "in the
background" from its first line (`test_background`), and the read loop then called the
X11 event pump, `app_event_func` → `X11_Input`, which read `ConnectionNumber(display)`
on the NULL display. Every such run segfaulted before executing a command: the CI's
`crashfix`, `crashfix2`, `crashfix3`, `exitcmd`, `carddefault` [8], `cornerscmd` [17],
`pyplot`, `rawfstring`, `fftnorm`, `loadpull`, `nport_native` and `stbfix` failures, on
Linux and macOS alike. A build without X compiles the branch out, which is why no
local sweep had met it. The readline event hook just above was already guarded by
`dispdev->Input == X11_Input`; the background branch now is too.

**2. `-r /dev/null` deleted /dev/null.** A run that writes nothing to its rawfile closes
it and unlinks it, so a failed or vector-less analysis leaves no empty file. The unlink
took any path, and several suites run `ngspice -b -r /dev/null deck` whose `.control`
block writes nothing to the rawfile: as root, in the Linux container, that removed the
device node, every later `open("/dev/null")` on the machine failed, and the sweep itself
died at suite 152 with `FileNotFoundError: '/dev/null'`. Reproduced without root through
a symbolic link to /dev/null passed as the rawfile: the E-769 binary deletes the link,
this one keeps it. `ft_drop_empty_rawfile` removes only a regular file.

**3. Two reloads in the same second shared a file.** `pre_osdi -f` maps a staged copy of
the recompiled object (E-229), named `ngspice_osdi_reload_<time>_<counter>.osdi` in
TMPDIR: the time in seconds and a per-process counter. Two ngspice processes reloading
within the same second both chose `…_<t>_0.osdi`, and one copied over, or removed, the
copy the other was about to map — a reload that kept the old model, or "could not stage
a reload copy". The CI's parallel sweep ran `osdireload` beside `carddefault`; on the
E-769 binary the two suites run side by side failed in 4 runs of 4. The name now
carries the process id.

**4. `savestate` lowercased its file name.** A deck's `.control` lines are lowercased
except for a list of commands whose arguments are data (`write`, `wrdata`, `load`,
`source`, …). `loadstate` is covered by `load`; `savestate` (E-131) was not, so
`savestate /__w/Ngspice_OpenVAF_Enhancements/…/_ck.state` wrote to
`/__w/ngspice_openvaf_enhancements/…` — on a case-insensitive Mac the same file, on
Linux a directory that does not exist. The `checkpoint` suite failed 22 of 22 there.
`savestate` joins the list.

**5. warn_physics said a thing once, twice, three or four times.** E-440's memo
suppresses a repeated `warn_physics` diagnostic, and was reset whenever the
`CKTcircuit` pointer changed. montecarlo rebuilds the circuit for every sample, and
whether the rebuilt one landed at the old address (memo kept, no repeat) or elsewhere
(memo dropped, the warning again) was up to the allocator: identical 20-sample runs
printed the warning 2, 3 or 4 times, and the CI's `argguard` saw 2 for 3 samples and 1
for 20. Each front-end circuit now carries a serial number that is never reused; a
circuit rebuilt from a kept copy of its deck (montecarlo's `mc_source`, `reset`) keeps
the serial of the deck it rebuilds, a newly sourced deck gets a new one, and the memo
is keyed on it. A 3- or 20-sample montecarlo now reports once, every time; sourcing a
deck again still reports afresh; a `reset` no longer repeats it (it rebuilt the same
deck, and before this the repeat depended on the allocator).

## The suites made portable

- `constguard`, `guardgaps`, `mcyield`, `reusesetup`: compared a NaN to the string
  `nan`; glibc prints the x86 default NaN (0/0) as `-nan`.
- `pyplot`: set the interpreter path with a quoted `set`, which a deck lowercases
  (quotes do not protect a `set` value; only E-553's `r"..."` raw strings do) — harmless
  on a Mac, a missing file on Linux. It uses `setcs`, which keeps the case, and the
  suite README says so.
- `reduce`: copied `rfanalyses_examples/rf_blocks.osdi`, the other suite's build
  product, which git ignores — a fresh checkout has none, and in a parallel sweep the
  other suite may be rewriting it. It compiles `rf_blocks.va` into its own scratch
  directory.
- `distoexact` [1]: HD3 at an amplitude of 1e-4 is 6.1e-13 V on a 0.55 V bias, and HB's
  own rounding is ~1e-4 of it: an arm64 build lands at 4.0e-6, an x86-64 build at
  4.9e-5, against a bound of 5e-5, with the same `.disto` value to 11 digits. The bound
  is 2e-4; `.disto`'s exactness is pinned by the A^n scaling in the same check. The
  check now prints what it parsed when it fails.
- `argguard`: the overflow check (`1e300*1e300` in a B-source) failed on Linux for a
  reason the log did not show; it now prints the lines it searched.
- `arrayscale`: see [E-771](Enhancement-771.md).

## Limits

- Not reproduced here, left for the next Linux run with the added detail: `argguard`'s
  overflow check (an x86-64 clang build prints the warning, so the difference is in the
  GCC build), and `collapsestate`, whose Sparse `sens` of `rd` read 5.65e-4 on Linux
  against 2.27e-4 (KLU, and every macOS build, 2.27e-4).
- The linux-arm job was stopped by the runner ("received a shutdown signal") two minutes
  into its sweep; its log does not say why, and the sweep's memory stays near 1 GB here.
- Windows' 65 failures are a separate list.
