# Enhancement-818: `altermod gm` with `gm` only inside a subcircuit no longer claims a top-level card was changed

**Scope:** F2 of the
[ngspice + OSDI hunt of 2026-10-08](../docs/bug_hunts/2026-10-08_ngspice-osdi-hierarchy-sweeps-events-and-outputs.md).
ngspice:
- `frontend/spiceif.c`: `if_hasmodel_toplevel`, declared in `fteext.h`.
- `frontend/device.c`: the concrete-name branch of `altermod` asks whether a top-level card
  exists before choosing its note.

`examples/subcktedit_examples/` (section [2], four checks). **ngspice only.**

**Suites:** [`subcktedit_examples`](../examples/subcktedit_examples/) 16 of 16 per solver (2 of
the 4 checks in [2] fail on the E-816 binaries; the other two are the layouts the old note
already handled). `showmodhier` and `hiername` are unchanged within the full sweep, 542 of 542.

## What was wrong

A `.model gm` declared only inside a subcircuit is flattened to `x1:gm`, `x2:gm`, `x3:gm`.
`altermod gm g=7m` then printed:

```
Error: no such device or model name gm
Note: 3 models are named 'gm' (the top-level card and 2 flattened subcircuit copies); only the
top-level one was changed -- use '@*:gm[...]' for all of them.
```

There is no top-level card: all three are copies, and nothing was changed. Enhancement-436's
note counted every model carrying the leaf name and took one of them for the top-level card.
With a single copy there was no note at all. With a real top-level card and two copies the
note was right.

## The change

`if_hasmodel_toplevel` says whether a model of exactly that name exists, a top-level card and
not a `<path>:name` copy, and returns the first copy it meets. The note now follows from what
is there:

- **A top-level card and copies:** the existing note (only the top-level card was changed).
- **Several copies and no top-level card:**
  ```
  Note: no top-level card is named 'gm'; the 3 models of that name are flattened subcircuit
  copies ('x3:gm', ...), and none was changed -- use '@*:gm[...]' for all of them, or a copy's
  own name for one.
  ```
- **One copy:**
  ```
  Note: no top-level card is named 'gm'; the only model of that name is the flattened
  subcircuit copy 'x1:gm', which was not changed -- name it 'x1:gm'.
  ```
- **A top-level card alone:** no note.

## The checks

`subcktedit_examples` [2] runs the four layouts, each with an OSDI card `gm`:
- a top-level card and two copies: the note is the old one, and only the card changed (3 → 9 mA);
- three copies: the new note, and nothing changed (3 mA);
- one copy: the new note names `x1:gm`, and nothing changed (1 mA);
- a top-level card alone: no note, and the card changed (1 → 7 mA).
