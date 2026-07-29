# Enhancement-367 — `sweep` produced plots nobody could name

A plain question — *"if I run several sweeps, what are the plots called?"* — turned
out to have an embarrassing answer: `unknown4`, `unknown7`, `unknown10`. And the
message `sweep` printed named a plot that had never existed.

Both defects had been shipping since `sweep` was added in
[Enhancement-146](Enhancement-146.md).

---

## 1. The plots were called "unknown"

`plot_alloc()` names a plot by looking its type up in the `plotabs[]` table in
`typesdef.c`, and falls back to the literal `"unknown"` when there is no entry:

```c
if ((s = ft_plotabbrev(name)) == NULL)
    s = "unknown";
plot_unique_typename(s, buf, sizeof buf);
pl->pl_typename = copy(buf);
```

That table lists ngspice's built-in analyses — `tran`, `ac`, `dc`, `pz`, `noise`,
`disto`, `sens`, `sp` — and **every plot type this project added was missing from
it**: `sweep`, `sweepwave`, `hb`, `envelope`, `eye`, `loadpull`, `rfstab`, `stb`.
All eight are now registered.

### Ordering in that table is load-bearing

`ft_plotabbrev()` returns the **first** entry whose pattern is a substring of the
plot name:

```c
for (i = 0; i < NUMPLOTTYPES && plotabs[i].p_name; i++)
    if (substring(plotabs[i].p_pattern, buf))
        return (plotabs[i].p_name);
```

So `"sweepwave"` must precede `"sweep"`, or a sweep-waveform plot would be
abbreviated `sweep` and collide with the point plot. The same rule already
explains a long-standing quirk: a plot named `spectrum` matches the earlier `sp`
entry, never `spect`.

The struct is `{p_name, p_pattern}` — the **second** field is the one matched and
the **first** is the abbreviation returned, so `{ "tran", "transient" }` means *a
plot named "transient" is abbreviated "tran"*. That reads backwards from the
table and is now spelled out in the source, because getting it wrong silently
produces a table that compiles and matches nothing.

## 2. The message named a plot that did not exist

```c
fprintf(cp_out, "sweep: %d points into the 'sweep' plot%s; ...
```

`'sweep'` was a **literal**. No plot was ever called that, so the single hint the
command offered for returning to an earlier sweep — `setplot sweep` — always
failed with *"no such plot named sweep"*. It now prints the real name, captured
from the block-scoped plot at the point it is created:

```
sweep: 3 points into plot 'sweep3' (now current); `plot <output>` to view vs v1.
```

Both summary branches — the single-knob one and the `-vs`/`-family` curve-family
one — carried the same literal, and both are fixed. The stale header comment in
`com_sweep.c`, which also documented the plot as being named `sweep`, is
corrected too.

## Why the numbers are not 1, 2, 3

`plot_unique_typename()` draws from a counter **shared by every plot type** and
advances it only far enough to avoid a collision. Each `sweep` internally runs one
analysis per point, so a three-point sweep burns `op1`, `op2`, `op3` and the sweep
plot lands on `sweep3`; the next one lands on `sweep6`.

That is pre-existing ngspice behaviour and is **not** what this changes — `op4`
and `sweep4` are allowed to coexist by design. What changes is that you no longer
have to guess: the command tells you the name it used.

## Verification

`examples/sweepname_examples` checks the naming, that the printed name is one
`setplot` accepts, that it then yields the sweep's data, that two sweeps in one
session get distinct names, and that the curve-family branch is fixed too.

```
   fixed:        6/6
   pre-fix bin:  1/5   sweep plot is named sweepN     got ['unknown3']
                       summary quotes the real name   no 'into plot' message
                       two sweeps get distinct names  none
                       -family summary                no message
```

Regression 291/291.

## Found alongside, and deliberately left open

Chasing the same table turned up `print alle` — the documented "print all event
nodes" shortcut — being **dead in every build configuration**. `edisplay` lists
the event nodes and `print <node>` prints them individually, but `print alle`
always answers *"vector alle is not available or has zero length"*.

The cause is a guard that cannot be satisfied. `findvec_alle()` in `vectors.c`
sits behind `#if defined(XSPICE) && defined(SIMULATOR)`, with a
`#ifndef SIMULATOR` stub returning `NULL` beside it. `-DSIMULATOR` is set on
`ngspice_CPPFLAGS` and `libngspice_la_CPPFLAGS`, which cover only `main.c`,
`ngspice.c` and `sharedspice.c` — every source in `src/frontend/` is compiled
**once** into `libfte.la` with `AM_CPPFLAGS` alone. Both the executable and the
shared library link that same convenience library, so the stub is what ships.
Confirmed by inspection: the string `DigitalData` from the real implementation is
absent from the binary.

Simply adding `-DSIMULATOR` to `src/frontend/Makefile.am` was tried and
**reverted**: `ngproc2mod`, `ngmultidec` and `ngmakeidx` also link `libfte.la` but
not the XSPICE libraries, so enabling the block makes `vectors.c` reference
`g_mif_info` and `EVTfindvec` and breaks those three tools at link time under
`--enable-oldapps`. The guard is unsatisfiable *by design*, not merely unset, and
a real fix means moving the event-node lookup into a simulator-only object rather
than flipping a flag.

Two smaller things are latent behind that same dead code and are noted here so
they are not re-discovered: `findvec_alle()` overwrites the `pl_typename` that
`plot_alloc()` just assigned with a hardcoded `copy("dig1")` — leaking that
string, leaving the registered completion keyword pointing at a name no plot has,
and giving every digital plot the identical name — and `get_all_type()` has a
misplaced parenthesis, `tolower(word[0] != 'a')` instead of
`tolower(word[0]) != 'a'`, which defeats the case-insensitivity it is written to
provide. The latter is currently harmless only because callers lowercase the word
first, which was verified: `print ALLV` and `print allv` behave identically today.
