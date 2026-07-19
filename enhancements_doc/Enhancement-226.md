# Enhancement-226 — ngspice rawfile-load crash hardening (fuzzing)

Continuing the fuzzing campaign onto another untrusted-input surface: the
**nutmeg rawfile reader** (`raw_read` in `frontend/rawfile.c`), reached by the
`load` command. A `.raw` file is external data — often written by another tool —
so its parser must survive malformed input.

Mutating a valid `.raw` file (produced by `write`) — tweaking the header counts,
corrupting the `Flags:` / `Variables:` lines, adding/removing value rows,
truncating, and flipping bytes — and `load`-ing each found a **NULL-dereference
crash** (SIGSEGV, `memmove` into `0x0`). The command/`.control` shell surface,
fuzzed in the same pass, was clean (7,500 iterations, 0 crashes — it is already
hardened by [E-212](Enhancement-212.md) / [E-222](Enhancement-222.md) /
[E-225](Enhancement-225.md)).

## Root cause

`raw_read` resets `flags = VF_PERMANENT` at the start of each plot and sets
`VF_REAL` / `VF_COMPLEX` only when it parses a `Flags:` line. Each vector is then
allocated with `dvec_alloc(NULL, SV_NOTYPE, flags, npoints, NULL)`, which
allocates `v_realdata` **or** `v_compdata` according to those bits.

A rawfile with **no valid `Flags:` line** — the line missing entirely, or carrying
only unknown flags (`Flags: xyz`) — leaves `flags` with neither `VF_REAL` nor
`VF_COMPLEX`, so `dvec_alloc` allocates **no data array at all**. The value-reading
loop then does `fread(&v->v_realdata[i], …)` / writes `v->v_compdata[i]` into a
**NULL** buffer → `memmove` into `0x0` → SIGSEGV.

By contrast a bad `No. Points:` / `No. Variables:` count (huge, negative,
non-numeric) was already handled cleanly — only the missing type was fatal.

## The fix

When the header is complete and vector allocation begins (at the `Variables:`
line), if `flags` carries neither `VF_REAL` nor `VF_COMPLEX`, **default to real**
(the common case) with a warning, instead of allocating a typeless vector:

```c
if (!(flags & (VF_REAL | VF_COMPLEX))) {
    fprintf(cp_err, "Warning: no real/complex 'Flags:' line; assuming real\n");
    flags |= VF_REAL;
}
```

The reset to `VF_PERMANENT` is per-plot, so the guard runs for every plot in a
multi-plot file. A valid file is unaffected (its `Flags:` line already set the
type).

## Verification (`examples/rawfuzz_examples`)

`verify_rawfuzz.py` writes a valid `.raw` with `write`, then crafts the
pathological variants — the `Flags:` line removed, and replaced with an unknown
`Flags: xyz` — and `load`s each, asserting a clean, bounded outcome (no
signal/abort) rather than the previous SIGSEGV. A regression check confirms a
valid `.raw` still round-trips through `write` → `load` with the correct vector
length.

## Scope

ngspice frontend only, one file (`frontend/rawfile.c`); no device, solver, or
OSDI change. Full regression: 185/185.
