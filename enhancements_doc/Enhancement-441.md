# Enhancement-441 — array instances

A schematic tool writes a repeated device as one symbol with a range on its
reference designator. The netlist that falls out of that is now the netlist
ngspice reads:

```
R[0:3]  a b            r=1k     ->  R[0] a b r=1k   ...  R[3] a b r=1k
N[0:3]  a[0:3] b       model    ->  N[0] a[0] b model  ...  N[3] a[3] b model
N[0:3]  a[0:3] a[1:4]  model    ->  N[0] a[0] a[1] model ... N[3] a[3] a[4] model
```

Four resistors in parallel, four devices each on its own bit, and a chain —
one line each.

## The rule, and why it is only one rule

A range on the **instance name** selects this reading. That single fact settles
everything else.

Enhancement-221 already gave a range in a *node* field a different and equally
useful meaning — one device with a wide port:

```
X1 bus[0:3] sub     ->  X1 bus[0] bus[1] bus[2] bus[3] sub
```

Decks depend on that, so the two readings cannot both apply to one line. The
instance name decides which:

| the name | what a node range means |
|---|---|
| a range (`R[0:3]`) | N cards, and a node range is indexed **in step** — element *i* takes bit *i* |
| scalar (`R1`) | one card, and a node range **expands in place** into consecutive terminals |

So `R1 a[0:3] b` is still a four-terminal connection of one device, and
`R[0:3] a[0:3] b` is four two-terminal devices. Nothing that parses today
changes meaning, because an instance name carrying `[lo:hi]` was not a usable
device name before.

`inp_expand_array_instances()` runs immediately before `inp_expand_buses()`, so
it consumes the node ranges belonging to the array reading and whatever survives
is E-221's by definition. Both passes read a range through one shared parser,
`inp_bus_range_parse()`, so they cannot drift apart about what a range is — and
an XSPICE port group `[d1 d2]`, which has no base, is refused by that parser and
therefore invisible to both.

Descending ranges pair positionally: `R[3:0] a[3:0] a[1:4]` builds the same four
devices as the ascending spelling, in the other order.

## Reaching the elements afterwards

An array instance is named `r[2]`, so the `@name[param]` accessor now carries two
bracket groups — and two places had to learn that. The **lexer** ended the token
at the first `]`, leaving `[resistance]` behind as a separate token; the **split**
in `vectors.c` and `device.c` took everything before the first `[` as the device
name. Between them, `@r[2][resistance]` looked for a device `r` with a parameter
`2`, so the element was visible to `show` but not addressable.

`ft_accessor_param_start()` is the shared rule, and it is deliberately narrow: a
bracket group holding **nothing but an integer** and **immediately followed by
another `[`** belongs to the name. That leaves the two established readings
alone — `@nd1[i_a[0]]` (Enhancement-408: the group is not an integer) and
`@*[[param]]` (Enhancement-269: it starts with `[`) — and a lone `@r[2]` still
means what it always did, device `r`, parameter `2`.

The split lives in **five** places, not the two the first round found. Verifying
the feature against subcircuit hierarchy and the whole `.control` surface turned
up the other three:

| path | symptom before |
|---|---|
| `parse.c` lexer | the token ended at the first `]`, so the accessor never saw the name |
| `vectors.c` | `print`, `let` |
| `device.c` | `alter`, `altermod` |
| `dctrcurv.c` | **`.dc` failed fatally** — "not in the circuit", card and command alike |
| `outitf.c` `parseSpecial` | **`save` lost the WHOLE plot**: a save list that matches nothing takes every vector with it, so `save @r[1][i]` ended the run with "no data saved … analysis not run" rather than dropping one vector |

`print`, `let`, `alter`, `altermod`, `sweep`, `dc`, `save`, `show`, `showmod`,
`meas` and `wrdata` all reach a single element now, flat or hierarchical
(`@r.x1.r[2][resistance]`).

## What is refused

**A width mismatch.** `N[0:3] a[0:1] b` has no sensible reading; pairing four
devices with two nodes is a mistake, not a shorthand. It is named and **the deck
is rejected** — an earlier version of this change printed the error and let the
line through, whereupon ngspice built one resistor literally named `r[0:3]` and
ran to completion with a circuit nobody had described. An error followed by a
finished run is worse than no error at all.

**XSPICE A-devices.** An A-device already spells its port groups with brackets,
so a bracket on its name is ambiguous by construction and XSPICE's connection
parser rejects the expanded name outright. Saying so is better than emitting
cards that fail with a message about something else.

**Instance names are no longer bus-expanded**, which is a correction in its own
right: the first token of an element line is a name, never a node list.
E-221 used to expand it, which turned a refused `R[0:3] a[0:1] 0 1k` into
`r[0] r[1] r[2] r[3] a[0] a[1] 0 1k` and buried the real complaint under a
message about a device called `r[3]`.

## A latent use-after-free, found by walking into it

`inp_rem_levels()` walks `p->line->level` — into the cards — so the scope tree
must be freed *before* the deck. `inp_readall` has three rejection sites: the
`inp_poly_2g6_compat` one has them in that order, and the `inp_vdmos_model` one
has them reversed.

The new rejection path was written by copying the vdmos site, and it crashed with
`EXC_BAD_ACCESS` at offset 8 — the `level` member — the first time it was
actually taken. Both sites are now in the correct order. The vdmos one had been
a use-after-free waiting for its first caller.

## Verification

* **`examples/arrayinst_examples` — 36/36, both solvers.** Every structural
  check is paired with an electrical one computed by hand, because a wrong
  expansion still simulates — it just answers a different question. Four 1k in
  parallel against a 250 Ω source read exactly 0.5 where a single one reads 0.8;
  the in-step form reproduces four different analytic divider voltages; the chain
  gives 5/6 and 1/6 for 6 kΩ end to end. The Verilog-A array is checked to give
  **bit-identical** answers to the resistor array, which is the right cross-check
  since `arrayres` with `r=1k` *is* a 1 kΩ resistor. Controls pin E-221's wide
  port, an ordinary `@dev[param]`, and a scalar bus bit.
* **Subcircuit hierarchy.** A subckt containing an array, instantiated twice,
  yields eight uniquely named devices (`r.x1.r[0]` … `r.x2.r[3]`) reading 0.5;
  arrays nest (`r.x1.x[0].r[0]`) and read 2/3; and an element's internal node and
  its parameter are both reachable hierarchically.
* **The `.control` surface** command by command, including the `.dc` and `save`
  paths above with their values checked analytically.
* **Full regression 353/353**, both solvers.

`xspicemodel`'s crash-guard list gained one accepted phrase: its fuzz deck
`a[0:0] D1 a b dm` is still cleanly rejected with no crash, now while the netlist
is read rather than when the model fails to bind.

## Not covered

An array instance cannot also use an E-221 wide-port node on the same line — the
array reading takes every range on that line. Write that device separately.
Sweeping a whole array as one knob (`sweep @r[0:3][param]`) is not implemented;
elements are swept by name.
