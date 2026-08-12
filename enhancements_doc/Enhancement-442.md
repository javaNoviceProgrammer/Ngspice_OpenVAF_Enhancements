# Enhancement-442 — `listing tree`

`listing e` answers *what is actually simulated*: a flat wall of one line per
device, with the structure only implicit in the dotted names.

```
     8 : r.x1.rin      a      x1.m  2k
    12 : r.x1.x3.r1    x1.m   0     4k
    14 : c.x1.x3.c1    x1.m   0     1n
     8 : r.x2.rin      a      x2.m  2k
    ...
```

That is the wrong shape for *what does this design contain*. On anything with
more than a couple of levels the structure is what you want first, and
reconstructing it by eye from flattened names does not scale.

```
.control
listing tree
.endc
```

```
two-stage amp
+- vdd
+- vin
+- x1 : amp
|  +- xd : diffpair
|  |  +- m1
|  |  +- m2
|  |  +- rt
|  |  +- rc
|  |  `- rc2
|  +- xg : gainstage
|  |  +- m3
|  |  `- rd
|  `- cc
`- rl

3 subcircuit instances, 11 devices, 3 levels deep
```

Each `X` is labelled with the subcircuit it instantiates, and every instance is
drawn where it is *used* rather than where it is written — the same subcircuit
appears once per instantiation, because that is what the design contains.

`listing t` works too, alongside the existing `l`, `p`, `d`, `e` and `r`.

## Which deck it walks

`ci_origdeck` — the deck as read, with `.subckt` blocks still intact — because
the expanded deck no longer knows which subcircuit each instance came from. That
choice has one useful consequence: array instances (Enhancement-441) are already
expanded at that point, so `X[0:2]` shows as three instances rather than one
line of notation.

## Two things the walk has to get right

**The subcircuit name is not "the last token before the parameters".** That rule
does not survive contact with a real deck: numparam rewrites

```
X1 in 0 sub PARAMS: rv=2k
```

into `x1 in 0 sub 2k` before this runs. The marker is gone and the tail looks
like an ordinary node, so counting tokens picks `2k` and reports the subcircuit
as undefined. Resolving against the definitions already collected is
unambiguous where counting is not: take the *last* token that names a
`.subckt`, since the name follows the nodes. Only if nothing resolves does it
fall back to the last bare token, so a name the user wrote is still the name
reported.

**A `.control` block's commands begin with a letter**, exactly like element
lines. Without skipping those blocks, `option` and `listing` were drawn as
devices and counted as such — and, more subtly, they also broke the *last child*
detection, so the final top-level entry kept a tee (`+-`) where it needed a
corner (`` `- ``) and its subtree was indented with a bar that led nowhere.

## What it does not report

No "subcircuit defined but never instantiated" line: ngspice comments such a
definition out of the deck (`*subckt spare p n`) long before this runs, so the
report could never fire. The `(undefined)` and `(recursive)` annotations are
kept as defensive labels rather than tested behaviour — both conditions abort
the deck during expansion, so `listing tree` is not reached with either.

## Verification

**`examples/listtree_examples` — 23/23, both solvers.** The shape checks are
specific rather than "some tree was printed": children indented under their
parent, grandchildren twice, and — the classic tree-drawing bug, invisible in a
one-level deck — the last child drawn with a corner and its subtree indented
with blanks rather than a trailing bar. The summary line is checked against
counts worked out by hand, eight levels of nesting are checked to stay aligned,
`.control` commands and dot cards are checked *not* to appear or be counted, and
the other listing forms (`p`, `e`, a bad type) are checked unchanged.

**Full regression 353/353**, both solvers.
