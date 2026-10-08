# Enhancement-803: `osdi` alone lists the loaded libraries and their modules; an unknown option and a `-f` with no file are refused

**Scope:** D9 of the
[ngspice + OSDI hunt of 2026-10-08](../docs/bug_hunts/2026-10-08_ngspice-osdi-hierarchy-sweeps-events-and-outputs.md).
ngspice:
- `frontend/com_dl.c`: `com_osdi`.
- `spicelib/devices/dev.c`: `load_osdi` records the modules each file registered
  (`osdi_loaded_mods`); new `osdi_list_loaded`.
- `spicelib/devices/dev.h`.
- `frontend/commands.c`: `osdi` and `pre_osdi` take zero or more arguments, and the help text
  says what none does.
- `docs/internals/ngspice_internals/ngspice_commands.md`: the table regenerated.

`examples/osdislips_examples/` (section [9], five checks). **ngspice only.**

**Suites:** [`osdislips_examples`](../examples/osdislips_examples/) 56 of 56 per solver (4 of the 5
in [9] fail on the E-795 binaries); `helpcmd` 27 of 27; the full sweep, 538 of 538.

## What was wrong

- `osdi` alone answered "osdi: too few args." Nothing in the session listed which libraries were
  loaded, or which modules each provided.
- `osdi -l` read `-l` as a file name: `Error opening osdi lib "-l"`.
- `osdi -f` with no file, meant as "reload what is loaded", did nothing, without a word. So did
  `osdi -va`.

## The change

`osdi` (or `pre_osdi`) with no argument lists every library loaded, in load order, with the
modules it registered:

```
OSDI libraries loaded (2):
  .../dp.osdi: dp
  .../rb.osdi: rb, rs, rs__2
```

With none loaded, it says how to load one:

```
No OSDI library is loaded. Load one with `osdi file.osdi` (in a deck, `pre_osdi file.osdi` in a .control block), or compile and load a source with `osdi -va file.va`.
```

The module list is taken when the file loads, and again on a forced reload. It holds the modules
the file actually provides. A module ignored as a duplicate of one already registered is not
listed.

A word beginning with `-` other than `-f`, `-force` and `-va` is refused, with the options named.
Flags with no file are refused too:

```
Error: osdi: unknown option '-l'; the options are -f (reload a file already loaded) and -va (compile a .va source first). `osdi` alone lists the loaded libraries.
Error: osdi: -f names no file to reload.
Error: osdi: -va names no file to compile.
```

Both count as load errors, as a missing file does (`ft_osdierror`, and the strict-error exit).

## The checks

osdislips [9]:

- `osdi` alone lists both libraries and their modules, a paramset family's members included;
- `-l` is refused and not opened;
- `-f`, `-va` and `-f -va` with no file each say so;
- the loaded model still runs;
- with nothing loaded, the listing says how to load one.

## Limits

- A path is listed as it was given. A relative path is relative to where ngspice ran. Under
  `-va`, the path is the compiled object's.
