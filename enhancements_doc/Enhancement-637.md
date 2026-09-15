# Enhancement-637: a bus actual connects positionally, in its declared or written order

**Scope:** F3 of the
[2026-09-14 hunt](../docs/bug_hunts/2026-09-14_openvaf-r-parameters-arrays-and-hierarchy.md),
and the whole-bus twin found while fixing it. `.a(p[3:0])` with `p` declared
`[0:3]` silently meant `p[0:3]`; `.a(p)` with `p` declared `[3:0]` onto a
`[0:3]` port wired `p[0]` to `a[0]` while `.a({p})` wired it to `a[3]`.
Compiler: `openvaf/hir/src/elaborate.rs` (`bind_port`). New suite
[`busorder_examples`](../examples/busorder_examples/) (8 checks per solver).
**Compiler side.**

**Suites:** `busorder_examples` 8 of 8 per solver, both solvers;
`partselect`, `lrmhier`, `arrayport`, `busname`, `busdir`, `hierdev`,
`busmix`, `busmixed`, `busnodes`, `busport`, `busportsub`, `genhier`,
`hierbranch`, `hiername`, `hiernode`, `subbus`, `probebus`, `arrayinst`,
`filterslice`, `idxlist` green; the `hir` crate tests green; full sweep
510 of 510.

## What was wrong

`bind_port` had two bit-order conventions. A `{...}` concatenation actual
(E-59, E-525) is positional: its bits are listed msb first and laid onto the
port's bits in the port's declared msb-to-lsb order, "so both `[1:0]` and
`[0:1]` declaration styles connect as written". A whole bus and a part-select
(E-85) were laid on by *index value*: the caller's bits ascending onto the
port's bits ascending, a part-select first normalised to ascending. Three
consequences:

| written | meant | while |
|---|---|---|
| `.a(p[3:0])`, `p` declared `[0:3]` | `p[0:3]` — `a[0]` ← `p[0]` | `.a({p[3],p[2],p[1],p[0]})` reversed |
| `.a(p)`, `p` `[3:0]`, `a` `[0:3]` | `a[0]` ← `p[0]` | `.a({p})` gave `a[0]` ← `p[3]` |
| `.a(p)`, `p` `[0:3]`, `a` `[3:0]` | `a[0]` ← `p[0]` | `.a({p})` gave `a[3]` ← `p[0]` |

`{p}` and `p` are the same expression, and a reversed part-select is at best
an abbreviation of the reversed concatenation — E-85's own array
part-select as a filter argument reads "in the order written: `cf[1:0]` is
`{cf[1], cf[0]}`", and this project holds that a construct means one thing
wherever it appears.

## What changes

Every bus actual is positional. The port's bits are walked in the port's
declared order, msb first (`port_bits`); a whole bus contributes its bits in
its own declared order, msb first; a part-select contributes the bits in
the order *written*, msb first. Same-direction connections — every one the
suites and the corpus use — are unchanged bit for bit: `p[0:3]` onto
`a[0:3]`, `p[3:0]` onto `a[3:0]`, E-85's `v[3:2]` and `.i(v[1:0])` route as
they did. What moves is the opposite-direction plain bus (now what `{p}`
always gave) and the reversed part-select (now what the reversed
concatenation always gave). The width check, the width-1 slice onto a
scalar port and the unknown-base fall-through are untouched.

The top-level OSDI port order — a `[3:0]` bus port still exported ascending
on the ngspice instance line (E-3, E-411's warning for the netlist side) —
is a different contract and is not changed here.

## Verification

Each parent bit is driven by its own 1 V source and the child puts (k+1) mA
per volt on `a[k]`, so the current at a parent bit names the child bit.

| connection | child | parent | reaches p[0], p[1], … |
|---|---|---|---|
| `p` | `[0:3]` | `[0:3]` | 1 2 3 4 (unchanged) |
| `p`, `{p}` | `[0:3]` | `[3:0]` | 4 3 2 1, both |
| `p`, `{p}` / `p` | `[3:0]` | `[0:3]` / `[3:0]` | 4 3 2 1 / 1 2 3 4 |
| `p[3:0]`, `{p[3],p[2],p[1],p[0]}` | `[0:3]` | `[0:3]` | 4 3 2 1, both |
| `p[0:3]` | `[0:3]` | `[0:3]` | 1 2 3 4 (unchanged) |
| `p[1:4]`, `p[4:1]` | `[0:3]` | `[0:5]` | bits 1..4: 1 2 3 4 / 4 3 2 1 |
| `p[3:0]`, `p[0:3]` | `[3:0]` | `[3:0]` | 1 2 3 4 / 4 3 2 1 |
| E-85's `v[3:2]`, `.i(v[1:0])`, `{v[0],v[3]}` | | | 8 V, 2 V, 3 V |
| `busorder_examples` | | | 8 / 8, both solvers |
| full sweep | | | 510 of 510 |
