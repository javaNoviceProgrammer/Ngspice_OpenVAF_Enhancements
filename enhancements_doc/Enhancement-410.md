# Enhancement-410 — the node is `x1.m`, so why is the device `r.x1.r1`?

A resistor inside a subcircuit is reached as `@r.x1.r1[resistance]`. The node
right beside it is plain `x1.m`. Written the obvious way,

```
@x1.r1[resistance]        ->  Error: no such device or model name x1.r1
```

This release makes the obvious spelling work, everywhere the accessor is
consumed, without changing what any existing name means.

## Why the device-type letter is there

It is not an accessor convention. `r.x1.r1` is genuinely the device's name —
`show all` prints it that way — and the letter is there because of **how
subcircuits are flattened**.

ngspice expands a subcircuit by rewriting its cards back into the deck and
re-parsing them as ordinary element lines, and the parser takes the device type
from the **first character** of the card (`inppas2.c`: `c = *(current->line);
switch (c)`). So the flattened refdes has to keep a type letter in front. Had
`r1` inside `x1` been renamed `x1.r1`, the emitted card

```
x1.r1 a m 1k
```

would begin with `x` and be re-read as **another subcircuit call**.

Two details in the code confirm that is the reason rather than a plausible
story:

* `translate_inst_name()` (`subckt.c`) **exempts `x` devices** —
  `if (tolower_c(*name) != 'x')` — because a subcircuit instance already starts
  with the right letter. So `x2` inside `x1` is plain `x1.x2`.
* **Nodes have no type, so they get no letter**: `translate_node_name` yields
  `x1.m` and `x1.x2.q`.

That asymmetry is the whole complaint, and it is why hierarchical *nodes* always
worked while hierarchical *devices* did not.

## The fallback needs no search

The letter prepended is literally the leaf name's own first character
(`bxx_putc(buffer, *name)`), and ngspice already requires a device's name to
begin with its type letter. So `x1.r1` can only ever mean `r.x1.r1` — two device
types cannot share a leaf name, because the leading letter *is* the type. The
reconstruction is one-to-one, at any depth (`x1.x2.r1` → `r.x1.x2.r1`), and it
applies to OSDI devices the same way (`x1.x2.nd1` → `n.x1.x2.nd1`).

`if_find_instance_hier()` (`spiceif.c`) does exactly that, and is **consulted
only after the exact lookups have already failed**. Every name that resolves
today resolves to precisely what it does today.

## Every consumer, not just `print`

`@dev[param]` is resolved in several independent places — the lesson of
Enhancement-408, where a bracketed parameter name worked for `print` and
silently did not for `alter`. All of them are routed through the new helper:

| path | serves |
| --- | --- |
| `finddev()` | `print`, `let`, `alter`, `altermod` |
| `finddev_special()` | the model-or-device accessor form |
| `DCTfindInstParam()` (`dctrcurv.c`) | `.dc @inst[param]` sweeps (E-62) |
| `sw_fp_bind()` (`com_sweep.c`) | the `sweep` command's knob binder |

**For `sweep` the old behaviour was not even an error.**
`sweep @x1.r1[resistance] 1k 3k 1k` ran three points whose results were all
**identical**, because the knob never bound — a silent no-op sweep. It now
tracks the resistance properly.

## `show` needed its own answer

`show` could not express the spelling at all. Its query grammar takes the
**first character as the device-type selector** (`type = *word++`) and uses
`:` or `#` — not `.` — as the subcircuit delimiter. So `show r.x1.r1` works
because it parses as type `r` plus the remainder `.x1.r1`, while `show x1.r1`
parses as *type `x`* and can never match a resistor.

Rather than change that grammar, `dgen_hier_match()` is consulted **alongside**
it as a whole-word alternative, and can only ever add a match. It requires a `.`
in the query and a flattened `<letter>.<path>` device name, so bare names and
top-level devices keep their existing meaning.

A first attempt widened the existing `strcmp` inside the decomposition instead.
It was measured as **dead code** — the query bails at the type check long before
that comparison — and reverted. The grammar has to be bypassed, not adjusted.

## Backward compatibility, asserted

Every exact spelling was diffed against the pre-410 binary rather than assumed:

| | |
| --- | --- |
| `@r.x1.r1[resistance]`, `@n.x1.x2.nd1[rval]` | identical |
| top-level `@v1[dc]`, `@r0[resistance]` | identical |
| `show all`, `show r0`, `show -v r0`, `show r0 c0` | identical |
| legacy `show :r1`, `show #dmod`, `showmod all` | identical |
| a name matching nothing, a bogus parameter | still reported |
| an `x` leaf (`@x1.x2[..]`) | no phantom prefix invented |
| hierarchical **nodes** (`v(x1.m)`) | untouched |

Across a sweep of 17 `show` forms, **14 are byte-identical** and the only 3 that
changed are the new spellings, each of which previously printed *"No matching
instances or models"*.

## Verification

* **`examples/hierdev_examples` 32/32**, and **15/32 on the pre-410 binary** —
  the example detects the change rather than describing it.
* Both spellings compared *to each other* for exact equality, not merely to an
  expected number.
* **Full regression 327/327**, including `sweep`, `sweepwild`, `nestedsweep`,
  `paramfastsweep`, `wildparam` and `staterestore`.
* Enhancement-49's `hiername_examples` is a different subject — hierarchical
  names *inside Verilog-A* (`V(u1.m)`, `$root`) — and is untouched.
* The compiler is untouched; this release is entirely ngspice-side.

## Found by

A user asking why the prefix was required at all. The answer turned out to be
load-bearing rather than arbitrary — it is what keeps a flattened card parsing as
the right device type — which is also why the fix is a *fallback* rather than a
change to how instances are named.
