# Enhancement-812: `display`, `load` and a noise plot's listing of a long vector name no longer overflow a stack buffer — `pvec` builds the line in a growing string

**Scope:** F21 of the
[ngspice + OSDI hunt of 2026-10-08](../docs/bug_hunts/2026-10-08_ngspice-osdi-hierarchy-sweeps-events-and-outputs.md).
ngspice:
- `frontend/plotting/pvec.c`: `pvec` writes its line with a `DSTRING`.

`examples/nameovf_examples/` (three checks). **ngspice only.**

**Suites:** [`nameovf_examples`](../examples/nameovf_examples/) 15 of 15 (all 3 of these fail on
the E-810 binaries: an abort for `display` and `load`, SIGSEGV for the noise deck under Guard
Malloc); the full sweep, 539 of 539.

## What was wrong

`pvec` lists one vector as `    name : type, real, N long, …`. It `sprintf`'d that into
`char buf[BSIZE_SP]`, 512 bytes on the stack, with the vector's name. It then `strcat`'d the
colour, the scale's name and the dimensions after it. Every route that lists vectors goes
through it:

- `display`: with a node of about 470 characters or more the fortified C library aborted, every
  time, plain runs included;
- a noise analysis with per-device contributions names a vector `onoise_<device>_thermal`, so a
  480-character OSDI instance made `display` of the `noise1` plot abort;
- `load` lists what it reads, so loading a raw file (binary or ASCII) that holds a 600-character
  name aborted. Writing that file was fine.

## The change

`pvec` builds the line in a growing string (`ds_cat_printf`), whatever the lengths of the name,
the colour, the scale's name and the dimensions. The line is otherwise the same, byte for
byte.

## The checks

nameovf, under Guard Malloc where it exists (macOS) and plainly elsewhere:
- `display` with a 600-character node lists the whole name;
- a noise analysis of a 600-character OSDI instance: `display` of `noise1` lists its
  contribution, and `print onoise_<instance>_thermal` reads 2.04e-9;
- `write` then `load` of a raw file holding a 600-character name: the listing and
  `print v(<name>)` = 2.
