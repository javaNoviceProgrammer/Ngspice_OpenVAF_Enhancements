# Enhancement-235 — `stb`: fix a latent use-after-free in the probe lookup

A defensive follow-up to [E-234](Enhancement-234.md). Building `loadpull`
uncovered a use-after-free in the source-terminal lookup shared, in identical
form, by the `stb` stability command ([E-198](Enhancement-198.md)); this fixes
it there too.

## The bug

`com_stb` located its voltage probe with

```c
vlookup = copy(vname);
INPretrieve(&vlookup, ft_curckt->ci_symtab);
inst = ft_sim->findInstance(ckt, vlookup);
...
tfree(vlookup);
```

`INPretrieve` (`spicelib/parser/inpsymt.c`) is a plain symbol-table hash lookup:
on a hit it does `*token = t->t_ent` — it **replaces the pointer with the
interned entry** and **does not free the old copy**. The interned entry is the
canonical device-name string that the voltage source's own name field also
points at. So after `INPretrieve` succeeds, `vlookup` is the interned name, our
`copy(vname)` has leaked, and `tfree(vlookup)` **double-frees the source's live
name and the symbol-table entry**.

It never manifested in `stb` because `stb` runs once and does not re-set-up the
circuit, so the freed string is not immediately reused. It is the exact same
defect that bit `loadpull` in E-234, where the per-Γ re-setups re-created the
drive source's branch node from that freed (and reallocated) memory, silently
renaming `vdr#branch` to `tran#branch`.

## The fix

Drop `INPretrieve` entirely — it does nothing `findInstance` needs (no
case-folding, no subcircuit translation; just pointer canonicalization) and only
sets up the double-free — and lowercase a private copy instead, since ngspice
stores instance names lowercased:

```c
vlookup = copy(vname);
{ char *p; for (p = vlookup; *p; p++) *p = (char) tolower((unsigned char) *p); }
inst = ft_sim->findInstance(ckt, vlookup);
...
tfree(vlookup);   /* now safe -- our own copy */
```

Only our own copy is freed. As a bonus the probe lookup becomes
**case-insensitive**: `stb Vprobe Iprobe` used to fail with *"no such probe
source 'Vprobe'"* and now resolves. The now-unused complex helper `stbsub` was
removed to keep the build warning-free.

## Verification (`examples/stbfix_examples`)

`verify_stbfix.py` (3 checks): a **mixed-case** probe name (`stb Vprobe Iprobe`)
now resolves and reports a loop gain (it failed "no such probe source" before);
the loop gain is still correct (a gain-1e5 buffer loop → ~100 dB DC loop gain,
measured 99.91 dB); and **60 repeated `stb` runs** stay stable.

## Scope

ngspice frontend only, one file (`frontend/com_stb.c`); no solver, analysis,
device, or compiler change; loop-gain results are unchanged. Full regression:
193/193.
