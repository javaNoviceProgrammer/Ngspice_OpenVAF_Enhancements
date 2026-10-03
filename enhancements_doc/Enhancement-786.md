# Enhancement-786: on Windows one ngspice deleted the model copy another had just staged — the stale-copy sweep removes only the copies of processes that are no longer running

**Scope:** ngspice: `spicelib/devices/dev.c` (`osdi_pid_alive`, `osdi_sweep_stale_copies`).
Examples: osdireload (one new check). From CI runs 37091735340, 37095422733 and 37099178157,
read through E-785's rings.

**Suites:** osdireload 14 of 14 (the new check passes on macOS, where a first load stages no
copy; it is the Windows job that exercises it); the full sweep on macOS, 536 of 536.

## What was wrong

Since E-775, ngspice on Windows loads every `.osdi` from a copy, staged in the temporary directory
as `ngspice_osdi_reload_<pid>_<time>_<n>.osdi`: Windows locks a loaded DLL, and the copy is what
gets locked, so the user's file can still be recompiled. Because a loaded copy cannot be deleted,
copies outlive their session, and E-775 also made each process's first load sweep the directory
of them -- every `ngspice_osdi_reload_*.osdi` it found. A copy in use by a running ngspice refuses
the delete and stays. But a copy another ngspice has *staged and not yet loaded* is not locked:
the sweep deleted it, and the other process's load failed.

Every parallel Windows sweep lost two to four suites that way, a different set each time, on
either solver pass, all passing when re-run alone -- analyses and autobusopt, then opargs and
reuseloops, then arrayret, autoadapt, autobuskicad and dynphys. E-785's rings showed the same
failing run in all four of the last sweep's:

```
Error opening osdi lib "C:\Users\RUNNER~1\AppData\Local\Temp/ngspice_osdi_reload_9684_1791006116_0.osdi": The specified module could not be found.
Error: Library adapt.osdi couldn't be loaded!
```

(arrayret's read "No such file or directory": the copy was gone before its `fopen`.)

## The change

The copy's name already carries the pid of the process that staged it (E-770). The sweep reads it
back and leaves a copy alone while that process is running -- `OpenProcess` and
`GetExitCodeProcess` (`STILL_ACTIVE`), the current process counting as running, and a process
that exists but will not open (access denied) counting as running too. Only the copies of
processes that have exited are removed, which is what the sweep was for.

## The check

osdireload starts eight ngspice processes at once, each loading the same model and running an
operating point, three times over; all 24 must load it and print -1 mA. On Windows every one of
those processes stages a copy and sweeps on its first load, so before the change the rounds raced
each other the way the sweep's suites did.

## Limits

- The Windows branch is built and run by the Windows CI job only; it was compiled here against
  stub declarations of the Win32 calls, for syntax.
- A pid reused by an unrelated process keeps an old copy until that process exits; the copy is
  harmless and goes at a later sweep.
