# Enhancement-500 — `pre_osdi -va` compiles Verilog-A and loads it in one step

A deck that ships its own models needed a separate build before it could run:
compile each `.va` by hand, then point `pre_osdi` at the objects.

```
pre_osdi -va rmod.va gmod.va
```

now does both — openvaf-r is invoked on each source and the objects it produces
are loaded, in the same command.

## Where the objects go

Into an **`osdi/` directory beside the netlist**, not beside the working
directory and not next to each source. Two reasons, one of them not obvious:

* a model directory stays clean when a deck carries a dozen `.va` files;
* it makes an input/output collision structurally impossible. Enhancement-452
  recorded `openvaf-r m.va -o m.va` **destroying the source and exiting 0**;
  writing to `osdi/<stem>.osdi` cannot name the input no matter what the input
  was called. The guard is asserted anyway, because the reasoning is easier to
  break than the code.

The `.va` argument is resolved against the netlist as well, exactly as
`load_osdi()` already resolves the object it is handed, so
`ngspice -b sub/deck.cir` finds `sub/rmod.va`. This was a bug in the first
version of this change: the object went beside the netlist while the source was
looked up beside the working directory, so the command worked from one directory
and not from another. The two halves of one command must not disagree about what
a relative path means.

## Which compiler

`osdi_find_openvaf()` is `pre_snp`'s existing lookup, exported rather than
reimplemented so both generators share one policy:

1. the `openvaf` ngspice variable (`set openvaf=/path/to/openvaf-r`)
2. the `OPENVAF` environment variable
3. `$SPICE_LIB_DIR/openvaf-r` — the prebuilt binary this tree ships
4. `openvaf-r` on `PATH`

`PATH` alone would have been the obvious implementation and the wrong one: for
anyone running the shipped bundle the compiler sits in `$SPICE_LIB_DIR` and is
frequently not on `PATH` at all.

## Recompiling is the default

`.option osdicache` opts into skipping a source whose object is already up to
date. The instinct is to cache by default; that is wrong here, and the reason is
worth stating plainly: a `.va` timestamp records whether the **source** changed,
and says nothing about the **compiler** having changed. While openvaf-r is itself
under development it changes far more often than the models do, so a cached
object is one built by a compiler that may no longer exist. Enhancement-453 was
exactly this shape — a cache key that omitted its own codegen settings — and
fixing only the key there would have turned a wrong answer into a panic.

The option is read from the deck's **options cards**, not through `cp_getvar`.
`pre_` commands run before the circuit is set up, so no option has been published
yet and `cp_getvar` would answer for the previous deck or for nothing at all —
the trap Enhancement-464 recorded for `autobus`. It is matched as a whole word
rather than with `strstr`, because Enhancement-451 shipped an option whose name
was decided by a substring search and `myseed`/`noseed`/`xseed` all set the seed;
and every spelling that means off means off (Enhancements 450, 451, 454, 466).

## `-f` forces the rebuild, not just the reload

Enhancement-229 added `-f` so that an edit → recompile → re-source loop picks up
a new model without restarting ngspice. Under `-va` the compile is *part* of that
loop, so honouring the flag for the load alone would reload the very object the
author is trying to replace — the one case the flag exists for. This was the
second bug in the first version, and it is the sharpest one: with
`.option osdicache` set, an edited `.va` silently kept answering with the old
model until `-f` reached the compiler.

The suite pins it down by actually editing a source: the answer moves from
`0.5` to `0.3333` only when `-f` is given.

## The staleness test

**Strictly** newer, never `>=`. `st_mtime` is one-second granular on POSIX and
two-second on FAT, so an edit and a re-run inside the same tick would otherwise
load the object built from the previous text. A tie costs one needless recompile;
the other way costs a wrong answer.

That choice is also what makes coarser filesystem clocks harmless rather than
dangerous — the only cost of a coarse clock is an extra compile.

## Portability

`stat` and `st_mtime` come from `<sys/stat.h>`, which `inpcom.c` has used on
Linux, macOS and Windows for years — MinGW maps `stat` to `_stat` internally.
`mkdir` is the one call that genuinely differs, and is guarded on `_WIN32`
(defined by MSVC, MinGW, MinGW-w64 and clang-on-Windows), where `_mkdir()` comes
from `<direct.h>`. Paths are built with `/`, which every Windows CRT accepts, and
the stem extractor recognises both separators.

## Mixing with plain `pre_osdi`

`-va` only changes how a `.va` **argument** becomes a path; anything else still
goes straight to `load_osdi`. The two mechanisms therefore converge on one
loader, which is why every arrangement works: `-va` and plain lines in either
order, both on one line in either order, `-f -va` alongside a pre-built object,
and the same model arriving by both routes at once (reported as already loaded,
which is Enhancement-229's existing behaviour and not an error). `-va` on a line
with no `.va` argument is a no-op rather than a complaint.

## Refusals

A source that does not exist is **named** — *"no such Verilog-A source: …"* —
rather than surfacing as `openvaf-r failed (exit 512)`, which names neither the
cause nor the fix. A source that does not compile shows the compiler's own
diagnostics followed by the message that lists all four ways to supply a
compiler. A read-only directory is not fatal: the objects are written beside the
netlist instead and the fallback is announced, so a deck in a shared PDK or a CI
checkout still runs.

## Verification

`examples/vacompile_examples/` — 33 checks under both linear solvers. Against
the pre-fix binary the suite does not complete at all: `-va` is not a flag there,
so `pre_osdi` tries to `dlopen` both `-va` and the `.va` itself and the run
aborts. Full regression 414/414.
