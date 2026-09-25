# Enhancement-719: a terminal the instance line leaves out is held by the dcpath gmin and named as an unconnected terminal — its node carried the '#' that marks a built-in device's internal node as reached, and the descriptor's entries for a `$port_connected`-guarded port say nothing about the guard, so the walk passed it by and every operating point went "singular matrix: check node n1#c" down the ladder to the transient operating point, 277 iterations for a two-line deck; `.option silentports` installs the hold without a word, `=ground` has no node to hold

**Scope:** F5 of the
[correctness campaign of 2026-09-25](../docs/bug_hunts/2026-09-25_openvaf-r-correctness-campaign.md).
**ngspice only.** `src/spicelib/analysis/cktsetup.c` (`dcpath_check`: the flag, the
message, `dcpath_silentports`), `src/osdi/osdisetup.c` (`OSDIdcpathEdges`: the flag,
the edges it withholds), `src/include/ngspice/osdiitf.h` (the signature). The compiler
is untouched.
[`examples/dcpath_examples/`](../examples/dcpath_examples/) (E-575's suite, section
[11], 12 checks, 69 per solver), [`examples/silentports_examples/`](../examples/silentports_examples/)
(E-481's, checks [7] and [8] re-pinned), [`examples/groundports_examples/`](../examples/groundports_examples/)
(E-482's, check [9] re-pinned). The hunt page and the handbook.

**Suites:** `dcpath` 69 of 69 per solver (60 of 69 on the E-714 binaries),
`silentports` 24 of 24 (22 of 24), `groundports` 59 of 59 (56 of 59); `portconnected`,
`floatnode` 16 of 16 per solver, `singularname` 12 of 12 per solver, `solvercore`,
`acgminhold` 10 of 10 per solver, `ctrlnode` 37 of 37, `oprobust` 32 of 32 per solver,
`warmstart` 5 of 5, `failacct` 9 of 9, `linesearch` 17 of 17 per solver, `bsrcconv`
5 of 5 per solver and `vafcrash2` 22 of 22 unchanged; full sweep 532 of 532, run alone.

## What was wrong

`module pc(a, b, c)` with `I(a,b) <+ 1e-3 V(a,b); if ($port_connected(c)) I(c,b) <+
1e-3 V(c,b);` — the LRM's idiom for an optional pin — instantiated as `N1 a 0 mm`
(`cc/I/pc.va`), on E-714:

```
Warning: instance n1: 1 of the 3 terminals of model type 'pc' are not connected.
         terminal 3 ('c') is absent
Warning: singular matrix:  check node n1#c
Note: Starting dynamic gmin stepping
Warning: singular matrix:  check node n1#c
Warning: Dynamic gmin stepping failed
Note: Starting true gmin stepping
Warning: singular matrix:  check node n1#c   (four times)
Warning: True gmin stepping failed
Note: Starting source stepping
Warning: source stepping failed
Note: Transient op started
Note: Transient op finished successfully
@n1[cc] = 0   @n1[it] = 277
```

The first warning is E-402's and is right: the terminal dangles, `$port_connected(c)`
reads 0, the guarded branch is absent. What follows is the failure path of an operating
point that had nothing wrong with it. The parser binds the missing terminal to −1 and
`osdisetup.c` makes it a node of its own, `n1#c`, with `CKTmkVolt`; nothing outside the
instance touches that node, and with the branch off its matrix row is all zero — the
node has no DC path to ground, which is exactly what [E-575](Enhancement-575.md)'s
`.option dcpath` walk exists to find and hold. It passed the node by, for two reasons
that each sufficed:

- **The walk's OSDI edges come from the descriptor's Jacobian pattern**
  (`OSDIdcpathEdges`), and the pattern has the entry (c, b) whether or not the guard
  around the contribution is true at run time. The walk joined c to b, b is ground, c
  was reached.
- **The node's name carries a '#'**, and `dcpath_check` takes a name with a '#' for a
  built-in device's internal node — `t1#int1`, a collector prime — which the device
  joins to its terminals through series elements the terminal table cannot see, and
  skips. The comment says OSDI internal nodes carry no '#' and stay in the walk; the
  node of an absent terminal is the one OSDI node that does carry one.

So the node went the way E-575 was written to end: down the gmin and source-stepping
ladders, singular at every rung, to the transient operating point — 277 iterations for
a two-line deck, and the same on every `op` of every analysis. [E-481](Enhancement-481.md)
had measured the six singular reports on the BSIM-BULK thermal port and pinned them as
"the option does not make an ill-posed circuit well posed"; [E-482](Enhancement-482.md)
added `=ground` as the repair. Both stand; this is the third state, where the netlist
leaves the port open on purpose and the model handles it as the LRM says.

## What changed

**`OSDIdcpathEdges` flags the node of every terminal an instance line left out**, in a
new `absent` array the walk hands it (one flag per global node), and joins such a node
to nothing: neither its Jacobian entries nor the branch-to-ground rule of E-575 count
for it. A group that holds a connected terminal is that terminal's circuit node and is
never flagged, whatever was collapsed onto it. A terminal the module never mentions was
already node 0 and stays so.

**`dcpath_check` holds a flagged node in every mode and says what it is.** The '#' rule
exempts it; the reactive walk (E-595) never releases it, since nothing outside the
instance can carry it; its message reads

```
Warning: no DC path from node 'n1#c' to ground -- the terminal is not connected; gmin (1e-12 S) installed to provide one, in every mode
```

and `dcpath=warn` and `dcpath=error` carry the same clause. Under `.option silentports`
([E-481](Enhancement-481.md)'s request for no word about the omission, read with
`inp2n.c`'s own value words) the hold is installed without the line and the node is not
counted against the five-message cap; a lone node beside it is named as before. Under
`.option silentports=ground` the terminal is node 0 and there is no node to hold.

| the F5 deck | E-714 | now |
|---|---|---|
| default | six singular reports, the ladder, the transient op, 277 iterations | held, named, 3 iterations |
| `.option silentports` | the same, without the five warning lines | held, no line at all, 3 |
| `.option silentports=ground` | `$port_connected` reads 1, 3 iterations | unchanged |
| `.option dcpath=off` | the ladder | the ladder (E-566's run, unchanged) |
| `.option dcpath=warn` | the ladder, no word | "the terminal is not connected (.option dcpath=warn: nothing installed)", the ladder |
| `.option dcpath=error` | the ladder | refused, naming `n1#c` as an unconnected terminal |
| a transient, an ac | the ladder at the op | held throughout, no singular report |

## Verification

`dcpath` section [11]: the guarded port left off the line is named as an unconnected
terminal and held, no singular report, no ladder, three iterations, `$port_connected`
0, `v(n1#c)` = 0, the current as before; `dcpath=off` is the old road (the ladder,
more than 100 iterations, the same current); `silentports` installs the hold without
a word and `=ground` has no node; a transient runs with the node at 0 and an ac runs;
`warn` and `error` say what the node is; an unguarded resistor to the open port is
held and named all the same, and the model's own path wins (`v(n1#c)` = `v(a)`);
seven open instances give five names and "2 more"; `silentports` beside a lone node
quiets the port's node only; the connected form draws no message and the branch is
live. `silentports` [7] and [8] and `groundports` [9] pin the new shape on the
BSIM-BULK-like gated thermal port: held and named by default, no singular matrix, no
ladder, the bare card silent about both lines, `=ground` with no private node and the
same operating point as writing the 0 by hand.

By hand: the campaign's probe (277 to 3); a capacitor to the open port through a
transient (held at 0); the tie-off shape `V(t) <+ 10` (10 V, as `groundports` [2]
pins); the fourteen suites; the sweep.

## What this does not do

- It does not ground the terminal. E-402's decision stands and `silentports=ground` is
  the word for grounding; the hold is gmin, a current of 1e-12 A per volt, and a model
  that conducts to the port itself sets the node — the unguarded resistor reads
  `v(n1#c)` = `v(a)` to 1e-9.
- The message says the terminal is not connected even when the model conducts to its
  node, as in that resistor case: true, the hold is harmless there, and the walk cannot
  see the guard that would tell the two apart.
- `.option dcpath=off` keeps E-566's run, ladder and all, as for every other node.
- Observed and left as it is: a 0 V short onto the open terminal in the guard's else
  branch (`else V(c, a) <+ 0`) does not collapse the node onto `a` — a terminal short
  with an unconnected endpoint is dropped as redundant at setup (E-401's rule, on the
  reading that "the ordinary collapse already applies", which it does not for a
  terminal) — so the node stays its own: it was singular, six reports, and is now held
  at 0 V rather than following `v(a)`. Recorded on the campaign page as a candidate.
