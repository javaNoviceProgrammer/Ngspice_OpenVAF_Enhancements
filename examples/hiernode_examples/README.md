# Reading a Verilog-A device's internal node

An **internal node** is one the model declares but does not expose as a port:

```verilog
module hiernode(a, c);
    inout a, c;   electrical a, c;
    electrical mid;              // internal -- not a terminal
    I(a, mid) <+ V(a, mid) / r1;
    I(mid, c) <+ V(mid, c) / r2;
endmodule
```

ngspice creates a node for it and names it after the instance that owns it:

```
<instance>#<node>
```

## How to name it

| where the device sits | write |
|---|---|
| top level, `N1 a 0 hiernode` | `v(n1#mid)` |
| inside `X1` | `v(x1.n1#mid)` |
| two levels down, `X3` → `X2` | `v(x3.x2.n1#mid)` |

Node names are case-insensitive, so `v(X1.N1#MID)` works too.

It behaves like any other node — usable from the netlist:

```
.save v(x1.n1#mid)
.print dc v(x1.n1#mid)
```

and from `.control`: `print`, `plot`, `let`, inside expressions, over a
transient, with `meas`, and through `write`/`wrdata`.

## Two things worth knowing

**`@n1[mid]` does not work.** `@device[...]` reaches *parameters* and operating-
point variables, not nodes — it answers `Error: no such parameter mid`. An
internal node is a node, so it goes through `v()`.

**You may also see `n.x1.n1#mid`**, and that spelling works as well. The leading
`n.` is the device *type letter*: subcircuit flattening re-parses the emitted
card and dispatches on its first character, so the flattened instance name has
to keep the letter in front — `x1.n1 …` would otherwise be re-read as another
subcircuit call ([Enhancement-410](../../enhancements_doc/Enhancement-410.md)
covers why). [Enhancement-428](../../enhancements_doc/Enhancement-428.md) made
the obvious spelling `x1.n1#mid` resolve everywhere as well, because a node name
is the last place anyone expects a device letter — the plain node beside it is
`x1.m`, with no letter at all.

## If you don't know the node's name

Run `display` after an analysis. Every node ngspice created is listed, so the
`#` names show up directly:

```
    a                   : voltage, real, 1 long [default scale]
    n1#mid              : voltage, real, 1 long
    n.x1.n1#mid         : voltage, real, 1 long
    n.x3.x2.n1#mid      : voltage, real, 1 long
```

## Running it

`internalnode.cir` is a single runnable deck showing all four spellings on one
circuit — a 1k/3k divider inside the model, so the internal node sits at
**0.75 V**, a value nothing else in the circuit takes and therefore one a
mis-resolved name cannot produce by accident:

```
ngspice -b internalnode.cir
```

The full verification — every consumer, deeper nesting, and the controls that
must not move — is `verify_hiernode.py`:

```
python3 verify_hiernode.py
```
