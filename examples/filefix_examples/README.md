# xfer / file_source heap out-of-bounds writes (Enhancement-252)

Two heap **out-of-bounds writes** in the analog XSPICE file-reading code models
`xfer` and `file_source`, found while sweeping the file-parser code models and
confirmed with AddressSanitizer. Both read a numeric data file into a growing
`double` array and under-reserve before storing, overrunning the heap.

## `xfer` — reserve 3, store up to 9

`read_file` (`analog/xfer/cfunc.mod`) reads a transfer-function file (a
Touchstone-style `# …` option line, then data). It `sscanf`s up to **9** values
per line and, via a small state machine, stores *every* value — so a line holding
more than one freq/real/imag record stores more than 3. But the allocation check
reserved only 3:

```c
if (i + 3 > size) { size += ALLOC; file_data = realloc(...); }
...
while (j < count)          /* count up to 9 */
    file_data[i++] = vals[j];
```

A multi-record line therefore wrote past the buffer once `i` reached the
`ALLOC` (1024-double) boundary:

```
AddressSanitizer: heap-buffer-overflow WRITE of size 8 ... in cm_xfer
```

**Fix:** reserve the `sscanf` maximum of 9 (`if (i + 9 > size)`).

## `file_source` — reserve `size`, store `size + 1`

`file_source` stores one record per line — a timepoint plus `size` channel
values, i.e. `stepsize = size + 1` doubles — but reserved only `size`:

```c
if (count > vecallocated - size) { vecallocated += size*1000; realloc(...); }
datavec[count++] = t;                     /* 1 */
for (i = 0; i < size; ++i) datavec[count++] = d;   /* size more */
```

One short. At the reallocation boundary the final channel wrote one double past
the end:

```
AddressSanitizer: heap-buffer-overflow WRITE of size 8 ... in cm_filesource
```

**Fix:** reserve a full record (`if (count > vecallocated - stepsize)`).

Both are heap OOB **writes** (not reads), reachable from a valid-syntax netlist
with a crafted data file. On the release build the few-double overrun corrupts
adjacent heap silently rather than always crashing — undefined behaviour either
way.

## Verification

`verify_filefix.py` (4 checks, both solvers): a valid transfer-function file and a
valid `file_source` data file simulate; an `xfer` file with multi-record (9-value)
lines and a `file_source` file long enough to cross the realloc boundary each run
without overrunning. Both overruns were reproduced under an AddressSanitizer build
of the code models (`cm_xfer` / `cm_filesource`) and shown fixed.

## Scope

XSPICE analog code models only (`xfer`, `file_source`). Fix is in `.cm` code
models, so `analog.cm` is rebuilt; the ngspice binary is unchanged. No solver,
analysis, or numerical change; a well-formed data file is unaffected.
