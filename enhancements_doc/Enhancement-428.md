# Enhancement-428 — the node is `x1.m`, so why is the internal node `n.x1.n1#mid`?

Enhancement-410 made `@x1.r1[resistance]` work, so a device inside a subcircuit
could be reached the obvious way. It left one name behind: the device's own
**internal nodes**.

```
print v(n.x1.n1#mid)     ->  7.50000000e-01
print v(x1.n1#mid)       ->  Warning ... not available or has zero length
```

That is the last place the device-type letter still leaks out, and it is the
worst one, because a *node* is exactly where nobody expects a device letter — the
plain node right beside it is `x1.m`, with no letter at all.

## Why the letter is in a node name

It is inherited, not chosen. Subcircuit expansion rewrites the inner cards back
into the deck and re-parses them as ordinary element lines, and the parser takes
the device type from the **first character** of the card. So the flattened
refdes has to keep a type letter in front: `n1` inside `x1` becomes `n.x1.n1`,
because `x1.n1 …` would begin with `x` and be re-read as another subcircuit call.
Enhancement-410 documents this at length.

An internal node is then named after the instance that owns it —
`<instance>#<node>` — so the letter comes along for the ride. Nothing decided
that a node should carry a device type; it simply fell out of the instance name.

## The reconstruction needs no search

Same argument as Enhancement-410, and it is what makes this safe rather than
heuristic. The letter prepended is literally the leaf instance name's own first
character, and ngspice requires a device's name to begin with its type letter —
so `x1.n1` can only ever mean `n.x1.n1`. Two device types cannot share a leaf
name, because the leading letter *is* the type. The mapping is one-to-one at any
depth: `x1.x2.n1#mid` → `n.x1.x2.n1#mid`.

An `x` instance is exempt, exactly as in `translate_inst_name`: it already starts
with the right letter and carries no prefix.

The fallback is **consulted only after the exact lookups have failed**, so every
name that resolves today resolves to precisely what it does today.

## Two resolution paths, not one

This is the Enhancement-408 lesson, and it very nearly bit again. Node vector
names are resolved in two independent places:

* `findvec` (`vectors.c`) — `print`, `let`, expressions, `meas`, `wrdata`,
  `write`, `.print`/`.plot` cards
* `name_eq` (`outitf.c`) — `.save` and the `save` command, which match saved
  names against the simulator's own data names

Fixing only the first left `save v(x1.n1#mid)` silently matching nothing — and
its failure is **destructive rather than local**:

```
Error: no data saved for Transient analysis; analysis not run
```

The whole plot is lost, not just the one vector. Both paths now share one
helper, `cp_hier_devname()`, so they cannot drift apart.

## Verification

* **`examples/hiernode_examples` — 17/17.** The model is a 1k/3k divider, so the
  internal node sits at 0.75 — a value nothing else in the circuit takes, which
  makes a wrong resolution visible rather than plausible.
* Both spellings are checked in every consumer, at one and two levels of
  nesting, and case-insensitively.
* The things that must not move are checked too: the device-letter form still
  works, an ordinary node and an ordinary *hierarchical* node are untouched, and
  a genuinely bad name still fails.
* **Full regression 345/345**, both solvers.

## Found by

A question rather than a hunt: *"if I need to read the voltage of an internal
node of a Verilog-A device, what should I do in the netlist?"* The answer was
`v(n1#mid)` at the top level and `v(n.x1.n1#mid)` inside a subcircuit — at which
point the second half stops being an answer and starts being a defect report.

Two notes on method.

**The suite's first draft passed for the wrong reason twice.** A check on
`v(x1.p)` "failed" because `p` is a subcircuit *port*, merged with the parent's
node and never a distinct vector; and `length()` returned nothing because
ngspice lowercases vector names on output and the probe matched case-sensitively.
Neither was an ngspice defect. Both are the same shape as the round-34
withdrawals: the measurement was wrong before the code was.

**The destructive `.save` failure was found by enumerating consumers, not by
reasoning.** `findvec` looked like the whole answer, and every interactive
command agreed. It took running `.save` explicitly to see the second path — and
that path fails by discarding the entire analysis output.
