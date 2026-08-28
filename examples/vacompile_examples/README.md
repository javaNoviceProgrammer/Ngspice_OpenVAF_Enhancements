# Enhancement-500 — `pre_osdi -va` compiles Verilog-A and loads it in one step

```
python3 verify_vacompile.py
```

33 checks, both linear solvers.

## What it does

```
pre_osdi -va rmod.va gmod.va
```

invokes openvaf-r on each source and loads the objects it produces. Before this,
a deck that shipped its own models needed a separate build first: compile each
`.va` by hand, then point `pre_osdi` at the results.

The objects are collected in an **`osdi/` directory beside the netlist** — not
beside the working directory, and not next to each source. That keeps a model
directory clean, and it makes an input/output collision structurally impossible:
[Enhancement-452](../../enhancements_doc/Enhancement-452.md) recorded
`openvaf-r m.va -o m.va` **destroying the source and exiting 0**.

The `.va` argument is resolved against the netlist too, exactly as `load_osdi()`
already resolves the object it is handed — so `ngspice -b sub/deck.cir` finds
`sub/rmod.va`. The two halves of one command must not disagree about what a
relative path means.

## Which compiler

`osdi_find_openvaf()`, shared with `pre_snp` rather than reimplemented:

1. the `openvaf` ngspice variable (`set openvaf=/path/to/openvaf-r`)
2. the `OPENVAF` environment variable
3. `$SPICE_LIB_DIR/openvaf-r` — the prebuilt binary this tree ships
4. `openvaf-r` on `PATH`

A bare `PATH` search would miss the compiler in the shipped bundle, which is
exactly where it lives for most users.

## Recompiling is the default

`.option osdicache` opts into skipping a `.va` whose object is already up to
date. The usual instinct is the other way round, and it is wrong while openvaf-r
itself is under development: a `.va` timestamp says only whether the **source**
changed, so a skipped rebuild loads an object built by a compiler that no longer
exists. That is the shape of
[Enhancement-453](../../enhancements_doc/Enhancement-453.md), whose cache key
omitted its own codegen settings.

`-f` bypasses the cache outright.
[Enhancement-229](../../enhancements_doc/Enhancement-229.md) added that flag for
the edit → recompile → re-source loop, and under `-va` the compile is *part* of
that loop — honouring `-f` for the load alone would reload the very object being
replaced. The suite pins that down by editing a `.va` and checking the answer
moves from `0.5` to `0.3333` only when `-f` is given.

The staleness test is **strictly** newer, never `>=`. `st_mtime` is one-second
granular on POSIX and two-second on FAT, so a tie must rebuild: a tie costs one
needless compile, the other way costs a wrong answer. Check `[12]` asserts it.

## Portability

`stat`/`st_mtime` come from `<sys/stat.h>`, which `inpcom.c` has used on Linux,
macOS and Windows for years. `mkdir` is the one that differs, and is guarded on
`_WIN32` — defined by MSVC, MinGW, MinGW-w64 and clang-on-Windows — where
`_mkdir()` comes from `<direct.h>`. Coarser filesystem clocks (FAT's two seconds)
only ever cost an extra compile, because a tie already rebuilds.

## Mixing with plain `pre_osdi`

`-va` only changes how a `.va` **argument** becomes a path; anything else still
goes straight to `load_osdi`, so both mechanisms converge on one loader. All five
arrangements are asserted — two lines either way round, one line either way
round, and `-f -va` alongside a pre-built object — as is the same model arriving
by both routes at once, which reports "already loaded" and is not an error.

## What must not change

Plain `pre_osdi file.osdi` is untouched, and `-va` on a line with no `.va`
argument is a no-op rather than an error. A missing source is named
(*"no such Verilog-A source"*) instead of surfacing as `exit 512`, and a source
that fails to compile shows the compiler's own errors followed by a message
naming all four ways to supply it.
