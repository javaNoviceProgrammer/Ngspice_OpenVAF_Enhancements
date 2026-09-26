# Enhancement-732: a `stop when` on an operating-point variable that was not saved reads it live, as `print` does, and a name that is nowhere is reported once per run — `stop when @n1[vm] > 0.3` with the variable outside the save set printed `Error: @n1[vm]: no such node` at every accepted point and never stopped, while `print @n1[vm]` read the value and `save @n1[vm]` made the same condition work

**Scope:** D2 of the
[ngspice + OSDI hunt of 2026-09-25, evening](../docs/bug_hunts/2026-09-25_ngspice-osdi-plumbing-hierarchy-and-runs.md).
**ngspice only.** `src/frontend/breakp.c` (`stop_live_value`, `stop_operand`;
`satisfied` reads both operands through them; `ft_bpcheck` clears the per-run mark at
the first point), `src/include/ngspice/ftedebug.h` (`db_said`).
[`examples/saveguard_examples/`](../examples/saveguard_examples/) (section [5], 4 checks,
42 per solver; `sg_op.va`). Handbook [§3.7](../docs/handbook/03-ngspice-workflows.md).
The hunt page.

**Suites:** `saveguard` 42 of 42 per solver, both solvers (39 of 42 on the E-730
binaries); `savemiss`, `namelookup`, `writemc`, `autosave`, `solvercore`, `saveused`
unchanged; no new build warnings; full sweep, run alone.

## What was wrong

An RC through an OSDI device whose mid-node voltage is the operating-point variable `vm`:

| control block | result |
|---|---|
| `save all @n1[vm]` / `stop when @n1[vm] > 0.3` / `tran … uic` | stops after 25 points, `condition met` |
| `save all` / `stop when @n1[vm] > 0.3` / `tran … uic` | `Error: @n1[vm]: no such node`, once per accepted point, the run to its end |

`satisfied` in breakp.c looked each operand up in the run plot with `vec_fromplot` and,
finding nothing, printed "no such node" and returned false — at every accepted point,
since `ft_bpcheck` runs at every one. An operating-point variable is in the plot only when
saved ([E-418](Enhancement-418.md) records it per point then); `print @n1[vm]` goes
through `vec_get`, which builds a one-point vector from `if_getparam` when the plot has no
such name, so the same name read fine one command earlier. The message was wrong (the
name is a variable, not a node) and repeated as many times as the run had points.

## What changed

**The live read.** `stop_operand` takes the plot's vector first, its last point, as
before. When there is none and the name is an accessor (`@dev[param]`), `stop_live_value`
splits it the way `vec_get` does (`ft_accessor_param_start`, then the `]` that matches, as
[E-408](Enhancement-408.md) reads a bracketed name) and asks `if_getparam` for the value:
the value the last accepted point left in the device, which is what the saved vector's
last element would be. No temporary vector is made. A parameter reads the same way, so
`stop when @n1[r] > 0.3` stops at the first point; a list-valued answer contributes its
first element, as `@dev[p][0]` would.

**Once per run.** When neither the plot nor the live read has the name, the condition's
entry is marked (`db_said`) and one line is printed with the stop's number — for an
accessor "no such vector in the plot, and no parameter of that name to read live", after
`if_getparam`'s own line naming what is missing (the device or the parameter); for any
other name the old "no such node" — and the stop is not evaluated again in that run.
`ft_bpcheck` clears the mark at the first point of the next run, since a `save` in
between may have supplied the name, and a run that still lacks it reports it again.

## Verification

`saveguard` section [5] (`sg_op`, an RC with `vm` as a variable): the saved run stops
part-way with `condition met` (the reference, passes on E-730); the unsaved run stops at
the same point count with no "no such" line (fails on E-730: the line per point, the run
to its end); `@n1[nosuch]` draws "no such parameter" and the stop's own line once each
and the run completes (fails on E-730: "no such node" per point); `nosuchnode` over two
runs draws "no such node" twice, once per run, not once per point (fails on E-730).

By hand: the hunt's [Q1] decks — saved and unsaved both stop after 25 points; `@n1[nosuch]`,
`@nosuchdev[vm]` and `nosuchnode` one report each; `resume` after the stop continues and
stops again at the next point; `stop when @n1[r] > 0.3` stops at once; a device inside a
subcircuit, `stop when @x1.n1[vm] > 0.3`, stops where the top-level one does.

## What this does not do

- `stop when 0.3 lt v(mid)` — a number on the left, a name on the right — crashes
  ngspice with a segmentation fault, on the E-730 binaries as well and with a plain node;
  the operand order is not touched here, and the crash is recorded on the hunt page's
  smaller notes.
- The live read costs one `if_getparam` per accepted point per unsaved operand; saving
  the variable is still the faster path, and leaves the vector for afterwards.
- `<` in a control-block `stop when` is still the shell's input redirection (`lt` and
  `gt` are the operators); unchanged.
