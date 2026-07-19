# `stb` use-after-free fix (Enhancement-235)

A defensive follow-up to [E-234](../../enhancements_doc/Enhancement-234.md): the
`loadpull` work uncovered a latent use-after-free in the `stb` command
([E-198](../../enhancements_doc/Enhancement-198.md)), and this fixes it.

`com_stb` resolved its voltage probe with `INPretrieve(&name, symtab)`, which
**replaces the pointer with the interned symbol-table string** — the same memory
the voltage source's own name field points at — and does **not** free the old
copy. The following `tfree(name)` therefore double-freed the source's live name
(and the symbol-table entry). It never bit in practice because `stb` runs once
with no re-setup, but it is real memory corruption, and it is the identical bug
that `loadpull` triggered (there the per-point re-setups re-created the source's
branch node from the freed, allocator-reused memory).

The fix drops `INPretrieve` — top-level device names need no subcircuit
translation, and `findInstance` does its own name match — and lowercases a
private copy instead (ngspice stores instance names lowercased), so only our own
copy is freed. As a bonus this makes the probe lookup **case-insensitive**:
`stb Vprobe Iprobe` used to fail with *"no such probe source"* and now resolves.
The now-unused complex helper `stbsub` was removed to keep the build
warning-free.

## Verify

```sh
python3 verify_stbfix.py
```

Three checks: a **mixed-case** probe name now resolves (pre-fix it failed); the
loop gain is still correct (a gain-1e5 buffer loop → ~100 dB DC loop gain); and
**60 repeated `stb` runs** stay stable (the use-after-free stress).
