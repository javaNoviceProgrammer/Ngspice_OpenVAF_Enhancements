# Enhancement-236 — `.meas`: fix a stack-buffer overflow on long measurement names

A memory-safety deep dive turned up a user-triggerable stack-buffer overflow in
the `.meas` (measurement) command, present in stock ngspice and reproducible on
the shipped binary.

## The bug

`get_measure2()` (`frontend/com_measure2.c`) formats each measurement result line
with, e.g.

```c
sprintf(out_line, "%-20s=  %.*e from=  %.*e to=  %.*e\n",
        mName, precision, meas->m_measured, precision, meas->m_from,
        precision, meas->m_to);
```

`out_line` is the caller's fixed **stack** buffer — `char out_line[1000]` in
`frontend/measure.c`. `mName` is the measurement **name**, taken verbatim from
the `.meas <analysis> <name> <func> ...` card:

```c
case 1:
    mName = cp_unquote(words->wl_word);   /* unbounded user token */
```

Nothing bounds its length. A `.meas` name longer than ~1000 characters overruns
`out_line`. On macOS the stack canary fires and the process aborts
(`SIGABRT`, exit 134); on platforms without a canary it is a plain stack
corruption. All ten result-formatting sites in `get_measure2()` share the flaw
(each is a `sprintf(out_line, "%-20s=…", mName, …)`).

Reproduce on the stock binary:

```
* meas long-name overflow
v1 1 0 dc 0 pulse(0 1 0 1n 1n 5n 10n)
r1 1 0 1k
.tran 0.1n 20n
.meas tran mAAAA…(4000 A's)… MAX v(1) FROM=0 TO=20n
.end
```

→ `ngspice -b` aborts with exit 134.

[E-225](Enhancement-225.md) had already hardened the sibling `errbuf[100]` in
this very file to `snprintf` (after a fuzz campaign on measure syntax), but the
fuzzing never exercised a long measurement *name*, so `out_line` was missed.

## The fix

Thread the destination buffer size through `get_measure2()` and bound every
write:

```c
int get_measure2(wordlist *wl, double *result, char *out_line,
                 size_t max_out_line, bool auto_check);
...
snprintf(out_line, max_out_line, "%-20s=  ...", mName, ...);   /* ×10 */
```

The three callers pass the real size:

| caller | out_line | size passed |
|--------|----------|-------------|
| `measure.c` batch `.meas` | `char out_line[1000]` | `sizeof out_line` |
| `measure.c` autostop check | `NULL` | `0` |
| `tclspice.c` interactive | `NULL` | `0` |

All ten sites are already guarded by `if (out_line)`, so the `NULL`/`0` callers
never reach `snprintf`. An over-long name is now safely truncated to 999
characters instead of overflowing; the measurement value itself is computed and
stored exactly as before.

## Verification (`examples/measovf_examples`)

`verify_measovf.py` (2 checks): a `.meas` statement with a ~4000-character name
no longer crashes (exit 0; was 134); and normal measurements still return the
correct numbers (MAX = 1.0, AVG = 0.6, a 0.1→0.9 rise time of 0.8 ns).

## Scope

ngspice frontend only — `com_measure2.c` (signature + ten `snprintf`),
`com_measure2.h` (prototype), `measure.c` (two callers), `tclspice.c` (one
caller). No solver, analysis, device, or compiler change; measurement results are
unchanged. Full regression: 194/194.
