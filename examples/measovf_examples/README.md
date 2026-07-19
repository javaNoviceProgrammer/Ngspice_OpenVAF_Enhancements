# `.meas` long-name stack overflow fix (Enhancement-236)

A user-triggerable stack-buffer overflow in the `.meas` (measurement) command,
found during a memory-safety deep dive.

`get_measure2()` ([com_measure2.c](../../ngspice-46/src/frontend/com_measure2.c))
formats each measurement result line with

```c
sprintf(out_line, "%-20s=  %.*e ...", mName, precision, meas->m_measured, ...);
```

into the caller's fixed `char out_line[1000]`
([measure.c](../../ngspice-46/src/frontend/measure.c)). `mName` is the
measurement **name** — taken verbatim from the `.meas <analysis> <name> ...`
card via `cp_unquote`, an unbounded user string. A `.meas` name longer than
~1000 characters overran the stack buffer: macOS aborts with a stack-smashing
`SIGABRT` (exit 134); elsewhere it is straight stack corruption.

[E-225](../../enhancements_doc/Enhancement-225.md) had already hardened the
sibling `errbuf[100]` in this same file to `snprintf`, but missed `out_line`.
E-236 threads the destination buffer size through `get_measure2()` and converts
all **ten** `sprintf(out_line, …)` sites to `snprintf(out_line, max_out_line, …)`,
so any combination of long fields is safely truncated instead of overflowing.
The three callers (`measure.c` ×2, `tclspice.c` ×1) pass `sizeof out_line`
(or `0` for the `NULL`-buffer autostop/interactive paths).

## Verify

```sh
python3 verify_measovf.py
```

Two checks: a `.meas` statement with a ~4000-character name no longer crashes
(exit 0; pre-fix it aborted with exit 134); and normal measurements still return
the correct numbers (MAX = 1.0, AVG = 0.6, a 0.1→0.9 rise time of 0.8 ns).
