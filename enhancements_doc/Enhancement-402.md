# Enhancement-402 — the terminals nobody mentioned

An OSDI instance line with **fewer nodes than the model has terminals** was
accepted in silence. Every built-in device rejects the same mistake:

| instance line | built-in | OSDI |
| --- | --- | --- |
| diode given one node | *"could not find a valid modelname"*, run aborts | — |
| resistor given one node | *"is not a valid resistor instance line, ignored!"* | — |
| MOSFET given 3 of 4 nodes | *"Error … Simulation interrupted"* | — |
| **OSDI device given 3 of 4 nodes** | | **nothing at all** |

The consequence is not cosmetic. A four-terminal device instantiated with three
nodes still simulates, and the answer changes: on a probe where the fully
connected device gives `v(g) = 1.333`, the three-node typo gives `v(g) = 2.000`,
with rc=0 and an empty diagnostic stream. The omitted pins dangle, so every
branch touching them goes dead and a different circuit is solved than the one
written.

## Why it was silent, and why the obvious fix is wrong

`src/spicelib/parser/inp2n.c` bounded the node count on one side only:

```c
numnodes = i - 1;
if (numnodes > *dev->terms) {
    LITERR("too many nodes connected to instance");
    return;
}
```

Too many is an error; too few was never asked about. The binding loop below then
writes `GENnode(fast)[i] = -1` for each unsupplied terminal, and `osdisetup.c`
reads that `-1` as *"this terminal is deliberately not connected"*
(`terminals[i] == -1` ⇒ `connected_terminals = i`).

**That sentinel is doing two jobs.** It marks a typo and it marks the LRM's
optional-terminal feature, which a netlist uses to leave a thermal or body pin
off and which the model reads back through `$port_connected`. Thirty-two models
in the corpus depend on it — BSIMSOI, BSIM-CMG/IMG/BULK, BSIM6, PSP-HV among
them. Rejecting a short instance line outright would kill that feature.

Nor is "give the pin a dangling node name instead" a substitute. Measured on a
three-terminal device whose `t`–`c` branch is a 1 kΩ resistor:

| instance line | `v(c)` | `$port_connected(t)` |
| --- | --- | --- |
| `n1 a c 0 ma` — `t` grounded explicitly | **0.200** | 1 |
| `n1 a c tt ma` — `t` on its own dangling node | 0.333 | **1** |
| `n1 a c ma` — `t` omitted | 0.333 | **0** |

Electrically a dangling node and an omitted pin agree; to `$port_connected` they
do not. So the feature genuinely needs the omission form.

**And note the first row against the third.** An omitted terminal is *not*
grounded — grounding it changes `v(c)` by 67%. That assumption is a natural one
to make and it is wrong, which is exactly why the diagnostic says so out loud.

## What this release does

The count is now bounded on both sides, and the lower bound *warns* rather than
rejects — the semantics are untouched, the silence is gone:

```
Warning: instance n1: 3 of the 7 terminals of model type 'bsimsoi_va' are not connected.
         terminal 5 ('p') is absent
         terminal 6 ('b') is absent
         terminal 7 ('t') is absent
         The model sees $port_connected() = 0 for these, and any branch
         to them carries no current. They are NOT grounded -- connect
         them to 0 explicitly if that is what you meant.
         Line: n1 g d 0 0 msoi
```

The terminal names come from `dev->termNames`, so they are the model's own port
names (a device type that publishes none falls back to `?`). The example above is
BSIMSOI compiled with `PORT_CONNECTED`, instantiated with four of its seven
terminals: the three named are precisely the optional ones its `$port_connected`
logic is written for. That case keeps working, and now says what it is doing.

## Verification

* **Fires** on 4-of-7, 3-of-4, 2-of-4 and 1-of-2 instance lines, naming each
  absent terminal.
* **Silent** when every terminal is given, when too many are given (already an
  error), and for pins explicitly grounded or explicitly left dangling.
* **Semantics unchanged**: the omitted-terminal deck still reads `v(c) = 0.333`
  and `$port_connected = 0`.
* **Full regression 322/322**, and the warning fires **zero** times across the
  suite — no shipped deck omits a terminal, so every future firing is signal.

`cargo test` and the corpus differential were not re-run: this release touches
one C file in the netlist parser, no Rust and no `.osdi` bytes.

## Found by

A one-hour bug hunt over ngspice + OSDI (303 decks, 59 models, ~20 seams). The
same sweep confirmed a great deal of adjacent behaviour correct — node collapsing
including chains and `$port_connected` gating, 44 cross-analysis orderings,
subcircuit multipliers across dc/ac/tran/noise, all six temperature knobs, LRM
4.6.4 coherent noise summing, `@(cross)` events, KCL over four terminal currents,
and loader hardening against truncated and non-`.osdi` files.
