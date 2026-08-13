# Enhancement-449 — autobus across a subcircuit boundary

[Enhancement-444](Enhancement-444.md) lets one node name stand for a whole
Verilog-A bus port. It does that in `INP2N`, because that is where the model —
and therefore the bus width — is known.

Inside a `.subckt` that is too late.

## The bus bits went to nodes that went nowhere

A definition declaring `a[0:4]` has the five formals `a[0]` … `a[4]`, so a
device line writing the bare `a` matched none of them. Flattening turned it into
the local node `x1.a`, and `INP2N` then expanded *that*:

```
.subckt bs a[0:4] b
N1 a b busdev
.ends
X1 n0 n1 n2 n3 n4 b bs
```

```
nodes after expansion:  n0 n1 n2 n3 n4 b  x1.a[0] x1.a[1] x1.a[2] x1.a[3] x1.a[4]
                        ^ the ports                ^ five floating nodes,
                                                     and the device is on these
```

The five bits read one identical voltage — the ladder alone, the device
contributing nothing.

**Nothing was reported.** Every terminal *did* receive a node, so
[E-402](Enhancement-402.md)'s under-connected warning had nothing to say.
Turning the option ON therefore removed the diagnostic the same deck gets with
it off:

```
autobus OFF:  Warning: instance n.x1.n1: 4 of the 6 terminals of model type
              'busdev' are not connected.
autobus ON :  no diagnostic at all, rc=0
```

That is the shape [E-445](Enhancement-445.md) recorded when autobus indexed
ground: switching a feature on removing an existing warning.

## The fix is at the substitution, not at device parse

A token that is not a formal, but for which formals `token[i]` exist, expands to
those formals' actuals. It needs no model — only the `.subckt` line — so it
works at flattening time, before `INP2N` ever sees the instance.

The option is not reachable from there in the obvious way. `cp_getvar("autobus")`
is false during flattening, because `inp_subcktexpand()` runs before
`inp_dodeck()` publishes the options; and the `.option` cards are no longer in
the deck either, having been split into the option lists. A deck scan finds
nothing. `inp.c` reads them from those lists and passes the answer in, the same
way it already reads `scale` a few lines above the expansion call.

Restricted to OSDI instance lines. A bare `a` on an R/C/L line inside the same
subcircuit is an ordinary local node and stays one — only a Verilog-A device can
have a bus port at all.

## Bit order comes from the declaration

The bits are emitted by **ascending bit index**, not in the order the `.subckt`
line lists them. The compiled model always orders a bus port's terminals by
ascending index whatever direction the Verilog-A declared — `inout [4:0] a`
still yields terminals `a[0]`, `a[1]` … `a[4]`, which was measured rather than
assumed — and the instance line is positional, so the bits have to leave the
expander in that order.

A *descending* `.subckt` declaration therefore binds in reverse:

```
.subckt bs a[0:4] b     ->  0.4469  0.5955  0.7144  0.7936  0.8403
.subckt bs a[4:0] b     ->  0.8403  0.7936  0.7144  0.5955  0.4469
```

which is [E-411](Enhancement-411.md)'s rule — the written order decides —
applied one level up. A model declared `[4:0]` still matches its own flat form.

## The other subcircuit form was already correct

This is worth stating plainly, because the two look similar and mean different
things:

```
.subckt mysub a b                  .subckt mysub a[0:1] b[0:2]
N1 a b twobus                      N1 a b twobus
.ends                              .ends
X1 p q mysub                       X1 p0 p1 q0 q1 q2 mysub
```

The left form declares two **scalar** formals. Both tokens on the device line
*are* formals, so flattening substitutes them normally and `INP2N` expands the
caller's own names — the subcircuit has two pins and the bits live in the
caller's scope as `p[0]`, `p[1]`, `q[0]` … This **already worked**, verified here
against a fully-written-out reference, for one instance and for two instances
with different actuals. It is unchanged.

The right form declares five **per-bit** formals: the subcircuit has five pins
and the caller wires each bit. That is the form this enhancement fixes.

Both are useful — the first passes a bus through as a unit, the second exposes
the bits — so both are pinned by the suite.

## Out of scope, and why

Writing **one bit** where the whole bus is expected is a different defect and is
not fixed here:

```
.subckt bs a[0:4] b
N1 a[0] b busdev        -> five floating n0[0] .. n0[4], silently
```

`a[0]` is a formal, so flattening resolves it to the actual `n0`, and by the
time `INP2N` sees the line nothing distinguishes it from a legitimate top-level
instance whose bus base happens to be called `n0`. It is **byte-identical before
and after this change**. E-445 guarded the two spellings it could recognise
(ground, an already-bracketed token); this one is not recognisable at either
end, and a heuristic for it belongs in its own investigation rather than bolted
to this one — [E-399](Enhancement-399.md)'s rule that a fix must be no wider
than its evidence.

Bus shorthand on a **subcircuit instance** line (`Xi a b inner`) is likewise not
supported, but it fails loudly — `Error: too few nodes`, rc=1 — never as a
silent mis-simulation.

## Verification

**`examples/subbus_examples` — 16/16, both solvers.** Every check is a
differential against the flat, fully-written-out instance, on a ladder where all
five bits read a different voltage, so a mis-ordered or mis-bound expansion
cannot pass by coincidence:

* `.subckt a[0:4]` + `N1 a b` reads **bit-identical** to the written-out form,
  and so do a bit-by-bit port list, two levels of subcircuit nesting, the
  plural `.options` spelling, and two bus ports plus a scalar on one device
* a descending `.subckt` declaration binds in reverse; a model declared `[4:0]`
  matches its own flat form
* with the option **off** the shorthand is still not expanded **and E-402 still
  reports the unconnected terminals**
* a bare bus-base name on an `R` line stays the local node `x1.a`
* a scalar formal `a` beside a bus `a[0:1]` still wins for `a`
* the written-out form is unaffected by the option
* ground as a bus token is still diagnosed

**Full regression 361/361**, both solvers.
