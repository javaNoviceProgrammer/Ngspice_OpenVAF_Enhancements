# Enhancement-811: `print` of a vector with a long name no longer overruns a heap buffer — the line is sized to the name

**Scope:** F20 of the
[ngspice + OSDI hunt of 2026-10-08](../docs/bug_hunts/2026-10-08_ngspice-osdi-hierarchy-sweeps-events-and-outputs.md).
ngspice:
- `frontend/postcoms.c`: `com_print`'s line form sizes `buf` to the name it formats; the
  column form's plot-name line is a bounded `snprintf`.

`examples/nameovf_examples/` (eight checks). **ngspice only.**

**Suites:** [`nameovf_examples`](../examples/nameovf_examples/) 15 of 15 (7 of these 8 fail on the
E-810 binaries with SIGSEGV under Guard Malloc; the module compile passes); the full sweep, 539
of 539.

## What was wrong

```spice
v1 1 0 2
rxxxx…x 1 0 1k          ; an instance name of 512 characters or more
.control
op
print @rxxxx…x[i]
.endc
```

`com_print` allocates `buf` with 512 bytes, or the terminal width if that is larger. In line
form it then `strcpy`s the vector's name into it, or `sprintf`s `plot.name` when the vectors
come from several plots. A name of 512 characters or more ran past the block:
- plain runs crashed in 2 of 12 tries, with ordinary heap corruption;
- under macOS Guard Malloc, every time.

The name can be an instance, a node or a Verilog-A parameter
(`print @lpm[<600-character parameter>]`), and generated netlists from a flattener or a layout
extractor reach such lengths. It is base ngspice: a built-in resistor reproduces it. `show`,
`showmod` and `devhelp` printed the same names safely.

## The change

Before formatting a name, `com_print` grows `buf` to the name's length plus the plot prefix,
tracking its capacity across the existing width-based reallocations. The column form's header
line (plot name and date) is written with `snprintf` into the same buffer. Its vector columns
were already truncated to 15 or 31 characters by their `%-16.15s`/`%-32.31s` formats.

Names are printed whole. Nothing is truncated in line form.

## The checks

nameovf, under Guard Malloc where it exists (macOS) and plainly elsewhere:
- `print @<instance>[i]` with a 600- and a 3000-character instance: the whole name and the
  value;
- `print v(<node>)` with a 600- and a 3000-character node;
- `print col` and `print all` with those names;
- a Verilog-A module with a 600-character parameter name compiles, and
  `print @lpm[<that name>]` shows the whole name and the value given on the card.
