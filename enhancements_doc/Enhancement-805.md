# Enhancement-805: too many nodes on an OSDI instance line names the model's terminals and the nodes left over

**Scope:** D11 of the
[ngspice + OSDI hunt of 2026-10-08](../docs/bug_hunts/2026-10-08_ngspice-osdi-hierarchy-sweeps-events-and-outputs.md).
ngspice:
- `spicelib/parser/inp2n.c`: `INP2N`'s node-count check.

`examples/osdislips_examples/` (section [11], three checks). **ngspice only.**

**Suites:** [`osdislips_examples`](../examples/osdislips_examples/) 93 of 93 per solver (2 of the 3
in [11] fail on the E-795 binaries); the full sweep, 538 of 538.

## What was wrong

```
n1 1 2 3 gm g=2m          (gm is a two-terminal module)
too many nodes connected to instance
```

The line named neither the model's terminal count nor its terminals. The neighbouring slips are
explained:
- too few nodes, by E-402: the omitted terminals dangle;
- a value without a name, by the 2026-09 hunts: "a value without a parameter name; the model is
  ...".

## The change

```
too many nodes: n1 connects 3, but model gm (module gres) has 2 terminals (a, b); '3' is left over
```

The message names the count connected, the model and module, the terminal count and names, and
the tokens past the last terminal. With two extras it says "'3 4' are left over".

## The checks

osdislips [11]:

- one extra node: the terminals and the node left over;
- two extra: both named;
- the right count still runs.

## Limits

- The built-in MOSFET's own "too many nodes" (`inp2m.c`) is unchanged; its terminal count
  depends on the model level.
