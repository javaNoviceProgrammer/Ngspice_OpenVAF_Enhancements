# Enhancement-252 — heap out-of-bounds writes in the xfer / file_source file parsers

Two heap **out-of-bounds writes** in the analog XSPICE file-reading code models
`xfer` and `file_source`, found while sweeping the file-parser code models
(`d_state`, `d_source`, `xfer`, `file_source`) and confirmed with
AddressSanitizer. Both read a numeric data file into a growing `double` array and
under-reserve before the store, overrunning the heap. Unlike the earlier
code-model finds (E-246/E-247/E-250, all reads or bounded errors), these are
out-of-bounds **writes** — silent heap corruption.

## `xfer` — reserve 3, store up to 9

`read_file` (`analog/xfer/cfunc.mod`) reads a transfer-function file: a
Touchstone-style `# …` option line, then data lines. It `sscanf`s up to **9**
values per line and, through a small state machine, stores *every* value —
freq/real/imag triples — so a line holding more than one record stores more than
three:

```c
if (i + 3 > size) {              /* reserve only 3 */
    size += ALLOC;              /* ALLOC = 1024 */
    file_data = realloc(file_data, size * sizeof(double));
}
while (j < count) {             /* count = sscanf result, up to 9 */
    file_data[i++] = vals[j];
    ...                        /* state machine walks freq/real/imag */
}
```

A line with two or more records advances `i` by more than the 3 reserved, so once
`i` reaches an `ALLOC` (1024-double) boundary the extra stores write past the
buffer:

```
AddressSanitizer: heap-buffer-overflow WRITE of size 8 ... in cm_xfer
```

**Fix:** reserve the `sscanf` maximum of 9 (`if (i + 9 > size)`) — the store loop
can append at most `count ≤ 9` values per line (`offset ≥ 1`, `span ≥ offset+2`
are already enforced, so `j` advances by ≥ 1 each iteration).

## `file_source` — reserve `size`, store `size + 1`

`file_source` (`analog/file_source/cfunc.mod`) stores one record per line — a
timepoint plus `size` channel values, i.e. `stepsize = size + 1` doubles — but
reserved only `size`:

```c
if (count > vecallocated - size) {         /* one short */
    vecallocated += size * 1000;
    datavec = realloc(datavec, sizeof(double) * vecallocated);
}
datavec[count++] = t;                       /* 1 timepoint  */
for (i = 0; i < size; ++i)
    datavec[count++] = d;                   /* + size channels = size+1 total */
```

At the reallocation boundary — where `count` lands exactly at
`vecallocated - size` (which happens for some channel counts once `vecallocated`
grows to a value no longer aligned to `stepsize`) — the final channel store writes
one double past the end:

```
AddressSanitizer: heap-buffer-overflow WRITE of size 8 ... in cm_filesource
```

**Fix:** reserve a full record (`if (count > vecallocated - stepsize)`).

Both are heap OOB **writes** reachable from a valid-syntax netlist with a crafted
data file. On the release build the few-double overrun corrupts adjacent heap
silently rather than always crashing — undefined behaviour either way. (The sibling
parsers were checked too: `d_source` validates its per-line token count against
the declared width, and `d_state`'s fixed line buffer is `fgets`-bounded — no
analogous overrun.)

## Verification

`examples/filefix_examples/verify_filefix.py` (4 checks, both solvers): a valid
transfer-function file and a valid `file_source` data file simulate; an `xfer`
file with multi-record (9-value) lines and a `file_source` file long enough to
cross the realloc boundary each run without overrunning. Both overruns were
reproduced under an AddressSanitizer build of the code models (`cm_xfer`,
`cm_filesource`) and shown fixed.

## Scope

XSPICE analog code models only (`xfer`, `file_source`). Fix is in `.cm` code
models, so `analog.cm` is rebuilt and redeployed under `bin/*/codemodels/`; the
ngspice binary is unchanged. No solver, analysis, or numerical change; a
well-formed data file is unaffected. Full regression: all examples pass.
