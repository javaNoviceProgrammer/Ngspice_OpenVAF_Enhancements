# Bug hunt — ngspice + OSDI, general

**Date:** 2026-09-02 · **Commit under test:** `eac1432c` · **Binaries:**
`ngspice-46/build/src/ngspice` and `OpenVAF-master-20260610/target/opt/openvaf-r`
as committed.

**Result: one crash and one minor consequence-of-design.** The crash is a
**SIGSEGV on legal Verilog-A**, reproducible, and **pre-existing** — not a
regression from the recent E-539 work, though it lives next door to it.

---

## H1 — scanning a `$fgets` result in the analog body segfaults ngspice

**Class:** SIGSEGV · **Status:** confirmed, reproducible 3/3 · **Age:**
pre-existing, reproduced with the pre-E-539 compiler

A file descriptor opened in `@(initial_step)`, read with `$fgets` in the analog
body and then scanned, crashes the simulator:

```verilog
analog begin
  @(initial_step) fd = $fopen("rdata.txt", "r");
  n = $fscanf(fd, "%g", g);          // or: $fgets(s,fd) then $sscanf(s,...)
  I(a,b) <+ V(a,b) * g * 1e-3;
end
```

```
EXC_BAD_ACCESS (code=1, address=0x0)
frame #0: rep.osdi`osdi_scan_real + 40      ; ldrb w8, [x19]
```

`osdi_scan_cursor` is NULL when a field scanner runs.

### Bounded by experiment

Every neighbouring construct works; only this combination fails.

| construct, in the analog body | exit |
|---|---|
| `$fgetc`, `$ungetc`, `$ftell`, `$feof`, `$ferror`, `$rewind`, `$fseek`, `$fgets` — each with `fd` from `@(initial_step)` | **0** |
| `$sscanf` on a **literal** | **0** |
| `$sscanf` on a `$sformat`-built runtime string (no file) | **0** |
| `$fopen` + `$fgets` + `$sscanf` all **in the body** (`fd` never crosses) | **0** |
| `$fopen` + `$fscanf` + `$fclose` all **in the body** | **0** |
| **`$fgets` + `$sscanf`, `fd` from `@(initial_step)`** | **139 (SIGSEGV)** |
| **`$fscanf`, `fd` from `@(initial_step)`** | **139 (SIGSEGV)** |

Two things fall out of that table:

* **It is not `$fscanf`'s fused lowering.** The manual equivalent — `$fgets`
  into a string, then `$sscanf` on that string — crashes identically. `$fscanf`
  is simply the shortest way to reach it.
* **The `@(initial_step)` crossing is essential.** The identical read-and-scan
  with the descriptor opened *in the body* runs clean. So the trigger is
  scanning a `$fgets` result on a descriptor that crossed from the
  initial-step block into per-evaluation code.

Not an exhaustion path either: a 20 000-line input crashes the same as a
4-line one.

### Not an E-539 regression

Verified rather than assumed, because the code next door is mine. The pre-E-539
compiler was extracted from git history
(`e3cdecaf:bin/macos/apple-silicon/openvaf-r`, confirmed to lack
`osdi_inst_name`) and run on the identical deck with the identical module name,
changing only the `.osdi`: **both exit 139**.

Worth recording that a first attempt at this comparison *appeared* to show a
regression — the old binary exited 1 while the new one crashed. That was an
artefact: the `sed` had renamed the model *type* but not the module inside the
`.va`, so ngspice never found the model and the old binary never ran the code
at all. Re-done correctly before any conclusion was drawn.

---

## H2 — one file open through both descriptor namespaces interleaves out of order

**Class:** ordering, no data loss · **Status:** confirmed · **Severity:** low

E-539 gave file descriptors and multichannel descriptors separate tables, so
`$fopen("x","w")` and `$fopen("x")` now return two independent `FILE*` handles
on the same file. Writes alternating between them leave the file out of order —
written `AAA`(fd), `BBB`(mcd), `CCC`(fd), the file contains `AAA`, `CCC`, `BBB`,
the two handles' buffers flushing independently. Before E-539 the single-table
same-name dedup returned one handle and order was preserved.

**No data loss**: the LRM 9.5.1.1 append rule stops the second open truncating
the first's content — verified by opening the multichannel descriptor first and
confirming all three lines survive.

Recorded as a known consequence of the namespace split rather than a defect
needing a fix: a model has to open one name through both spellings to reach it,
and the LRM gives no reading under which that is meaningful.

---

## Coverage, honestly

This was one hour against a large surface, and it went deep on one seam rather
than broad. What that means:

* The file-I/O-in-the-analog-body seam was swept **systematically** — nine
  system tasks, plus literal/runtime/file string sources, plus the
  descriptor-crossing variable. That table is the reason H1 is bounded rather
  than merely observed.
* **Everything else in ngspice + OSDI was not touched**: parameter and
  `alter`/`altermod` paths, node collapse, temperature, AC and noise, `$limit`,
  `absdelay`/`last_crossing`, terminal currents, the matrix/solver layer.
* **Root cause was not established.** H1 is characterised, not diagnosed — why
  the descriptor crossing NULLs the scan cursor is left to whoever fixes it.
  The table above is meant to be the diagnostic starting point.

No claim is made that these areas are sound; they were simply not looked at.
